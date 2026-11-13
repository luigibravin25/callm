"""Server-Sent Events del back-end (step 10): copia delle utilità dell'agente (il back-end non
importa codice dell'agente). Formato degli eventi e segnale di vita durante i silenzi.

Un evento SSE e' "event: <tipo>" + "data: <JSON>" + una riga vuota. Mentre il modello ragiona
(o lavorano router e revisore) non passano eventi anche per minuti: con_ping manda un commento
": ping" ogni INTERVALLO_PING secondi, cosi' chi riceve sa che il turno e' vivo e chi invia si
accorge presto se il client ha chiuso la connessione.
"""
# librerie standard: JSON, coda e thread, dataclass
import json
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

# commento SSE: i client lo ignorano; serve solo a far passare qualcosa sulla connessione
PING = ": ping\n\n"
# secondi senza eventi dopo i quali parte un ping
INTERVALLO_PING = 5.0


# un evento del turno: tipo (fase, bozza, testo, strumento, revisione, fine, errore) e dati
@dataclass
class Evento:
    tipo: str
    dati: object = field(default_factory=dict)


# testo SSE di un evento: dati in JSON leggibile (accenti non tradotti in \u...)
def formatta(tipo: str, dati: dict) -> str:
    return f"event: {tipo}\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n"


# segnali interni della coda tra il thread e il consumatore
_FINE = object()


# righe della sorgente con un ping a ogni silenzio di "intervallo" secondi. La sorgente gira in un
# thread che mette le righe in una coda; chiudere questo generatore (client disconnesso) ferma il
# thread al prossimo elemento e chiude la sorgente (una chiamata gia' partita finisce da sola).
# alla_chiusura: chiamata subito (da chi legge) se il generatore si chiude prima della fine, per
# avvisare la sorgente bloccata in un'attesa (es. impostare un threading.Event "annullato").
def con_ping(sorgente: Iterator[str], intervallo: float | None = None,
             alla_chiusura: Callable[[], None] | None = None) -> Iterator[str]:
    # letto qui (non come predefinito): i test possono ridurre INTERVALLO_PING del modulo
    intervallo = INTERVALLO_PING if intervallo is None else intervallo
    coda: queue.Queue = queue.Queue()
    stop = threading.Event()

    def produttore() -> None:
        try:
            for riga in sorgente:
                if stop.is_set():
                    break
                coda.put(riga)
        except BaseException as errore:  # anche errori imprevisti: li vede il consumatore
            coda.put(errore)
        finally:
            # client andato via: la sorgente si chiude qui, nel thread che la esegue
            if stop.is_set():
                close = getattr(sorgente, "close", None)
                if close:
                    close()
            coda.put(_FINE)

    threading.Thread(target=produttore, daemon=True, name="sse-produttore").start()
    finito = False
    try:
        while True:
            try:
                elemento = coda.get(timeout=intervallo)
            except queue.Empty:
                yield PING
                continue
            if elemento is _FINE:
                finito = True
                return
            if isinstance(elemento, BaseException):
                raise elemento
            yield elemento
    finally:
        # fine normale, errore o chiusura del consumatore: il produttore si ferma
        stop.set()
        if not finito and alla_chiusura is not None:
            alla_chiusura()
