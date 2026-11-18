from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location(
    "sheriff_interactive",
    SCRIPTS_DIR / "sheriff-interactive.py",
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SheriffDiffTest(unittest.TestCase):
    def test_full_diff_uses_same_colorization_as_preview(self) -> None:
        colored = module.colorize_diff(["-removed", "+added", "@@ section", " context"])

        self.assertIn("\033[31m", colored)
        self.assertIn("\033[32m", colored)
        self.assertIn("\033[36m", colored)

    def test_full_diff_shows_all_lines_without_truncation(self) -> None:
        many_lines = "\n".join(f"+line{i}" for i in range(50))

        result = module.format_diff_full(many_lines)

        self.assertEqual(50, result.count("\n") + 1)
        self.assertNotIn("Vis full diff", result)

    def test_full_diff_reports_when_empty(self) -> None:
        self.assertIn("Ingen diff tilgjengelig", module.format_diff_full(""))

    def test_candidate_table_lists_critical_and_high_alert_counts(self) -> None:
        candidate = module.Candidate(
            "navikt",
            "example",
            {"number": 1, "title": "Bump dependency", "author": {"login": "dependabot[bot]"}},
        )
        report = {
            "repositories": {
                "example": {
                    "github": {
                        "dependabot": {
                            "items": [
                                {"state": "open", "severity": "critical", "cve": "CVE-2026-1000"},
                                {"state": "open", "severity": "high", "cve": "CVE-2026-2000"},
                            ]
                        }
                    }
                }
            }
        }

        self.assertEqual((1, 1), module.alert_counts(report, candidate))

    def test_candidate_table_truncates_title_for_80_column_terminal(self) -> None:
        candidate = module.Candidate(
            "navikt",
            "example",
            {"number": 1, "title": "A very long dependency update title that must remain on one table row"},
        )

        headers, rows = module.candidate_table_rows({}, [(candidate, False, False)])

        self.assertEqual(("Prioritet", "Repo", "PR", "Tittel", "GH C/H", "Nais C/H"), headers)
        self.assertEqual("A very long dependency update title that must remain on one table row", rows[0][3])

    def test_candidate_table_displays_unavailable_nais_data_as_dashes(self) -> None:
        candidate = module.Candidate("navikt", "example", {"number": 1, "title": "Bump dependency"})

        _, rows = module.candidate_table_rows({}, [(candidate, False, False)])

        self.assertEqual("-/-", rows[0][-1])

    def test_rejects_outdated_report_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "sheriff-report.json"
            report.write_text('{"schema_version": 1}')

            with self.assertRaisesRegex(RuntimeError, "feil versjon"):
                module.load_report(report)

    def test_reconcile_blocked_entries_handles_conflicting_status_without_crash(self) -> None:
        """Regresjonstest: 'ready_to_merge' må være definert for alle statusgrener,
        ellers krasjer sheriff med UnboundLocalError for CONFLICTING/BLOCKED/BEHIND-PR-er."""
        state = {
            "prs": {
                "navikt/example#1": {
                    "status": module.STATUS_BLOCKED,
                    "org": "navikt",
                    "repo": "example",
                    "number": 1,
                    "base_ref": "main",
                    "title": "Bump dependency",
                    "url": "https://example/1",
                    "error": "Konflikt med base-branch.",
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with (
                patch.object(module, "managed_slugs", return_value=frozenset({"navikt/example"})),
                patch.object(
                    module,
                    "fetch_pr_status",
                    return_value={"mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY", "state": "OPEN"},
                ),
            ):
                module.reconcile_blocked_entries(state, state_path, interactive=False)

        self.assertEqual(module.STATUS_BLOCKED, state["prs"]["navikt/example#1"]["status"])

    def test_blocked_entry_for_unmanaged_repository_is_not_checked(self) -> None:
        state = {
            "prs": {
                "navikt/archived#79": {
                    "status": module.STATUS_BLOCKED,
                    "org": "navikt",
                    "repo": "archived",
                    "number": 79,
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(module, "managed_slugs", return_value=frozenset({"navikt/example"})),
                patch.object(module, "fetch_pr_status") as fetch,
            ):
                module.reconcile_blocked_entries(state, Path(directory) / "state.json", interactive=True)

        fetch.assert_not_called()
        self.assertIn("navikt/archived#79", state["prs"])

    def test_pending_count_ignores_unmanaged_repositories(self) -> None:
        state = {
            "prs": {
                "navikt/example#1": {"org": "navikt", "repo": "example", "status": module.STATUS_WAITING_CI},
                "navikt/archived#2": {"org": "navikt", "repo": "archived", "status": module.STATUS_WAITING_CI},
            }
        }

        with patch.object(module, "managed_slugs", return_value=frozenset({"navikt/example"})):
            self.assertEqual(1, module.count_pending(state))

    def test_managed_slugs_follow_managed_flag_in_repos_yaml(self) -> None:
        module.managed_slugs.cache_clear()

        slugs = module.managed_slugs()

        self.assertIn("navikt/historisk-pensjon", slugs)
        self.assertNotIn("navikt/historisk-gravferdkalkulator", slugs)

    def test_fresh_report_clears_previous_choices(self) -> None:
        state = {"prs": {"navikt/example#1": {"org": "navikt", "repo": "example", "status": module.STATUS_SKIPPED}}}

        def write_report(command: list[str]) -> module.subprocess.CompletedProcess:
            Path(command[-1]).write_text("{}")
            return module.subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            state_path = Path(directory) / "state.json"
            with (
                patch.object(module, "STATE_PATH", state_path),
                patch.object(module.subprocess, "run", side_effect=write_report),
                patch.object(module, "load_report", return_value={}),
            ):
                module.generate_fresh_report(report_path, state, dry_run=False)

            self.assertEqual({}, state["prs"])
            self.assertEqual({"prs": {}}, module.load_state(state_path))

    def test_failed_fresh_report_keeps_previous_choices(self) -> None:
        state = {"prs": {"navikt/example#1": {"org": "navikt", "repo": "example", "status": module.STATUS_SKIPPED}}}
        completed = module.subprocess.CompletedProcess([], 1)

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(module, "STATE_PATH", Path(directory) / "state.json"),
                patch.object(module.subprocess, "run", return_value=completed),
                self.assertRaises(RuntimeError),
            ):
                module.generate_fresh_report(Path(directory) / "report.json", state, dry_run=False)

        self.assertIn("navikt/example#1", state["prs"])

    def test_exit_alt_screen_is_imported_and_callable(self) -> None:
        """Regresjonstest: exit_alt_screen() kalles flere steder i skriptet (normal
        avslutning og krasjhåndtering), men var tidligere ikke importert fra
        terminal_ui — det ga NameError i stedet for ren avslutning."""
        self.assertTrue(callable(module.exit_alt_screen))

    def test_candidate_table_offers_summary_action(self) -> None:
        candidate = module.Candidate("navikt", "example", {"number": 1, "title": "Bump dependency"})
        with patch.object(module, "choose", return_value="summary") as mocked_choose:
            self.assertEqual("summary", module.show_candidate_table({}, [(candidate, False, False)]))

        self.assertIn(("summary", "Vis sammendragsrapport", "o"), mocked_choose.call_args.args[1])

    def test_candidate_summary_shows_given_pr_status(self) -> None:
        candidate = module.Candidate("navikt", "example", {"number": 346, "title": "Bump group"})
        pr = {
            "title": "Bump group",
            "baseRefName": "main",
            "reviewDecision": "APPROVED",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        }
        output = io.StringIO()

        with patch.object(module, "fetch_pr_diff", return_value=""), redirect_stdout(output):
            module.print_candidate(candidate, pr, 1, 1, False, False)

        self.assertIn("→ main", output.getvalue())
        self.assertIn("grønn", output.getvalue())
        self.assertIn("(1)  ·  review APPROVED", output.getvalue())
        self.assertIn("merge MERGEABLE / CLEAN", output.getvalue())

    def test_candidate_summary_shows_dash_for_missing_merge_status(self) -> None:
        candidate = module.Candidate("navikt", "example", {"number": 346})
        pr = {"title": "Bump group", "mergeable": None, "mergeStateStatus": None}
        output = io.StringIO()

        with patch.object(module, "fetch_pr_diff", return_value=""), redirect_stdout(output):
            module.print_candidate(candidate, pr, 1, 1, False, False)

        self.assertIn("merge - / -", output.getvalue())

    def test_group_pr_is_not_security_relevant_from_substring_alert_matches(self) -> None:
        pr = {
            "title": "chore(deps-dev): bump the npm-minor-patch group in /frontend with 3 updates",
            "body": "Bumps the npm-minor-patch group in /frontend with 3 updates: "
            "[@biomejs/biome](https://x), [@types/node](https://y) and [vite](https://z).\n"
            "Release notes shows how to start the ws server.",
        }

        self.assertFalse(module.is_security_relevant(pr, {"ws", "tar", "ip", "ejs"}))

    def test_group_pr_is_security_relevant_when_updated_package_has_alert(self) -> None:
        pr = {
            "title": "chore(deps-dev): bump the npm-minor-patch group in /frontend with 3 updates",
            "body": "Bumps the npm-minor-patch group in /frontend with 3 updates: "
            "[@biomejs/biome](https://x), [@types/node](https://y) and [vite](https://z).",
        }

        self.assertTrue(module.is_security_relevant(pr, {"vite"}))

    def test_single_bump_title_is_security_relevant_when_package_has_alert(self) -> None:
        pr = {"title": "Bump org.example:lib from 1.0.0 to 1.0.1 in /backend", "body": ""}

        self.assertTrue(module.is_security_relevant(pr, {"org.example:lib"}))

    def test_security_word_only_counts_in_title(self) -> None:
        pr = {"title": "Bump vite from 5.0.0 to 5.0.1", "body": "Fixes a security issue in the dev server."}

        self.assertFalse(module.is_security_relevant(pr, set()))

    def test_security_word_in_package_name_does_not_count(self) -> None:
        pr = {"title": "Bump no.nav.security:token-client-spring from 5.0.1 to 5.0.2", "body": ""}

        self.assertFalse(module.is_security_relevant(pr, set()))

    def test_security_word_in_title_counts(self) -> None:
        pr = {"title": "chore(security): bump vite from 5.0.0 to 5.0.1", "body": ""}

        self.assertTrue(module.is_security_relevant(pr, set()))


if __name__ == "__main__":
    unittest.main()
