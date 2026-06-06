"""Application entry point."""

from __future__ import annotations

import tkinter as tk

from .ui.main_window import MainWindow


def main() -> None:
    root = tk.Tk()
    root.title("vcsupdate — remote vcstool meta-repo updater")
    root.geometry("1080x640")
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
