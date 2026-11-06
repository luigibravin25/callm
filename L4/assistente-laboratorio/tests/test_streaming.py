import logging
from datetime import datetime, timezone

import pytest
from langchain_core.messages import (AIMessage, AIMessageChunk, HumanMessage,
                                     SystemMessage, ToolMessage)

from app import tools
from app.cli import ETICHETTA_ASSISTENTE, PROMPT_UTENTE, imposta_log, main
from app.graph import build_graph
from app.llm import SYSTEM_PROMPT


class ModelloStream:
    """Modello finto con invoke e stream: ogni turno e' una lista di pezzi."""

    def __init__(self, turni):
        self.turni = list(turni)
        self.chiamate = []
        self.invoke_usato = False

    def stream(self, messaggi):
        self.chiamate.append(list(messaggi))
        yield from self.turni.pop(0)

    def invoke(self, messaggi):
        self.invoke_usato = True
        self.chiamate.append(list(messaggi))
        return AIMessage("".join(p.content for p in self.turni.pop(0)))


def _pezzi(*testi):
    return [AIMessageChunk(content=t) for t in testi]


def _chiamata_strumento(nome="tooltime"):
    return [AIMessageChunk(content="", tool_call_chunks=[
        {"name": nome, "args": '{"fuso": "Asia/Tokyo"}', "id": "c1", "index": 0}])]


def _esegui(llm, righe, **kwargs):
    it = iter(righe)
    uscite, token = [], []
    main(input_fn=lambda _p="": next(it), output_fn=uscite.append,
         token_fn=token.append, llm=llm, **kwargs)
    return uscite, token


@pytest.fixture(autouse=True)
def _orologio_fisso(monkeypatch):
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


def test_stream_vero_token_per_token():
    llm = ModelloStream([_pezzi("Ci", "ao", " a tutti")])
    uscite, token = _esegui(llm, ["ciao", "exit"], stream=True)
    assert token == [ETICHETTA_ASSISTENTE, "Ci", "ao", " a tutti", "\n"]
    assert not llm.invoke_usato
    assert not any("Ciao a tutti" in u for u in uscite)  # nessuna copia in blocco


def test_stream_falso_risposta_in_blocco():
    llm = ModelloStream([_pezzi("Ci", "ao")])
    uscite, token = _esegui(llm, ["ciao", "exit"], stream=False)
    assert ETICHETTA_ASSISTENTE + "Ciao" in uscite
    assert token == []
    assert llm.invoke_usato


def test_stream_la_cronologia_ha_il_testo_completo():
    llm = ModelloStream([_pezzi("Ci", "ao"), _pezzi("Di", " nuovo")])
    _esegui(llm, ["uno", "due", "exit"], stream=True)
    contenuti = [m.content for m in llm.chiamate[1]]
    assert contenuti == [SYSTEM_PROMPT, "uno", "Ciao", "due"]


def test_stream_con_strumento_tooltime():
    llm = ModelloStream([_chiamata_strumento(), _pezzi("A Tokyo ", "sono le 20:00.")])
    token = []
    grafo = build_graph(llm, on_token=token.append)
    out = grafo.invoke({"messages": [HumanMessage("Che ore sono a Tokyo?")], "steps": 0})
    assert out["messages"][-1].content == "A Tokyo sono le 20:00."
    assert token == ["A Tokyo ", "sono le 20:00."]  # la chiamata allo strumento non e' testo
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.name == "tooltime"
    assert "ore 20 in punto" in risultato.content


def test_stream_risposta_vuota():
    llm = ModelloStream([_pezzi("")])
    token = []
    out = build_graph(llm, on_token=token.append).invoke(
        {"messages": [HumanMessage("ciao")], "steps": 0})
    assert "i token sono finiti nel ragionamento" in "".join(token)
    assert "i token sono finiti nel ragionamento" in out["messages"][-1].content


