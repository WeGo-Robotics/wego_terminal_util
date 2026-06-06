"""Small reusable UI helpers."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Tuple


def human_size(n) -> str:
    """Format a byte count compactly; '' for None."""
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            if unit == "B":
                return f"{int(n)}{unit}"
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


# list_dir(dirpath) -> list of (name, is_dir); may raise on error.
ListDirFn = Callable[[str], List[Tuple[str, bool]]]


class PathCompleter:
    """Dropdown path autocompletion for an Entry.

    Generic over the backend via ``list_dir`` (local os.listdir or remote SFTP).
    Splits the typed text into directory + prefix, lists the directory, filters
    by prefix, and shows matches in a popup. Selecting a directory drills in.
    """

    def __init__(self, entry: tk.Entry, textvar: tk.StringVar,
                 list_dir: ListDirFn, sep: str = "/", debounce_ms: int = 200):
        self.entry = entry
        self.var = textvar
        self.list_dir = list_dir
        self.sep = sep
        self.debounce_ms = debounce_ms
        self._popup: tk.Toplevel | None = None
        self._listbox: tk.Listbox | None = None
        self._items: List[Tuple[str, bool]] = []
        self._after_id = None
        self._cache: dict = {}

        entry.bind("<KeyRelease>", self._on_key, add="+")
        entry.bind("<Down>", self._focus_list, add="+")
        entry.bind("<Escape>", lambda e: self._close(), add="+")
        entry.bind("<FocusOut>", self._on_focusout, add="+")

    # ---- public ----
    def clear_cache(self) -> None:
        self._cache.clear()

    def destroy(self) -> None:
        self._close()

    # ---- text splitting ----
    def _split(self) -> Tuple[str, str]:
        text = self.var.get()
        if not text or text.endswith(self.sep):
            return text, ""
        if self.sep in text:
            head, _, tail = text.rpartition(self.sep)
            return head + self.sep, tail
        return "", text

    # ---- events ----
    def _on_key(self, event) -> None:
        if event.keysym in ("Up", "Down", "Left", "Right", "Return",
                            "Escape", "Tab", "Shift_L", "Shift_R"):
            return
        if self._after_id is not None:
            self.entry.after_cancel(self._after_id)
        self._after_id = self.entry.after(self.debounce_ms, self._show)

    def _on_focusout(self, event) -> None:
        # Close unless focus moved into the popup listbox.
        self.entry.after(120, self._maybe_close)

    def _maybe_close(self) -> None:
        if self._popup is None:
            return
        focus = self._popup.focus_get()
        if focus is not self._listbox:
            self._close()

    # ---- popup ----
    def _list(self, dirpath: str) -> List[Tuple[str, bool]]:
        if dirpath in self._cache:
            return self._cache[dirpath]
        try:
            items = self.list_dir(dirpath)
        except Exception:
            items = []
        # directories first, then files; both alphabetical
        items.sort(key=lambda it: (not it[1], it[0].lower()))
        self._cache[dirpath] = items
        return items

    def _show(self) -> None:
        self._after_id = None
        if self.entry.focus_get() is not self.entry:
            return
        dirpath, prefix = self._split()
        entries = self._list(dirpath)
        plo = prefix.lower()
        matches = [it for it in entries if it[0].lower().startswith(plo)]
        if not matches:
            self._close()
            return
        self._items = matches
        self._render(matches)

    def _render(self, matches: List[Tuple[str, bool]]) -> None:
        if self._popup is None:
            self._popup = tk.Toplevel(self.entry)
            self._popup.wm_overrideredirect(True)
            self._listbox = tk.Listbox(self._popup, activestyle="dotbox",
                                       exportselection=False)
            self._listbox.pack(fill="both", expand=True)
            self._listbox.bind("<Double-Button-1>", lambda e: self._accept())
            self._listbox.bind("<Return>", lambda e: self._accept())
            self._listbox.bind("<Escape>", lambda e: (self._close(), self.entry.focus_set()))
        lb = self._listbox
        lb.delete(0, "end")
        for name, is_dir in matches:
            lb.insert("end", name + (self.sep if is_dir else ""))
        lb.configure(height=min(8, len(matches)))
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        w = self.entry.winfo_width()
        self._popup.wm_geometry(f"{w}x{lb.winfo_reqheight()}+{x}+{y}")
        self._popup.deiconify()

    def _focus_list(self, event):
        if self._popup is not None and self._listbox is not None:
            self._listbox.focus_set()
            self._listbox.selection_clear(0, "end")
            self._listbox.selection_set(0)
            self._listbox.activate(0)
            return "break"

    def _accept(self) -> None:
        if self._listbox is None:
            return
        sel = self._listbox.curselection()
        if not sel:
            return
        name, is_dir = self._items[sel[0]]
        dirpath, _prefix = self._split()
        base = dirpath
        if base and not base.endswith(self.sep):
            base += self.sep
        value = base + name + (self.sep if is_dir else "")
        self.var.set(value)
        self.entry.icursor("end")
        self.entry.focus_set()
        self._close()
        if is_dir:
            self._show()  # drill into the selected directory

    def _close(self) -> None:
        if self._popup is not None:
            self._popup.destroy()
            self._popup = None
            self._listbox = None
