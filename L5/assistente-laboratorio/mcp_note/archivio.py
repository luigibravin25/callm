"""Archivio delle note su SQLite: aggiunta, elenco, lettura ed eliminazione.

Logica pura, senza MCP: il server (server.py) la pubblica come tool. Una connessione per
operazione, chiusa subito (il server riparte a ogni chiamata). Gli ID non vengono mai riusati
(AUTOINCREMENT): dopo aver eliminato la nota 3, nessuna nota nuova diventa la "nota 3".
"""
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MAX_TESTO = 500
MIN_LIMIT = 1
MAX_LIMIT = 50
LIMIT_PREDEFINITO = 10
FUSO = ZoneInfo("Europe/Rome")
# cartella del progetto (assistente-laboratorio/): l'archivio predefinito sta in dati/
CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent

_SCHEMA = ("CREATE TABLE IF NOT EXISTS note ("
           "id INTEGER PRIMARY KEY AUTOINCREMENT, testo TEXT NOT NULL, creata TEXT NOT NULL)")


class ErroreNote(Exception):
    """Input rifiutato o archivio non accessibile; il messaggio spiega il motivo."""


def percorso_archivio() -> Path:
    """NOTE_DB se impostata, altrimenti assistente-laboratorio/dati/note.sqlite."""
    valore = os.environ.get("NOTE_DB", "").strip()
    return Path(valore) if valore else CARTELLA_PROGETTO / "dati" / "note.sqlite"


def _intero(valore, nome: str) -> int:
    # bool e' una sottoclasse di int: True non e' un numero valido
    if isinstance(valore, bool) or not isinstance(valore, int):
        raise ErroreNote(f"{nome} deve essere un numero intero, ricevuto {valore!r}.")
    return valore


def _esegui(percorso: Path | None, operazione):
    """Apre l'archivio, esegue `operazione(connessione)` in una transazione e chiude."""
    percorso = percorso if percorso is not None else percorso_archivio()
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(percorso)) as con:
            con.row_factory = sqlite3.Row
            with con:  # commit se tutto va bene, rollback in caso di errore
                con.execute(_SCHEMA)
                return operazione(con)
    except ErroreNote:
        raise
    except (sqlite3.Error, OSError) as errore:
        raise ErroreNote(f"Archivio delle note non accessibile: {errore}.") from None


def _nota(riga) -> dict:
    return {"id": riga["id"], "testo": riga["testo"], "creata": riga["creata"]}


def aggiungi(testo: str, percorso: Path | None = None) -> dict:
    """Salva una nota (spazi esterni tolti) e la restituisce con ID e data."""
    testo = testo.strip()
    if not testo:
        raise ErroreNote("Il testo della nota è vuoto: scrivi che cosa ricordare.")
    if len(testo) > MAX_TESTO:
        raise ErroreNote(f"Il testo della nota è troppo lungo: {len(testo)} caratteri, "
                         f"massimo {MAX_TESTO}.")
    creata = datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S")

    def operazione(con):
        cursore = con.execute("INSERT INTO note (testo, creata) VALUES (?, ?)", (testo, creata))
        return {"id": cursore.lastrowid, "testo": testo, "creata": creata}

    return _esegui(percorso, operazione)


def elenca(limit: int = LIMIT_PREDEFINITO, percorso: Path | None = None) -> tuple[list[dict], int]:
    """Le note dalla piu' recente alla piu' vecchia (al massimo `limit`) e il totale."""
    _intero(limit, "limit")
    if not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise ErroreNote(f"limit deve essere tra {MIN_LIMIT} e {MAX_LIMIT}, ricevuto {limit}.")

    def operazione(con):
        totale = con.execute("SELECT COUNT(*) FROM note").fetchone()[0]
        righe = con.execute("SELECT id, testo, creata FROM note ORDER BY creata DESC, id DESC "
                            "LIMIT ?", (limit,)).fetchall()
        return [_nota(r) for r in righe], totale

    return _esegui(percorso, operazione)


def _cerca(con, note_id: int):
    return con.execute("SELECT id, testo, creata FROM note WHERE id = ?", (note_id,)).fetchone()


def _id_valido(note_id) -> int:
    _intero(note_id, "note_id")
    if note_id < 1:
        raise ErroreNote(f"note_id deve essere un intero positivo, ricevuto {note_id}.")
    return note_id


def leggi(note_id: int, percorso: Path | None = None) -> dict:
    """Una nota per ID (per l'anteprima della conferma)."""
    _id_valido(note_id)

    def operazione(con):
        riga = _cerca(con, note_id)
        if riga is None:
            raise ErroreNote(f"La nota {note_id} non esiste.")
        return _nota(riga)

    return _esegui(percorso, operazione)


def elimina(note_id: int, percorso: Path | None = None) -> dict:
    """Elimina una nota per ID e la restituisce; un ID inesistente non cambia nulla."""
    _id_valido(note_id)

    def operazione(con):
        riga = _cerca(con, note_id)
        if riga is None:
            raise ErroreNote(f"La nota {note_id} non esiste: nessuna nota eliminata.")
        con.execute("DELETE FROM note WHERE id = ?", (note_id,))
        return _nota(riga)

    return _esegui(percorso, operazione)
