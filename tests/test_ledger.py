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

    def test_integrity_check_accepts_valid_ledger_and_detects_tampered_entry(self):
        entry_id = self.ledger.post_entry(
            "2026-01-01",
            "Opening",
            [EntryLine("1000", debit="25"), EntryLine("3000", credit="25")],
        )
        self.ledger.verify_integrity()

        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER lines_immutable_update")
            connection.execute(
                """UPDATE journal_lines SET debit_minor = 2600
                   WHERE entry_id = ? AND line_number = 1""",
                (entry_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(AccountingError, "incomplete or unbalanced"):
            self.ledger.verify_integrity()

    def test_sql_shaped_account_input_is_data_not_sql(self):
        payload = "1000' OR 1=1 --"
        self.ledger.create_account(payload, "Literal SQL-shaped code", AccountType.ASSET)
        with self.assertRaisesRegex(AccountingError, "Unknown account"):
            self.ledger.post_entry(
                "2026-01-01",
                "Injection probe",
                [
                    EntryLine(payload + "' OR '1'='1", debit="1"),
                    EntryLine("3000", credit="1"),
                ],
            )
        self.assertEqual(
            [account.code for account in self.ledger.list_accounts() if account.code == payload],
            [payload],
        )

    def test_inventory_receipts_and_issues_use_moving_average_and_post_entries(self):
        self.ledger.create_account("1200", "Inventory", AccountType.ASSET)
        self.ledger.create_inventory_item(
            "PEN-1", "Blue pen", "pcs", "1200", "5000", reorder_level="2"
        )
        self.ledger.receive_inventory(
            "PEN-1", "2026-01-01", "10", "2.00", "3000", "Opening stock", "GRN-1"
        )
        self.ledger.receive_inventory(
            "PEN-1", "2026-01-02", "10", "4.00", "3000", "Restock", "GRN-2"
        )

        item = self.ledger.list_inventory_items()[0]
        self.assertEqual(item.quantity_on_hand, Decimal("20.000"))
        self.assertEqual(item.carrying_value, Decimal("60.00"))
        self.ledger.issue_inventory("PEN-1", "2026-01-03", "5", "Sale", "ISS-1")

        item = self.ledger.list_inventory_items()[0]
        self.assertEqual(item.quantity_on_hand, Decimal("15.000"))
        self.assertEqual(item.carrying_value, Decimal("45.00"))
        report = self.ledger.trial_balance("2026-01-03")
        balances = {account.code: (debit, credit) for account, debit, credit in report.rows}
        self.assertEqual(balances["1200"], (Decimal("45.00"), Decimal("0.00")))
        self.assertEqual(balances["5000"], (Decimal("15.00"), Decimal("0.00")))
        self.assertEqual(report.debit_total, report.credit_total)
        history = self.ledger.inventory_history()
        self.assertEqual([movement.movement_type for movement in history],
                         ["issue", "receipt", "receipt"])
        self.assertEqual(history[0].value, Decimal("15.00"))
        self.ledger.verify_integrity()

    def test_inventory_failures_do_not_change_stock_or_create_entries(self):
        self.ledger.create_account("1200", "Inventory", AccountType.ASSET)
        self.ledger.create_inventory_item(
            "PEN-2", "Red pen", "pcs", "1200", "5000"
        )
        with self.assertRaisesRegex(AccountingError, "Unknown account"):
            self.ledger.receive_inventory(
                "PEN-2", "2026-01-01", "5", "1.00", "9999", "Invalid receipt"
            )
        self.assertEqual(self.ledger.inventory_history(), ())
        self.assertEqual(self.ledger.journal_history(), ())
        with self.assertRaisesRegex(AccountingError, "Insufficient stock"):
            self.ledger.issue_inventory("PEN-2", "2026-01-02", "1", "Oversell")
        self.assertEqual(self.ledger.inventory_history(), ())
        self.assertEqual(self.ledger.journal_history(), ())

    def test_inventory_integrity_check_detects_manual_balance_tampering(self):
        self.ledger.create_account("1200", "Inventory", AccountType.ASSET)
        self.ledger.create_inventory_item(
            "PEN-3", "Green pen", "pcs", "1200", "5000"
        )
        self.ledger.receive_inventory(
            "PEN-3", "2026-01-01", "3", "2.00", "3000", "Opening stock"
        )
        self.ledger.verify_integrity()

        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER inventory_movements_immutable_update")
            connection.execute(
                "UPDATE inventory_items SET on_hand_milli = 2000 WHERE sku = 'PEN-3'"
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(AccountingError, "Inventory balance"):
            self.ledger.verify_integrity()


if __name__ == "__main__":
    unittest.main()
