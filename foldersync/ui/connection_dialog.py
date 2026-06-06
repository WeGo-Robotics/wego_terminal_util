"""Per-pane source configuration dialog (Local vs SSH)."""

from __future__ import annotations

import os
import stat as stat_mod
import tkinter as tk
from tkinter import filedialog, ttk
from typing import List, Optional, Tuple

from ..fs.ssh_config import (
    SourceSpec,
    build_ssh_client,
    list_host_aliases,
    resolve_host,
    spec_from_alias,
)
from .widgets import PathCompleter


class ConnectionDialog(tk.Toplevel):
    """Modal dialog returning a SourceSpec via ``self.result`` (None if cancelled)."""

    def __init__(self, parent, side: str, initial: Optional[SourceSpec] = None):
        super().__init__(parent)
        self.title(f"{side.capitalize()} source")
        self.resizable(False, False)
        self.result: Optional[SourceSpec] = None

        self.kind = tk.StringVar(value=(initial.kind if initial else "local"))
        self.local_path = tk.StringVar(value=(initial.path if initial and initial.kind == "local" else ""))
        self.alias = tk.StringVar(value=(initial.alias if initial else ""))
        self.remote_path = tk.StringVar(value=(initial.path if initial and initial.kind == "ssh" else ""))
        # manual fields
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.user = tk.StringVar()
        self.key_file = tk.StringVar()

        # lazy SFTP connection used only for remote-path autocompletion
        self._ssh = None
        self._sftp = None
        self._sftp_key = None
        self._conn_failed = False
        self.local_completer: Optional[PathCompleter] = None
        self.remote_completer: Optional[PathCompleter] = None
        self._destroyed = False

        self._build()
        self.transient(parent)
        self.grab_set()
        self._sync_enabled()

    # ---- layout ----
    def _build(self) -> None:
        pad = dict(padx=8, pady=4)

        kind_frame = ttk.Frame(self)
        kind_frame.grid(row=0, column=0, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(kind_frame, text="Local", variable=self.kind,
                        value="local", command=self._sync_enabled).pack(side="left")
        ttk.Radiobutton(kind_frame, text="SSH", variable=self.kind,
                        value="ssh", command=self._sync_enabled).pack(side="left")

        # --- Local ---
        self.local_frame = ttk.LabelFrame(self, text="Local folder")
        self.local_frame.grid(row=1, column=0, columnspan=3, sticky="ew", **pad)
        self.local_entry = ttk.Entry(self.local_frame, textvariable=self.local_path, width=44)
        self.local_entry.grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(self.local_frame, text="Browse…", command=self._browse).grid(
            row=0, column=1, padx=4, pady=4)
        self.local_completer = PathCompleter(
            self.local_entry, self.local_path, self._local_listdir, sep=os.sep)

        # --- SSH ---
        self.ssh_frame = ttk.LabelFrame(self, text="SSH source")
        self.ssh_frame.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(self.ssh_frame, text="Host alias:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        aliases = list_host_aliases() + ["<Manual…>"]
        self.alias_combo = ttk.Combobox(self.ssh_frame, textvariable=self.alias,
                                        values=aliases, state="readonly", width=24)
        self.alias_combo.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self.alias_combo.bind("<<ComboboxSelected>>", lambda e: self._on_alias())
        if aliases and not self.alias.get():
            self.alias_combo.current(0)

        ttk.Label(self.ssh_frame, text="Remote path:").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        self.remote_entry = ttk.Entry(self.ssh_frame, textvariable=self.remote_path, width=30)
        self.remote_entry.grid(row=1, column=1, columnspan=2, sticky="w", padx=4, pady=4)
        self.remote_completer = PathCompleter(
            self.remote_entry, self.remote_path, self._remote_listdir, sep="/")

        # manual block
        self.manual_frame = ttk.Frame(self.ssh_frame)
        self.manual_frame.grid(row=2, column=0, columnspan=3, sticky="ew")
        rows = [("Host:", self.host), ("Port:", self.port), ("User:", self.user)]
        for i, (lbl, var) in enumerate(rows):
            ttk.Label(self.manual_frame, text=lbl).grid(row=i, column=0, sticky="e", padx=4, pady=2)
            ttk.Entry(self.manual_frame, textvariable=var, width=24).grid(
                row=i, column=1, sticky="w", padx=4, pady=2)
        ttk.Label(self.manual_frame, text="Key file:").grid(row=3, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(self.manual_frame, textvariable=self.key_file, width=24).grid(
            row=3, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(self.manual_frame, text="…", width=3, command=self._browse_key).grid(
            row=3, column=2, padx=2)

        # buttons — on the right column so the path-autocomplete dropdown
        # (which drops down below the entry) never covers them
        btns = ttk.Frame(self)
        btns.grid(row=0, column=3, rowspan=3, sticky="n", **pad)
        ttk.Button(btns, text="OK", command=self._ok).pack(side="top", fill="x", pady=2)
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="top", fill="x", pady=2)

    # ---- behavior ----
    def _sync_enabled(self) -> None:
        local = self.kind.get() == "local"
        _set_state(self.local_frame, local)
        _set_state(self.ssh_frame, not local)
        if not local:
            self._on_alias()

    def _on_alias(self) -> None:
        manual = self.alias.get() == "<Manual…>"
        _set_state(self.manual_frame, manual)
        # alias/source changed -> drop any cached completion connection
        self._teardown_sftp()
        if self.remote_completer is not None:
            self.remote_completer.clear_cache()

    # ---- autocompletion providers ----
    def _local_listdir(self, dirpath: str) -> List[Tuple[str, bool]]:
        if not dirpath:
            return []
        try:
            names = os.listdir(dirpath)
        except OSError:
            return []
        out = []
        for n in names:
            try:
                is_dir = os.path.isdir(os.path.join(dirpath, n))
            except OSError:
                is_dir = False
            out.append((n, is_dir))
        return out

    def _remote_listdir(self, dirpath: str) -> List[Tuple[str, bool]]:
        sftp = self._get_sftp()
        if sftp is None:
            return []
        target = dirpath if dirpath else "."
        out = []
        for attr in sftp.listdir_attr(target):
            out.append((attr.filename, stat_mod.S_ISDIR(attr.st_mode or 0)))
        return out

    def _current_ssh_spec(self) -> Optional[SourceSpec]:
        if self.kind.get() != "ssh":
            return None
        alias = self.alias.get()
        if alias == "<Manual…>":
            host = self.host.get().strip()
            if not host:
                return None
            return SourceSpec(
                kind="ssh", path=".", host=host,
                port=int(self.port.get() or 22),
                user=self.user.get().strip(),
                key_files=[self.key_file.get().strip()] if self.key_file.get().strip() else [],
            )
        if alias:
            return spec_from_alias(alias, ".")
        return None

    def _get_sftp(self):
        spec = self._current_ssh_spec()
        if spec is None:
            return None
        key = (spec.alias, spec.host, spec.port, spec.user, tuple(spec.key_files))
        if key != self._sftp_key:
            self._teardown_sftp()
            self._sftp_key = key
            self._conn_failed = False
            if self.remote_completer is not None:
                self.remote_completer.clear_cache()
        if self._conn_failed:
            return None
        if self._sftp is None:
            try:
                self._ssh = build_ssh_client(spec)
                self._sftp = self._ssh.open_sftp()
            except Exception:
                # one failed attempt disables retry per keystroke (avoids UI hangs)
                self._conn_failed = True
                self._teardown_sftp()
                return None
        return self._sftp

    def _teardown_sftp(self) -> None:
        try:
            if self._sftp is not None:
                self._sftp.close()
            if self._ssh is not None:
                self._ssh.close()
        except Exception:
            pass
        self._sftp = None
        self._ssh = None

    def _browse(self) -> None:
        path = filedialog.askdirectory(parent=self)
        if path:
            self.local_path.set(path)

    def _browse_key(self) -> None:
        path = filedialog.askopenfilename(parent=self)
        if path:
            self.key_file.set(path)

    def _ok(self) -> None:
        if self.kind.get() == "local":
            self.result = SourceSpec(kind="local", path=self.local_path.get().strip())
        else:
            alias = self.alias.get()
            remote = self.remote_path.get().strip() or "."
            if alias == "<Manual…>":
                self.result = SourceSpec(
                    kind="ssh",
                    path=remote,
                    alias="",
                    host=self.host.get().strip(),
                    port=int(self.port.get() or 22),
                    user=self.user.get().strip(),
                    key_files=[self.key_file.get().strip()] if self.key_file.get().strip() else [],
                )
            else:
                self.result = spec_from_alias(alias, remote)
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def destroy(self) -> None:
        if not self._destroyed:
            self._destroyed = True
            self._teardown_sftp()
            for c in (self.local_completer, self.remote_completer):
                if c is not None:
                    c.destroy()
        super().destroy()


def _set_state(frame, enabled: bool) -> None:
    state = "normal" if enabled else "disabled"
    for child in frame.winfo_children():
        try:
            child.configure(state=state)
        except tk.TclError:
            pass
        if child.winfo_children():
            _set_state(child, enabled)


def ask_source(parent, side: str, initial: Optional[SourceSpec] = None) -> Optional[SourceSpec]:
    dlg = ConnectionDialog(parent, side, initial)
    parent.wait_window(dlg)
    return dlg.result
