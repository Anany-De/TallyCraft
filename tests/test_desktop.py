import os
import tempfile
import unittest
from pathlib import Path

from tallycraft.desktop import (
    STARTER_ACCOUNTS,
    open_default_ledger,
    spreadsheet_safe_text,
)


class DesktopBookTests(unittest.TestCase):
    def test_csv_text_neutralizes_spreadsheet_formula_prefixes(self):
        for value in (
            "=HYPERLINK(\"https://example.invalid\")",
            "+1+1",
            "-1+1",
            "@SUM(A1:A2)",
            "\t=1+1",
            "\r=1+1",
            "\n=1+1",
            "  =1+1",
        ):
            with self.subTest(value=value):
                self.assertEqual(spreadsheet_safe_text(value), "'" + value)

        self.assertEqual(spreadsheet_safe_text("Rent expense"), "Rent expense")
        self.assertEqual(spreadsheet_safe_text(""), "")

    def test_first_launch_creates_starter_chart_in_user_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("APPDATA")
            os.environ["APPDATA"] = directory
            try:
                ledger = open_default_ledger()
                try:
                    self.assertEqual(
                        len(ledger.list_accounts()),
                        len(STARTER_ACCOUNTS),
                    )
                    self.assertTrue(
                        (Path(directory) / "TallyCraft" / "books.sqlite3").is_file()
                    )
                finally:
                    ledger.close()

                ledger = open_default_ledger()
                try:
                    self.assertEqual(len(ledger.list_accounts()), len(STARTER_ACCOUNTS))
                finally:
                    ledger.close()
            finally:
                if previous is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = previous


if __name__ == "__main__":
    unittest.main()
