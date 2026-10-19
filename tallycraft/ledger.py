"""Clean-room, persistent double-entry accounting ledger for TallyCraft."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


class AccountingError(ValueError):
    """Raised when a requested accounting operation violates ledger rules."""


class AccountType:
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"
    VALUES = (ASSET, LIABILITY, EQUITY, INCOME, EXPENSE)


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    type: str


@dataclass(frozen=True)
class EntryLine:
    account_code: str
    debit: Decimal | str | int = Decimal("0")
    credit: Decimal | str | int = Decimal("0")


@dataclass(frozen=True)
class TrialBalance:
    as_of: date
    rows: tuple[tuple[Account, Decimal, Decimal], ...]
    debit_total: Decimal
    credit_total: Decimal


@dataclass(frozen=True)
class JournalSummary:
    id: int
    entry_date: date
    memo: str
    reference: str | None
    amount: Decimal


@dataclass(frozen=True)
class InventoryItem:
    sku: str
    name: str
    unit: str
    inventory_account_code: str
    cogs_account_code: str
    reorder_level: Decimal
    quantity_on_hand: Decimal
    carrying_value: Decimal


@dataclass(frozen=True)
class InventoryMovement:
    id: int
    journal_entry_id: int
    entry_date: date
    sku: str
    item_name: str
    movement_type: str
    quantity: Decimal
    value: Decimal
    reference: str | None
    memo: str


@dataclass(frozen=True)
class JournalLineDetail:
    entry_id: int
    line_number: int
    account_code: str
    debit: Decimal
    credit: Decimal


class Ledger:
    """Append-only journal with exact-cent amounts and a trial-balance report."""

    def __init__(self, database: str | Path = "tallycraft.sqlite3") -> None:
        self._db = sqlite3.connect(str(database))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(
            """CREATE TABLE IF NOT EXISTS accounts (
                   id INTEGER PRIMARY KEY,
                   code TEXT NOT NULL UNIQUE,
                   name TEXT NOT NULL,
                   type TEXT NOT NULL CHECK (type IN
                       ('asset','liability','equity','income','expense'))
               );
               CREATE TABLE IF NOT EXISTS journal_entries (
                   id INTEGER PRIMARY KEY,
                   entry_date TEXT NOT NULL,
                   memo TEXT NOT NULL,
                   reference TEXT,
                   created_at TEXT NOT NULL
               );
               CREATE TABLE IF NOT EXISTS journal_lines (
                   entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
                   line_number INTEGER NOT NULL,
                   account_id INTEGER NOT NULL REFERENCES accounts(id),
                   debit_minor INTEGER NOT NULL CHECK (debit_minor >= 0),
                   credit_minor INTEGER NOT NULL CHECK (credit_minor >= 0),
                   PRIMARY KEY (entry_id, line_number),
                   CHECK ((debit_minor > 0 AND credit_minor = 0) OR
                          (credit_minor > 0 AND debit_minor = 0))
               );
               CREATE TABLE IF NOT EXISTS inventory_items (
                   id INTEGER PRIMARY KEY,
                   sku TEXT NOT NULL UNIQUE,
                   name TEXT NOT NULL,
                   unit TEXT NOT NULL,
                   inventory_account_id INTEGER NOT NULL REFERENCES accounts(id),
                   cogs_account_id INTEGER NOT NULL REFERENCES accounts(id),
                   reorder_milli INTEGER NOT NULL DEFAULT 0 CHECK (reorder_milli >= 0),
                   on_hand_milli INTEGER NOT NULL DEFAULT 0 CHECK (on_hand_milli >= 0),
                   value_minor INTEGER NOT NULL DEFAULT 0 CHECK (value_minor >= 0),
                   CHECK ((on_hand_milli = 0 AND value_minor = 0) OR on_hand_milli > 0)
               );
               CREATE TABLE IF NOT EXISTS inventory_movements (
                   id INTEGER PRIMARY KEY,
                   item_id INTEGER NOT NULL REFERENCES inventory_items(id),
                   entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id),
                   movement_date TEXT NOT NULL,
                   movement_type TEXT NOT NULL CHECK
                       (movement_type IN ('receipt', 'issue')),
                   quantity_milli INTEGER NOT NULL CHECK (quantity_milli > 0),
                   value_minor INTEGER NOT NULL CHECK (value_minor > 0),
                   reference TEXT,
                   memo TEXT NOT NULL
               );
               CREATE INDEX IF NOT EXISTS journal_entry_date_idx
                   ON journal_entries(entry_date, id);
               CREATE INDEX IF NOT EXISTS inventory_movement_item_date_idx
                   ON inventory_movements(item_id, movement_date, id);
               CREATE TRIGGER IF NOT EXISTS entries_immutable_update
                   BEFORE UPDATE ON journal_entries BEGIN
                       SELECT RAISE(ABORT, 'posted entries are immutable');
                   END;
               CREATE TRIGGER IF NOT EXISTS entries_immutable_delete
                   BEFORE DELETE ON journal_entries BEGIN
                       SELECT RAISE(ABORT, 'posted entries are immutable');
                   END;
               CREATE TRIGGER IF NOT EXISTS lines_immutable_update
                   BEFORE UPDATE ON journal_lines BEGIN
                       SELECT RAISE(ABORT, 'posted lines are immutable');
                   END;
               CREATE TRIGGER IF NOT EXISTS lines_immutable_delete
                   BEFORE DELETE ON journal_lines BEGIN
                       SELECT RAISE(ABORT, 'posted lines are immutable');
                   END;
               CREATE TRIGGER IF NOT EXISTS inventory_movements_immutable_update
                   BEFORE UPDATE ON inventory_movements BEGIN
                       SELECT RAISE(ABORT, 'posted inventory movements are immutable');
                   END;
               CREATE TRIGGER IF NOT EXISTS inventory_movements_immutable_delete
                   BEFORE DELETE ON inventory_movements BEGIN
                       SELECT RAISE(ABORT, 'posted inventory movements are immutable');
                   END;"""
        )

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_account(self, code: str, name: str, account_type: str) -> Account:
        if not isinstance(code, str) or not code.strip():
            raise AccountingError("Account code is required.")
        if not isinstance(name, str) or not name.strip():
            raise AccountingError("Account name is required.")
        if account_type not in AccountType.VALUES:
            raise AccountingError("Unsupported account type.")
        account = Account(code.strip(), name.strip(), account_type)
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO accounts (code,name,type) VALUES (?,?,?)",
                    (account.code, account.name, account.type),
                )
        except sqlite3.IntegrityError as error:
            raise AccountingError(f"Duplicate account code: {account.code}") from error
        return account

    def list_accounts(self) -> tuple[Account, ...]:
        return tuple(
            Account(row["code"], row["name"], row["type"])
            for row in self._db.execute("SELECT code,name,type FROM accounts ORDER BY code")
        )

    def post_entry(
        self,
        entry_date: date | str,
        memo: str,
        lines: Iterable[EntryLine],
        reference: str | None = None,
    ) -> int:
        posted_date = self._parse_date(entry_date)
        if not isinstance(memo, str) or not memo.strip():
            raise AccountingError("Journal entry memo is required.")
        if reference is not None and (not isinstance(reference, str) or not reference.strip()):
            raise AccountingError("Reference must be non-empty when provided.")
        normalized: list[tuple[str, int, int]] = []
        debit_total = credit_total = 0
        for line in lines:
            if not isinstance(line, EntryLine) or not isinstance(line.account_code, str):
                raise AccountingError("Journal lines must specify an account code.")
            code = line.account_code.strip()
            if not code:
                raise AccountingError("Account code is required on each line.")
            debit, credit = self._minor(line.debit), self._minor(line.credit)
            if (debit > 0) == (credit > 0):
                raise AccountingError("Each line must be either a debit or a credit.")
            normalized.append((code, debit, credit))
            debit_total += debit
            credit_total += credit
        if len(normalized) < 2:
            raise AccountingError("An entry must contain at least two lines.")
        if debit_total != credit_total:
            raise AccountingError("Journal entry debits and credits must balance.")
        with self._db:
            return self._post_entry_transaction(
                posted_date, memo.strip(), reference.strip() if reference else None, normalized
            )

    def create_inventory_item(
        self,
        sku: str,
        name: str,
        unit: str,
        inventory_account_code: str,
        cogs_account_code: str,
        reorder_level: Decimal | str | int = 0,
    ) -> InventoryItem:
        for value, label in ((sku, "SKU"), (name, "Item name"), (unit, "Unit")):
            if not isinstance(value, str) or not value.strip():
                raise AccountingError(f"{label} is required.")
        reorder_milli = self._quantity_milli(reorder_level, allow_zero=True)
        try:
            with self._db:
                accounts = {
                    row["code"]: row
                    for row in self._db.execute(
                        "SELECT id, code, type FROM accounts WHERE code IN (?, ?)",
                        (inventory_account_code, cogs_account_code),
                    )
                }
                inventory_account = accounts.get(inventory_account_code)
                cogs_account = accounts.get(cogs_account_code)
                if inventory_account is None or inventory_account["type"] != AccountType.ASSET:
                    raise AccountingError("Inventory control account must be an asset.")
                if cogs_account is None or cogs_account["type"] != AccountType.EXPENSE:
                    raise AccountingError("Cost of goods sold account must be an expense.")
                if inventory_account_code == cogs_account_code:
                    raise AccountingError("Inventory and cost accounts must be different.")
                self._db.execute(
                    """INSERT INTO inventory_items
                       (sku, name, unit, inventory_account_id, cogs_account_id, reorder_milli)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        sku.strip(),
                        name.strip(),
                        unit.strip(),
                        inventory_account["id"],
                        cogs_account["id"],
                        reorder_milli,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise AccountingError(f"SKU already exists: {sku.strip()}") from error
        item = next(item for item in self.list_inventory_items() if item.sku == sku.strip())
        return item

    def list_inventory_items(self) -> tuple[InventoryItem, ...]:
        rows = self._db.execute(
            """SELECT i.sku, i.name, i.unit, ia.code AS inventory_code,
                      ca.code AS cogs_code, i.reorder_milli, i.on_hand_milli,
                      i.value_minor
               FROM inventory_items i
               JOIN accounts ia ON ia.id = i.inventory_account_id
               JOIN accounts ca ON ca.id = i.cogs_account_id
               ORDER BY i.sku"""
        )
        return tuple(
            InventoryItem(
                row["sku"],
                row["name"],
                row["unit"],
                row["inventory_code"],
                row["cogs_code"],
                self._quantity_decimal(row["reorder_milli"]),
                self._quantity_decimal(row["on_hand_milli"]),
                self._decimal(row["value_minor"]),
            )
            for row in rows
        )

    def inventory_history(self, limit: int = 100) -> tuple[InventoryMovement, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise AccountingError("History limit must be a positive integer.")
        rows = self._db.execute(
            """SELECT m.id, m.entry_id, m.movement_date, i.sku, i.name, m.movement_type,
                      m.quantity_milli, m.value_minor, m.reference, m.memo
               FROM inventory_movements m
               JOIN inventory_items i ON i.id = m.item_id
               ORDER BY m.movement_date DESC, m.id DESC
               LIMIT ?""",
            (limit,),
        )
        return tuple(
            InventoryMovement(
                row["id"],
                row["entry_id"],
                date.fromisoformat(row["movement_date"]),
                row["sku"],
                row["name"],
                row["movement_type"],
                self._quantity_decimal(row["quantity_milli"]),
                self._decimal(row["value_minor"]),
                row["reference"],
                row["memo"],
            )
            for row in rows
        )

    def receive_inventory(
        self,
        sku: str,
        entry_date: date | str,
        quantity: Decimal | str | int,
        unit_cost: Decimal | str | int,
        offset_account_code: str,
        memo: str,
        reference: str | None = None,
    ) -> int:
        posted_date = self._parse_date(entry_date)
        quantity_milli = self._quantity_milli(quantity)
        unit_cost_minor = self._minor(unit_cost)
        receipt_value = self._round_ratio(quantity_milli * unit_cost_minor, 1000)
        if receipt_value == 0:
            raise AccountingError("Receipt total must be at least one cent.")
        memo, reference = self._validate_inventory_description(memo, reference)
        with self._db:
            item = self._inventory_item_row(sku)
            if offset_account_code == item["inventory_code"]:
                raise AccountingError("Receipt offset must differ from inventory account.")
            entry_id = self._post_entry_transaction(
                posted_date,
                memo,
                reference,
                [
                    (item["inventory_code"], receipt_value, 0),
                    (offset_account_code, 0, receipt_value),
                ],
            )
            self._db.execute(
                """UPDATE inventory_items
                   SET on_hand_milli = on_hand_milli + ?, value_minor = value_minor + ?
                   WHERE id = ?""",
                (quantity_milli, receipt_value, item["id"]),
            )
            self._db.execute(
                """INSERT INTO inventory_movements
                   (item_id, entry_id, movement_date, movement_type, quantity_milli,
                    value_minor, reference, memo)
                   VALUES (?, ?, ?, 'receipt', ?, ?, ?, ?)""",
                (
                    item["id"], entry_id, posted_date.isoformat(), quantity_milli,
                    receipt_value, reference, memo,
                ),
            )
        return entry_id

    def issue_inventory(
        self,
        sku: str,
        entry_date: date | str,
        quantity: Decimal | str | int,
        memo: str,
        reference: str | None = None,
    ) -> int:
        posted_date = self._parse_date(entry_date)
        quantity_milli = self._quantity_milli(quantity)
        memo, reference = self._validate_inventory_description(memo, reference)
        with self._db:
            item = self._inventory_item_row(sku)
            on_hand = item["on_hand_milli"]
            inventory_value = item["value_minor"]
            if quantity_milli > on_hand:
                raise AccountingError(
                    f"Insufficient stock for {sku}: "
                    f"{self._quantity_decimal(on_hand)} {item['unit']} available."
                )
            issue_value = (
                inventory_value
                if quantity_milli == on_hand
                else self._round_ratio(inventory_value * quantity_milli, on_hand)
            )
            if issue_value == 0:
                raise AccountingError("Issue value must be at least one cent.")
            if quantity_milli < on_hand and issue_value >= inventory_value:
                raise AccountingError(
                    "This partial issue would consume all remaining value; issue all stock instead."
                )
            entry_id = self._post_entry_transaction(
                posted_date,
                memo,
                reference,
                [
                    (item["cogs_code"], issue_value, 0),
                    (item["inventory_code"], 0, issue_value),
                ],
            )
            self._db.execute(
                """UPDATE inventory_items
                   SET on_hand_milli = on_hand_milli - ?, value_minor = value_minor - ?
                   WHERE id = ?""",
                (quantity_milli, issue_value, item["id"]),
            )
            self._db.execute(
                """INSERT INTO inventory_movements
                   (item_id, entry_id, movement_date, movement_type, quantity_milli,
                    value_minor, reference, memo)
                   VALUES (?, ?, ?, 'issue', ?, ?, ?, ?)""",
                (
                    item["id"], entry_id, posted_date.isoformat(), quantity_milli,
                    issue_value, reference, memo,
                ),
            )
        return entry_id

    def _post_entry_transaction(
        self,
        posted_date: date,
        memo: str,
        reference: str | None,
        normalized: list[tuple[str, int, int]],
    ) -> int:
        codes = {code for code, _, _ in normalized}
        placeholders = ",".join("?" for _ in codes)
        accounts = {
            row["code"]: row["id"]
            for row in self._db.execute(
                f"SELECT id,code FROM accounts WHERE code IN ({placeholders})", tuple(codes)
            )
        }
        missing = sorted(codes - accounts.keys())
        if missing:
            raise AccountingError(f"Unknown account code(s): {', '.join(missing)}")
        cursor = self._db.execute(
            "INSERT INTO journal_entries(entry_date,memo,reference,created_at) VALUES(?,?,?,?)",
            (
                posted_date.isoformat(), memo, reference,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        entry_id = cursor.lastrowid
        self._db.executemany(
            """INSERT INTO journal_lines
               (entry_id,line_number,account_id,debit_minor,credit_minor)
               VALUES(?,?,?,?,?)""",
            [
                (entry_id, i, accounts[code], debit, credit)
                for i, (code, debit, credit) in enumerate(normalized, 1)
            ],
        )
        return int(entry_id)

    def _inventory_item_row(self, sku: str) -> sqlite3.Row:
        row = self._db.execute(
            """SELECT i.id, i.sku, i.name, i.unit, i.on_hand_milli, i.value_minor,
                      ia.code AS inventory_code, ca.code AS cogs_code
               FROM inventory_items i
               JOIN accounts ia ON ia.id = i.inventory_account_id
               JOIN accounts ca ON ca.id = i.cogs_account_id
               WHERE i.sku = ?""",
            (sku,),
        ).fetchone()
        if row is None:
            raise AccountingError(f"Unknown inventory SKU: {sku}")
        return row

    @staticmethod
    def _validate_inventory_description(
        memo: str, reference: str | None
    ) -> tuple[str, str | None]:
        if not isinstance(memo, str) or not memo.strip():
            raise AccountingError("Inventory movement memo is required.")
        if reference is not None and (
            not isinstance(reference, str) or not reference.strip()
        ):
            raise AccountingError("Reference must be non-empty when provided.")
        return memo.strip(), reference.strip() if reference else None

    @staticmethod
    def _quantity_milli(value: Decimal | str | int, allow_zero: bool = False) -> int:
        if isinstance(value, (float, bool)):
            raise AccountingError("Quantities must not be floats or booleans.")
        try:
            quantity = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as error:
            raise AccountingError("Quantity must be a valid decimal value.") from error
        if not quantity.is_finite() or quantity < 0 or (quantity == 0 and not allow_zero):
            raise AccountingError("Quantity must be positive.")
        milli = quantity * 1000
        if milli != milli.to_integral_value():
            raise AccountingError("Quantities may have at most three decimal places.")
        return int(milli)

    @staticmethod
    def _quantity_decimal(milli: int) -> Decimal:
        return (Decimal(milli) / 1000).quantize(Decimal("0.001"))

    @staticmethod
    def _round_ratio(numerator: int, denominator: int) -> int:
        return (2 * numerator + denominator) // (2 * denominator)


    def trial_balance(self, as_of: date | str) -> TrialBalance:
        cutoff = self._parse_date(as_of)
        query = self._db.execute(
            """SELECT a.code,a.name,a.type,
                      COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.debit_minor ELSE 0 END),0) debits,
                      COALESCE(SUM(CASE WHEN je.id IS NOT NULL THEN jl.credit_minor ELSE 0 END),0) credits
               FROM accounts a LEFT JOIN journal_lines jl ON jl.account_id=a.id
               LEFT JOIN journal_entries je ON je.id=jl.entry_id AND je.entry_date<=?
               GROUP BY a.id ORDER BY a.code""", (cutoff.isoformat(),)
        )
        rows = []
        debit_sum = credit_sum = 0
        for row in query:
            net = row["debits"] - row["credits"]
            debit, credit = max(net, 0), max(-net, 0)
            debit_sum += debit
            credit_sum += credit
            rows.append((Account(row["code"], row["name"], row["type"]),
                         self._decimal(debit), self._decimal(credit)))
        return TrialBalance(cutoff, tuple(rows), self._decimal(debit_sum), self._decimal(credit_sum))

    def journal_history(self, limit: int = 100) -> tuple[JournalSummary, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise AccountingError("History limit must be a positive integer.")
        rows = self._db.execute(
            """SELECT je.id, je.entry_date, je.memo, je.reference,
                      COALESCE(SUM(jl.debit_minor), 0) AS amount
               FROM journal_entries je
               JOIN journal_lines jl ON jl.entry_id = je.id
               GROUP BY je.id
               ORDER BY je.entry_date DESC, je.id DESC
               LIMIT ?""",
            (limit,),
        )
        return tuple(
            JournalSummary(
                row["id"],
                date.fromisoformat(row["entry_date"]),
                row["memo"],
                row["reference"],
                self._decimal(row["amount"]),
            )
            for row in rows
        )

    def journal_line_details(self) -> tuple[JournalLineDetail, ...]:
        rows = self._db.execute(
            """SELECT je.id AS entry_id, jl.line_number, a.code,
                      jl.debit_minor, jl.credit_minor
               FROM journal_entries je
               JOIN journal_lines jl ON jl.entry_id = je.id
               JOIN accounts a ON a.id = jl.account_id
               ORDER BY je.id, jl.line_number"""
        )
        return tuple(
            JournalLineDetail(
                row["entry_id"],
                row["line_number"],
                row["code"],
                self._decimal(row["debit_minor"]),
                self._decimal(row["credit_minor"]),
            )
            for row in rows
        )

    def export_excel(self, path: str | Path) -> None:
        from .excel import export_workbook

        export_workbook(self, path)

    def import_excel(self, path: str | Path) -> int:
        from .excel import import_workbook

        return import_workbook(self, path)

    def verify_integrity(self) -> None:
        """Raise if SQLite structure or posted double-entry records are inconsistent."""
        result = self._db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise AccountingError(f"Database integrity check failed: {result}")

        foreign_key_error = self._db.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_error is not None:
            raise AccountingError(
                "Database contains a broken foreign-key reference "
                f"in table {foreign_key_error['table']}."
            )

        invalid_entry = self._db.execute(
            """SELECT je.id
               FROM journal_entries je
               LEFT JOIN journal_lines jl ON jl.entry_id = je.id
               GROUP BY je.id
               HAVING COUNT(jl.line_number) < 2
                   OR COALESCE(SUM(jl.debit_minor), 0)
                      != COALESCE(SUM(jl.credit_minor), 0)
               LIMIT 1"""
        ).fetchone()
        if invalid_entry is not None:
            raise AccountingError(
                f"Journal entry {invalid_entry['id']} is incomplete or unbalanced."
            )

        invalid_item = self._db.execute(
            """SELECT i.sku
               FROM inventory_items i
               LEFT JOIN inventory_movements m ON m.item_id = i.id
               GROUP BY i.id
               HAVING i.on_hand_milli != COALESCE(SUM(
                          CASE m.movement_type WHEN 'receipt' THEN m.quantity_milli
                               WHEN 'issue' THEN -m.quantity_milli ELSE 0 END
                      ), 0)
                   OR i.value_minor != COALESCE(SUM(
                          CASE m.movement_type WHEN 'receipt' THEN m.value_minor
                               WHEN 'issue' THEN -m.value_minor ELSE 0 END
                      ), 0)
               LIMIT 1"""
        ).fetchone()
        if invalid_item is not None:
            raise AccountingError(
                f"Inventory balance does not match movement history for SKU {invalid_item['sku']}."
            )

    @staticmethod
    def _parse_date(value: date | str) -> date:
        if isinstance(value, datetime):
            raise AccountingError("Use a calendar date, not a datetime.")
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            raise AccountingError("Date must be a date or YYYY-MM-DD string.")
        try:
            result = date.fromisoformat(value)
        except ValueError as error:
            raise AccountingError("Date must use YYYY-MM-DD format.") from error
        if result.isoformat() != value:
            raise AccountingError("Date must use YYYY-MM-DD format.")
        return result

    @staticmethod
    def _minor(value: Decimal | str | int) -> int:
        if isinstance(value, (float, bool)):
            raise AccountingError("Amounts must not be floats or booleans.")
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as error:
            raise AccountingError("Amount must be a valid decimal value.") from error
        if not amount.is_finite() or amount < 0:
            raise AccountingError("Amounts must be finite and non-negative.")
        minor = amount * 100
        if minor != minor.to_integral_value():
            raise AccountingError("Amounts may have at most two decimal places.")
        return int(minor)

    @staticmethod
    def _decimal(minor: int) -> Decimal:
        return (Decimal(minor) / 100).quantize(Decimal("0.01"))
