# -*- coding: utf-8 -*-
"""
Plattform-Helfer: Windows + macOS/Linux
- Windows: Extended-Length-Pfade (\\?\\) + Hidden/System via WinAPI
- Unix: Pfade unverändert, "hidden" = führender Punkt
"""

import os

def _is_windows() -> bool:
    return os.name == "nt"

if _is_windows():
    import ctypes
    from ctypes import wintypes

    FILE_ATTRIBUTE_HIDDEN = 0x2
    FILE_ATTRIBUTE_SYSTEM = 0x4
    INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

    GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
    GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    GetFileAttributesW.restype = wintypes.DWORD

    def to_long_path(path: str) -> str:
        """Extended-Length-Pfad für Windows; andernfalls unverändert."""
        if not path:
            return path
        path = os.path.abspath(path)
        if path.startswith("\\\\?\\"):
            return path
        if path.startswith("\\\\"):  # UNC -> \\?\UNC\server\share\...
            return "\\\\?\\UNC\\" + path[2:]
        return "\\\\?\\" + path

    def is_hidden_or_system_dir(path: str) -> bool:
        """True, wenn Ordner Hidden/System (Windows) oder "."-hidden (Unix-Style) ist."""
        try:
            attrs = GetFileAttributesW(path)
            if attrs == INVALID_FILE_ATTRIBUTES:
                return False
            if attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                return True
            base = os.path.basename(path.rstrip("\\/"))
            return base.startswith(".")
        except Exception:
            return False

else:
    # Non-Windows-Fallbacks
    def to_long_path(path: str) -> str:
        # Auf POSIX-Systemen gibt es keine Long-Path-Präfixe.
        return os.path.abspath(path) if path else path

    def is_hidden_or_system_dir(path: str) -> bool:
        # "hidden" auf macOS/Linux: führender Punkt.
        try:
            base = os.path.basename(path.rstrip("/"))
            return base.startswith(".")
        except Exception:
            return False
