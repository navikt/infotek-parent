import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import setup_github_packages as setup
from scripts import setup_node_package_token

TOKEN = "ghp_" + "x" * 36
ENV_SERVER = (
    b"<settings><servers><server><id>github</id>"
    b"<username>${env.MAVEN_USERNAME}</username>"
    b"<password>${env.MAVEN_PASSWORD}</password>"
    b"</server></servers></settings>"
)


def run_main(home: Path, *args: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch("scripts.setup_github_packages.Path.home", return_value=home), patch(
        "sys.argv", ["setup_github_packages", *args]
    ), patch("scripts.setup_github_packages.node.validate_gh"), contextlib.redirect_stdout(
        stdout
    ), contextlib.redirect_stderr(stderr):
        result = setup.main()
    return result, stdout.getvalue(), stderr.getvalue()


class NpmrcWarningsTest(unittest.TestCase):
    def test_accepts_environment_reference(self):
        self.assertEqual(
            setup.npmrc_warnings("//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"),
            [],
        )

    def test_warns_about_direct_github_token_without_showing_it(self):
        warnings = setup.npmrc_warnings(f"//npm.pkg.github.com/:_authToken={TOKEN}\n")

        self.assertEqual(len(warnings), 1)
        self.assertIn("npm.pkg.github.com", warnings[0])
        self.assertIn("${NODE_AUTH_TOKEN}", warnings[0])
        self.assertNotIn(TOKEN, warnings[0])

    def test_warns_about_direct_token_for_other_registry(self):
        warnings = setup.npmrc_warnings(f"//registry.npmjs.org/:_authToken={TOKEN}\n")

        self.assertEqual(len(warnings), 1)
        self.assertIn("//registry.npmjs.org", warnings[0])
        self.assertNotIn(TOKEN, warnings[0])


class ZshrcWarningsTest(unittest.TestCase):
    def test_ignores_managed_blocks_and_references(self):
        content = (
            setup_node_package_token.ZSHRC_BLOCK
            + "export MAVEN_PASSWORD=\"$(gh auth token)\"\n"
            + "export NODE_AUTH_TOKEN=$GITHUB_TOKEN\n"
        )

        self.assertEqual(setup.zshrc_warnings(content), [])

    def test_warns_about_direct_token_exports(self):
        warnings = setup.zshrc_warnings(
            f"export NODE_AUTH_TOKEN={TOKEN}\nexport MAVEN_PASSWORD='{TOKEN}'\n"
        )

        self.assertEqual(len(warnings), 2)
        self.assertNotIn(TOKEN, "".join(warnings))


class MavenWarningsTest(unittest.TestCase):
    def test_accepts_environment_references(self):
        self.assertEqual(setup.maven_warnings(ENV_SERVER), [])

    def test_warns_about_direct_credentials_without_showing_them(self):
        data = (
            b"<settings><servers><server><id>github</id>"
            b"<username>utvikler</username><password>" + TOKEN.encode() + b"</password>"
            b"</server></servers></settings>"
        )

        warnings = setup.maven_warnings(data)

        self.assertEqual(len(warnings), 2)
        self.assertIn("${env.MAVEN_USERNAME}", warnings[0])
        self.assertIn("${env.MAVEN_PASSWORD}", warnings[1])
        self.assertNotIn(TOKEN, "".join(warnings))
        self.assertNotIn("utvikler", "".join(warnings))

    def test_warns_about_reference_without_env_prefix(self):
        data = (
            b"<settings><servers><server><id>github</id>"
            b"<username>${env.MAVEN_USERNAME}</username>"
            b"<password>${MAVEN_PASSWORD}</password>"
            b"</server></servers></settings>"
        )

        warnings = setup.maven_warnings(data)

        self.assertEqual(len(warnings), 1)
        self.assertIn("env.-prefiks", warnings[0])

    def test_ignores_other_servers_and_encrypted_password(self):
        data = (
            b'<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"><servers>'
            b"<server><id>other</id><password>plain</password></server>"
            b"<server><id>github</id><username>${env.MAVEN_USERNAME}</username>"
            b"<password>{COQLCE6DU6GtcS5P=}</password></server>"
            b"</servers></settings>"
        )

        self.assertEqual(setup.maven_warnings(data), [])


class MainTest(unittest.TestCase):
    def test_existing_env_server_reports_ok_without_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            settings.write_bytes(ENV_SERVER)

            result, stdout, stderr = run_main(home, "--only", "maven")

            self.assertEqual(result, 0)
            self.assertIn("leses fra miljøvariabler", stdout)
            self.assertEqual(stderr, "")
            self.assertEqual(settings.read_bytes(), ENV_SERVER)

    def test_existing_server_with_token_warns_without_changing_or_printing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".m2" / "settings.xml"
            settings.parent.mkdir()
            original = (
                b"<settings><servers><server><id>github</id>"
                b"<password>" + TOKEN.encode() + b"</password>"
                b"</server></servers></settings>"
            )
            settings.write_bytes(original)

            result, stdout, stderr = run_main(home, "--only", "maven")

            self.assertEqual(result, 0)
            self.assertIn("Advarsel:", stderr)
            self.assertNotIn(TOKEN, stdout + stderr)
            self.assertEqual(settings.read_bytes(), original)

    def test_node_warns_about_direct_npmrc_token_and_replaces_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            npmrc = home / ".npmrc"
            npmrc.write_text(f"//npm.pkg.github.com/:_authToken={TOKEN}\n")

            result, stdout, stderr = run_main(home, "--only", "node")

            self.assertEqual(result, 0)
            self.assertIn("Advarsel:", stderr)
            self.assertNotIn(TOKEN, stdout + stderr)
            self.assertNotIn(TOKEN, npmrc.read_text())
            self.assertIn("${NODE_AUTH_TOKEN}", npmrc.read_text())

    def test_runs_both_parts_and_reports_failure_per_part(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {}, clear=True
        ):
            home = Path(directory)

            result, stdout, stderr = run_main(home)

            self.assertEqual(result, 1)
            self.assertIn(f"Oppdaterte {home / '.npmrc'}", stdout)
            self.assertIn("Feil (Maven): Sett MAVEN_USERNAME", stderr)
            self.assertFalse((home / ".m2").exists())

    def test_stops_node_part_before_file_changes_when_gh_validation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            stderr = io.StringIO()
            with patch("scripts.setup_github_packages.Path.home", return_value=home), patch(
                "sys.argv", ["setup_github_packages", "--only", "node"]
            ), patch(
                "scripts.setup_github_packages.node.validate_gh",
                side_effect=setup.SetupError("ingen token"),
            ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                self.assertEqual(setup.main(), 1)

            self.assertIn("Feil (npm/pnpm): ingen token", stderr.getvalue())
            self.assertFalse((home / ".npmrc").exists())
            self.assertFalse((home / ".zshrc").exists())


if __name__ == "__main__":
    unittest.main()
