import contextlib
import io
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from scripts import setup_maven_credentials as setup


class SetupMavenCredentialsTest(unittest.TestCase):
    credentials = {"MAVEN_USERNAME": "utvikler", "MAVEN_PASSWORD": "secret-token"}

    def test_creates_settings_with_references_not_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            changed = setup.configure(home, self.credentials)
            settings = home / ".m2" / "settings.xml"

            self.assertEqual(changed, [settings])
            content = settings.read_text()
            server = ElementTree.fromstring(content).find("./servers/server")
            self.assertEqual(server.findtext("id"), "github")
            self.assertEqual(server.findtext("username"), "${env.MAVEN_USERNAME}")
            self.assertEqual(server.findtext("password"), "${env.MAVEN_PASSWORD}")
            self.assertNotIn("secret-token", content)
            self.assertNotIn("utvikler", content)
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)

    def test_preserves_other_servers_and_original_content(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            original = (
                b'<?xml version="1.0" encoding="UTF-8"?>\n'
                b'<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">\n'
                b'  <!-- <server><id>github</id></server> -->\n'
                b'  <servers>\n    <server><id>other</id><password>keep</password></server>\n'
                b'  </servers>\n</settings>\n'
            )
            settings.write_bytes(original)
            setup.configure(home, self.credentials)

            content = settings.read_bytes()
            self.assertIn(original[: original.index(b"  </servers>")], content)
            self.assertIn(b'<password>keep</password>', content)
            root = ElementTree.fromstring(content)
            ns = {"m": "http://maven.apache.org/SETTINGS/1.0.0"}
            ids = [node.text for node in root.findall("./m:servers/m:server/m:id", ns)]
            self.assertEqual(ids, ["other", "github"])

    def test_does_not_change_existing_github_server_or_require_env(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            original = b"<settings><servers><server><id>github</id><password>keep</password></server></servers></settings>"
            settings.write_bytes(original)

            self.assertEqual(setup.configure(home, {}), [])
            self.assertEqual(setup.configure(home, {}, use_gh_token=True), [])
            self.assertEqual(settings.read_bytes(), original)
            self.assertFalse((home / ".zshrc").exists())

    def test_existing_server_prints_migration_warning_without_changing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            original = b"<settings><servers><server><id>github</id><password>old-token</password></server></servers></settings>"
            settings.write_bytes(original)
            output = io.StringIO()

            with patch("scripts.setup_maven_credentials.Path.home", return_value=home), patch.object(
                sys, "argv", ["setup_maven_credentials"]
            ), contextlib.redirect_stdout(output):
                self.assertEqual(setup.main(), 0)

            self.assertIn("bør du endre den manuelt", output.getvalue())
            self.assertIn("${env.MAVEN_PASSWORD}", output.getvalue())
            self.assertNotIn("old-token", output.getvalue())
            self.assertEqual(settings.read_bytes(), original)
            self.assertFalse((home / ".zshrc").exists())

    def test_repeated_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            setup.configure(home, self.credentials)
            settings = home / ".m2" / "settings.xml"
            first = settings.read_bytes()

            self.assertEqual(setup.configure(home, {}), [])
            self.assertEqual(settings.read_bytes(), first)

    def test_missing_credentials_do_not_create_or_change_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for env in ({}, {"MAVEN_USERNAME": "user"}, {"MAVEN_USERNAME": " "}, {"MAVEN_PASSWORD": "token"}):
                with self.subTest(env=env), self.assertRaises(setup.SetupError):
                    setup.configure(home, env)
                self.assertFalse((home / ".m2").exists())

            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            settings.write_bytes(b"<settings><servers/></settings>")
            with self.assertRaisesRegex(setup.SetupError, "MAVEN_PASSWORD"):
                setup.configure(home, {"MAVEN_USERNAME": "user"})
            self.assertEqual(settings.read_bytes(), b"<settings><servers/></settings>")

    def test_rejects_invalid_xml_and_doctype_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            for original in (b"", b"<settings><servers>", b'<!DOCTYPE settings [<!ENTITY x "secret">]><settings/>'):
                settings.write_bytes(original)
                with self.assertRaises(setup.SetupError):
                    setup.configure(home, self.credentials)
                self.assertEqual(settings.read_bytes(), original)

    def test_self_closing_and_prefixed_settings_remain_valid(self):
        for original in (
            b"<settings/>",
            b"<settings><servers/></settings>",
            b'<m:settings xmlns:m="http://maven.apache.org/SETTINGS/1.0.0"><m:servers/></m:settings>',
        ):
            with self.subTest(original=original):
                updated, changed = setup.update_settings(original)
                self.assertTrue(changed)
                root = ElementTree.fromstring(updated)
                self.assertEqual(len(root.findall(".//{*}server")), 1)
                self.assertEqual(setup.update_settings(updated), (updated, False))

    @patch("scripts.setup_maven_credentials.platform.system", return_value="Darwin")
    @patch("scripts.setup_maven_credentials.validate_gh")
    @patch("scripts.setup_maven_credentials.subprocess.run")
    def test_optional_gh_integration_stores_command_not_token(self, run, validate, _system):
        run.return_value.returncode = 0
        run.return_value.stdout = "secret-token\n"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            home.joinpath(".zshrc").write_text("export EDITOR=vim\n")
            changed = setup.configure(home, {"MAVEN_USERNAME": "utvikler", "SHELL": "/bin/zsh"}, use_gh_token=True)

            self.assertEqual(changed, [home / ".m2" / "settings.xml", home / ".zshrc"])
            self.assertIn("export EDITOR=vim", home.joinpath(".zshrc").read_text())
            self.assertIn('export MAVEN_PASSWORD="$(gh auth token)"', home.joinpath(".zshrc").read_text())
            self.assertNotIn("secret-token", home.joinpath(".zshrc").read_text())
            self.assertNotIn("secret-token", home.joinpath(".m2/settings.xml").read_text())
            validate.assert_called_once_with()

    @patch("scripts.setup_maven_credentials.platform.system", return_value="Darwin")
    @patch("scripts.setup_maven_credentials.validate_gh")
    @patch("scripts.setup_maven_credentials.subprocess.run")
    def test_gh_error_does_not_modify_files_or_print_token(self, run, validate, _system):
        run.return_value.returncode = 1
        run.return_value.stdout = "secret-token\n"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaisesRegex(setup.SetupError, "kunne ikke hente token"):
                    setup.configure(home, {"MAVEN_USERNAME": "user", "SHELL": "/bin/zsh"}, use_gh_token=True)
            self.assertNotIn("secret-token", stderr.getvalue())
            self.assertFalse(home.joinpath(".m2").exists())
            self.assertFalse(home.joinpath(".zshrc").exists())

    def test_conflicting_shell_export_prevents_any_change(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            home.joinpath(".zshrc").write_text("export MAVEN_PASSWORD=existing\n")
            with patch("scripts.setup_maven_credentials.platform.system", return_value="Darwin"), patch("scripts.setup_maven_credentials.validate_gh"), patch(
                "scripts.setup_maven_credentials.subprocess.run"
            ) as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "secret-token\n"
                with self.assertRaisesRegex(setup.SetupError, "allerede MAVEN_PASSWORD"):
                    setup.configure(home, {"MAVEN_USERNAME": "user", "SHELL": "/bin/zsh"}, use_gh_token=True)
            self.assertFalse(home.joinpath(".m2").exists())

    def test_gh_integration_rejects_unsupported_shell_without_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.setup_maven_credentials.platform.system", return_value="Darwin"
        ):
            home = Path(directory)
            with self.assertRaisesRegex(setup.SetupError, "macOS med zsh"):
                setup.configure(home, {"MAVEN_USERNAME": "user", "SHELL": "/bin/bash"}, use_gh_token=True)
            self.assertFalse(home.joinpath(".m2").exists())


if __name__ == "__main__":
    unittest.main()
