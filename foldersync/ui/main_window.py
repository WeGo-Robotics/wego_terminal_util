"""Main window: toolbar, unified diff Treeview, status bar."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..compare.result import CompareReport, DiffStatus
from ..core import settings
from ..core.controller import Controller
from ..core.worker import (
    CompareDone,
    Connected,
    CopyDone,
    Error,
    Progress,
    WorkerThread,
)
from ..fs.ssh_config import spec_from_dict, spec_label, spec_to_dict
from .connection_dialog import ask_source
from .widgets import human_size

STATUS_LABEL = {
    DiffStatus.SAME: "same",
    DiffStatus.DIFFERENT: "different",
    DiffStatus.LEFT_ONLY: "left only",
    DiffStatus.RIGHT_ONLY: "right only",
}
STATUS_TAG = {
    DiffStatus.SAME: "same",
    DiffStatus.DIFFERENT: "different",
    DiffStatus.LEFT_ONLY: "left_only",
    DiffStatus.RIGHT_ONLY: "right_only",
}


class MainWindow(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root)
        self.root = root
        self.pack(fill="both", expand=True)

        self.worker = WorkerThread()
        self.worker.start()
        self.controller = Controller(self.worker)

        # restore persisted settings
        self._settings = settings.load()
        self.left_spec = spec_from_dict(self._settings.get("left"))
        self.right_spec = spec_from_dict(self._settings.get("right"))
        self.git_mode = tk.BooleanVar(value=bool(self._settings.get("git_mode", False)))
        self.show_same = tk.BooleanVar(value=bool(self._settings.get("show_same", False)))
        self._report: CompareReport = CompareReport()

        self._build()
        geom = self._settings.get("geometry")
        if geom:
            try:
                self.root.geometry(geom)
            except tk.TclError:
                pass
        # show restored sources on buttons, then auto-connect them
        for side, spec in (("left", self.left_spec), ("right", self.right_spec)):
            if spec is not None:
                self._set_button(side, spec_label(spec))
        self.root.after(50, self._drain)
        self.root.after(150, self._autoconnect)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_button(self, side: str, text: str) -> None:
        btn = self.left_btn if side == "left" else self.right_btn
        btn.configure(text=f"{side.capitalize()}: {text}")

    def _autoconnect(self) -> None:
        for side, spec in (("left", self.left_spec), ("right", self.right_spec)):
            if spec is not None:
                self.status_var.set(f"reconnecting {side}…")
                self.controller.connect(side, spec)

    # ---- layout ----
    def _build(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=4)

        self.left_btn = ttk.Button(bar, text="Left: (not set)", width=34,
                                   command=lambda: self._pick("left"))
        self.left_btn.pack(side="left", padx=2)
        self.right_btn = ttk.Button(bar, text="Right: (not set)", width=34,
                                    command=lambda: self._pick("right"))
        self.right_btn.pack(side="left", padx=2)

        mode = ttk.Frame(bar)
        mode.pack(side="left", padx=8)
        ttk.Radiobutton(mode, text="Normal", variable=self.git_mode, value=False,
                        command=self._save_settings).pack(side="left")
        ttk.Radiobutton(mode, text="Git", variable=self.git_mode, value=True,
                        command=self._save_settings).pack(side="left")

        ttk.Button(bar, text="Compare", command=self._compare).pack(side="left", padx=2)
        ttk.Button(bar, text="Cancel", command=self.controller.cancel).pack(side="left", padx=2)

        action = ttk.Frame(self)
        action.pack(fill="x", padx=4)
        ttk.Button(action, text="Copy →", command=lambda: self._copy_selected("l2r")).pack(side="left", padx=2)
        ttk.Button(action, text="← Copy", command=lambda: self._copy_selected("r2l")).pack(side="left", padx=2)
        ttk.Checkbutton(action, text="Show identical", variable=self.show_same,
                        command=self._on_show_same).pack(side="left", padx=12)

        # tree
        cols = ("left", "status", "right")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Path")
        self.tree.heading("left", text="Left")
        self.tree.heading("status", text="Status")
        self.tree.heading("right", text="Right")
        self.tree.column("#0", width=420, anchor="w")
        self.tree.column("left", width=80, anchor="e")
        self.tree.column("status", width=90, anchor="center")
        self.tree.column("right", width=80, anchor="e")
        self.tree.tag_configure("different", foreground="#b58900")
        self.tree.tag_configure("left_only", foreground="#268bd2")
        self.tree.tag_configure("right_only", foreground="#859900")
        self.tree.tag_configure("same", foreground="#888888")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        vsb.pack(side="left", fill="y", pady=4)

        # context menu
        self.menu = tk.Menu(self.tree, tearoff=0)
        self.menu.add_command(label="Copy Left → Right", command=lambda: self._copy_selected("l2r"))
        self.menu.add_command(label="Copy Right → Left", command=lambda: self._copy_selected("r2l"))
        self.tree.bind("<Button-3>", self._popup)

        # status bar
        status = ttk.Frame(self)
        status.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(status, mode="determinate", length=200)
        self.progress.pack(side="left", padx=4, pady=2)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(status, textvariable=self.status_var).pack(side="left", padx=4)

    # ---- actions ----
    def _pick(self, side: str) -> None:
        initial = self.left_spec if side == "left" else self.right_spec
        spec = ask_source(self.root, side, initial)
        if spec is None:
            return
        if side == "left":
            self.left_spec = spec
        else:
            self.right_spec = spec
        self._save_settings()
        self.status_var.set(f"connecting {side}…")
        self.controller.connect(side, spec)

    def _on_show_same(self) -> None:
        self._refresh_tree()
        self._save_settings()

    def _save_settings(self) -> None:
        self._settings.update({
            "left": spec_to_dict(self.left_spec),
            "right": spec_to_dict(self.right_spec),
            "git_mode": bool(self.git_mode.get()),
            "show_same": bool(self.show_same.get()),
        })
        try:
            self._settings["geometry"] = self.root.winfo_geometry()
        except tk.TclError:
            pass
        settings.save(self._settings)

    def _compare(self) -> None:
        if self.controller.left_fs is None or self.controller.right_fs is None:
            messagebox.showwarning("foldersync", "Set both Left and Right sources first.")
            return
        self.status_var.set("comparing…")
        self.progress.configure(value=0)
        self.controller.compare(self.git_mode.get())

    def _copy_selected(self, direction: str) -> None:
        items = [(rel, direction) for rel in self.tree.selection()]
        if not items:
            return
        self.status_var.set(f"copying {len(items)} file(s)…")
        self.controller.copy_many(items)

    def _popup(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.menu.tk_popup(event.x_root, event.y_root)

    # ---- tree rendering ----
    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        show_same = self.show_same.get()
        for pair in self._report.pairs:
            if pair.status is DiffStatus.SAME and not show_same:
                continue
            lsize = human_size(pair.left.size) if pair.left else ""
            rsize = human_size(pair.right.size) if pair.right else ""
            self.tree.insert(
                "", "end", iid=pair.relpath, text=pair.relpath,
                values=(lsize, STATUS_LABEL[pair.status], rsize),
                tags=(STATUS_TAG[pair.status],),
            )

    def _update_row(self, relpath: str, status: DiffStatus) -> None:
        if not self.tree.exists(relpath):
            return
        if status is DiffStatus.SAME and not self.show_same.get():
            self.tree.delete(relpath)
            return
        vals = list(self.tree.item(relpath, "values"))
        vals[1] = STATUS_LABEL[status]
        self.tree.item(relpath, values=vals, tags=(STATUS_TAG[status],))

    # ---- worker pump ----
    def _drain(self) -> None:
        try:
            while True:
                msg = self.worker.results.get_nowait()
                self._handle(msg)
        except Exception:  # queue.Empty
            pass
        self.root.after(50, self._drain)

    def _handle(self, msg) -> None:
        if isinstance(msg, Progress):
            text = msg.msg or ""
            if msg.total:
                self.progress.configure(maximum=msg.total, value=msg.done)
                pct = int(msg.done * 100 / msg.total) if msg.total else 0
                counter = f"{msg.done}/{msg.total} ({pct}%)"
                text = f"{text}  {counter}" if text else counter
            else:
                self.progress.configure(value=0)
            if text:
                self.status_var.set(text)
        elif isinstance(msg, Connected):
            btn = self.left_btn if msg.side == "left" else self.right_btn
            btn.configure(text=f"{msg.side.capitalize()}: {msg.label}")
            self.status_var.set(f"{msg.side} connected: {msg.label}")
        elif isinstance(msg, CompareDone):
            self._report = msg.report
            self._refresh_tree()
            c = msg.report.counts()
            self.status_var.set(
                f"{len(msg.report.pairs)} files — "
                f"{c[DiffStatus.DIFFERENT]} different, "
                f"{c[DiffStatus.LEFT_ONLY]} left-only, "
                f"{c[DiffStatus.RIGHT_ONLY]} right-only, "
                f"{c[DiffStatus.SAME]} same"
            )
        elif isinstance(msg, CopyDone):
            self._update_row(msg.relpath, DiffStatus.SAME)
            self.status_var.set(f"copied {msg.relpath}")
        elif isinstance(msg, Error):
            messagebox.showerror("foldersync", f"{msg.context}\n{msg.message}".strip())
            self.status_var.set("error")

    def _on_close(self) -> None:
        self._save_settings()
        try:
            self.controller.close()
            self.worker.shutdown()
        finally:
            self.root.destroy()
