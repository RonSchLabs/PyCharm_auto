# -*- coding: utf-8 -*-
"""
Hilfsfunktionen für Dateipfade.

Unter Windows werden Extended-Length-Pfade (``\\\\?\\``) sowie
Attribut-Abfragen über ``GetFileAttributesW`` unterstützt. Auf anderen
Plattformen (z.\u00a0B. macOS) werden einfache Implementierungen verwendet,
die lediglich versteckte Dateien anhand ihres ``.``-Präfixes erkennen.
"""

import os
import sys

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
        if path.startswith("\\\\"):
            # UNC -> \\?\UNC\server\share\...
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
            # Unix-artige "hidden" (Prefix ".") optional:
            base = os.path.basename(path.rstrip("\\/"))
            return base.startswith(".")
        except Exception:
            return False
else:
    # Auf Nicht-Windows-Plattformen reichen einfache Implementierungen aus.
    def to_long_path(path: str) -> str:
        return os.path.abspath(path)

    def is_hidden_or_system_dir(path: str) -> bool:
        base = os.path.basename(path.rstrip("/"))
        return base.startswith(".")
