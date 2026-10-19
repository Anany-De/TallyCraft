"""Clean-room, persistent double-entry accounting ledger for TallyCraft."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
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
               CREATE INDEX IF NOT EXISTS journal_entry_date_idx
                   ON journal_entries(entry_date, id);
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
                (posted_date.isoformat(), memo.strip(), reference.strip() if reference else None,
                 datetime.now(timezone.utc).isoformat()),
            )
            entry_id = cursor.lastrowid
            self._db.executemany(
                "INSERT INTO journal_lines(entry_id,line_number,account_id,debit_minor,credit_minor) VALUES(?,?,?,?,?)",
                [(entry_id, i, accounts[code], debit, credit)
                 for i, (code, debit, credit) in enumerate(normalized, 1)],
            )
        return int(entry_id)

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
