"""Archivio delle note su SQLite: aggiunta, elenco, lettura ed eliminazione.

Logica pura, senza MCP: il server (server.py) la pubblica come tool. Una connessione per
operazione, chiusa subito (il server riparte a ogni chiamata). Gli ID non vengono mai riusati
(AUTOINCREMENT): dopo aver eliminato la nota 3, nessuna nota nuova diventa la "nota 3".
"""
import os  # per leggere la variabile d'ambiente NOTE_DB
import sqlite3  # database SQLite della libreria standard: un solo file, nessun server
from contextlib import closing  # chiude la connessione anche in caso di errore
from datetime import datetime  # data e ora di creazione della nota
from pathlib import Path  # percorsi indipendenti dal sistema operativo
from zoneinfo import ZoneInfo  # fuso orario italiano per la data di creazione

# --- limiti del contratto (gli stessi della spec e delle descrizioni dei tool) ---
MAX_TESTO = 500  # caratteri massimi di una nota, dopo aver tolto gli spazi esterni
MIN_LIMIT = 1  # list_notes: almeno una nota
MAX_LIMIT = 50  # list_notes: al massimo 50 note per chiamata
LIMIT_PREDEFINITO = 10  # list_notes senza limit
FUSO = ZoneInfo("Europe/Rome")  # le date sono in ora italiana
# cartella del progetto (assistente-laboratorio/): l'archivio predefinito sta in dati/
CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent

# tabella delle note: AUTOINCREMENT impedisce di riusare l'ID di una nota eliminata;
# IF NOT EXISTS la crea solo al primo uso
_SCHEMA = ("CREATE TABLE IF NOT EXISTS note ("
           "id INTEGER PRIMARY KEY AUTOINCREMENT, testo TEXT NOT NULL, creata TEXT NOT NULL)")


class ErroreNote(Exception):
    """Input rifiutato o archivio non accessibile; il messaggio spiega il motivo."""


def percorso_archivio() -> Path:
    """NOTE_DB se impostata, altrimenti assistente-laboratorio/dati/note.sqlite."""
    valore = os.environ.get("NOTE_DB", "").strip()  # i test e Docker la impostano
    return Path(valore) if valore else CARTELLA_PROGETTO / "dati" / "note.sqlite"


def _intero(valore, nome: str) -> int:
    """Accetta solo interi veri: bool e' una sottoclasse di int, ma True non e' un numero."""
    if isinstance(valore, bool) or not isinstance(valore, int):
        raise ErroreNote(f"{nome} deve essere un numero intero, ricevuto {valore!r}.")
    return valore


def _esegui(percorso: Path | None, operazione):
    """Apre l'archivio, esegue `operazione(connessione)` in una transazione e chiude.

    Ogni errore di SQLite o del file system diventa ErroreNote («archivio non accessibile»),
    cosi' il server risponde con un errore chiaro invece di cadere.
    """
    percorso = percorso if percorso is not None else percorso_archivio()
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)  # crea dati/ al primo uso
        with closing(sqlite3.connect(percorso)) as con:  # connessione chiusa all'uscita
            con.row_factory = sqlite3.Row  # righe leggibili per nome di colonna
            with con:  # transazione: commit se tutto va bene, rollback in caso di errore
                con.execute(_SCHEMA)
                return operazione(con)
    except ErroreNote:
        raise  # errori di contratto (es. nota inesistente): passano invariati
    except (sqlite3.Error, OSError) as errore:
        raise ErroreNote(f"Archivio delle note non accessibile: {errore}.") from None


def _nota(riga) -> dict:
    """Riga SQLite -> dizionario con le tre chiavi del contratto."""
    return {"id": riga["id"], "testo": riga["testo"], "creata": riga["creata"]}


def aggiungi(testo: str, percorso: Path | None = None) -> dict:
    """Salva una nota (spazi esterni tolti) e la restituisce con ID e data."""
    testo = testo.strip()
    # controlli del contratto prima di toccare l'archivio: nessun salvataggio se non validi
    if not testo:
        raise ErroreNote("Il testo della nota è vuoto: scrivi che cosa ricordare.")
    if len(testo) > MAX_TESTO:
        raise ErroreNote(f"Il testo della nota è troppo lungo: {len(testo)} caratteri, "
                         f"massimo {MAX_TESTO}.")
    creata = datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S")  # es. 2026-11-05 15:40:12

    def operazione(con):
        # parametri "?": il testo non viene mai inserito direttamente nella query SQL
        cursore = con.execute("INSERT INTO note (testo, creata) VALUES (?, ?)", (testo, creata))
        return {"id": cursore.lastrowid, "testo": testo, "creata": creata}

    return _esegui(percorso, operazione)


def elenca(limit: int = LIMIT_PREDEFINITO, percorso: Path | None = None) -> tuple[list[dict], int]:
    """Le note dalla piu' recente alla piu' vecchia (al massimo `limit`) e il totale."""
    _intero(limit, "limit")
    if not MIN_LIMIT <= limit <= MAX_LIMIT:  # fuori intervallo: errore, nessun ritaglio
        raise ErroreNote(f"limit deve essere tra {MIN_LIMIT} e {MAX_LIMIT}, ricevuto {limit}.")

    def operazione(con):
        totale = con.execute("SELECT COUNT(*) FROM note").fetchone()[0]  # per «Mostrate N di M»
        # piu' recenti prima; a parita' di secondo decide l'ID (piu' alto = piu' recente)
        righe = con.execute("SELECT id, testo, creata FROM note ORDER BY creata DESC, id DESC "
                            "LIMIT ?", (limit,)).fetchall()
        return [_nota(r) for r in righe], totale

    return _esegui(percorso, operazione)


def _cerca(con, note_id: int):
    """La riga della nota con quell'ID, oppure None."""
    return con.execute("SELECT id, testo, creata FROM note WHERE id = ?", (note_id,)).fetchone()


def _id_valido(note_id) -> int:
    """note_id deve essere un intero positivo (gli ID partono da 1)."""
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
        # prima si cerca la nota: se non c'e' si risponde con un errore e non si cancella nulla
        riga = _cerca(con, note_id)
        if riga is None:
            raise ErroreNote(f"La nota {note_id} non esiste: nessuna nota eliminata.")
        con.execute("DELETE FROM note WHERE id = ?", (note_id,))
        return _nota(riga)  # la nota eliminata, per la conferma all'utente

    return _esegui(percorso, operazione)
