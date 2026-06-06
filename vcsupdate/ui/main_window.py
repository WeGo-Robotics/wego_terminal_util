"""Main window: connection bar, repo tree, live work log, per-repo git actions.

Mirrors foldersync/ui/main_window.py: a WorkerThread does all blocking SSH work
and posts dataclass messages onto a queue that ``_drain`` pumps into the UI via
``root.after``. New here vs foldersync: a Treeview of the vcstool workspace
(meta root + sub-repos) and a ScrolledText that streams command output live.
"""

from __future__ import annotations

import os
import posixpath
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from ..core import commands, credential, repolist, settings
from ..core.runner import capture_exec, stream_exec
from ..core.worker import (
    Connected,
    Error,
    LogLine,
    RepoList,
    TaskDone,
    WorkerThread,
)
from ..ssh.ssh_config import (
    build_ssh_client,
    github_identity_file,
    list_host_aliases,
    spec_from_alias,
)

# Tree row tags -> colours.
STATE_TAG = {
    repolist.PRESENT: "present",
    repolist.MISSING: "missing",
    repolist.EXTRA: "extra",
}

# Mutating ops trigger an automatic tree refresh when they finish.
_MUTATING = {"vcs pull", "vcs import", "git fetch", "git pull", "git push", "git checkout"}


