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

    def test_filters_scope_to_requested_managed_repositories(self) -> None:
        repositories = [
            {"org": "navikt", "name": "first"},
            {"org": "navikt", "name": "second"},
        ]

        selected = module.select_repositories(repositories, ["navikt/second"])

        self.assertEqual([{"org": "navikt", "name": "second"}], selected)

    def test_rejects_unknown_repository_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown"):
            module.select_repositories([{"org": "navikt", "name": "first"}], ["navikt/unknown"])

    def test_nais_summary_counts_only_managed_repository_workloads(self) -> None:
        report = {
            "scope": {
                "repositories": [
                    {"name": "genie", "namespace": "infotek", "nais_workloads": ["genie-pdfgen"]},
                    {"name": "brukeroppslag", "namespace": "infotek"},
                ]
            },
            "nais": {
                "infotek": {
                    "summary": {
                        "status": "ok",
                        "summary": [
                            {"workload_name": "genie", "critical": 1, "high": 1, "medium": 0, "low": 0},
                            {"workload_name": "genie-pdfgen", "critical": 2, "high": 0, "medium": 0, "low": 0},
                            {"workload_name": "brukeroppslag-backend", "critical": 0, "high": 3, "medium": 0, "low": 0},
                            {"workload_name": "arkivert-app", "critical": 9, "high": 9, "medium": 9, "low": 9},
                        ],
                    },
                    "vulnerabilities": {
                        "status": "ok",
                        "items": [{"workload_name": "genie-pdfgen"}, {"workload_name": "arkivert-app"}],
                    },
                }
            },
        }

        totals = module.managed_nais_totals(report, "infotek", report["nais"]["infotek"])

        self.assertEqual(3, totals["critical"])
        self.assertEqual(4, totals["high"])
        self.assertEqual(1, totals["findings"])
        self.assertEqual(["brukeroppslag-backend", "genie", "genie-pdfgen"], totals["workloads"])

    def test_repository_alert_counts_use_nais_workload_name(self) -> None:
        report = {
            "nais": {
                "infotrygd": {
                    "summary": {
                        "status": "ok",
                        "summary": [
                            {"workload_name": "hentsaksliste-backend", "critical": 1, "high": 2},
                            {"workload_name": "hentsaksliste-frontend", "critical": 0, "high": 1},
                        ],
                    },
                    "vulnerabilities": {"status": "ok", "items": []},
                }
            }
        }

        self.assertEqual((1, 3), module.nais_alert_counts(report, {"name": "hentsaksliste", "namespace": "infotrygd"}))

    def test_dependabot_prs_include_status_from_pr_view(self) -> None:
        listed = {"status": "ok", "items": [{"number": 7, "title": "Bump x", "user": {"login": "dependabot[bot]"}}]}
        details = (
            '{"baseRefName": "main", "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", '
            '"reviewDecision": "APPROVED", "statusCheckRollup": '
            '[{"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"}]}'
        )

        with (
            patch.object(module, "list_open_pull_requests", return_value=listed),
            patch.object(module, "run", return_value=(0, details, "")),
        ):
            result = module.fetch_dependabot_prs({"org": "navikt", "name": "example"}, [])

        pr = result["items"][0]
        self.assertEqual("main", pr["baseRefName"])
        self.assertEqual("MERGEABLE", pr["mergeable"])
        self.assertEqual("CLEAN", pr["mergeStateStatus"])
        self.assertEqual("APPROVED", pr["reviewDecision"])
        self.assertEqual("SUCCESS", pr["statusCheckRollup"][0]["conclusion"])


if __name__ == "__main__":
    unittest.main()
