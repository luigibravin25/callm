"""Contatore delle richieste a Open-Meteo con un limite giornaliero.

Il server meteo e' avviato dall'adattatore a ogni chiamata: un contatore in memoria
ripartirebbe sempre da zero. Per questo il conteggio sta in un file SQLite (una riga per giorno)
che sopravvive ai riavvii. Il giorno e' quello di Roma: a mezzanotte il conteggio riparte.

Variabili d'ambiente:
- METEO_LIMITE_GIORNALIERO: richieste al giorno (intero >= 1, predefinito 1000);
- METEO_CONTATORE: percorso del file (predefinito assistente-laboratorio/dati/meteo_richieste.sqlite).
"""
# os: variabili d'ambiente; sqlite3: file del contatore; sys: avvisi su stderr;
# datetime, ZoneInfo: il giorno corrente a Roma; Path: percorso del file;
# Callable: tipo dell'"orologio" passato al contatore
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

# errori del meteo che il contatore puo' sollevare
from mcp_meteo.errori import ContatoreNonAccessibile, LimiteRaggiunto

LIMITE_PREDEFINITO = 1000  # ben sotto le circa 10.000 richieste al giorno gratuite di Open-Meteo
FUSO_CONTATORE = "Europe/Rome"  # il "giorno" del contatore
# assistente-laboratorio/ (questo file sta in mcp_meteo/)
CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent


# Legge dall'ambiente quante richieste al giorno sono permesse
def limite_giornaliero() -> int:
    """Limite da METEO_LIMITE_GIORNALIERO; assente o vuoto -> 1000, non valido -> 1000 con avviso."""
    testo = os.environ.get("METEO_LIMITE_GIORNALIERO", "").strip()
    if not testo:
        return LIMITE_PREDEFINITO  # variabile non impostata: valore predefinito, nessun avviso
    try:
        valore = int(testo)
    except ValueError:
        valore = 0  # non e' un intero: trattato come non valido qui sotto
    if valore < 1:
        # avviso su stderr (stdout del server e' riservato al protocollo MCP)
        print(f"Avviso: METEO_LIMITE_GIORNALIERO={testo!r} non valido, uso "
              f"{LIMITE_PREDEFINITO}.", file=sys.stderr)
        return LIMITE_PREDEFINITO
    return valore  # intero valido, almeno 1


# Dove sta il file SQLite del contatore
def percorso_contatore() -> Path:
    """File del contatore da METEO_CONTATORE, altrimenti dati/meteo_richieste.sqlite."""
    testo = os.environ.get("METEO_CONTATORE", "").strip()  # i test la impostano
    return Path(testo) if testo else CARTELLA_PROGETTO / "dati" / "meteo_richieste.sqlite"


# Il contatore vero: ogni richiesta a Open-Meteo passa prima da registra()
class Contatore:
    """Conta le richieste di oggi in un file SQLite e blocca quelle oltre il limite."""

    # Memorizza file, limite e orologio
    def __init__(self, percorso: Path, limite: int, adesso: Callable[[], datetime]):
        """File del contatore, limite giornaliero e orologio (sostituibile nei test)."""
        self.percorso = Path(percorso)
        self.limite = limite
        self.adesso = adesso  # istante corrente (sostituibile nei test)

    # Il giorno di oggi a Roma, usato come chiave nella tabella
    def _giorno(self) -> str:
        """Data di oggi a Roma in formato ISO: e' la chiave della riga del contatore."""
        return self.adesso().astimezone(ZoneInfo(FUSO_CONTATORE)).date().isoformat()

    # Apre la connessione al database del contatore
    def _connetti(self) -> sqlite3.Connection:
        """Apre il file (creando cartella e tabella al primo uso)."""
        self.percorso.parent.mkdir(parents=True, exist_ok=True)  # crea dati/ se manca
        # isolation_level=None: le transazioni le apre il codice con BEGIN IMMEDIATE
        # timeout=5: se un altro processo sta scrivendo, aspetta fino a 5 secondi
        connessione = sqlite3.connect(self.percorso, timeout=5, isolation_level=None)
        # una riga per giorno: il giorno e' la chiave, numero e' il conteggio
        connessione.execute("CREATE TABLE IF NOT EXISTS richieste ("
                            "giorno TEXT PRIMARY KEY, numero INTEGER NOT NULL)")
        return connessione

    # Conta una richiesta, o la blocca se il limite di oggi e' gia' raggiunto
    def registra(self) -> int:
        """Conta una richiesta in arrivo e restituisce il nuovo conteggio di oggi.

        Controllo e incremento stanno in una sola transazione (BEGIN IMMEDIATE blocca la
        scrittura agli altri processi): due server avviati insieme non superano il limite.
        Limite gia' raggiunto -> LimiteRaggiunto e nessun incremento.
        """
        giorno = self._giorno()
        try:
            connessione = self._connetti()
            try:
                connessione.execute("BEGIN IMMEDIATE")
                riga = connessione.execute("SELECT numero FROM richieste WHERE giorno = ?",
                                           (giorno,)).fetchone()
                numero = riga[0] if riga else 0  # nessuna riga: oggi nessuna richiesta
                if numero >= self.limite:
                    connessione.execute("ROLLBACK")  # niente da scrivere
                    raise LimiteRaggiunto(f"{self.limite} richieste al servizio meteo per oggi. "
                                          "Per ora non posso rispondere, riprova domani.")
                # inserisce la riga di oggi o incrementa quella esistente
                connessione.execute(
                    "INSERT INTO richieste (giorno, numero) VALUES (?, 1) "
                    "ON CONFLICT(giorno) DO UPDATE SET numero = numero + 1", (giorno,))
                connessione.execute("COMMIT")  # salva e libera il blocco
                return numero + 1
            finally:
                connessione.close()  # chiusa sempre, anche dopo un errore
        except (sqlite3.Error, OSError) as errore:
            # file bloccato, cartella non scrivibile, archivio rovinato: meglio fermarsi che
            # superare il limite senza saperlo
            raise ContatoreNonAccessibile(f"{self.percorso}: {errore}") from None

    # Legge quante richieste sono gia' state contate oggi, senza aggiungerne
    def conteggio_di_oggi(self) -> int:
        """Richieste gia' contate oggi (0 se nessuna)."""
        try:
            connessione = self._connetti()
            try:
                riga = connessione.execute("SELECT numero FROM richieste WHERE giorno = ?",
                                           (self._giorno(),)).fetchone()
            finally:
                connessione.close()
        except (sqlite3.Error, OSError) as errore:
            # problemi del file: stesso errore di registra()
            raise ContatoreNonAccessibile(f"{self.percorso}: {errore}") from None
        return riga[0] if riga else 0
