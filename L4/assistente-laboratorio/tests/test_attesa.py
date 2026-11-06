import time

from langchain_core.messages import AIMessageChunk

from app.cli import ETICHETTA_ASSISTENTE, Attesa, main
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
