# -*- coding: utf-8 -*-
"""
Plattformneutrale FS-Utilities:
- Windows: Extended-Length-Pfade (\\?\\) + Hidden/System via Win-Attribute
- macOS/Linux: Fallbacks (normale Pfade, Hidden nur via "."-Prefix)

Diese Datei kann auf allen Plattformen importiert werden.
"""
from __future__ import annotations

import os
import sys

# ---------- Windows-spezifische Implementierung ----------
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    FILE_ATTRIBUTE_HIDDEN = 0x2
    FILE_ATTRIBUTE_SYSTEM = 0x4
    INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

    GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
    GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    GetFileAttributesW.restype = wintypes.DWORD

    def to_long_path(path: str) -> str:
        """Erzeugt Extended-Length-Pfad für Windows."""
        if not path:
            return path
        path = os.path.abspath(path)
        if path.startswith("\\\\?\\"):
            return path
        if path.startswith("\\\\"):  # UNC -> \\?\UNC\server\share\...
            return "\\\\?\\UNC\\" + path[2:]
        return "\\\\?\\" + path

    def is_hidden_or_system_dir(path: str) -> bool:
        """True, wenn Ordner Hidden oder System ist (Windows-Attribute)."""
        try:
            attrs = GetFileAttributesW(path)
            if attrs == INVALID_FILE_ATTRIBUTES:
                return False
            if attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                return True
            # Unix-artige "hidden" zusätzlich tolerieren
            base = os.path.basename(path.rstrip("\\/"))
            return base.startswith(".")
        except Exception:
            return False

# ---------- Fallback für macOS/Linux ----------
else:
    def to_long_path(path: str) -> str:
        """Auf Nicht-Windows einfach normalisieren."""
        return os.path.abspath(path or "")

    def is_hidden_or_system_dir(path: str) -> bool:
        """macOS/Linux: 'hidden' per '.'-Prefix; System-Flag ignorieren."""
        try:
            base = os.path.basename(path.rstrip("/"))
            return base.startswith(".")
        except Exception:
            return False
