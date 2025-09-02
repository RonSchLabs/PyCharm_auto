# style_check

Gekapseltes Lint-/Style-Toolkit für beliebige Projekte.  
Einfach den Ordner `style_check/` ins Projekt kopieren und loslegen.  
Unterstützt **macOS/Linux** und **Windows**.

---

## Inhalt
- `style_check.py` – Python-Runner: sammelt Projektdateien, ruft passende Linter auf, installiert fehlende Abhängigkeiten automatisch
- `eslint.config.cjs` – ESLint Flat-Config (JS/TS)
- `stylelint.config.cjs` – Stylelint-Konfiguration (CSS/SCSS/SASS)
- `.htmlhintrc` – HTMLHint-Konfiguration
- `package.json` – Node-„Mini-Projekt“ mit Linter-Dependencies (werden in `style_check/node_modules/` installiert)

---

## Voraussetzungen

### macOS / Linux
- **Python 3** (am besten im Projekt-eigenen `.venv`)
- **Node.js + npm** (z. B. via Homebrew: `brew install node`)

### Windows
- **Python 3** (im Projekt-eigenen `venv`)
- **Node.js + npm** (Download von [nodejs.org](https://nodejs.org))

> Der Runner installiert bei Bedarf selbst:
> - `pyflakes` (Python) via `pip`
> - alle Node-Dependencies (ESLint, Stylelint, HTMLHint) via `npm install` in `style_check/`

---

## Schnellstart

### Variante A (empfohlen): Python-Runner

**macOS / Linux (Bash, Zsh):**
```bash
python3 style_check/style_check.py
```

**Windows (PowerShell / CMD):**
```powershell
python style_check\style_check.py
```

---

### Variante B: npm-Scripts

**macOS / Linux:**
```bash
npm -C style_check run lint
```

**Windows (PowerShell):**
```powershell
npm --prefix style_check run lint
```

---

## Was wird geprüft?

| Tool        | Dateiendungen                                    |
|-------------|---------------------------------------------------|
| Pyflakes    | `.py`                                             |
| ESLint      | `.js`, `.cjs`, `.mjs`, `.jsx`, `.ts`, `.tsx`     |
| Stylelint   | `.css`, `.scss`, `.sass`                          |
| HTMLHint    | `.html`, `.htm`                                   |

Der Python-Runner durchläuft rekursiv das **Projekt-Root** (eine Ebene über `style_check/`) und ignoriert u. a.:
```
.venv, node_modules, style_check, .git, build, dist, __pycache__, .cache, ...
```

---

## Auto-Install

Beim Start prüft `style_check.py` automatisch:
1. **Python:** Ist `pyflakes` importierbar? → sonst `pip install pyflakes`.
2. **Node/npm vorhanden?** → andernfalls Abbruch mit Hinweis.
3. **`style_check/package.json` vorhanden?** → sonst Minimal-`package.json` erzeugen.
4. **`style_check/node_modules` vorhanden?** → sonst `npm install` in `style_check/`.

Folgeläufe sind still (keine Re-Installation).

---

## Fix-Kommandos (Autoformat, wo möglich)

**macOS / Linux:**
```bash
npm -C style_check run fix:css
npm -C style_check run fix:js
```

**Windows (PowerShell):**
```powershell
npm --prefix style_check run fix:css
npm --prefix style_check run fix:js
```

---

## In ein neues Projekt kopieren

1. Ordner `style_check/` **ins Projekt-Root** kopieren (direkt unterhalb des Repos).
2. Ausführen:

   **macOS / Linux:**
   ```bash
   python3 style_check/style_check.py
   ```

   **Windows:**
   ```powershell
   python style_check\style_check.py
   ```

   → Abhängigkeiten werden bei Bedarf automatisch installiert, danach werden alle passenden Dateien geprüft.

---

## Updates & Wartung

### Warum updaten?
- **ESLint** und **Stylelint** entwickeln sich schnell (neue Syntax/Regeln).
- **Pyflakes** ist stabiler, profitiert aber von Support für neue Python-Versionen.
- **HTMLHint** ändert sich selten.

---

### Update-Check (Node)

**macOS / Linux / Windows:**
```bash
cd style_check
npm outdated
```

---

### Update ausführen (Node)

**macOS / Linux / Windows:**
```bash
cd style_check
npm update
```

oder gezielt:
```bash
npm install eslint@latest @eslint/js@latest
npm install stylelint@latest stylelint-config-standard@latest
npm install htmlhint@latest
```

---

### Python

**macOS / Linux:**
```bash
pip install --upgrade pyflakes
```

**Windows (PowerShell / CMD):**
```powershell
pip install --upgrade pyflakes
```

---

## Versionen einfrieren

Um sicherzustellen, dass alle Entwickler und alle CI/CD-Pipelines **exakt dieselben Versionen** verwenden:

1. Aktuelle Versionen ermitteln:
   ```bash
   cd style_check
   npm list --depth=0
   ```
   Beispiel:
   ```
   ├── @eslint/js@9.33.0
   ├── eslint@9.33.0
   ├── htmlhint@1.2.3
   ├── stylelint@16.23.1
   └── stylelint-config-standard@39.0.0
   ```

2. Diese Nummern **ohne Caret `^`** in `package.json` eintragen:
   ```json
   {
    "devDependencies": {
      "eslint": "9.33.0",
      "@eslint/js": "9.33.0",
      "stylelint": "16.23.1",
      "stylelint-config-standard": "39.0.0",
      "htmlhint": "1.2.3"
    }
   }
   ```

3. Alternativ kannst du `package.json` so lassen und dich auf **`package-lock.json` + `npm ci`** verlassen:
   - `npm install` → holt neue Minor-/Patch-Versionen (wenn `^` vorhanden ist).
   - `npm ci` → installiert exakt die Versionen aus `package-lock.json`.

4. Für Python (`pyflakes`) die Version anzeigen:
   ```bash
   pip show pyflakes
   ```
   → Beispiel: `Version: 3.2.0`  
   Diese Nummer kannst du in `requirements.txt` festhalten:
   ```
   pyflakes==3.2.0
   ```
   Dann mit:
   ```bash
   pip install -r requirements.txt
   ```
   überall reproduzierbar.

---

## Troubleshooting

- **`npm`/`npx` nicht gefunden:** Node.js installieren.  
  - macOS: `brew install node`  
  - Windows: [nodejs.org](https://nodejs.org) Installer nutzen.  
- **`ConfigurationError: No configuration provided` (Stylelint):**  
  Stelle sicher, dass `stylelint.config.cjs` in `style_check/` liegt.  
- **HTMLHint meckert `doctype-first` bei Jinja-Templates:**  
  In `.htmlhintrc` ist `doctype-first: false` gesetzt – Templates sind so korrekt.  
- **PyCharm „Typos“ wie `htmlhint`, `stylelint`, `dirnames`:**  
  Per *Alt+Enter → Save to dictionary* ins Wörterbuch aufnehmen, oder Variablen umbenennen.  
- **IDE warnt in `eslint.config.cjs` über `configs`:**  
  Kommentar `// noinspection JSUnresolvedVariable` oben einfügen oder Node.js-Core-Library in **Preferences → JavaScript → Libraries** aktivieren.

---

## Tipps

- **CI/CD:** In GitHub Actions oder Jenkins einfach `python style_check/style_check.py` als Step.  
- **Pre-commit Hooks:** Optional `husky` + `lint-staged` in `style_check/` verwenden, wenn du JS/HTML/CSS vor jedem Commit auto-fixen willst.

---

## Lizenz
Interner Projekt-Helper. Kopieren/Anpassen ausdrücklich erwünscht. ✌️
