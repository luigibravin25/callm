# test delle utilità SSE: formato degli eventi e segnale di vita (ping) durante i silenzi
import threading
import time

import pytest

from app.sse import PING, con_ping, formatta


# Verifica il formato di un evento: tipo, dati JSON leggibili (accenti non tradotti), riga vuota.
def test_formatta():
    assert formatta("testo", {"testo": "è"}) == 'event: testo\ndata: {"testo": "è"}\n\n'


# Verifica che durante un silenzio della sorgente arrivi almeno un ping prima della riga.
def test_ping_nel_silenzio():
    def lenta():
        time.sleep(0.3)
        yield "riga\n\n"
    uscite = list(con_ping(lenta(), intervallo=0.1))
    assert uscite[0] == PING
    assert uscite[-1] == "riga\n\n"


# Verifica che un'eccezione della sorgente arrivi al consumatore.
def test_eccezione_risale():
    def rotta():
        yield "uno\n\n"
        raise RuntimeError("modello caduto")
    gen = con_ping(rotta(), intervallo=1)
    assert next(gen) == "uno\n\n"
    with pytest.raises(RuntimeError, match="modello caduto"):
        next(gen)


# Verifica che chiudere il consumatore (client disconnesso) fermi e chiuda anche la sorgente.
def test_chiusura_ferma_la_sorgente():
    chiusa = threading.Event()

    def infinita():
        try:
            while True:
                yield "x\n\n"
                time.sleep(0.01)
        finally:
            chiusa.set()

    gen = con_ping(infinita(), intervallo=1)
    assert next(gen) == "x\n\n"
    gen.close()
    assert chiusa.wait(1.0)
