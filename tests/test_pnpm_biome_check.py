import importlib.util
import shutil
import sys
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parent.parent / "scripts" / "pnpm-biome-check.py"
SPEC = importlib.util.spec_from_file_location("pnpm_biome_check", SCRIPT)
biome_check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = biome_check
SPEC.loader.exec_module(biome_check)


class PnpmBiomeCheckTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / ".pnpm_biome_check_testdata" / uuid.uuid4().hex
        self.repos = self.root / "repos"
        self.repos.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root.parent, ignore_errors=True)
        self.repos_file = self.root / "repos.yaml"
        self.repos_file.write_text(
            "repos:\n"
            "  - name: managed-app\n    managed: true\n"
            "  - name: bff-app\n    managed: true\n"
            "  - name: unmanaged-app\n"
            "  - name: excluded-app\n    managed: false\n"
        )
        self.make_frontend("managed-app", "frontend")
        self.make_frontend("bff-app", "backend-for-frontend/frontend")
        self.make_frontend("unmanaged-app", "frontend")
        self.make_frontend("excluded-app", "frontend")

    def make_frontend(self, repo: str, relative: str) -> None:
        (self.repos / repo / ".git").mkdir(parents=True)
        frontend = self.repos / repo / relative
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text("{}")

    def test_checks_only_managed_repos(self):
        checked = []
        with patch.object(biome_check, "REPOS_DIR", self.repos), \
                patch.object(biome_check, "REPOS_FILE", self.repos_file), \
                patch.object(biome_check, "check_repo", side_effect=lambda repo: checked.append(repo.name) or (0, 0)), \
                redirect_stdout(StringIO()):
            biome_check.main()

        self.assertEqual(checked, ["bff-app", "managed-app"])

    def test_finds_frontend_under_backend_for_frontend(self):
        frontend = biome_check.find_frontend(self.repos / "bff-app")

        self.assertEqual(frontend, self.repos / "bff-app" / "backend-for-frontend" / "frontend")


if __name__ == "__main__":
    unittest.main()
