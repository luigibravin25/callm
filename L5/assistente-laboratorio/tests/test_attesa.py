import logging
import time

from langchain_core.messages import AIMessageChunk

from app.cli import ETICHETTA_ASSISTENTE, Attesa, log_con_attesa, main
from tests.test_streaming import ModelloStream, _pezzi


class AttesaSpia:
    """Registra start e stop dell'attesa senza thread."""

    def __init__(self, eventi):
        self.eventi = eventi

    def avvia(self):
        self.eventi.append("avvia")

    def ferma(self):
        self.eventi.append("ferma")


def test_attesa_anima_i_puntini_e_cancella_la_riga():
    scritti = []
    attesa = Attesa(scrivi=scritti.append, intervallo=0.01, attiva=True)
    attesa.avvia()
    time.sleep(0.1)
    attesa.ferma()
    assert scritti[0] == f"\r{ETICHETTA_ASSISTENTE}.  "
    assert f"\r{ETICHETTA_ASSISTENTE}.. " in scritti
    assert f"\r{ETICHETTA_ASSISTENTE}..." in scritti
    assert scritti[-1].startswith("\r ") and scritti[-1].endswith("\r")
    n = len(scritti)
    time.sleep(0.05)
    assert len(scritti) == n  # dopo ferma() non scrive piu'


def test_attesa_muta_se_non_attiva():
    scritti = []
    attesa = Attesa(scrivi=scritti.append, intervallo=0.01, attiva=False)
    attesa.avvia()
    time.sleep(0.03)
    attesa.ferma()
    assert scritti == []


def test_attesa_ferma_prima_del_primo_token():
    eventi = []
    llm = ModelloStream([_pezzi("Ci", "ao")])
    righe = iter(["ciao", "exit"])
    main(input_fn=lambda _p="": next(righe), output_fn=lambda _t: None,
         token_fn=eventi.append, llm=llm, stream=True, attesa=AttesaSpia(eventi))
    assert eventi[:4] == ["avvia", "ferma", ETICHETTA_ASSISTENTE, "Ci"]
    assert eventi.count("avvia") == 1


def test_attesa_riparte_dopo_lo_strumento():
    eventi = []
    chiamata = [AIMessageChunk(content="", tool_call_chunks=[
        {"name": "tooltime", "args": '{"fuso": "Asia/Tokyo"}', "id": "c1", "index": 0}])]
    llm = ModelloStream([chiamata, _pezzi("Sono le 20")])
    righe = iter(["che ore sono?", "exit"])
    main(input_fn=lambda _p="": next(righe), output_fn=lambda _t: None,
         token_fn=eventi.append, llm=llm, stream=True, attesa=AttesaSpia(eventi))
    assert eventi == ["avvia", "avvia", "ferma", ETICHETTA_ASSISTENTE, "Sono le 20",
                      "ferma", "\n", "ferma"]


class _Registra(logging.Handler):
    """Gestore di log finto: mette ogni log nella lista degli eventi."""

    def __init__(self, eventi):
        super().__init__()
        self.eventi = eventi

    def emit(self, record):
        self.eventi.append(("log", record.getMessage()))


def _log_httpx2(eventi, attesa, avviata: bool) -> None:
    """Scrive un log [httpx2] con log_con_attesa attivo, al posto dei gestori veri."""
    radice, logger = logging.getLogger(), logging.getLogger("httpx2")
    gestori, livello = radice.handlers[:], logger.level  # da rimettere alla fine
    radice.handlers = [_Registra(eventi)]
    logger.setLevel(logging.INFO)
    try:
        if avviata:
            attesa.avvia()
            time.sleep(0.05)  # qualche giro di puntini prima del log
        with log_con_attesa(attesa):
            logger.info('HTTP Request: POST http://x/v1/chat/completions "HTTP/1.1 200 OK"')
        time.sleep(0.05)  # i puntini, se ripartono, hanno il tempo di comparire
        attesa.ferma()
    finally:
        radice.handlers = gestori  # gestori e livello di prima: gli altri test non cambiano
        logger.setLevel(livello)


def test_log_http_su_una_riga_sua_e_puntini_che_ripartono():
    """Un log di httpx2 durante l'attesa: riga dei puntini cancellata, log, puntini di nuovo."""
    eventi = []
    attesa = Attesa(scrivi=lambda t: eventi.append(("puntini", t)), intervallo=0.01, attiva=True)
    _log_httpx2(eventi, attesa, avviata=True)
    i = eventi.index(("log", 'HTTP Request: POST http://x/v1/chat/completions "HTTP/1.1 200 OK"'))
    prima = eventi[i - 1][1]
    assert prima.startswith("\r ") and prima.endswith("\r")  # riga dei puntini cancellata
    dopo = [t for tipo, t in eventi[i + 1:] if tipo == "puntini"]
    assert dopo and dopo[0].startswith(f"\r{ETICHETTA_ASSISTENTE}.")  # i puntini ripartono


def test_log_senza_attesa_non_avvia_i_puntini():
    """Un log mentre i puntini sono fermi (es. dopo il primo token) non li fa partire."""
    eventi = []
    attesa = Attesa(scrivi=lambda t: eventi.append(("puntini", t)), intervallo=0.01, attiva=True)
    _log_httpx2(eventi, attesa, avviata=False)
    assert [tipo for tipo, _ in eventi] == ["log"]


def test_attesa_ferma_se_il_server_non_risponde():
    from openai import APIConnectionError
    import httpx

    class LlmKo:
        def invoke(self, _m):
            raise APIConnectionError(request=httpx.Request("POST", "http://x"))

    eventi, uscite = [], []
    righe = iter(["ciao", "exit"])
    main(input_fn=lambda _p="": next(righe), output_fn=uscite.append,
         llm=LlmKo(), stream=False, attesa=AttesaSpia(eventi))
    assert eventi == ["avvia", "ferma", "ferma"]  # invoca() e poi la chiusura di main()
    assert "Impossibile raggiungere LM Studio" in uscite[-1]
