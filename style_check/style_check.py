#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
style_check/style_check.py
- Läuft rekursiv über das Projekt (eine Ebene höher als dieses Skript),
- ignoriert versteckte/übliche Ordner (inkl. .venv & style_check/),
- ruft Linter gekapselt aus style_check/ auf (npx im style_check-Workingdir + explizite --config/-c Pfade),
- prüft/erstellt fehlende Abhängigkeiten (pyflakes / npm install) automatisch.
"""

import argparse
import json
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

# ---------- Pfade & Basiskonfig ----------
THIS_DIR = Path(__file__).resolve().parent               # .../style_check
PROJECT_ROOT = THIS_DIR.parent                           # Projekt-Root
CONFIG_DIR = THIS_DIR                                    # style_check/

EXCLUDED_DIRS = {
    ".venv", "venv", "__pycache__", ".git", ".idea", ".vscode",
    "node_modules", "dist", "build", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".cache",
    "style_check"  # sich selbst nicht durchsuchen
}

EXTENSIONS = {
    "python": {".py"},
    "eslint": {".js", ".cjs", ".mjs", ".jsx", ".ts", ".tsx"},
    "stylelint": {".css", ".scss", ".sass"},
    "htmlhint": {".html", ".htm"},
}
ALL_EXTS = set().union(*EXTENSIONS.values())

USE_UNICODE = True

# ---------- Ausgabe-Helpers ----------
def symbol_ok() -> str:   return "✅" if USE_UNICODE else "[OK]"
def symbol_warn() -> str: return "⚠️" if USE_UNICODE else "[WARN]"
def symbol_err() -> str:  return "❌" if USE_UNICODE else "[ERR]"

def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)

def should_skip_dir(name: str) -> bool:
    return name.startswith(".") or name in EXCLUDED_DIRS

def detect_tool(file_path: Path) -> Optional[str]:
    ext = file_path.suffix.lower()
    for tool, exts in EXTENSIONS.items():
        if ext in exts:
            return tool
    return None

def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", f"Tool nicht gefunden: {e}"
    except Exception as e:
        return 2, "", f"Unerwarteter Fehler bei {cmd}: {e}"

# ---------- Abhängigkeits-Checks (neu) ----------
def ensure_python_deps() -> None:
    """Sichert, dass pyflakes im aktiven Interpreter vorhanden ist (installiert sonst)."""
    try:
        import pyflakes  # noqa: F401
        print(f"{symbol_ok()} Python-Abhängigkeit vorhanden: pyflakes")
    except Exception:
        print(f"{symbol_warn()} Python-Modul 'pyflakes' fehlt – Installation wird versucht …")
        rc, out, err = run_cmd([sys.executable, "-m", "pip", "install", "pyflakes"], cwd=PROJECT_ROOT)
        if rc != 0:
            print(f"{symbol_err()} Konnte 'pyflakes' nicht installieren.\n{out or ''}\n{err or ''}")
            sys.exit(1)
        print(f"{symbol_ok()} 'pyflakes' installiert.")

def ensure_node_and_deps() -> None:
    """Sichert, dass Node/npm da sind und node_modules in style_check/ installiert ist.
       Fehlt package.json, wird eine minimale erzeugt (mit devDependencies für die Linter)."""
    if not which("npm"):
        print(f"{symbol_err()} 'npm' wurde nicht gefunden. Bitte Node.js installieren (z. B. via Homebrew: brew install node).")
        sys.exit(1)

    pkg_json = CONFIG_DIR / "package.json"
    node_modules = CONFIG_DIR / "node_modules"

    if not pkg_json.exists():
        print(f"{symbol_warn()} Keine package.json in {CONFIG_DIR} – minimale wird erzeugt.")
        minimal_pkg = {
            "name": "style_check",
            "version": "1.0.0",
            "private": True,
            "type": "commonjs",
            "description": "Gekapselte Lint-Umgebung für das Projekt.",
            "scripts": {
                "lint:css": 'stylelint "../static/**/*.css" --config stylelint.config.cjs',
                "lint:html": 'htmlhint "../templates/**/*.html" -c .htmlhintrc',
                "lint:js": 'eslint "../" --config eslint.config.cjs',
                "lint": "npm run lint:css && npm run lint:html && npm run lint:js"
            },
            "devDependencies": {
                "@eslint/js": "^9.33.0",
                "eslint": "^9.33.0",
                "htmlhint": "^1.2.3",
                "stylelint": "^16.23.1",
                "stylelint-config-standard": "^39.0.0"
            }
        }
        pkg_json.write_text(json.dumps(minimal_pkg, ensure_ascii=False, indent=2), encoding="utf-8")

    if not node_modules.exists():
        print(f"{symbol_warn()} node_modules fehlt – 'npm install' wird in {CONFIG_DIR} ausgeführt …")
        rc, out, err = run_cmd(["npm", "install"], cwd=CONFIG_DIR)
        if rc != 0:
            print(f"{symbol_err()} npm install fehlgeschlagen.\n{out or ''}\n{err or ''}")
            sys.exit(1)
        print(f"{symbol_ok()} npm-Dependencies installiert.")

# ---------- Linter Runner (gekapselt via style_check/ npx) ----------
def run_pyflakes(file_path: Path) -> Tuple[int, str, str]:
    cmd = [sys.executable, "-m", "pyflakes", str(file_path)]
    return run_cmd(cmd, cwd=PROJECT_ROOT)

def run_eslint(file_path: Path) -> Tuple[int, str, str]:
    if not which("npx"):
        return 127, "", "npx nicht gefunden (eslint übersprungen)."
    cmd = ["npx", "eslint", str(file_path), "--config", "eslint.config.cjs"]
    return run_cmd(cmd, cwd=CONFIG_DIR)

def run_stylelint(file_path: Path) -> Tuple[int, str, str]:
    if not which("npx"):
        return 127, "", "npx nicht gefunden (stylelint übersprungen)."
    cmd = ["npx", "stylelint", str(file_path), "--config", "stylelint.config.cjs"]
    return run_cmd(cmd, cwd=CONFIG_DIR)

def run_htmlhint(file_path: Path) -> Tuple[int, str, str]:
    if not which("npx"):
        return 127, "", "npx nicht gefunden (htmlhint übersprungen)."
    cmd = ["npx", "htmlhint", str(file_path), "-c", ".htmlhintrc"]
    return run_cmd(cmd, cwd=CONFIG_DIR)

# ---------- Lint-Workflow ----------
def lint_one(file_path: Path) -> Dict:
    tool = detect_tool(file_path)
    rel = file_path.relative_to(PROJECT_ROOT)

    if tool is None:
        return {"file": str(rel), "tool": None, "status": "skipped",
                "message": "Kein Linter zugeordnet.", "rc": 0, "stdout": "", "stderr": ""}

    if tool == "python":
        rc, out, err = run_pyflakes(file_path)
        status = "ok" if rc == 0 and not out and not err else ("error" if rc != 0 else "warn")
        return {"file": str(rel), "tool": "pyflakes", "status": status, "rc": rc,
                "stdout": out.strip(), "stderr": err.strip(), "message": "Python geprüft (pyflakes)."}

    if tool == "eslint":
        rc, out, err = run_eslint(file_path)
        status = "ok" if rc == 0 else ("error" if rc > 1 else "warn")
        return {"file": str(rel), "tool": "eslint", "status": status, "rc": rc,
                "stdout": out.strip(), "stderr": err.strip(), "message": "JavaScript/TypeScript geprüft (eslint)."}

    if tool == "stylelint":
        rc, out, err = run_stylelint(file_path)
        status = "ok" if rc == 0 else ("error" if rc > 1 else "warn")
        return {"file": str(rel), "tool": "stylelint", "status": status, "rc": rc,
                "stdout": out.strip(), "stderr": err.strip(), "message": "CSS geprüft (stylelint)."}

    if tool == "htmlhint":
        rc, out, err = run_htmlhint(file_path)
        status = "ok" if rc == 0 else ("error" if rc > 1 else "warn")
        return {"file": str(rel), "tool": "htmlhint", "status": status, "rc": rc,
                "stdout": out.strip(), "stderr": err.strip(), "message": "HTML geprüft (htmlhint)."}

    return {"file": str(rel), "tool": tool, "status": "skipped",
            "rc": 0, "stdout": "", "stderr": "", "message": "Unbekanntes Tool."}

def gather_files(start: Path) -> List[Path]:
    files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(start):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for fn in filenames:
            if fn.startswith("."):
                continue
            p = Path(dirpath) / fn
            if p.suffix.lower() in ALL_EXTS:
                files.append(p)
    return files

def print_result(res: Dict) -> None:
    status = res["status"]; tool = res.get("tool") or "-"; file = res["file"]
    if status == "ok":
        print(f"{symbol_ok()} {file} [{tool}]")
    elif status == "warn":
        print(f"{symbol_warn()} {file} [{tool}]")
        if res.get("stdout"): print(res["stdout"])
        if res.get("stderr"): print(res["stderr"])
    elif status == "error":
        print(f"{symbol_err()} {file} [{tool}]")
        if res.get("stdout"): print(res["stdout"])
        if res.get("stderr"): print(res["stderr"])

def summarize(results: List[Dict]) -> Dict:
    summary = {"ok": 0, "warn": 0, "error": 0, "skipped": 0, "by_tool": {}}
    for r in results:
        st = r["status"]
        summary[st] = summary.get(st, 0) + 1
        tool = r.get("tool") or "none"
        summary["by_tool"].setdefault(tool, {"ok": 0, "warn": 0, "error": 0, "skipped": 0})
        summary["by_tool"][tool][st] += 1
    return summary

# ---------- Main ----------
def main():
    # Abhängigkeiten vorab sicherstellen
    ensure_python_deps()
    ensure_node_and_deps()

    ap = argparse.ArgumentParser(description="Style/Lint-Check für das Projekt (gekapselt).")
    ap.add_argument("--root", default=str(PROJECT_ROOT), help="Projekt-Root (Default: eine Ebene über style_check).")
    ap.add_argument("--max-workers", type=int, default=min(8, (os.cpu_count() or 2)))
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    print(f"🔍 Starte Linting in: {root}")
    print("   (Ignoriert: versteckte Ordner + " + ", ".join(sorted(EXCLUDED_DIRS)) + ")")
    start = time.time()

    files = gather_files(root)
    if not files:
        print("Keine passenden Dateien gefunden. Beende.")
        sys.exit(0)

    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        futures = [ex.submit(lint_one, f) for f in files]
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            print_result(res)

    summary = summarize(results)
    dur = time.time() - start

    print("\n— Zusammenfassung —")
    print(f"{symbol_ok()} OK: {summary['ok']}   {symbol_warn()} Warnungen: {summary['warn']}   {symbol_err()} Fehler: {summary['error']}   (übersprungen: {summary['skipped']})")
    print("\nNach Tool:")
    for tool, c in sorted(summary["by_tool"].items()):
        print(f"  - {tool:9s} -> OK: {c['ok']:3d} | Warn: {c['warn']:3d} | Fehler: {c['error']:3d} | Skip: {c['skipped']:3d}")
    print(f"\n⏱ Dauer: {dur:.2f}s   | Geprüfte Dateien: {len(results)}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"results": results, "summary": summary, "duration_s": dur}, f, ensure_ascii=False, indent=2)
        print(f"JSON-Report gespeichert: {args.json_out}")

    sys.exit(1 if summary["error"] > 0 else 0)

if __name__ == "__main__":
    main()
