# -*- coding: utf-8 -*-
import os
import time
import threading
import platform
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.ticker as ticker

from model import Node, format_int_de
from scanner import scan_tree, DEFAULT_WORKERS

COPYRIGHT_TEXT = "Shopfloor IT Gießerei und Bearbeitung | COK-Z/5 | Ronny Schmidt"


class PfadAnalyseApp(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("Pfadanalyse v2 – Ordneranalyse (Windows/macOS)")
        self.master.geometry("1600x980")
        self.pack(fill="both", expand=True)

        self._is_mac = (platform.system() == "Darwin")

        # State
        self.root_node: Node | None = None
        self.anim_seconds = tk.DoubleVar(value=5.0)
        self.scanning = False
        self._scan_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._scan_start_ts = None
        self._current_path = tk.StringVar(value="")

        self.top_n_enabled = tk.BooleanVar(value=False)  # standardmäßig aus
        self.top_n = tk.IntVar(value=15)
        self.sort_mode = tk.StringVar(value="size")  # "size" oder "count"

        # PanedWindow/Tree Sichtbarkeit
        self._tree_visible = True
        self._last_sash = 520  # Default-Position merken

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_footer()

        # Sash initial positionieren
        self.after(300, self._ensure_initial_sash)

        # Sauberes Beenden (auch in der EXE) sicherstellen
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI Aufbau ----------
    def _build_menu(self):
        m = tk.Menu(self.master)
        self.master.config(menu=m)

        filem = tk.Menu(m, tearoff=False)
        filem.add_command(
            label=f"Ordner scannen… ({'Cmd+O' if self._is_mac else 'Strg+O'})",
            command=self.cmd_scan_folder,
            accelerator="Cmd+O" if self._is_mac else "Ctrl+O"
        )
        filem.add_separator()
        filem.add_command(
            label=f"Snapshot laden… ({'Cmd+J' if self._is_mac else 'Strg+J'})",
            command=self.cmd_load_json,
            accelerator="Cmd+J" if self._is_mac else "Ctrl+J"
        )
        filem.add_command(
            label=f"Snapshot speichern… ({'Cmd+S' if self._is_mac else 'Strg+S'})",
            command=self.cmd_save_json,
            accelerator="Cmd+S" if self._is_mac else "Ctrl+S"
        )
        filem.add_separator()
        filem.add_command(
            label=f"CSV exportieren ({'Cmd+E' if self._is_mac else 'Strg+E'})",
            command=self.cmd_export_csv,
            accelerator="Cmd+E" if self._is_mac else "Ctrl+E"
        )
        filem.add_separator()
        filem.add_command(label="Beenden", command=self.master.destroy)
        m.add_cascade(label="Datei", menu=filem)

        viewm = tk.Menu(m, tearoff=False)
        sortm = tk.Menu(viewm, tearoff=False)
        sortm.add_radiobutton(label="Sortieren nach Größe", variable=self.sort_mode, value="size", command=self.on_tree_select)
        sortm.add_radiobutton(label="Sortieren nach Anzahl", variable=self.sort_mode, value="count", command=self.on_tree_select)
        viewm.add_cascade(label="Sortieren nach …", menu=sortm)
        viewm.add_checkbutton(label="Nur Top-N anzeigen", onvalue=True, offvalue=False, variable=self.top_n_enabled, command=self.on_tree_select)
        viewm.add_command(label="Top-N einstellen…", command=self._set_top_n)
        m.add_cascade(label="Ansicht", menu=viewm)

        # Shortcuts
        self.master.bind_all("<Command-o>" if self._is_mac else "<Control-o>", lambda e: self.cmd_scan_folder())
        self.master.bind_all("<Command-j>" if self._is_mac else "<Control-j>", lambda e: self.cmd_load_json())
        self.master.bind_all("<Command-s>" if self._is_mac else "<Control-s>", lambda e: self.cmd_save_json())
        self.master.bind_all("<Command-e>" if self._is_mac else "<Control-e>", lambda e: self.cmd_export_csv())

    def _build_toolbar(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=6)

        ttk.Label(bar, text="Animationsdauer (s):").pack(side="left")
        tk.Spinbox(bar, from_=0.5, to=20.0, increment=0.5, textvariable=self.anim_seconds, width=6).pack(side="left", padx=(6, 20))

        ttk.Label(bar, text="Scanner-Threads:").pack(side="left")
        self.worker_var = tk.IntVar(value=DEFAULT_WORKERS)
        tk.Spinbox(bar, from_=1, to=16, increment=1, textvariable=self.worker_var, width=4).pack(side="left", padx=(6, 12))

        self.btn_scan = ttk.Button(bar, text="Ordner scannen…", command=self.cmd_scan_folder)
        self.btn_scan.pack(side="left", padx=(0, 6))

        self.btn_stop = ttk.Button(bar, text="Stopp", command=self.cmd_stop_scan, state="disabled")
        self.btn_stop.pack(side="left", padx=(0, 6))

        self.btn_toggle_tree = ttk.Button(bar, text="Baum ausblenden", command=self._toggle_tree)
        self.btn_toggle_tree.pack(side="left", padx=(0, 12))

        ttk.Label(bar, text="Pfad:").pack(side="left")
        path_lbl = ttk.Label(bar, textvariable=self._current_path, width=80)
        path_lbl.pack(side="left", padx=(6, 0))

        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=220)
        self.progress.pack(side="right", padx=(10, 0))

    def _build_body(self):
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.body = body  # Referenz

        # Tree (links)
        left = ttk.Frame(body)
        body.add(left, weight=1)
        self.left = left

        self.tree = ttk.Treeview(
            left,
            columns=("files", "dirs", "totalsize"),
            selectmode="browse",
            show="tree headings"
        )
        self.tree.heading("#0", text="Ordner")
        self.tree.heading("files", text="Dateien")
        self.tree.heading("dirs", text="Ordner")
        self.tree.heading("totalsize", text="Größe")

        self.tree.column("#0", width=300, minwidth=250, anchor="w", stretch=True)
        self.tree.column("files", width=70, minwidth=70, anchor="e", stretch=False)
        self.tree.column("dirs", width=70, minwidth=70, anchor="e", stretch=False)
        self.tree.column("totalsize", width=70, minwidth=70, anchor="e", stretch=True)

        hscroll = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=hscroll.set)

        self.tree.pack(fill="both", expand=True)
        hscroll.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # Charts (rechts, untereinander)
        right = ttk.Frame(body)
        body.add(right, weight=2)
        self.right = right

        self.figure, (self.ax_count, self.ax_size) = plt.subplots(2, 1, figsize=(9, 8))
        self.figure.subplots_adjust(hspace=0.35, left=0.10, right=0.98, top=0.92, bottom=0.10)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Auto-Resize letzte Spalte
        self.left.bind("<Configure>", lambda e: self._autosize_tree_last_col())
        self.after(100, self._init_layout)

    def _init_layout(self):
        try:
            self.body.sashpos(0, 600)
        except Exception:
            pass
        self._autosize_tree_last_col()
        self._fullwidth_redraw()

    def _ensure_initial_sash(self):
        try:
            self.update_idletasks()
            bw = max(1, self.body.winfo_width())
            target = int(bw * 0.38)
            self.body.sashpos(0, target)
            self._last_sash = target
        except Exception:
            pass
        self._fullwidth_redraw()

    def _autosize_tree_last_col(self):
        try:
            total_w = max(0, self.tree.winfo_width())
            used = 0
            for cid in ("#0", "files", "dirs"):
                used += int(self.tree.column(cid, option="width"))
            avail = max(120, total_w - used - 24)
            self.tree.column("totalsize", width=avail)
        except Exception:
            pass

    def _toggle_tree(self):
        if self._tree_visible:
            try:
                self._last_sash = self.body.sashpos(0)
            except Exception:
                pass
            self.body.forget(self.left)
            self.btn_toggle_tree.configure(text="Baum einblenden")
            self._tree_visible = False
        else:
            try:
                self.body.insert(0, self.left)
            except Exception:
                self.body.add(self.left, weight=1)
            self.after(10, lambda: self.body.sashpos(0, self._last_sash))
            self.btn_toggle_tree.configure(text="Baum ausblenden")
            self._tree_visible = True
            # Layout anpassen
            self.after(50, self._fullwidth_redraw)

    def _build_footer(self):
        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=8, pady=(0, 8))
        self.status = tk.Label(foot, text="Bereit", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.footer_label = tk.Label(foot, text=COPYRIGHT_TEXT, anchor="e", font=("Arial", 8))
        self.footer_label.pack(side="right")

    # ---------- Commands ----------
    def cmd_scan_folder(self):
        path = filedialog.askdirectory(title="Ordner für Pfadanalyse wählen")
        if not path:
            return
        if not os.path.isdir(path):
            messagebox.showerror("Fehler", "Ungültiger Ordner.")
            return
        self._current_path.set(path)
        self._start_scan(path)

    def cmd_stop_scan(self):
        if not self.scanning:
            return
        self._stop_event.set()
        self.status.config(text="Abbruch angefordert…")

    def cmd_load_json(self):
        fn = filedialog.askopenfilename(title="Snapshot (JSON) laden", filetypes=[("JSON", "*.json")])
        if not fn:
            return
        try:
            with open(fn, "r", encoding="utf-8") as f:
                txt = f.read()
            self.root_node = Node.from_json(txt)
            self._populate_tree()
            self.status.config(text=f"Snapshot geladen: {fn}")
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte JSON nicht laden:\n{e}")

    def cmd_save_json(self):
        if not self.root_node:
            messagebox.showinfo("Hinweis", "Kein Snapshot vorhanden.")
            return
        fn = filedialog.asksaveasfilename(title="Snapshot speichern", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not fn:
            return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(self.root_node.to_json())
            self.status.config(text=f"Snapshot gespeichert: {fn}")
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte JSON nicht speichern:\n{e}")

    def cmd_export_csv(self):
        node = self._get_selected_node()
        if not node:
            messagebox.showinfo("Hinweis", "Bitte einen Ordner im Baum auswählen.")
            return
        fn = filedialog.asksaveasfilename(title="CSV exportieren (aktuelle Ansicht)", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not fn:
            return
        try:
            import csv
            with open(fn, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Ordnername", "Dateien ges.", "Ordner ges.", "Größe (Bytes) ges."])
                for child in node.child_list():
                    w.writerow([child.name, child.total_files, child.total_dirs, child.total_size])
                w.writerow([])
                w.writerow(["", "", "", COPYRIGHT_TEXT])
            self.status.config(text=f"CSV exportiert: {fn}")
        except Exception as e:
            messagebox.showerror("Fehler", f"CSV-Export fehlgeschlagen:\n{e}")

    # ---------- Scan ----------
    def _start_scan(self, path: str):
        if self.scanning:
            return
        self.scanning = True
        self._stop_event.clear()
        self._scan_start_ts = time.time()
        self.status.config(text=f"Scanne… ({path})")
        self.progress.start(12)
        self.btn
