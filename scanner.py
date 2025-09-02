# -*- coding: utf-8 -*-
"""
Schneller rekursiver Scanner (Windows/macOS):
- Versteckte/System-Ordner werden übersprungen
- Symlinks/Junctions werden nicht verfolgt (follow_symlinks=False)
- Optional: mehrere Worker (Default 1 – I/O-freundlich)
- Kooperativer Abbruch über stop_event (threading.Event)
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from model import Node
from winutils import to_long_path, is_hidden_or_system_dir

DEFAULT_WORKERS = 1  # 1 ist Default (I/O freundlich); für SSD ggf. 4–8 probieren
IS_WINDOWS = (os.name == "nt")


def _scan_single_dir(path: str, stop_event=None) -> Tuple[int, int, int, List[str]]:
    """Scant EIN Verzeichnis (nur Ebene 1)."""
    if stop_event is not None and stop_event.is_set():
        return 0, 0, 0, []

    files = 0
    size_sum = 0
    dirs = 0
    child_dirs: List[str] = []

    long = to_long_path(path) if IS_WINDOWS else os.path.abspath(path)

    try:
        with os.scandir(long) as it:
            for entry in it:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    if entry.is_dir(follow_symlinks=False):
                        real_child = os.path.join(path, entry.name)
                        if is_hidden_or_system_dir(real_child):
                            continue
                        child_dirs.append(real_child)
                        dirs += 1
                    elif entry.is_file(follow_symlinks=False):
                        files += 1
                        try:
                            size_sum += entry.stat(follow_symlinks=False).st_size
                        except Exception:
                            pass
                except (PermissionError, FileNotFoundError):
                    # Zugriffsprobleme oder inzwischen verschwunden -> überspringen
                    continue
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        # Direktes Scannen des Ordners nicht möglich -> als leer behandeln
        return 0, 0, 0, []
    except Exception:
        # Defensive: keine harten Abbrüche in einem Worker
        return files, dirs, size_sum, child_dirs

    return files, dirs, size_sum, child_dirs


def scan_tree(
    root_path: str,
    workers: int = DEFAULT_WORKERS,
    progress_cb: Optional[Callable[[str, int, int, int], None]] = None,
    stop_event=None,
) -> Node:
    """
    Baut den kompletten Baum mit aggregierten Werten (rekursiv).
    progress_cb(path, files, dirs, size) wird bei jedem Ordner gerufen (optional).
    stop_event: threading.Event für kooperativen Abbruch.
    """
    root_path = os.path.abspath(root_path.rstrip("\\/"))
    root = Node(path=root_path, name=os.path.basename(root_path) or root_path)

    # Iterativ mit eigenem Stack (kein Python-Recursion-Limit)
    stack: List[Tuple[Node, str, bool]] = [(root, root_path, False)]

    while stack:
        if stop_event is not None and stop_event.is_set():
            break

        node, path, expanded = stack.pop()
        if not expanded:
            files, dcount, size_sum, children = _scan_single_dir(path, stop_event=stop_event)
            node.immediate_files = files
            node.immediate_dirs = dcount
            node.immediate_size = size_sum

            child_nodes: List[Tuple[Node, str, bool]] = []
            for cpath in children:
                cname = os.path.basename(cpath)
                cn = Node(path=cpath, name=cname)
                node.children[cname] = cn
                child_nodes.append((cn, cpath, False))

            # denselben Knoten erneut zum Aggregieren einplanen
            stack.append((node, path, True))

            # ggf. parallel die erste Ebene unterhalb abarbeiten
            if len(child_nodes) > 0 and workers > 1 and not (stop_event and stop_event.is_set()):
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(_scan_single_dir, cp, stop_event): (cn, cp) for (cn, cp, _) in child_nodes}
                    for fut in as_completed(futs):
                        if stop_event is not None and stop_event.is_set():
                            break
                        cn, cp = futs[fut]
                        try:
                            f2, d2, s2, ch2 = fut.result()
                        except Exception:
                            f2 = d2 = s2 = 0
                            ch2 = []
                        cn.immediate_files = f2
                        cn.immediate_dirs = d2
                        cn.immediate_size = s2
                        for sub in ch2:
                            sname = os.path.basename(sub)
                            sn = Node(path=sub, name=sname)
                            cn.children[sname] = sn
                        stack.append((cn, cp, False))
            else:
                stack.extend(child_nodes)

            if progress_cb:
                progress_cb(path, files, dcount, size_sum)

        else:
            # Aggregation: totals = immediate + Summe der Kinder
            tf = node.immediate_files
            td = node.immediate_dirs
            ts = node.immediate_size
            for c in node.children.values():
                tf += c.total_files
                td += (1 + c.total_dirs)
                ts += c.total_size
            node.total_files = tf
            node.total_dirs = td
            node.total_size = ts

    return root
