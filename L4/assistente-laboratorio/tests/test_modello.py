import os

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.cli import main
from app.config import load_settings
from app.graph import build_graph


class ModelloFinto:
    """Modello finto: registra i messaggi ricevuti e risponde con i contenuti dati."""

    def __init__(self, risposte):
        self.risposte = list(risposte)
        self.chiamate = []

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        r = self.risposte.pop(0)
        if isinstance(r, BaseException):
            raise r
        return AIMessage(r)


def _esegui(righe, llm):
    it = iter(righe)

    def input_fn(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    uscite = []
    main(input_fn=input_fn, output_fn=uscite.append, llm=llm)
    return uscite


def test_cronologia_passata_al_modello():
    llm = ModelloFinto(["Ciao Luigi", "Ti chiami Luigi"])
    uscite = _esegui(["Mi chiamo Luigi", "Come mi chiamo?", "exit"], llm)
    assert len(llm.chiamate[0]) == 1
    assert [m.content for m in llm.chiamate[1]] == [
        "Mi chiamo Luigi", "Ciao Luigi", "Come mi chiamo?"]
    assert "Ti chiami Luigi" in uscite


def test_config_mancante(monkeypatch):
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.delenv("LM_MODEL", raising=False)
    with pytest.raises(ValueError, match="LM_MODEL"):
        load_settings()
    monkeypatch.delenv("LM_BASE_URL")
    monkeypatch.setenv("LM_MODEL", "m")
    with pytest.raises(ValueError, match="LM_BASE_URL"):
        load_settings()


def test_config_valida(monkeypatch):
    monkeypatch.setenv("LM_BASE_URL", "http://x/v1")
    monkeypatch.setenv("LM_MODEL", "m")
    monkeypatch.delenv("MAX_STEPS", raising=False)
    assert load_settings().max_steps == 5
    monkeypatch.setenv("MAX_STEPS", "0")
    with pytest.raises(ValueError, match="MAX_STEPS"):
        load_settings()


def test_risposta_vuota():
    llm = ModelloFinto(["  \n"])
    out = build_graph(llm).invoke({"messages": [HumanMessage("ciao")], "steps": 0})
    assert "i token sono finiti nel ragionamento" in out["messages"][-1].content


def test_server_non_raggiungibile():
    errore = openai.APIConnectionError(
        request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    llm = ModelloFinto([errore, "Eccomi"])
    uscite = _esegui(["ciao", "di nuovo", "exit"], llm)
    assert any("LM_BASE_URL" in u for u in uscite)
    assert "Eccomi" in uscite  # il ciclo continua dopo l'errore
    # la domanda fallita non resta nella cronologia
    assert [m.content for m in llm.chiamate[1]] == ["di nuovo"]


def test_ctrl_c_durante_la_richiesta():
    llm = ModelloFinto([KeyboardInterrupt()])
    _esegui(["ciao"], llm)  # deve uscire senza propagare


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_lm_studio():
    from app.llm import build_llm

    llm = build_llm(load_settings())
    uscite = _esegui(["Mi chiamo Luigi.", "Come mi chiamo?", "exit"], llm)
    assert "Luigi" in uscite[-1]


def test_errore_http_del_server():
    risposta = httpx.Response(
        500, request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    errore = openai.InternalServerError("boom", response=risposta, body=None)
    llm = ModelloFinto([errore, "Eccomi"])
    uscite = _esegui(["ciao", "di nuovo", "exit"], llm)
    assert any("500" in u for u in uscite)
    assert "Eccomi" in uscite
    assert [m.content for m in llm.chiamate[1]] == ["di nuovo"]
