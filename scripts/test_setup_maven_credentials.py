import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from scripts import setup_maven_credentials as setup

TOKEN = "ghp_" + "x" * 36


def gh_login(login="utvikler", returncode=0):
    return patch(
        "scripts.setup_maven_credentials.subprocess.run",
        return_value=type("Result", (), {"returncode": returncode, "stdout": f"{login}\n"})(),
    )


class SetupMavenCredentialsTest(unittest.TestCase):
    def setUp(self):
        validate = patch("scripts.setup_maven_credentials.validate_gh")
        self.validate = validate.start()
        self.addCleanup(validate.stop)

    def test_creates_settings_and_zshrc_with_references_not_credentials(self):
        with tempfile.TemporaryDirectory() as directory, gh_login():
            home = Path(directory)
            home.joinpath(".zshrc").write_text("export EDITOR=vim\n")

            changed = setup.configure(home)

            settings = home / ".m2" / "settings.xml"
            zshrc = home / ".zshrc"
            self.assertEqual(changed, [settings, zshrc])
            server = ElementTree.fromstring(settings.read_text()).find("./servers/server")
            self.assertEqual(server.findtext("id"), "github")
            self.assertEqual(server.findtext("username"), "${env.MAVEN_USERNAME}")
            self.assertEqual(server.findtext("password"), "${env.MAVEN_PASSWORD}")
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
            content = zshrc.read_text()
            self.assertIn("export EDITOR=vim", content)
            self.assertIn('export MAVEN_USERNAME="utvikler"', content)
            self.assertIn('export MAVEN_PASSWORD="$(gh auth token)"', content)
            self.validate.assert_called_once_with()

    def test_preserves_other_servers_and_original_content(self):
        with tempfile.TemporaryDirectory() as directory, gh_login():
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

            setup.configure(home)

            content = settings.read_bytes()
            self.assertIn(original[: original.index(b"  </servers>")], content)
            root = ElementTree.fromstring(content)
            ns = {"m": "http://maven.apache.org/SETTINGS/1.0.0"}
            ids = [node.text for node in root.findall("./m:servers/m:server/m:id", ns)]
            self.assertEqual(ids, ["other", "github"])

    def test_existing_github_server_is_unchanged_but_zshrc_is_added(self):
        with tempfile.TemporaryDirectory() as directory, gh_login():
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            original = b"<settings><servers><server><id>github</id><password>keep</password></server></servers></settings>"
            settings.write_bytes(original)

            self.assertEqual(setup.configure(home), [home / ".zshrc"])
            self.assertEqual(settings.read_bytes(), original)

    def test_repeated_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, gh_login():
            home = Path(directory)
            setup.configure(home)
            settings = (home / ".m2" / "settings.xml").read_bytes()
            zshrc = (home / ".zshrc").read_text()

            self.assertEqual(setup.configure(home), [])
            self.assertEqual((home / ".m2" / "settings.xml").read_bytes(), settings)
            self.assertEqual((home / ".zshrc").read_text(), zshrc)

    def test_gh_failure_changes_no_files(self):
        with tempfile.TemporaryDirectory() as directory, gh_login(TOKEN, returncode=1):
            home = Path(directory)
            with self.assertRaisesRegex(setup.SetupError, "gh auth status") as error:
                setup.configure(home)
            self.assertNotIn(TOKEN, str(error.exception))
            self.assertFalse((home / ".m2").exists())
            self.assertFalse((home / ".zshrc").exists())

    def test_rejects_unsafe_username_from_gh(self):
        with tempfile.TemporaryDirectory() as directory, gh_login('x"; rm -rf ~'):
            home = Path(directory)
            with self.assertRaisesRegex(setup.SetupError, "Ugyldig GitHub-brukernavn"):
                setup.configure(home)
            self.assertFalse((home / ".zshrc").exists())

    def test_rejects_invalid_xml_and_doctype_without_changes(self):
        with tempfile.TemporaryDirectory() as directory, gh_login():
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            for original in (b"", b"<settings><servers>", b'<!DOCTYPE settings [<!ENTITY x "secret">]><settings/>'):
                settings.write_bytes(original)
                with self.assertRaises(setup.SetupError):
                    setup.configure(home)
                self.assertEqual(settings.read_bytes(), original)
            self.assertFalse((home / ".zshrc").exists())

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

    def test_conflicting_shell_export_prevents_any_change(self):
        with tempfile.TemporaryDirectory() as directory, gh_login():
            home = Path(directory)
            original = f"export MAVEN_PASSWORD={TOKEN}\n"
            home.joinpath(".zshrc").write_text(original)
            with self.assertRaisesRegex(setup.SetupError, "allerede MAVEN_PASSWORD"):
                setup.configure(home)
            self.assertFalse(home.joinpath(".m2").exists())
            self.assertEqual(home.joinpath(".zshrc").read_text(), original)


if __name__ == "__main__":
    unittest.main()
