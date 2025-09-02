# Pfadanalyse v2 (Windows, Tkinter + Matplotlib)

## Funktionen
- Schneller Vorscan (voll rekursiv) mit Größen (Bytes), Datei-/Ordneranzahl je Verzeichnis.
- Versteckte & System-Ordner werden standardmäßig übersprungen.
- Windows-Überlängen unterstützt (`\\?\`-Präfix; UNC ebenfalls).
- TreeView-Navigation: Beim Anklicken eines Ordners erscheinen **zwei Diagramme**:
  - Gesamtgröße je Unterordner
  - Anzahl Dateien + Ordner je Unterordner
- „Slide“-Effekt: Balken füllen sich sanft in einer einstellbaren Dauer (Standard 5 s).
- Blinkende rote Statuszeile + indeterminater Progress während des Scans.
- Export: CSV (aktuelle Ansicht) & JSON (Snapshot, wieder ladbar).

## Start
```bash
python app.py