class MainWindow(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root)
        self.root = root
        self.pack(fill="both", expand=True)

        self.worker = WorkerThread()
        self.worker.start()

        self._client = None          # paramiko client (set on worker thread)
        self._connected = False      # Tk-side flag
        self._cred = None            # credential.Credential (injected key)
        self._git_ssh = ""           # GIT_SSH_COMMAND value for the injected key
        self._cred_ready = False     # Tk-side flag: key injected, git auth ready
        self._node_by_iid = {}       # tree iid -> RepoNode

        self._settings = settings.load()
        s = self._settings
        self.alias_var = tk.StringVar(value=s.get("alias", ""))
        self.workspace_var = tk.StringVar(value=s.get("workspace", ""))
        self.repos_var = tk.StringVar(value=s.get("repos", ""))
        self.prefix_var = tk.StringVar(value=s.get("prefix", "src"))  # subdir .repos imports into
        self.key_var = tk.StringVar(value=s.get("key") or github_identity_file())
        self.workers_var = tk.IntVar(value=int(s.get("workers", 8)))
        self.status_var = tk.StringVar(value="Not connected.")

        self._build()
        geom = s.get("geometry")
        if geom:
            try:
                self.root.geometry(geom)
            except tk.TclError:
                pass
        self.root.after(50, self._drain)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _save_settings(self) -> None:
        self._settings.update({
            "alias": self.alias_var.get(),
            "workspace": self.workspace_var.get(),
            "repos": self.repos_var.get(),
            "prefix": self.prefix_var.get(),
            "key": self.key_var.get(),
            "workers": int(self.workers_var.get()),
        })
        try:
            self._settings["geometry"] = self.root.winfo_geometry()
        except tk.TclError:
            pass
        settings.save(self._settings)

    # ---- layout ----
    def _build(self) -> None:
        # connection bar
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(bar, text="Robot:").pack(side="left")
        self.alias_cb = ttk.Combobox(bar, textvariable=self.alias_var, width=24,
                                     values=list_host_aliases())
        self.alias_cb.pack(side="left", padx=2)
        self.connect_btn = ttk.Button(bar, text="Connect", command=self._connect)
        self.connect_btn.pack(side="left", padx=2)
        ttk.Label(bar, textvariable=self.status_var).pack(side="left", padx=8)

        # workspace / repos inputs
        row = ttk.Frame(self)
        row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text="Workspace (remote):").pack(side="left")
        ttk.Entry(row, textvariable=self.workspace_var, width=28).pack(side="left", padx=2)
        ttk.Label(row, text="src subdir:").pack(side="left", padx=(8, 0))
        ttk.Entry(row, textvariable=self.prefix_var, width=6).pack(side="left", padx=2)
        ttk.Label(row, text=".repos (local):").pack(side="left", padx=(8, 0))
        ttk.Entry(row, textvariable=self.repos_var, width=28).pack(side="left", padx=2)
        ttk.Button(row, text="…", width=3, command=self._browse_repos).pack(side="left")
        ttk.Label(row, text="Workers:").pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=1, to=32, width=4, textvariable=self.workers_var).pack(side="left")

        krow = ttk.Frame(self)
        krow.pack(fill="x", padx=4, pady=(0, 2))
        ttk.Label(krow, text="GitHub SSH key (local):").pack(side="left")
        ttk.Entry(krow, textvariable=self.key_var, width=46).pack(side="left", padx=2)
        ttk.Button(krow, text="…", width=3, command=self._browse_key).pack(side="left")
        ttk.Label(krow, text="(injected into robot /dev/shm at runtime, removed on disconnect)",
                  foreground="#888888").pack(side="left", padx=6)

        # workspace-wide action buttons
        act = ttk.Frame(self)
        act.pack(fill="x", padx=4, pady=2)
        self.refresh_btn = ttk.Button(act, text="Refresh tree", command=self._refresh)
        self.refresh_btn.pack(side="left", padx=2)
        ttk.Separator(act, orient="vertical").pack(side="left", fill="y", padx=6)
        self.bulk_status_btn = ttk.Button(act, text="vcs status", command=self._bulk_status)
        self.bulk_status_btn.pack(side="left", padx=2)
        self.bulk_pull_btn = ttk.Button(act, text="vcs pull", command=self._bulk_pull)
        self.bulk_pull_btn.pack(side="left", padx=2)
        self.bulk_import_btn = ttk.Button(act, text="vcs import", command=self._bulk_import)
        self.bulk_import_btn.pack(side="left", padx=2)
        ttk.Separator(act, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(act, text="Selected:").pack(side="left")
        self.sel_pull_btn = ttk.Button(
            act, text="git pull", command=lambda: self._repo_op("git pull", commands.git_pull, needs_cred=True))
        self.sel_pull_btn.pack(side="left", padx=2)
        self.sel_push_btn = ttk.Button(
            act, text="git push", command=lambda: self._repo_op("git push", commands.git_push, needs_cred=True))
        self.sel_push_btn.pack(side="left", padx=2)
        self.sel_sync_btn = ttk.Button(
            act, text="↻ Sync", command=lambda: self._repo_op("git sync", commands.git_sync, needs_cred=True))
        self.sel_sync_btn.pack(side="left", padx=2)
        ttk.Separator(act, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(act, text="Cancel", command=self.worker.cancel).pack(side="left", padx=2)

        self._action_btns = [
            self.refresh_btn, self.bulk_status_btn, self.bulk_pull_btn, self.bulk_import_btn,
            self.sel_pull_btn, self.sel_push_btn, self.sel_sync_btn,
        ]
        for b in self._action_btns:
            b.state(["disabled"])

        # main split: tree (left) + log (right)
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=4, pady=4)

        tree_frame = ttk.Frame(pane)
        cols = ("branch", "sync", "changes", "state", "version")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="Repo")
        self.tree.heading("branch", text="Branch")
        self.tree.heading("sync", text="↓↑")
        self.tree.heading("changes", text="Changes")
        self.tree.heading("state", text="State")
        self.tree.heading("version", text="Defined")
        self.tree.column("#0", width=260, anchor="w")
        self.tree.column("branch", width=120, anchor="w")
        self.tree.column("sync", width=70, anchor="center")
        self.tree.column("changes", width=70, anchor="center")
        self.tree.column("state", width=70, anchor="center")
        self.tree.column("version", width=90, anchor="w")
        self.tree.tag_configure("present", foreground="#222222")
        self.tree.tag_configure("missing", foreground="#dc322f")
        self.tree.tag_configure("extra", foreground="#268bd2")
        self.tree.tag_configure("dirty", foreground="#cb4b16")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        pane.add(tree_frame, weight=3)

        log_frame = ttk.Frame(pane)
        self.log = scrolledtext.ScrolledText(log_frame, wrap="none", height=20,
                                             state="disabled", background="#fdf6e3")
        self.log.tag_configure("out", foreground="#073642")
        self.log.tag_configure("err", foreground="#dc322f")
        self.log.tag_configure("info", foreground="#268bd2")
        self.log.pack(fill="both", expand=True)
        pane.add(log_frame, weight=4)

        # per-repo context menu
        self.menu = tk.Menu(self.tree, tearoff=0)
        self.menu.add_command(label="git status", command=lambda: self._repo_op("git status", commands.git_status))
        self.menu.add_command(label="git fetch", command=lambda: self._repo_op("git fetch", commands.git_fetch, needs_cred=True))
        self.menu.add_command(label="git pull", command=lambda: self._repo_op("git pull", commands.git_pull, needs_cred=True))
        self.menu.add_command(label="git push", command=lambda: self._repo_op("git push", commands.git_push, needs_cred=True))
        self.menu.add_command(label="↻ Sync (pull+push)", command=lambda: self._repo_op("git sync", commands.git_sync, needs_cred=True))
        self.menu.add_command(label="git checkout…", command=self._checkout)
        self.menu.add_separator()
        self.menu.add_command(label="git log", command=lambda: self._repo_op("git log", commands.git_log))
        self.menu.add_command(label="git diff", command=lambda: self._repo_op("git diff", commands.git_diff))
        self.tree.bind("<Button-3>", self._popup)

        # status bar
        statusbar = ttk.Frame(self)
        statusbar.pack(side="bottom", fill="x")
        self.task_var = tk.StringVar(value="Ready.")
        ttk.Label(statusbar, textvariable=self.task_var).pack(side="left", padx=4, pady=2)

    # ---- logging ----
    def _log(self, text: str, stream: str = "out") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", (stream,))
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---- connection ----
    def _connect(self) -> None:
        alias = self.alias_var.get().strip()
        if not alias:
            messagebox.showwarning("vcsupdate", "Pick or type a robot SSH alias first.")
            return
        key_path = self.key_var.get().strip()
        self._save_settings()
        self.task_var.set(f"connecting {alias}…")

        def task(w: WorkerThread) -> None:
            w.post(LogLine(f"$ ssh {alias}", "info"))
            spec = spec_from_alias(alias)
            self._client = build_ssh_client(spec)

            # Validate + inject the git key into the robot's RAM (/dev/shm).
            fp, err = credential.load_and_check(key_path)
            if err:
                self._cred = None
                self._git_ssh = ""
                w.post(Connected(host=spec.host, cred_ok=False, detail=err))
                return
            w.post(LogLine(f"git key ok ({key_path}, fp {fp}); injecting into robot RAM…", "info"))
            cred = credential.inject(self._client, key_path, fp)
            self._cred = cred
            self._git_ssh = credential.git_ssh_command(cred)
            w.post(LogLine(f"injected → {cred.remote_key} (removed on disconnect)", "info"))
            w.post(Connected(host=spec.host, cred_ok=True, detail=fp))

        self.worker.submit(task, name="connect")

    # ---- workspace-wide actions ----
    def _refresh(self) -> None:
        ws = self.workspace_var.get().strip()
        if not self._require(ws):
            return
        repos_text = self._read_local_repos()
        self._save_settings()
        self.task_var.set("refreshing tree…")

        def task(w: WorkerThread) -> None:
            w.post(LogLine(f"$ {commands.vcs_export(ws)}", "info"))
            rc, export_text, err = capture_exec(self._client, commands.vcs_export(ws))
            if rc != 0:
                w.post(LogLine(err.strip() or "vcs export failed", "err"))
                if rc == 127:
                    w.post(LogLine("vcstool not installed on robot? (pip install vcstool)", "err"))
            _rc2, status_text, _err2 = capture_exec(self._client, commands.vcs_status_short(ws))
            root = repolist.build_tree(
                workspace_label=f"{self.alias_var.get()}:{ws}",
                repos_text=repos_text,
                export_text=export_text,
                status_text=status_text,
                import_prefix=self.prefix_var.get(),
                ws_name=posixpath.basename(ws.rstrip("/")),
            )
            w.post(RepoList(root=root))

        self.worker.submit(task, name="refresh")

    def _bulk_status(self) -> None:
        ws = self.workspace_var.get().strip()
        if self._require(ws):
            self._run_stream("vcs status", commands.vcs_status(ws))

    def _bulk_pull(self) -> None:
        ws = self.workspace_var.get().strip()
        if self._require(ws):
            cmd = commands.with_cred(commands.vcs_pull(ws, self.workers_var.get()), self._git_ssh)
            self._run_stream("vcs pull", cmd)

    def _bulk_import(self) -> None:
        ws = self.workspace_var.get().strip()
        if not self._require(ws):
            return
        repos_text = self._read_local_repos()
        if not repos_text.strip():
            messagebox.showwarning("vcsupdate", "Pick a local .repos file for import first.")
            return
        cmd = commands.with_cred(
            commands.vcs_import_stdin(ws, self.prefix_var.get(), self.workers_var.get()),
            self._git_ssh,
        )
        self._run_stream("vcs import", cmd, stdin_data=repos_text)

    # ---- per-repo actions ----
    def _selected_repos(self):
        """Return [(name, RepoNode)] for selected repo rows (skip container root)."""
        out = []
        for iid in self.tree.selection():
            node = self._node_by_iid.get(iid)
            if node is not None and node.is_repo:
                out.append((self.tree.item(iid, "text"), node))
        return out

    def _repo_op(self, op: str, cmd_fn, needs_cred: bool = False) -> None:
        ws = self.workspace_var.get().strip()
        if not self._require(ws):
            return
        repos = self._selected_repos()
        if not repos:
            messagebox.showinfo("vcsupdate", "Select one or more repos in the tree.")
            return
        jobs = []
        for name, node in repos:
            if node.state == repolist.MISSING:
                self._log(f"[skip] {name}: not cloned on robot — use vcs import", "err")
                continue
            cmd = cmd_fn(commands.repo_dir(ws, node.path))
            if needs_cred:
                cmd = commands.with_cred(cmd, self._git_ssh)
            jobs.append((name, cmd))
        if jobs:
            self._run_stream_many(op, jobs)

    def _checkout(self) -> None:
        ws = self.workspace_var.get().strip()
        if not self._require(ws):
            return
        repos = self._selected_repos()
        if not repos:
            messagebox.showinfo("vcsupdate", "Select one or more repos in the tree.")
            return
        ref = simpledialog.askstring("git checkout", "Branch or tag to check out:", parent=self.root)
        if not ref:
            return
        ref = ref.strip()
        if not commands.is_valid_ref(ref):
            messagebox.showerror("vcsupdate", f"Unsafe/invalid ref: {ref!r}")
            return
        jobs = []
        for name, node in repos:
            if node.state == repolist.MISSING:
                self._log(f"[skip] {name}: not cloned on robot", "err")
                continue
            cmd = commands.git_checkout(commands.repo_dir(ws, node.path), ref)
            jobs.append((name, commands.with_cred(cmd, self._git_ssh)))
        if jobs:
            self._run_stream_many("git checkout", jobs)

    # ---- task runners ----
    def _run_stream(self, op: str, command: str, stdin_data: str = "") -> None:
        self.task_var.set(f"{op}…")

        def task(w: WorkerThread) -> None:
            w.post(LogLine(f"$ {command}", "info"))
            rc = stream_exec(self._client, command,
                             lambda t, s: w.post(LogLine(t, s)),
                             w.cancel_event, stdin_data=stdin_data)
            w.post(TaskDone(name=op, exit_code=rc))

        self.worker.submit(task, name=op)

    def _run_stream_many(self, op: str, jobs) -> None:
        """Run several per-repo commands sequentially under one task."""
        self.task_var.set(f"{op} ×{len(jobs)}…")

        def task(w: WorkerThread) -> None:
            last_rc = 0
            for name, command in jobs:
                if w.cancel_event.is_set():
                    w.post(LogLine("cancelled", "err"))
                    break
                w.post(LogLine(f"=== {name}: {op} ===", "info"))
                w.post(LogLine(f"$ {command}", "info"))
                last_rc = stream_exec(self._client, command,
                                      lambda t, s: w.post(LogLine(t, s)),
                                      w.cancel_event)
            w.post(TaskDone(name=op, exit_code=last_rc))

        self.worker.submit(task, name=op)

    # ---- helpers ----
    def _require(self, ws: str) -> bool:
        if not self._connected:
            messagebox.showwarning("vcsupdate", "Connect to a robot first.")
            return False
        if not self._cred_ready:
            messagebox.showwarning(
                "vcsupdate",
                "No git credential injected — connect with a valid (unencrypted) "
                "GitHub SSH key first.",
            )
            return False
        if not ws:
            messagebox.showwarning("vcsupdate", "Enter the remote workspace path.")
            return False
        return True

    def _read_local_repos(self) -> str:
        path = self.repos_var.get().strip()
        if not path or not os.path.isfile(path):
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            self._log(f"cannot read .repos: {exc}", "err")
            return ""

    def _browse_repos(self) -> None:
        path = filedialog.askopenfilename(
            title="Select .repos file",
            filetypes=[("repos files", "*.repos *.yaml *.yml"), ("all files", "*.*")],
        )
        if path:
            self.repos_var.set(path)

    def _browse_key(self) -> None:
        path = filedialog.askopenfilename(title="Select GitHub SSH private key")
        if path:
            self.key_var.set(path)

    def _popup(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.menu.tk_popup(event.x_root, event.y_root)

    # ---- tree rendering ----
    @staticmethod
    def _sync_str(node) -> str:
        """VSCode-style ↓behind ↑ahead indicator, or ✓ when in sync."""
        if node.state == repolist.MISSING or not node.is_repo:
            return ""
        if node.ahead or node.behind:
            return f"↓{node.behind} ↑{node.ahead}"
        return "✓"

    @staticmethod
    def _changes_str(node) -> str:
        return str(node.changes) if node.changes else ""

    def _render_tree(self, root) -> None:
        self.tree.delete(*self.tree.get_children())
        self._node_by_iid.clear()
        label = root.label or "workspace"
        root_state = "meta repo" if root.is_repo else ""
        root_tags = ["present"]
        if root.dirty:
            root_tags.append("dirty")
        root_iid = self.tree.insert(
            "", "end", text=label, open=True,
            values=(root.actual_branch, self._sync_str(root), self._changes_str(root),
                    root_state, ""),
            tags=tuple(root_tags),
        )
        self._node_by_iid[root_iid] = root
        for node in root.children:
            tags = [STATE_TAG.get(node.state, "present")]
            if node.dirty:
                tags.append("dirty")
            iid = self.tree.insert(
                root_iid, "end", text=node.path,
                values=(node.actual_branch, self._sync_str(node), self._changes_str(node),
                        node.state, node.defined_version),
                tags=tuple(tags),
            )
            self._node_by_iid[iid] = node

    # ---- worker pump ----
    def _drain(self) -> None:
        try:
            while True:
                self._handle(self.worker.results.get_nowait())
        except Exception:  # queue.Empty
            pass
        self.root.after(50, self._drain)

    def _handle(self, msg) -> None:
        if isinstance(msg, LogLine):
            self._log(msg.text, msg.stream)
        elif isinstance(msg, Connected):
            self._connected = True
            self._cred_ready = msg.cred_ok
            if msg.cred_ok:
                for b in self._action_btns:
                    b.state(["!disabled"])
                self.status_var.set(f"Connected: {msg.host}  (git key fp {msg.detail})")
                self.task_var.set("connected — credential injected")
                self._log(f"connected to {msg.host}; git credential ready", "info")
            else:
                self.status_var.set(f"Connected: {msg.host}  (NO git credential)")
                self.task_var.set("connected — no credential")
                self._log(f"git credential not available: {msg.detail}", "err")
        elif isinstance(msg, RepoList):
            self._render_tree(msg.root)
            n = len(msg.root.children)
            self.task_var.set(f"tree refreshed — {n} repo(s)")
        elif isinstance(msg, TaskDone):
            tag = "info" if msg.exit_code == 0 else "err"
            self._log(f"[{msg.name}] exit {msg.exit_code}", tag)
            self.task_var.set(f"{msg.name} done (exit {msg.exit_code})")
            if msg.exit_code == 127:
                self._log("command not found on robot — is vcstool/git installed?", "err")
            if msg.name in _MUTATING and msg.exit_code == 0:
                self._refresh()
        elif isinstance(msg, Error):
            self._log(f"{msg.context}: {msg.message}".strip(": "), "err")
            messagebox.showerror("vcsupdate", f"{msg.context}\n{msg.message}".strip())
            self.task_var.set("error")

    def _on_close(self) -> None:
        self._save_settings()
        try:
            if self._client is not None:
                credential.cleanup(self._client, self._cred)  # wipe key from robot RAM
                self._client.close()
            self.worker.shutdown()
        finally:
            self.root.destroy()
