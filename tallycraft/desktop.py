"""Native TallyCraft desktop accounting MVP, built with the Python standard library."""

from __future__ import annotations

import csv
import os
import tkinter as tk
from datetime import date
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .ledger import AccountType, EntryLine, Ledger

APP_NAME = "TallyCraft"
_SPREADSHEET_FORMULA_PREFIXES = frozenset("=+-@")
STARTER_ACCOUNTS = (
    ("1000", "Cash", AccountType.ASSET),
    ("1010", "Bank", AccountType.ASSET),
    ("1100", "Accounts receivable", AccountType.ASSET),
    ("1200", "Inventory", AccountType.ASSET),
    ("2000", "Accounts payable", AccountType.LIABILITY),
    ("2100", "Tax payable", AccountType.LIABILITY),
    ("3000", "Owner equity", AccountType.EQUITY),
    ("3100", "Retained earnings", AccountType.EQUITY),
    ("4000", "Sales income", AccountType.INCOME),
    ("5000", "Cost of goods sold", AccountType.EXPENSE),
    ("5100", "Operating expenses", AccountType.EXPENSE),
    ("5200", "Rent expense", AccountType.EXPENSE),
)


def spreadsheet_safe_text(value: str) -> str:
    """Prevent spreadsheet software from evaluating user-controlled CSV text."""
    if not value:
        return value
    candidate = value.lstrip(" \t\r\n\x00")
    if value[0] in "\t\r\n" or (
        candidate and candidate[0] in _SPREADSHEET_FORMULA_PREFIXES
    ):
        return "'" + value
    return value


COLORS = {
    "background": "#f3f6fa",
    "surface": "#ffffff",
    "sidebar": "#17283f",
    "sidebar_active": "#263e5d",
    "ink": "#1b2a3d",
    "muted": "#718096",
    "accent": "#1b806d",
    "accent_hover": "#156958",
    "border": "#e3e9f0",
    "positive": "#19825d",
    "negative": "#bd554c",
}


def default_database_path() -> Path:
    """Return the per-user application database location."""
    base = Path(os.environ.get("APPDATA") or Path.home())
    return base / "TallyCraft" / "books.sqlite3"


def open_default_ledger() -> Ledger:
    path = default_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(path)
    if not ledger.list_accounts():
        for code, name, account_type in STARTER_ACCOUNTS:
            ledger.create_account(code, name, account_type)
    return ledger


