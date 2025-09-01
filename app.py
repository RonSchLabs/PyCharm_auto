# -*- coding: utf-8 -*-
import tkinter as tk
from gui import PfadAnalyseApp

def main():
    root = tk.Tk()
    app = PfadAnalyseApp(root)

    def on_close():
        try:
            app.shutdown()   # <- zuerst alles im App-Objekt sauber stoppen
        except Exception:
            pass
        try:
            root.quit()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