def test_stream_limite_passaggi_scritto_sul_flusso():
    llm = ModelloStream([_chiamata_strumento(), _chiamata_strumento()])
    token = []
    build_graph(llm, max_steps=1, on_token=token.append).invoke(
        {"messages": [HumanMessage("ora?")], "steps": 0})
    assert "limite di 1 passaggi" in "".join(token)


def test_system_prompt_anteposto_e_fuori_dalla_cronologia():
    llm = ModelloStream([_pezzi("Ciao")])
    out = build_graph(llm).invoke({"messages": [HumanMessage("ciao")], "steps": 0})
    prima = llm.chiamate[0]
    assert isinstance(prima[0], SystemMessage) and prima[0].content == SYSTEM_PROMPT
    assert not any(isinstance(m, SystemMessage) for m in out["messages"])


def test_prompt_utente_e_etichetta_assistente():
    prompt = []
    righe = iter(["ciao", "exit"])

    def input_fn(p=""):
        prompt.append(p)
        return next(righe)

    token = []
    main(input_fn=input_fn, output_fn=[].append, token_fn=token.append,
         llm=ModelloStream([_pezzi("Ciao")]), stream=True)
    assert prompt[0] == PROMPT_UTENTE == "Tu: "
    assert ETICHETTA_ASSISTENTE == "Assistente: "
    assert token.count(ETICHETTA_ASSISTENTE) == 1  # una sola volta per risposta


@pytest.mark.parametrize("acceso, livello", [(False, logging.CRITICAL), (True, logging.INFO)])
def test_log_grafo_e_http_si_attivano_con_la_variabile(acceso, livello):
    imposta_log(log_http=acceso, log_grafo=acceso)
    for nome in ("app.graph", "httpx", "httpx2"):
        assert logging.getLogger(nome).level == livello


def test_history_vero_il_modello_ricorda():
    llm = ModelloStream([_pezzi("Ciao"), _pezzi("Di nuovo")])
    _esegui(llm, ["uno", "due", "exit"], stream=True, history=True)
    assert [m.content for m in llm.chiamate[1]] == [SYSTEM_PROMPT, "uno", "Ciao", "due"]


def test_history_falso_ogni_domanda_parte_da_zero():
    llm = ModelloStream([_pezzi("Ciao"), _pezzi("Di nuovo")])
    uscite, token = _esegui(llm, ["uno", "due", "exit"], stream=True, history=False)
    assert [m.content for m in llm.chiamate[1]] == [SYSTEM_PROMPT, "due"]
    assert token.count(ETICHETTA_ASSISTENTE) == 2  # le risposte escono comunque


def test_history_falso_senza_streaming():
    llm = ModelloStream([_pezzi("Ciao"), _pezzi("Di nuovo")])
    uscite, _ = _esegui(llm, ["uno", "due", "exit"], stream=False, history=False)
    assert ETICHETTA_ASSISTENTE + "Di nuovo" in uscite
    assert [m.content for m in llm.chiamate[1]] == [SYSTEM_PROMPT, "due"]


def test_byte_non_utf8_dal_terminale_non_fanno_cadere_l_app():
    # byte 0xC3 isolato: Python lo legge dal terminale come surrogato U+DCC3
    sporco = b"che ore sono a citta ? \xc3 ?".decode("utf-8", "surrogateescape")
    assert any(0xDC80 <= ord(c) <= 0xDCFF for c in sporco)
    llm = ModelloStream([_pezzi("Ciao")])
    _esegui(llm, [sporco, "exit"], stream=True)
    ricevuto = llm.chiamate[0][-1].content
    ricevuto.encode("utf-8")  # niente UnicodeEncodeError
    assert chr(0xFFFD) in ricevuto


def test_testo_utf8_valido_resta_identico():
    domanda = "che ore sono a Perth? " + chr(0xE8) + " citt" + chr(0xE0)
    llm = ModelloStream([_pezzi("Ciao")])
    _esegui(llm, [domanda, "exit"], stream=True)
    assert llm.chiamate[0][-1].content == domanda
