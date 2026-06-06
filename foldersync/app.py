"""Application entry point."""

from __future__ import annotations

import tkinter as tk

from .ui.main_window import MainWindow


def main() -> None:
    root = tk.Tk()
    root.title("foldersync — compare & sync")
    root.geometry("820x560")
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
