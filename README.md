# TallyCraft

TallyCraft is an independently implemented, open-source accounting application.
It is not affiliated with or derived from TallyPrime. This project does not
reproduce proprietary source, branding, interface assets, or undocumented data
formats.

## Run the desktop app

Requires Python 3.10 or later with Tkinter available. From the repository
directory, start the app with:

```powershell
python -m tallycraft
```

On first launch, TallyCraft creates a starter chart of accounts and local book.
The database is stored in `%APPDATA%\TallyCraft\books.sqlite3` on Windows and
`~/TallyCraft/books.sqlite3` on other platforms. Excel workbook import/export
requires `openpyxl`; install it from source with:

```powershell
python -m pip install -r requirements.txt
```

## Current desktop features

- **Overview:** cash and bank balances, income and expense balances, and recent
  vouchers.
- **Accounts:** starter chart, account balances, and account creation.
- **Vouchers:** multi-line journal voucher entry with balance validation and
  journal history.
- **Inventory:** stock items, receipts and issues, reorder levels, moving-average
  valuation, and matching accounting entries.
- **Reports:** date-based trial balance with CSV export.
- **Excel:** import and export `.xlsx` workbooks containing accounts, journal
  vouchers and lines, inventory items, stock movements, and trial balance.
- **Ledger foundation:** exact-cent storage, balanced double-entry postings,
  SQLite persistence, append-only posted entries, and a ledger/database
  consistency check (`Ledger.verify_integrity()`).

Use **Import Excel** or **Export Excel** in the top bar. Imports merge matching
accounts into the current book, but are restricted to books with no journal
entries and no existing inventory items to prevent accidental duplicate
postings. The workbook must use the sheets and column headings in a TallyCraft
workbook exported by the app. Excel support uses `openpyxl`; install it when
running from source with:

```powershell
python -m pip install -r requirements.txt
```

Create a journal voucher with **Ctrl+N** and refresh the current view with
**F5**. Run tests with:

```powershell
python -m unittest discover -s tests
```

## Build a Windows executable

On a Windows machine with Python and Tkinter installed, run these commands from
the repository directory:

```powershell
python -m pip install -r requirements-build.txt
.\build_windows.cmd
```

The standalone GUI executable includes inventory and Excel import/export and is
written to `dist\TallyCraft.exe`. The first Windows build may take a few minutes.
Windows builds should be produced on Windows; this script does not
cross-compile from macOS or Linux.

## Scope

This is an early desktop MVP, not feature parity with TallyPrime. Inventory
valuation is limited to moving-average stock receipts and issues; sales and
purchase invoices, receivables/payables workflows,
jurisdiction-specific tax compliance and filings, banking and reconciliation,
payroll, multi-company and user access, and packaged installers remain future
work. The integrity check detects SQLite consistency, foreign-key, and
unbalanced/incomplete journal problems; it is not cryptographic tamper-proofing
and cannot protect a database from someone who can replace or edit the local
database file.
