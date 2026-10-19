import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tallycraft import AccountType, EntryLine, Ledger
from tallycraft.ledger import AccountingError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path)
        self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        self.ledger.create_account("3000", "Equity", AccountType.EQUITY)
        self.ledger.create_account("4000", "Sales", AccountType.INCOME)
        self.ledger.create_account("5000", "Supplies", AccountType.EXPENSE)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_journal_and_trial_balance(self):
        self.ledger.post_entry("2026-01-01", "Capital", [
            EntryLine("1000", debit="1000.00"), EntryLine("3000", credit="1000.00")])
        self.ledger.post_entry("2026-01-02", "Sale", [
            EntryLine("1000", debit="125.50"), EntryLine("4000", credit="125.50")])
        self.ledger.post_entry("2026-01-03", "Supplies", [
            EntryLine("5000", debit="20.25"), EntryLine("1000", credit="20.25")])
        report = self.ledger.trial_balance("2026-01-31")
        self.assertEqual(report.debit_total, Decimal("1125.50"))
        self.assertEqual(report.credit_total, Decimal("1125.50"))
        self.assertEqual(
            [(account.code, debit, credit) for account, debit, credit in report.rows],
            [("1000", Decimal("1105.25"), Decimal("0.00")),
             ("3000", Decimal("0.00"), Decimal("1000.00")),
             ("4000", Decimal("0.00"), Decimal("125.50")),
             ("5000", Decimal("20.25"), Decimal("0.00"))])

    def test_rejects_unbalanced_and_invalid_lines(self):
        with self.assertRaisesRegex(AccountingError, "must balance"):
            self.ledger.post_entry("2026-01-01", "Unbalanced", [
                EntryLine("1000", debit="10"), EntryLine("3000", credit="9")])
        for value in ("1.001", "-1", "NaN", 1.0):
            with self.subTest(value=value), self.assertRaises(AccountingError):
                self.ledger.post_entry("2026-01-01", "Invalid", [
                    EntryLine("1000", debit=value), EntryLine("3000", credit="1")])
        with self.assertRaisesRegex(AccountingError, "either a debit or a credit"):
            self.ledger.post_entry("2026-01-01", "Both sides", [
                EntryLine("1000", debit="1", credit="1"), EntryLine("3000", credit="2")])

    def test_unknown_account_and_invalid_date_do_not_post(self):
        with self.assertRaisesRegex(AccountingError, "Unknown account"):
            self.ledger.post_entry("2026-01-01", "Missing", [
                EntryLine("1000", debit="1"), EntryLine("9999", credit="1")])
        with self.assertRaisesRegex(AccountingError, "YYYY-MM-DD"):
            self.ledger.post_entry("01/01/2026", "Bad date", [
                EntryLine("1000", debit="1"), EntryLine("3000", credit="1")])
        self.assertEqual(self.ledger.trial_balance("2026-01-01").debit_total, 0)

    def test_posted_records_are_immutable(self):
        entry_id = self.ledger.post_entry("2026-01-01", "Opening", [
            EntryLine("1000", debit="1"), EntryLine("3000", credit="1")])
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE journal_entries SET memo='Changed' WHERE id=?", (entry_id,))
            connection.rollback()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute("DELETE FROM journal_lines WHERE entry_id=?", (entry_id,))
        finally:
            connection.close()

    def test_journal_history_is_newest_first_and_has_entry_total(self):
        self.ledger.post_entry(
            "2026-01-01",
            "Opening",
            [EntryLine("1000", debit="25.25"), EntryLine("3000", credit="25.25")],
            reference="OPEN-1",
        )
        self.ledger.post_entry(
            "2026-01-02",
            "Sale",
            [EntryLine("1000", debit="10"), EntryLine("4000", credit="10")],
        )
        history = self.ledger.journal_history()
        self.assertEqual([entry.memo for entry in history], ["Sale", "Opening"])
        self.assertEqual(history[0].amount, Decimal("10.00"))
        self.assertEqual(history[1].reference, "OPEN-1")
        self.assertEqual(len(self.ledger.journal_history(1)), 1)
        with self.assertRaisesRegex(AccountingError, "positive integer"):
            self.ledger.journal_history(0)


if __name__ == "__main__":
    unittest.main()
