# Pfadanalyse v2 (Windows/macOS, Tkinter + Matplotlib)

## Funktionen
- Schneller Vorscan (voll rekursiv) mit Größen (Bytes), Datei-/Ordneranzahl je Verzeichnis.
- Versteckte & System-Ordner werden standardmäßig übersprungen.
- Windows-Überlängen unterstützt (`\\?\`-Präfix; UNC ebenfalls), auf macOS/Linux no-op.
- TreeView-Navigation mit zwei Diagrammen (Größe / Anzahl).
- Export: CSV (aktuelle Ansicht) & JSON (Snapshot).

## Start
```bash
python app.py
