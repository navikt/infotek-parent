from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("pr_behandle", SCRIPTS_DIR / "pr-behandle.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ReviewReportTest(unittest.TestCase):
    def test_loads_open_pull_requests_from_shared_sheriff_report(self) -> None:
        original = module.REVIEW_REPORT_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                module.REVIEW_REPORT_FILE = Path(directory) / "sheriff-report.json"
                module.REVIEW_MODE = True
                module.REVIEW_AUTHOR_FILTER = "uten_bot"
                module.REVIEW_REPORT_FILE.write_text("""{
                  "schema_version": 7,
                  "scope": {"repositories": [{"org": "navikt", "name": "example", "managed": true}]},
                  "repositories": {
                    "example": {
                      "open_prs": {"status": "ok", "items": [{"number": 1, "url": "https://example/1", "author": {"login": "alice"}}]}
                      ,"github": {
                        "dependabot": {"items": [
                          {"state": "open", "severity": "critical", "cve": "CVE-2026-1000"},
                          {"state": "OPEN", "severity": "critical", "cve": "CVE-2026-2000"},
                          {"state": "open", "severity": "high", "cve": "CVE-2026-3000"},
                          {"state": "dismissed", "severity": "critical", "cve": "CVE-2026-4000"}
                        ]}
                      },
                      "nais_vulnerabilities": {"critical": 3, "high": 4}
                    }
                  }
                }""")
                loaded = module.load_review_report()
                self.assertEqual("example", loaded[0]["name"])
                self.assertEqual(1, loaded[0]["entries"][0]["pr"]["number"])
                self.assertEqual(2, loaded[0]["github_critical"])
                self.assertEqual(1, loaded[0]["github_high"])
                self.assertEqual(2, loaded[0]["entries"][0]["github_critical"])
                self.assertEqual(1, loaded[0]["entries"][0]["github_high"])
                self.assertEqual(3, loaded[0]["nais_critical"])
                self.assertEqual(4, loaded[0]["nais_high"])
                self.assertEqual(3, loaded[0]["entries"][0]["nais_critical"])
                self.assertEqual(4, loaded[0]["entries"][0]["nais_high"])
        finally:
            module.REVIEW_REPORT_FILE = original

    def test_rejects_outdated_shared_report(self) -> None:
        original = module.REVIEW_REPORT_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                module.REVIEW_REPORT_FILE = Path(directory) / "sheriff-report.json"
                module.REVIEW_REPORT_FILE.write_text('{"schema_version": 1}')

                with self.assertRaisesRegex(RuntimeError, "feil rapportversjon"):
                    module.load_review_report()
        finally:
            module.REVIEW_REPORT_FILE = original


if __name__ == "__main__":
    unittest.main()
