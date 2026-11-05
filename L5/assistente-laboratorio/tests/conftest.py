"""Impostazioni comuni ai test."""
import os
import tempfile
from pathlib import Path

# i test non devono mai toccare l'archivio vero delle note (assistente-laboratorio/dati/):
# per tutta la sessione NOTE_DB punta a una cartella temporanea. I singoli test possono
# sovrascriverla con monkeypatch.
_CARTELLA_NOTE = tempfile.mkdtemp(prefix="note-test-")
os.environ["NOTE_DB"] = str(Path(_CARTELLA_NOTE) / "note.sqlite")
