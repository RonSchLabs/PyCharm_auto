# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List
import json

@dataclass
class Node:
    path: str
    name: str
    immediate_files: int = 0
    immediate_dirs: int = 0
    immediate_size: int = 0
    total_files: int = 0
    total_dirs: int = 0
    total_size: int = 0
    children: Dict[str, "Node"] = field(default_factory=dict)

    def child_list(self) -> List["Node"]:
        return list(self.children.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "immediate_files": self.immediate_files,
            "immediate_dirs": self.immediate_dirs,
            "immediate_size": self.immediate_size,
            "total_files": self.total_files,
            "total_dirs": self.total_dirs,
            "total_size": self.total_size,
            "children": [c.to_dict() for c in self.child_list()],
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Node":
        n = Node(
            path=d["path"],
            name=d["name"],
            immediate_files=d.get("immediate_files", 0),
            immediate_dirs=d.get("immediate_dirs", 0),
            immediate_size=d.get("immediate_size", 0),
            total_files=d.get("total_files", 0),
            total_dirs=d.get("total_dirs", 0),
            total_size=d.get("total_size", 0),
        )
        for cd in d.get("children", []):
            c = Node.from_dict(cd)
            n.children[c.name] = c
        return n

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(s: str) -> "Node":
        return Node.from_dict(json.loads(s))

def format_int_de(n: int) -> str:
    s = f"{int(n):,}"
    return s.replace(",", ".")

def format_bytes_mb_gb(total_bytes: int) -> (float, str):
    GB = 1024 ** 3
    MB = 1024 ** 2
    if total_bytes >= GB:
        return total_bytes / GB, "GB"
    else:
        return total_bytes / MB, "MB"
