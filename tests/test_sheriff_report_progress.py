from __future__ import annotations

import io
import importlib.util
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location(
    "nais_vulnerability_report",
    SCRIPTS_DIR / "nais-vulnerability-report.py",
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
print_progress_table = module.print_progress_table
repository_commands = module.repository_commands


class SheriffReportProgressTest(unittest.TestCase):
    def test_displays_completed_repository_in_progress_table(self) -> None:
        report = {
            "repositories": {
                "example": {
                    "github": {
                        "dependabot": {"status": "ok", "items": []},
                        "code-scanning": {"status": "ok", "items": []},
                        "secret-scanning": {"status": "ok", "items": []},
                    },
                    "dependabot_prs": {"status": "ok", "items": []},
                }
            }
        }
        output = io.StringIO()

        with redirect_stdout(output):
            print_progress_table(report, 2, "navikt/next")

        self.assertIn("Sheriff-rapport (1/2 repoer ferdig)", output.getvalue())
        self.assertIn("example", output.getvalue())
        self.assertIn("Henter: navikt/next", output.getvalue())

    def test_groups_report_commands_by_repository(self) -> None:
        report = {
            "scope": {"repositories": [{"org": "navikt", "name": "first"}]},
            "progress": [
                {"label": "navikt/first / dependabot", "command": "gh api first"},
                {"label": "navikt/second / dependabot", "command": "gh api second"},
            ],
        }

        slug, commands = repository_commands(report, "first")

        self.assertEqual("navikt/first", slug)
        self.assertEqual(["gh api first"], commands)

    def test_shows_all_active_repository_commands_with_progress(self) -> None:
        report = {
            "progress": [
                {"label": "navikt/example / dependabot", "command": "gh api dependabot"},
                {"label": "navikt/example / PR-er", "command": "gh pr list"},
            ],
            "repositories": {},
        }
        module.start_repository_progress(report, 1, {"org": "navikt", "name": "example", "environments": []})
        output = io.StringIO()

        with redirect_stdout(output):
            module.show_active_repository_commands()

        self.assertIn("navikt/example — Kommando 2/5", output.getvalue())
        self.assertIn("1/5  gh api dependabot", output.getvalue())
        self.assertIn("2/5  gh pr list", output.getvalue())

    def test_maps_naissummary_workload_to_repository(self) -> None:
        report = {
            "nais": {
                "infotek": {
                    "summary": {
                        "status": "ok",
                        "summary": {"workloads": [{"applicationName": "example", "critical": 2, "high": 3}]},
                    },
                    "vulnerabilities": {"status": "ok", "items": []},
                }
            }
        }

        self.assertEqual((2, 3), module.nais_alert_counts(report, {"name": "example", "namespace": "infotek"}))

    def test_stops_when_nais_authentication_is_required(self) -> None:
        with self.assertRaises(module.NaisAuthenticationRequired):
            module.nais_result(1, "", "WARNING: You must (re-)authenticate to run this command.", "summary")

    def test_can_mark_all_nais_teams_as_skipped(self) -> None:
        results = module.skipped_nais_results(("infotek", "historisk"))

        self.assertEqual("skipped", results["infotek"]["summary"]["status"])
        self.assertEqual("skipped", results["historisk"]["vulnerabilities"]["status"])

    def test_offers_interactive_login_when_nais_is_installed(self) -> None:
        with patch.object(module, "choose", return_value="login") as mocked_choose:
            self.assertEqual("login", module.choose_naisscope(can_login=True))

        self.assertIn(("login", "Logg inn i Nais nå", "l"), mocked_choose.call_args.args[1])

    def test_does_not_offer_login_when_nais_cli_is_missing(self) -> None:
        with patch.object(module, "choose", return_value="skip") as mocked_choose:
            self.assertEqual("skip", module.choose_naisscope(can_login=False))

        self.assertNotIn(("login", "Logg inn i Nais nå", "l"), mocked_choose.call_args.args[1])

    def test_marks_skipped_nais_data_in_summary(self) -> None:
        report = {
            "nais": {
                "infotek": {
                    "summary": {"status": "skipped"},
                    "vulnerabilities": {"status": "skipped", "items": []},
                }
            }
        }
        output = io.StringIO()

        with redirect_stdout(output):
            module.print_nais_summary(report)

        self.assertIn("HOPPET OVER", output.getvalue())


if __name__ == "__main__":
    unittest.main()