class TallyCraftDesktop:
    def __init__(self, root: tk.Tk, ledger: Ledger) -> None:
        self.root = root
        self.ledger = ledger
        self.accounts_by_label: dict[str, str] = {}
        self.account_labels: list[str] = []
        self.nav_buttons: dict[str, tk.Button] = {}
        self.active_view = "Overview"

        root.title(f"{APP_NAME} | Books & accounts")
        root.geometry("1180x780")
        root.minsize(930, 640)
        root.configure(bg=COLORS["background"])
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-n>", lambda _event: self.new_voucher())
        root.bind("<F5>", lambda _event: self.refresh())
        self._setup_styles()
        self._build_shell()
        self._refresh_account_choices()
        self.show_view("Overview")

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            rowheight=34,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#f4f7fa",
            foreground=COLORS["muted"],
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Treeview",
            background=[("selected", "#e2f2ee")],
            foreground=[("selected", COLORS["ink"])],
        )
        style.configure("TCombobox", padding=6, font=("Segoe UI", 10))

    def _build_shell(self) -> None:
        self.shell = tk.Frame(self.root, bg=COLORS["background"])
        self.shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(self.shell, bg=COLORS["sidebar"], width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=22, pady=(26, 34))
        tk.Label(
            brand, text="TC", bg=COLORS["accent"], fg="white",
            font=("Segoe UI Semibold", 13), width=3, height=1,
        ).pack(side="left", padx=(0, 11))
        wordmark = tk.Frame(brand, bg=COLORS["sidebar"])
        wordmark.pack(side="left")
        tk.Label(
            wordmark, text="TallyCraft", bg=COLORS["sidebar"], fg="white",
            font=("Segoe UI Semibold", 15),
        ).pack(anchor="w")
        tk.Label(
            wordmark, text="ACCOUNTING DESK", bg=COLORS["sidebar"], fg="#a8bbd1",
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 0))

        tk.Label(
            self.sidebar, text="WORKSPACE", bg=COLORS["sidebar"], fg="#92a6be",
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", padx=24, pady=(0, 10))
        for label, icon in (
            ("Overview", "⌂"),
            ("Accounts", "▤"),
            ("Inventory", "▦"),
            ("Vouchers", "＋"),
            ("Reports", "▥"),
        ):
            button = tk.Button(
                self.sidebar,
                text=f"  {icon}    {label}",
                command=lambda selected=label: self.show_view(selected),
                anchor="w",
                padx=17,
                pady=11,
                bg=COLORS["sidebar"],
                fg="#e2eaf3",
                activebackground=COLORS["sidebar_active"],
                activeforeground="white",
                relief="flat",
                bd=0,
                font=("Segoe UI", 10),
                cursor="hand2",
            )
            button.pack(fill="x", padx=11, pady=2)
            self.nav_buttons[label] = button

        footer = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        footer.pack(side="bottom", fill="x", padx=19, pady=19)
        tk.Frame(footer, height=1, bg="#34475f").pack(fill="x", pady=(0, 13))
        tk.Label(
            footer, text="LOCAL COMPANY BOOK", bg=COLORS["sidebar"], fg="#a8bbd1",
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        tk.Label(
            footer, text="Saved on this computer", bg=COLORS["sidebar"], fg="#e2eaf3",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(5, 0))

        self.content = tk.Frame(self.shell, bg=COLORS["background"])
        self.content.pack(side="left", fill="both", expand=True)
        topbar = tk.Frame(self.content, bg=COLORS["surface"], height=58)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        self.page_label = tk.Label(
            topbar, text="Overview", bg=COLORS["surface"], fg=COLORS["ink"],
            font=("Segoe UI Semibold", 12),
        )
        self.page_label.pack(side="left", padx=27)
        self.today_label = tk.Label(
            topbar, text=date.today().strftime("%A, %d %B %Y"),
            bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9),
        )
        self.today_label.pack(side="right", padx=26)
        self._button(topbar, "Export Excel", self.export_excel, secondary=True).pack(
            side="right", padx=(0, 10)
        )
        self._button(topbar, "Import Excel", self.import_excel, secondary=True).pack(
            side="right", padx=(0, 10)
        )
        tk.Frame(self.content, height=1, bg=COLORS["border"]).pack(fill="x")
        self.page = tk.Frame(self.content, bg=COLORS["background"])
        self.page.pack(fill="both", expand=True, padx=27, pady=24)

    def _clear_page(self) -> None:
        for child in self.page.winfo_children():
            child.destroy()

    def _page_heading(
        self, title: str, subtitle: str, action: tuple[str, object] | None = None
    ) -> None:
        heading = tk.Frame(self.page, bg=COLORS["background"])
        heading.pack(fill="x", pady=(0, 20))
        copy = tk.Frame(heading, bg=COLORS["background"])
        copy.pack(side="left")
        tk.Label(
            copy, text=title, bg=COLORS["background"], fg=COLORS["ink"],
            font=("Segoe UI Semibold", 21),
        ).pack(anchor="w")
        tk.Label(
            copy, text=subtitle, bg=COLORS["background"], fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(5, 0))
        if action:
            self._button(heading, action[0], action[1]).pack(side="right", pady=3)

    def _button(
        self, parent: tk.Misc, text: str, command: object, secondary: bool = False
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["surface"] if secondary else COLORS["accent"],
            fg=COLORS["ink"] if secondary else "white",
            activebackground=COLORS["border"] if secondary else COLORS["accent_hover"],
            activeforeground=COLORS["ink"] if secondary else "white",
            relief="solid" if secondary else "flat",
            bd=1 if secondary else 0,
            highlightthickness=0,
            padx=15,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )

    def _card(self, parent: tk.Misc, title: str, value: str, caption: str) -> tk.Frame:
        card = tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["border"],
                        highlightthickness=1)
        tk.Label(
            card, text=title.upper(), bg=COLORS["surface"], fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", padx=17, pady=(15, 8))
        tk.Label(
            card, text=value, bg=COLORS["surface"], fg=COLORS["ink"],
            font=("Segoe UI Semibold", 20),
        ).pack(anchor="w", padx=17)
        tk.Label(
            card, text=caption, bg=COLORS["surface"], fg=COLORS["muted"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=17, pady=(4, 15))
        return card

    def _section(self, parent: tk.Misc, title: str, caption: str = "") -> tk.Frame:
        section = tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["border"],
                           highlightthickness=1)
        header = tk.Frame(section, bg=COLORS["surface"])
        header.pack(fill="x", padx=17, pady=(14, 11))
        tk.Label(
            header, text=title, bg=COLORS["surface"], fg=COLORS["ink"],
            font=("Segoe UI Semibold", 11),
        ).pack(side="left")
        if caption:
            tk.Label(
                header, text=caption, bg=COLORS["surface"], fg=COLORS["muted"],
                font=("Segoe UI", 8),
            ).pack(side="right")
        return section

    def _tree(
        self,
        parent: tk.Misc,
        columns: tuple[tuple[str, str, int], ...],
        height: int = 8,
    ) -> ttk.Treeview:
        tree = ttk.Treeview(
            parent,
            columns=tuple(column[0] for column in columns),
            show="headings",
            height=height,
        )
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w" if key in ("date", "memo", "name", "code", "type", "reference") else "e")
        return tree

    def _refresh_account_choices(self) -> None:
        accounts = self.ledger.list_accounts()
        self.accounts_by_label = {
            f"{account.code} · {account.name}": account.code for account in accounts
        }
        self.account_labels = list(self.accounts_by_label)

    def show_view(self, name: str) -> None:
        self.active_view = name
        self.page_label.configure(text=name)
        for label, button in self.nav_buttons.items():
            button.configure(
                bg=COLORS["sidebar_active"] if label == name else COLORS["sidebar"],
                font=("Segoe UI Semibold" if label == name else "Segoe UI", 10),
            )
        self._clear_page()
        {
            "Overview": self._show_overview,
            "Accounts": self._show_accounts,
            "Inventory": self._show_inventory,
            "Vouchers": self._show_vouchers,
            "Reports": self._show_reports,
        }[name]()

    def refresh(self) -> None:
        self._refresh_account_choices()
        self.show_view(self.active_view)

    def export_excel(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export TallyCraft workbook",
            defaultextension=".xlsx",
            filetypes=(("Excel workbook", "*.xlsx"),),
            initialfile=f"tallycraft-{date.today().isoformat()}.xlsx",
        )
        if not path:
            return
        try:
            self.ledger.export_excel(path)
        except (OSError, ValueError, ImportError) as error:
            messagebox.showerror("Excel export failed", str(error), parent=self.root)
            return
        messagebox.showinfo(
            "Workbook exported", f"Workbook saved to:\n{path}", parent=self.root
        )

    def import_excel(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Import TallyCraft workbook",
            filetypes=(("Excel workbook", "*.xlsx"),),
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Import workbook",
            "Import accounts, journal vouchers, and inventory from this workbook?\n\n"
            "The current book must have no journal entries or inventory items. "
            "Matching accounts can be reused. The import is validated and applied "
            "as one transaction.",
            parent=self.root,
        ):
            return
        try:
            imported = self.ledger.import_excel(path)
        except (OSError, ValueError, ImportError) as error:
            messagebox.showerror("Excel import failed", str(error), parent=self.root)
            return
        self.refresh()
        messagebox.showinfo(
            "Workbook imported",
            f"Imported {imported} journal vouchers. Account and inventory records "
            "are now available in the book.",
            parent=self.root,
        )

    def _show_overview(self) -> None:
        self._page_heading(
            "Good business starts with clear books",
            "Your accounting overview, with every posted transaction backed by the ledger.",
            ("＋  New voucher", self.new_voucher),
        )
        report = self.ledger.trial_balance(date.today())
        totals = {kind: Decimal("0.00") for kind in AccountType.VALUES}
        for account, debit, credit in report.rows:
            if account.type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.INCOME):
                totals[account.type] += credit - debit
            else:
                totals[account.type] += debit - credit
        cash = sum(
            (debit - credit for account, debit, credit in report.rows
             if account.code in ("1000", "1010")),
            Decimal("0.00"),
        )
        history = self.ledger.journal_history(1000)

        cards = tk.Frame(self.page, bg=COLORS["background"])
        cards.pack(fill="x", pady=(0, 19))
        metrics = (
            ("Cash & bank", cash, "Cash and bank account balances"),
            ("Income", totals[AccountType.INCOME], "Net income account balance"),
            ("Expenses", totals[AccountType.EXPENSE], "Net expense account balance"),
            ("Accounts", len(self.ledger.list_accounts()), "In your chart of accounts"),
        )
        for index, (title, value, caption) in enumerate(metrics):
            cards.grid_columnconfigure(index, weight=1, uniform="metric")
            shown = str(value) if isinstance(value, int) else self._money(value)
            self._card(cards, title, shown, caption).grid(
                row=0, column=index, sticky="ew", padx=(0 if index == 0 else 7, 0 if index == 3 else 7)
            )

        recent = self._section(self.page, "Recent activity", "Latest posted journal vouchers")
        tree = self._tree(
            recent,
            (("date", "DATE", 115), ("memo", "DESCRIPTION", 360),
             ("reference", "REFERENCE", 170), ("amount", "AMOUNT", 140)),
            height=9,
        )
        tree.pack(fill="x", padx=10, pady=(0, 12))
        for entry in self.ledger.journal_history(12):
            tree.insert(
                "", "end",
                values=(entry.entry_date.isoformat(), entry.memo, entry.reference or "—",
                        self._money(entry.amount)),
            )
        if not history:
            tk.Label(
                recent, text="No vouchers yet. Post your first transaction to get started.",
                bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9),
            ).pack(anchor="w", padx=18, pady=(0, 17))

    def _show_accounts(self) -> None:
        self._page_heading(
            "Chart of accounts",
            "A clear structure for assets, liabilities, equity, income, and expenses.",
            ("＋  Add account", self.add_account),
        )
        section = self._section(self.page, "Your accounts", f"{len(self.ledger.list_accounts())} accounts")
        tree = self._tree(
            section,
            (("code", "CODE", 135), ("name", "ACCOUNT NAME", 400),
             ("type", "TYPE", 180), ("balance", "BALANCE", 160)),
            height=15,
        )
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        report_rows = {account.code: (debit, credit)
                       for account, debit, credit in self.ledger.trial_balance(date.today()).rows}
        for account in self.ledger.list_accounts():
            debit, credit = report_rows[account.code]
            tree.insert("", "end", values=(
                account.code, account.name, account.type.title(), self._money(debit - credit)
            ))

    def _show_vouchers(self) -> None:
        self._page_heading(
            "Journal vouchers",
            "Record the business event once; balanced debits and credits do the rest.",
            ("＋  New voucher", self.new_voucher),
        )
        section = self._section(self.page, "Journal", "Newest entries first")
        tree = self._tree(
            section,
            (("date", "DATE", 130), ("memo", "DESCRIPTION", 350),
             ("reference", "REFERENCE", 180), ("amount", "DEBIT TOTAL", 150)),
            height=16,
        )
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        for entry in self.ledger.journal_history():
            tree.insert("", "end", values=(
                entry.entry_date.isoformat(), entry.memo, entry.reference or "—",
                self._money(entry.amount),
            ))

    def _show_inventory(self) -> None:
        items = self.ledger.list_inventory_items()
        low_stock_count = sum(
            item.reorder_level > 0 and item.quantity_on_hand <= item.reorder_level
            for item in items
        )
        self._page_heading(
            "Inventory",
            "Track stock quantities and moving-average cost alongside the general ledger.",
            ("＋  Add item", self.add_inventory_item),
        )
        actions = tk.Frame(self.page, bg=COLORS["background"])
        actions.pack(fill="x", pady=(0, 14))
        self._button(
            actions, "Receive stock", lambda: self.inventory_transaction(receive=True)
        ).pack(side="left")
        self._button(
            actions, "Issue stock", lambda: self.inventory_transaction(receive=False),
            secondary=True,
        ).pack(side="left", padx=(8, 0))

        section = self._section(
            self.page,
            "Stock on hand",
            f"{len(items)} items · {low_stock_count} at or below reorder level",
        )
        tree = self._tree(
            section,
            (("sku", "SKU", 100), ("name", "ITEM", 230), ("unit", "UNIT", 75),
             ("quantity", "ON HAND", 100), ("reorder", "REORDER AT", 105),
             ("value", "CARRYING VALUE", 145), ("account", "CONTROL ACCOUNT", 155)),
            height=9,
        )
        tree.pack(fill="x", padx=10, pady=(0, 12))
        tree.tag_configure("low_stock", foreground=COLORS["negative"])
        for item in items:
            tree.insert(
                "",
                "end",
                values=(
                    item.sku,
                    item.name,
                    item.unit,
                    str(item.quantity_on_hand),
                    str(item.reorder_level),
                    self._money(item.carrying_value),
                    item.inventory_account_code,
                ),
                tags=("low_stock",)
                if item.reorder_level > 0 and item.quantity_on_hand <= item.reorder_level
                else (),
            )
        if not items:
            tk.Label(
                section,
                text="No stock items yet. Add an item to start tracking inventory.",
                bg=COLORS["surface"],
                fg=COLORS["muted"],
                font=("Segoe UI", 9),
            ).pack(anchor="w", padx=18, pady=(0, 17))

        movements = self._section(self.page, "Recent stock movements", "Receipts and issues")
        history_tree = self._tree(
            movements,
            (("date", "DATE", 105), ("sku", "SKU", 90), ("name", "ITEM", 190),
             ("movement", "TYPE", 85), ("quantity", "QUANTITY", 95),
             ("value", "VALUE", 110), ("reference", "REFERENCE", 115),
             ("memo", "DESCRIPTION", 190)),
            height=5,
        )
        history_tree.pack(fill="x", padx=10, pady=(0, 12))
        for movement in self.ledger.inventory_history(10):
            history_tree.insert(
                "",
                "end",
                values=(
                    movement.entry_date.isoformat(),
                    movement.sku,
                    movement.item_name,
                    movement.movement_type.title(),
                    str(movement.quantity),
                    self._money(movement.value),
                    movement.reference or "—",
                    movement.memo,
                ),
            )

    def add_inventory_item(self) -> None:
        accounts = self.ledger.list_accounts()
        assets = [account for account in accounts if account.type == AccountType.ASSET]
        expenses = [account for account in accounts if account.type == AccountType.EXPENSE]
        if not assets or not expenses:
            messagebox.showerror(
                "Accounts needed",
                "Create an asset account and an expense account before adding inventory.",
                parent=self.root,
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Add inventory item")
        dialog.configure(bg=COLORS["surface"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = tk.Frame(dialog, bg=COLORS["surface"])
        frame.pack(fill="both", padx=24, pady=20)
        tk.Label(
            frame,
            text="Set up a stock item",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 15),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        sku = self._form_field(frame, "SKU / item code", 1, "e.g. ITEM-001")
        name = self._form_field(frame, "Item name", 3, "e.g. Notebook")
        unit = self._form_field(frame, "Unit of measure", 5, "e.g. pcs")
        inventory_choice = ttk.Combobox(
            frame,
            state="readonly",
            width=34,
            values=[f"{account.code} · {account.name}" for account in assets],
        )
        preferred_asset = next(
            (a for a in assets if a.name.casefold() == "inventory"), assets[0]
        )
        inventory_choice.set(f"{preferred_asset.code} · {preferred_asset.name}")
        self._label(frame, "Inventory asset account").grid(
            row=7, column=0, sticky="w", pady=(8, 3)
        )
        inventory_choice.grid(row=8, column=0, columnspan=2, sticky="ew", ipady=5)
        cogs_choice = ttk.Combobox(
            frame,
            state="readonly",
            width=34,
            values=[f"{account.code} · {account.name}" for account in expenses],
        )
        preferred_cogs = next(
            (a for a in expenses if a.name.casefold() == "cost of goods sold"),
            expenses[0],
        )
        cogs_choice.set(f"{preferred_cogs.code} · {preferred_cogs.name}")
        self._label(frame, "Cost of goods sold account").grid(
            row=9, column=0, sticky="w", pady=(8, 3)
        )
        cogs_choice.grid(row=10, column=0, columnspan=2, sticky="ew", ipady=5)
        reorder = self._form_field(frame, "Reorder alert at (quantity)", 11, "0")
        buttons = tk.Frame(frame, bg=COLORS["surface"])
        buttons.grid(row=13, column=0, columnspan=2, sticky="e", pady=(16, 0))
        self._button(buttons, "Cancel", dialog.destroy, secondary=True).pack(
            side="left", padx=5
        )

        def save_item() -> None:
            try:
                self.ledger.create_inventory_item(
                    sku.get(),
                    name.get(),
                    unit.get(),
                    inventory_choice.get().split(" · ", 1)[0],
                    cogs_choice.get().split(" · ", 1)[0],
                    reorder.get() or "0",
                )
            except (ValueError, TypeError) as error:
                messagebox.showerror("Item not saved", str(error), parent=dialog)
                return
            dialog.destroy()
            self.show_view("Inventory")

        self._button(buttons, "Save item", save_item).pack(side="left", padx=5)
        sku.focus_set()
        self._center_dialog(dialog, 460, 540)

    def inventory_transaction(self, receive: bool) -> None:
        items = self.ledger.list_inventory_items()
        if not items:
            messagebox.showerror(
                "Inventory item needed",
                "Add an inventory item before recording a stock movement.",
                parent=self.root,
            )
            return
        dialog = tk.Toplevel(self.root)
        title = "Receive stock" if receive else "Issue stock"
        dialog.title(title)
        dialog.configure(bg=COLORS["surface"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = tk.Frame(dialog, bg=COLORS["surface"])
        frame.pack(fill="both", padx=24, pady=20)
        tk.Label(
            frame, text=title, bg=COLORS["surface"], fg=COLORS["ink"],
            font=("Segoe UI Semibold", 16),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        item_labels = {f"{item.sku} · {item.name}": item for item in items}
        item_choice = ttk.Combobox(
            frame, values=list(item_labels), state="readonly", width=36
        )
        item_choice.current(0)
        self._label(frame, "Stock item").grid(
            row=1, column=0, sticky="w", pady=(5, 3)
        )
        item_choice.grid(row=2, column=0, columnspan=2, sticky="ew", ipady=5)
        date_entry = self._form_field(frame, "Movement date", 3, date.today().isoformat())
        quantity = self._form_field(frame, "Quantity (up to 3 decimal places)", 5, "1")
        unit_cost = None
        offset_choice = None
        if receive:
            unit_cost = self._form_field(frame, "Unit cost", 7, "0.00")
            self._label(frame, "Offset account (e.g. bank or accounts payable)").grid(
                row=9, column=0, sticky="w", pady=(8, 3)
            )
            offset_choice = ttk.Combobox(frame, state="readonly", width=36)
            offset_choice.grid(row=10, column=0, columnspan=2, sticky="ew", ipady=5)
        else:
            unit_cost = None
        memo = self._form_field(frame, "Description", 11 if receive else 7, title)
        reference = self._form_field(
            frame, "Reference (optional)", 13 if receive else 9, "e.g. PO-1042"
        )

        def update_offset(*_args: object) -> None:
            if offset_choice is None:
                return
            selected = item_labels.get(item_choice.get())
            if selected is None:
                offset_choice.configure(values=[])
                return
            options = [
                account for account in self.ledger.list_accounts()
                if account.code != selected.inventory_account_code
            ]
            labels = [f"{account.code} · {account.name}" for account in options]
            offset_choice.configure(values=labels)
            if labels:
                offset_choice.set(labels[0])
        item_choice.bind("<<ComboboxSelected>>", update_offset)
        update_offset()
        buttons = tk.Frame(frame, bg=COLORS["surface"])
        buttons.grid(
            row=15 if receive else 11,
            column=0,
            columnspan=2,
            sticky="e",
            pady=(16, 0),
        )
        self._button(buttons, "Cancel", dialog.destroy, secondary=True).pack(
            side="left", padx=5
        )

        def post_movement() -> None:
            item = item_labels.get(item_choice.get())
            if item is None:
                messagebox.showerror("Item required", "Select an inventory item.", parent=dialog)
                return
            try:
                if receive:
                    if offset_choice is None or not offset_choice.get():
                        raise ValueError("Select an offset account.")
                    self.ledger.receive_inventory(
                        item.sku,
                        date_entry.get(),
                        quantity.get(),
                        unit_cost.get() if unit_cost else "0",
                        offset_choice.get().split(" · ", 1)[0],
                        memo.get(),
                        reference.get() or None,
                    )
                else:
                    self.ledger.issue_inventory(
                        item.sku, date_entry.get(), quantity.get(), memo.get(),
                        reference.get() or None,
                    )
            except (ValueError, TypeError) as error:
                messagebox.showerror("Stock movement not posted", str(error), parent=dialog)
                return
            dialog.destroy()
            self.show_view("Inventory")

        self._button(buttons, title, post_movement).pack(side="left", padx=5)
        dialog.bind("<Return>", lambda _event: post_movement())
        self._center_dialog(dialog, 490, 640 if receive else 525)

    def _show_reports(self) -> None:
        self._page_heading(
            "Financial reports",
            "Review account balances for a chosen reporting date.",
        )
        controls = tk.Frame(self.page, bg=COLORS["background"])
        controls.pack(fill="x", pady=(0, 15))
        tk.Label(
            controls, text="AS OF", bg=COLORS["background"], fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).pack(side="left", padx=(0, 8))
        date_input = ttk.Entry(controls, width=14, font=("Segoe UI", 10))
        date_input.insert(0, date.today().isoformat())
        date_input.pack(side="left", ipady=5, padx=(0, 8))
        section = self._section(self.page, "Trial balance", "Closing balances by account")
        tree = self._tree(
            section,
            (("code", "CODE", 115), ("name", "ACCOUNT", 300),
             ("type", "TYPE", 160), ("debit", "DEBIT", 160), ("credit", "CREDIT", 160)),
            height=13,
        )
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 9))
        totals = tk.Label(
            section, bg=COLORS["surface"], fg=COLORS["ink"],
            font=("Segoe UI Semibold", 10), anchor="e",
        )
        totals.pack(fill="x", padx=16, pady=(3, 15))

        def load_report() -> None:
            try:
                report = self.ledger.trial_balance(date_input.get().strip())
            except (ValueError, OverflowError) as error:
                messagebox.showerror("Invalid date", str(error), parent=self.root)
                return
            tree.delete(*tree.get_children())
            for account, debit, credit in report.rows:
                tree.insert("", "end", values=(
                    account.code, account.name, account.type.title(),
                    self._money(debit) if debit else "—",
                    self._money(credit) if credit else "—",
                ))
            totals.configure(
                text=f"Debits  {self._money(report.debit_total)}      "
                     f"Credits  {self._money(report.credit_total)}"
            )
            self._current_report = report

        def export_report() -> None:
            report = getattr(self, "_current_report", None)
            if report is None:
                load_report()
                report = getattr(self, "_current_report", None)
            if report is None:
                return
            path = filedialog.asksaveasfilename(
                parent=self.root, title="Export trial balance",
                defaultextension=".csv", filetypes=(("CSV files", "*.csv"),),
                initialfile=f"trial-balance-{report.as_of.isoformat()}.csv",
            )
            if not path:
                return
            try:
                with open(path, "w", newline="", encoding="utf-8-sig") as file:
                    writer = csv.writer(file)
                    writer.writerow(("As of", report.as_of.isoformat()))
                    writer.writerow(("Code", "Account", "Type", "Debit", "Credit"))
                    for account, debit, credit in report.rows:
                        writer.writerow((
                            spreadsheet_safe_text(account.code),
                            spreadsheet_safe_text(account.name),
                            spreadsheet_safe_text(account.type),
                            debit,
                            credit,
                        ))
                    writer.writerow(("", "", "Total", report.debit_total, report.credit_total))
            except OSError as error:
                messagebox.showerror("Export failed", str(error), parent=self.root)
                return
            messagebox.showinfo("Report exported", f"Saved to:\n{path}", parent=self.root)

        self._button(controls, "Export CSV", export_report, secondary=True).pack(side="right")
        self._button(controls, "Show report", load_report).pack(side="right", padx=(0, 8))
        load_report()

    def add_account(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Add account")
        dialog.configure(bg=COLORS["surface"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = tk.Frame(dialog, bg=COLORS["surface"])
        frame.pack(fill="both", padx=25, pady=21)
        tk.Label(
            frame, text="Add to your chart of accounts", bg=COLORS["surface"],
            fg=COLORS["ink"], font=("Segoe UI Semibold", 15),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
        code = self._form_field(frame, "Account code", 1, "e.g. 1050")
        name = self._form_field(frame, "Account name", 3, "e.g. Petty cash")
        type_input = ttk.Combobox(frame, values=AccountType.VALUES, state="readonly", width=29)
        type_input.set(AccountType.ASSET)
        self._label(frame, "Account type").grid(row=5, column=0, sticky="w", pady=(10, 3))
        type_input.grid(row=6, column=0, columnspan=2, sticky="ew", ipady=5)
        buttons = tk.Frame(frame, bg=COLORS["surface"])
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(18, 0))
        self._button(buttons, "Cancel", dialog.destroy, secondary=True).pack(side="left", padx=5)

        def save() -> None:
            try:
                self.ledger.create_account(code.get(), name.get(), type_input.get())
            except (ValueError, TypeError) as error:
                messagebox.showerror("Account not saved", str(error), parent=dialog)
                return
            dialog.destroy()
            self._refresh_account_choices()
            self.show_view("Accounts")

        self._button(buttons, "Save account", save).pack(side="left", padx=5)
        code.focus_set()
        self._center_dialog(dialog, 430, 345)

    def new_voucher(self) -> None:
        self._refresh_account_choices()
        if len(self.account_labels) < 2:
            messagebox.showerror(
                "Accounts needed", "Add at least two accounts before creating a voucher.",
                parent=self.root,
            )
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("New journal voucher")
        dialog.configure(bg=COLORS["background"])
        dialog.minsize(770, 590)
        dialog.transient(self.root)
        dialog.grab_set()
        body = tk.Frame(dialog, bg=COLORS["background"])
        body.pack(fill="both", expand=True, padx=22, pady=19)
        tk.Label(
            body, text="New journal voucher", bg=COLORS["background"],
            fg=COLORS["ink"], font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        tk.Label(
            body, text="Each line is either a debit or a credit. Total debits must equal credits.",
            bg=COLORS["background"], fg=COLORS["muted"], font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 14))

        meta = tk.Frame(body, bg=COLORS["background"])
        meta.pack(fill="x", pady=(0, 15))
        tk.Label(meta, text="DATE", bg=COLORS["background"], fg=COLORS["muted"],
                 font=("Segoe UI Semibold", 8)).grid(row=0, column=0, sticky="w")
        tk.Label(meta, text="DESCRIPTION", bg=COLORS["background"], fg=COLORS["muted"],
                 font=("Segoe UI Semibold", 8)).grid(row=0, column=1, sticky="w", padx=(12, 0))
        tk.Label(meta, text="REFERENCE (OPTIONAL)", bg=COLORS["background"], fg=COLORS["muted"],
                 font=("Segoe UI Semibold", 8)).grid(row=0, column=2, sticky="w", padx=(12, 0))
        date_entry = ttk.Entry(meta, width=14)
        date_entry.insert(0, date.today().isoformat())
        date_entry.grid(row=1, column=0, sticky="ew", ipady=5, pady=5)
        memo_entry = ttk.Entry(meta, width=31)
        memo_entry.grid(row=1, column=1, sticky="ew", ipady=5, padx=(12, 0), pady=5)
        reference_entry = ttk.Entry(meta, width=20)
        reference_entry.grid(row=1, column=2, sticky="ew", ipady=5, padx=(12, 0), pady=5)
        meta.columnconfigure(1, weight=1)

        panel = tk.Frame(body, bg=COLORS["surface"], highlightbackground=COLORS["border"],
                         highlightthickness=1)
        panel.pack(fill="both", expand=True)
        headings = tk.Frame(panel, bg="#f4f7fa")
        headings.pack(fill="x", padx=1, pady=1)
        headings.grid_columnconfigure(0, weight=4)
        headings.grid_columnconfigure(1, weight=2)
        headings.grid_columnconfigure(2, weight=2)
        for column, title in enumerate(("ACCOUNT", "DEBIT", "CREDIT")):
            tk.Label(headings, text=title, bg="#f4f7fa", fg=COLORS["muted"],
                     font=("Segoe UI Semibold", 8), anchor="w").grid(
                row=0, column=column, sticky="ew", padx=10, pady=9
            )
        rows: list[tuple[ttk.Combobox, ttk.Entry, ttk.Entry]] = []
        for index in range(8):
            row = tk.Frame(panel, bg=COLORS["surface"])
            row.pack(fill="x", padx=8)
            row.grid_columnconfigure(0, weight=4)
            row.grid_columnconfigure(1, weight=2)
            row.grid_columnconfigure(2, weight=2)
            account = ttk.Combobox(row, values=self.account_labels, state="readonly")
            debit = ttk.Entry(row, justify="right")
            credit = ttk.Entry(row, justify="right")
            account.grid(row=0, column=0, sticky="ew", padx=3, pady=4, ipady=3)
            debit.grid(row=0, column=1, sticky="ew", padx=3, pady=4, ipady=4)
            credit.grid(row=0, column=2, sticky="ew", padx=3, pady=4, ipady=4)
            rows.append((account, debit, credit))
        totals = tk.Label(body, text="", bg=COLORS["background"],
                          fg=COLORS["muted"], font=("Segoe UI Semibold", 9))
        totals.pack(anchor="e", pady=(10, 4))
        buttons = tk.Frame(body, bg=COLORS["background"])
        buttons.pack(fill="x", pady=(9, 0))
        self._button(buttons, "Cancel", dialog.destroy, secondary=True).pack(side="right", padx=(8, 0))

        def post() -> None:
            lines: list[EntryLine] = []
            for row_number, (account, debit, credit) in enumerate(rows, start=1):
                selected = account.get().strip()
                debit_value, credit_value = debit.get().strip(), credit.get().strip()
                if not selected and not debit_value and not credit_value:
                    continue
                if not selected:
                    messagebox.showerror(
                        "Incomplete voucher", f"Choose an account on line {row_number}.",
                        parent=dialog,
                    )
                    return
                try:
                    lines.append(EntryLine(
                        self.accounts_by_label[selected],
                        debit=Decimal(debit_value) if debit_value else Decimal("0"),
                        credit=Decimal(credit_value) if credit_value else Decimal("0"),
                    ))
                except (KeyError, ArithmeticError, ValueError) as error:
                    messagebox.showerror(
                        "Invalid amount", f"Line {row_number}: {error or 'Check the amount.'}",
                        parent=dialog,
                    )
                    return
            try:
                self.ledger.post_entry(
                    date_entry.get().strip(), memo_entry.get(), lines,
                    reference_entry.get().strip() or None,
                )
            except (ValueError, TypeError) as error:
                messagebox.showerror("Voucher not posted", str(error), parent=dialog)
                return
            dialog.destroy()
            self.refresh()
            messagebox.showinfo("Voucher posted", "Your journal voucher was posted.", parent=self.root)

        self._button(buttons, "Post voucher", post).pack(side="right")
        self._center_dialog(dialog, 850, 640)

    @staticmethod
    def _label(parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(
            parent, text=text, bg=COLORS["surface"], fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        )

    def _form_field(
        self, parent: tk.Misc, label: str, row: int, placeholder: str
    ) -> ttk.Entry:
        self._label(parent, label).grid(row=row, column=0, columnspan=2, sticky="w",
                                        pady=(8 if row > 1 else 0, 3))
        entry = ttk.Entry(parent, width=34)
        entry.insert(0, placeholder)
        entry.grid(row=row + 1, column=0, columnspan=2, sticky="ew", ipady=5)
        entry.bind("<FocusIn>", lambda _event: entry.delete(0, "end")
                   if entry.get() == placeholder else None)
        return entry

    @staticmethod
    def _money(amount: Decimal) -> str:
        return f"{amount:,.2f}"

    def _center_dialog(self, dialog: tk.Toplevel, width: int, height: int) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def close(self) -> None:
        self.ledger.close()
        self.root.destroy()


def main() -> None:
    ledger = open_default_ledger()
    root = tk.Tk()
    TallyCraftDesktop(root, ledger)
    root.mainloop()


if __name__ == "__main__":
    main()
