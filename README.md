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
`~/TallyCraft/books.sqlite3` on other platforms. No network connection or
third-party Python package is required.

## Current desktop features

- **Overview:** cash and bank balances, income and expense balances, and recent
  vouchers.
- **Accounts:** starter chart, account balances, and account creation.
- **Vouchers:** multi-line journal voucher entry with balance validation and
  journal history.
- **Reports:** date-based trial balance with CSV export.
- **Ledger foundation:** exact-cent storage, balanced double-entry postings,
  SQLite persistence, and append-only posted entries.

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

The standalone GUI executable is written to `dist\TallyCraft.exe`. The first
Windows build may take a few minutes. Windows builds should be produced on
Windows; this script does not cross-compile from macOS or Linux.

## Scope

This is an early desktop MVP, not feature parity with TallyPrime. Inventory
valuation, sales and purchase invoices, receivables/payables workflows,
jurisdiction-specific tax compliance and filings, banking and reconciliation,
payroll, multi-company and user access, and packaged installers remain future
work.
