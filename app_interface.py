#!/usr/bin/env python3
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENT_DIR = ROOT / "client"
GUI_DIR = ROOT / "gui"

# Le dipendenze (requests, python-dotenv) sono nella venv: se lo script è
# lanciato con un altro Python (./app_interface.py, python di sistema) si
# rilancia con l'interprete della venv
VENV_PYTHON = ROOT / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    sys.exit(subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]))

# client.py e web_gui.py stanno in sottocartelle: si aggiungono al percorso
# di import così `import client` e `import web_gui` funzionano
sys.path[:0] = [str(CLIENT_DIR), str(GUI_DIR)]

MENU = """
=== Assistente LLM ===
1) Chat da terminale (senza interfaccia)
2) Chat con interfaccia grafica
3) Esci
"""

while True:
    print(MENU)
    scelta = input("Scelta: ").strip()
    if scelta == "1":
        # Esegue client.py come script: parte il suo ciclo di chat
        runpy.run_path(str(CLIENT_DIR / "client.py"), run_name="__main__")
    elif scelta == "2":
        # Interfaccia web (HTML + CSS) servita in locale
        import web_gui
        web_gui.run()
    elif scelta == "3":
        break
    else:
        print("Scelta non valida: scrivi 1, 2 o 3.")
