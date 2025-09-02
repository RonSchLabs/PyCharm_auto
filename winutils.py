# -*- coding: utf-8 -*-
r"""
Windows-Helfer:
- Extended-Length-Pfade (\\?\\) für Windows
- UNC-Pfade (z. B. \x5c\x5c?\x5cUNC\x5cserver\x5cshare\x5c...)
- Hidden/System-Erkennung
"""

import os
import ctypes
from ctypes import wintypes

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
GetFileAttributesW.restype = wintypes.DWORD

def to_long_path(path: str) -> str:
    """
    Erzeugt Extended-Length-Pfad für Windows.

    Beispiele:
      - Lokale Pfade:        \\?\\C:\\...   (Präfix \\?\\)
      - UNC-Variante:        \x5c\x5c?\x5cUNC\x5cserver\x5cshare\x5c...  (Präfix \\?\\UNC\\)
    """
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
