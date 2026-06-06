"""Filesystem abstraction: unified interface over local and SFTP backends."""

from .base import FileSystem, FileEntry, FileStat

__all__ = ["FileSystem", "FileEntry", "FileStat"]
