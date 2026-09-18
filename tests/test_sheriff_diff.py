from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
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

    def test_preview_only_mentions_full_diff_when_truncated(self) -> None:
        complete = module.format_diff_preview("+one\n-two")
        truncated = module.format_diff_preview("\n".join("+line" for _ in range(module.DIFF_PREVIEW_LINES + 1)))

        self.assertNotIn("Vis full diff", complete)
        self.assertIn(f"viser {module.DIFF_PREVIEW_LINES} av {module.DIFF_PREVIEW_LINES + 1} linjer", truncated)
        self.assertIn("Vis full diff", truncated)

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

    def test_candidate_table_offers_summary_action(self) -> None:
        candidate = module.Candidate("navikt", "example", {"number": 1, "title": "Bump dependency"})
        with patch.object(module, "choose", return_value="summary") as mocked_choose:
            self.assertEqual("summary", module.show_candidate_table({}, [(candidate, False, False)]))

        self.assertIn(("summary", "Vis sammendragsrapport", "o"), mocked_choose.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
