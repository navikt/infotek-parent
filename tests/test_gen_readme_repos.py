import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parent.parent / "scripts" / "gen-readme-repos.py"
SPEC = importlib.util.spec_from_file_location("gen_readme_repos", SCRIPT)
gen_readme_repos = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gen_readme_repos
SPEC.loader.exec_module(gen_readme_repos)


class GenerateSectionTest(unittest.TestCase):
    @patch.object(gen_readme_repos, "fetch_github_description", return_value="Testbeskrivelse")
    def test_includes_all_repositories_and_marks_only_unmanaged(self, _fetch_description):
        section = gen_readme_repos.generate_section(
            [
                {
                    "name": "managed-repo",
                    "org": "navikt",
                    "namespace": "infotek",
                    "managed": True,
                    "environments": [],
                },
                {
                    "name": "unmanaged-repo",
                    "org": "navikt",
                    "namespace": "infotek",
                    "managed": False,
                    "environments": [],
                },
            ]
        )

        self.assertIn(
            "| [managed-repo](https://github.com/navikt/managed-repo) |",
            section,
        )
        self.assertIn(
            "| [unmanaged-repo](https://github.com/navikt/unmanaged-repo) ⚠️ |",
            section,
        )


if __name__ == "__main__":
    unittest.main()
