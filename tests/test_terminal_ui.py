from __future__ import annotations

import builtins
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.terminal_ui import REPORT_CHOICE_TIMEOUT_SECONDS, choose, choose_cached_report, choose_checkboxes, choose_table, fit_table


class TerminalUiTest(unittest.TestCase):
    def test_uses_default_when_non_interactive_input_is_closed(self) -> None:
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            with patch.object(builtins, "input", side_effect=EOFError):
                self.assertEqual("fresh", choose("Rapport", [("cached", "Lagret"), ("fresh", "Ny")], 1))

    def test_accepts_numbered_non_interactive_choice(self) -> None:
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            with patch.object(builtins, "input", return_value="2"):
                self.assertEqual("fresh", choose("Rapport", [("cached", "Lagret"), ("fresh", "Ny")]))

    def test_accepts_visible_shortcut(self) -> None:
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            with patch.object(builtins, "input", return_value="f"):
                self.assertEqual("fresh", choose("Rapport", [("cached", "Lagret", "l"), ("fresh", "Ny", "f")]))

    def test_accepts_two_letter_shortcut(self) -> None:
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            with patch.object(builtins, "input", return_value="ny"):
                self.assertEqual("fresh", choose("Rapport", [("cached", "Lagret", "la"), ("fresh", "Ny", "ny")]))

    def test_table_fallback_accepts_numeric_row_selection(self) -> None:
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            with patch.object(builtins, "input", return_value="2"):
                self.assertEqual(
                    "row-1",
                    choose_table("Review", ("PR",), [("1",), ("2",)], (("quit", "Avslutt", "q"),)),
                )

    def test_cached_report_menu_can_exit_when_cache_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.terminal_ui.choose", return_value="quit") as mocked_choose:
                self.assertEqual("quit", choose_cached_report(Path(directory) / "missing.json", "Rapport", lambda: "0 PR-er"))
            self.assertEqual(REPORT_CHOICE_TIMEOUT_SECONDS, mocked_choose.call_args.kwargs["timeout_seconds"])

    def test_cached_report_timeout_defaults_to_fresh_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.touch()
            os.utime(report, (time.time() - 16 * 60, time.time() - 16 * 60))

            with patch("scripts.terminal_ui.choose", return_value="ny") as mocked_choose:
                self.assertEqual("ny", choose_cached_report(report, "Rapport", lambda: "0 PR-er"))

            self.assertEqual(1, mocked_choose.call_args.kwargs["default"])
            self.assertEqual(REPORT_CHOICE_TIMEOUT_SECONDS, mocked_choose.call_args.kwargs["timeout_seconds"])

    def test_fits_wide_review_table_into_80_columns(self) -> None:
        headers, rows, widths = fit_table(
            ("Tast", "Repo", "Branch", "Tittel", "Forfatter", "Status", "GH C/H", "Nais C/H"),
            [("[1]", "historisk-tidsbegrenset-uforestonad", "dependabot/npm_and_yarn/frontend/typescript-6.1.0", "A very long dependency update title", "dependabot[bot]", "CI grønn", "12/32", "3/4")],
            maximum_width=80,
        )

        self.assertLessEqual(sum(widths) + 2 * (len(widths) - 1), 80)
        self.assertTrue(rows[0][3].endswith("…"))

    def test_checkbox_selector_toggles_and_returns_selected_keys(self) -> None:
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            with patch.object(builtins, "input", side_effect=["2", ""]):
                self.assertEqual(
                    ["first"],
                    choose_checkboxes("Repoer", [("first", "Første"), ("second", "Andre")]),
                )

    def test_checkbox_selector_can_be_cancelled(self) -> None:
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            with patch.object(builtins, "input", return_value="q"):
                self.assertIsNone(choose_checkboxes("Repoer", [("first", "Første")]))


if __name__ == "__main__":
    unittest.main()
