import contextlib
import io
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import setup_node_package_token


class SetupNodePackageTokenTest(unittest.TestCase):
    def test_configure_creates_zshrc_and_npmrc(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            changed = setup_node_package_token.configure(home)

            self.assertEqual(changed, [home / ".zshrc", home / ".npmrc"])
            self.assertEqual(
                (home / ".zshrc").read_text(),
                setup_node_package_token.ZSHRC_BLOCK,
            )
            self.assertEqual(
                (home / ".npmrc").read_text(),
                "@navikt:registry=https://npm.pkg.github.com/\n"
                "@nais:registry=https://npm.pkg.github.com/\n"
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n",
            )
            self.assertEqual(
                stat.S_IMODE((home / ".zshrc").stat().st_mode),
                stat.S_IRUSR | stat.S_IWUSR,
            )

    def test_configure_replaces_existing_block_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".zshrc").write_text(
                "export EDITOR=vim\n"
                f"{setup_node_package_token.ZSHRC_MARKER_START}\n"
                "export NODE_AUTH_TOKEN=old\n"
                f"{setup_node_package_token.ZSHRC_MARKER_END}\n"
            )

            setup_node_package_token.configure(home)
            setup_node_package_token.configure(home)

            content = (home / ".zshrc").read_text()
            self.assertEqual(content.count("export NODE_AUTH_TOKEN="), 1)
            self.assertIn("export EDITOR=vim", content)
            self.assertIn('"$(gh auth token)"', content)

    def test_configure_normalizes_old_token_variables_and_preserves_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".npmrc").write_text(
                "registry=https://registry.npmjs.org/\n"
                "@navikt:registry=https://npm.pkg.github.com\n"
                "//npm.pkg.github.com/:_authToken=${NPM_TOKEN}\n"
                "ignore-scripts=true\n"
            )

            setup_node_package_token.configure(home)

            content = (home / ".npmrc").read_text()
            self.assertIn("registry=https://registry.npmjs.org/", content)
            self.assertIn("ignore-scripts=true", content)
            self.assertIn(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}",
                content,
            )
            self.assertNotIn("${NPM_TOKEN}", content)
            self.assertIn(
                "@nais:registry=https://npm.pkg.github.com/",
                content,
            )

    def test_configure_removes_duplicate_github_package_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".npmrc").write_text(
                "@navikt:registry=https://npm.pkg.github.com\n"
                "@navikt:registry=https://npm.pkg.github.com/\n"
                "//npm.pkg.github.com/:_authToken=${GITHUB_PACKAGES_TOKEN}\n"
                "//npm.pkg.github.com/:_authToken=${NPM_TOKEN}\n"
            )

            setup_node_package_token.configure(home)

            content = (home / ".npmrc").read_text()
            self.assertEqual(content.count("@navikt:registry="), 1)
            self.assertEqual(
                content.count("//npm.pkg.github.com/:_authToken="),
                1,
            )
            self.assertNotIn("GITHUB_PACKAGES_TOKEN", content)

    def test_dry_run_changes_no_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            npmrc = home / ".npmrc"
            npmrc.write_text("ignore-scripts=true\n")

            changed = setup_node_package_token.configure(home, dry_run=True)

            self.assertEqual(changed, [home / ".zshrc", npmrc])
            self.assertFalse((home / ".zshrc").exists())
            self.assertEqual(npmrc.read_text(), "ignore-scripts=true\n")

    def test_configure_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            setup_node_package_token.configure(home)
            zshrc = (home / ".zshrc").read_bytes()
            npmrc = (home / ".npmrc").read_bytes()

            changed = setup_node_package_token.configure(home)

            self.assertEqual(changed, [])
            self.assertEqual((home / ".zshrc").read_bytes(), zshrc)
            self.assertEqual((home / ".npmrc").read_bytes(), npmrc)

    def test_configure_does_not_create_maven_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            setup_node_package_token.configure(home)

            self.assertFalse((home / ".m2").exists())

    def test_configure_rejects_unbalanced_zshrc_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            zshrc = home / ".zshrc"
            original = (
                f"{setup_node_package_token.ZSHRC_MARKER_START}\n"
                "export EDITOR=vim\n"
            )
            zshrc.write_text(original)

            with self.assertRaises(setup_node_package_token.SetupError):
                setup_node_package_token.configure(home)

            self.assertEqual(zshrc.read_text(), original)
            self.assertFalse((home / ".npmrc").exists())

    def test_atomic_write_updates_symlink_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "dotfiles" / "zshrc"
            target.parent.mkdir()
            target.write_text("old\n")
            link = root / ".zshrc"
            link.symlink_to(target)

            setup_node_package_token.atomic_write(link, "new\n")

            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), "new\n")

    def test_detects_unmanaged_token_export(self):
        self.assertTrue(
            setup_node_package_token.has_unmanaged_token_export(
                "export NODE_AUTH_TOKEN=old-token\n"
                f"{setup_node_package_token.ZSHRC_BLOCK}"
            )
        )
        self.assertFalse(
            setup_node_package_token.has_unmanaged_token_export(
                setup_node_package_token.ZSHRC_BLOCK
            )
        )

    @patch("scripts.setup_node_package_token.shutil.which", return_value="/usr/bin/gh")
    @patch("scripts.setup_node_package_token.subprocess.run")
    def test_validate_gh_accepts_authenticated_cli(self, run, _which):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess(
                [],
                0,
                "HTTP/2 200\nx-oauth-scopes: repo, read:packages\n\n",
                "",
            ),
            subprocess.CompletedProcess([], 0, "secret-token\n", ""),
        ]

        setup_node_package_token.validate_gh()

        self.assertEqual(run.call_count, 3)

    @patch("scripts.setup_node_package_token.shutil.which", return_value="/usr/bin/gh")
    @patch("scripts.setup_node_package_token.subprocess.run")
    def test_validate_gh_rejects_missing_read_packages_scope(self, run, _which):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess(
                [],
                0,
                "HTTP/2 200\nx-oauth-scopes: repo\n\n",
                "",
            ),
        ]

        with self.assertRaisesRegex(
            setup_node_package_token.SetupError,
            "mangler read:packages",
        ):
            setup_node_package_token.validate_gh()

    @patch("scripts.setup_node_package_token.shutil.which", return_value="/usr/bin/gh")
    @patch("scripts.setup_node_package_token.subprocess.run")
    def test_validate_gh_does_not_include_token_in_error(self, run, _which):
        token = "secret-token"
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess(
                [],
                0,
                "HTTP/2 200\nx-oauth-scopes: read:packages\n\n",
                "",
            ),
            subprocess.CompletedProcess([], 1, token, token),
        ]

        with self.assertRaises(setup_node_package_token.SetupError) as error:
            setup_node_package_token.validate_gh()

        self.assertNotIn(token, str(error.exception))

    @patch("scripts.setup_node_package_token.configure")
    @patch("scripts.setup_node_package_token.validate_gh")
    @patch(
        "scripts.setup_node_package_token.parse_args",
        return_value=type("Args", (), {"dry_run": False})(),
    )
    def test_main_stops_before_file_changes_when_validation_fails(
        self,
        _parse_args,
        validate_gh,
        configure,
    ):
        validate_gh.side_effect = setup_node_package_token.SetupError("ingen token")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            result = setup_node_package_token.main()

        self.assertEqual(result, 1)
        configure.assert_not_called()
        self.assertNotIn("secret-token", stderr.getvalue())

    def test_atomic_write_preserves_existing_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".npmrc"
            path.write_text("old\n")
            path.chmod(0o640)

            setup_node_package_token.atomic_write(path, "new\n")

            self.assertEqual(path.read_text(), "new\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)


if __name__ == "__main__":
    unittest.main()
