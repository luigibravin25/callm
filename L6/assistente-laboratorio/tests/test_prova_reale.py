# prova reale con LM Studio: parte solo con RUN_LM_STUDIO=1 (servono LM_BASE_URL e LM_MODEL)
import os

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

# senza la variabile i test vengono saltati: la suite normale non dipende da LM Studio
pytestmark = pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                                reason="prova reale: impostare RUN_LM_STUDIO=1")

DUE_PARTI = "Che ore sono a Tokyo e che giorno è oggi a New York?"


# grafo vero: modelli di LM Studio, strumenti del server MCP, preferenze date dal test
def _grafo_vero(preferenze=None):
    from app.adattatore_mcp import carica_strumenti
    from app.config import load_ambito, load_settings
    from app.graph import build_graph
    from app.llm import (build_llm, build_revisore_llm, build_riassunto_llm, build_router_llm,
                         prompt_agente)
    from app.preferenze import predefinite
    s = load_settings()
    ambito = load_ambito(s.ambito_file)
    strumenti = carica_strumenti()
    p = preferenze or predefinite(s.fuso_predefinito)
    grafo = build_graph(build_llm(s, strumenti), build_router_llm(s, ambito), build_revisore_llm(s),
                        build_riassunto_llm(s), ambito, s.max_steps, s.max_revisioni,
                        s.soglia_riassunto, s.messaggi_recenti, strumenti=strumenti,
                        system_prompt=prompt_agente(p, True), fuso_predefinito=p.fuso)
    return grafo, ambito


# grafo vero con le preferenze predefinite (italiano, fuso di riserva, sintetico)
@pytest.fixture(scope="module")
def grafo_e_ambito():
    return _grafo_vero()


# solo il modello del revisore, per provarlo su risposte scritte nel test
@pytest.fixture(scope="module")
def revisore_llm():
    from app.config import load_settings
    from app.llm import build_revisore_llm
    return build_revisore_llm(load_settings())


# esegue il grafo vero con una domanda
def _chiedi(grafo, domanda):
    return grafo.invoke({"messages": [HumanMessage(domanda)], "steps": 0, "revisioni": 0,
                         "riassunto": ""})


# Verifica con gemma: domanda sull'ora a Tokyo -> router in ambito e tooltime eseguito.
def test_prova_reale_in_ambito(grafo_e_ambito):
    grafo, _ = grafo_e_ambito
    out = _chiedi(grafo, "Che ore sono a Tokyo?")
    assert out["categoria"] == "conversazione"
    assert any(isinstance(m, ToolMessage) and m.name == "tooltime" for m in out["messages"])


# Verifica con gemma: ricetta -> rifiuto fisso del file dell'ambito.
def test_prova_reale_fuori_ambito(grafo_e_ambito):
    grafo, ambito = grafo_e_ambito
    out = _chiedi(grafo, "Dammi la ricetta della carbonara")
    assert out["categoria"] == "fuori_ambito"
    assert out["messages"][-1].content == ambito.rifiuto


# Verifica con gemma: una risposta che copre solo Tokyo e' giudicata non coerente.
def test_prova_reale_revisore_risposta_parziale(revisore_llm):
    from app.revisore import valuta
    decisione = valuta(revisore_llm, DUE_PARTI, "A Tokyo sono le ore 20 in punto.")
    assert decisione.coerente is False, decisione.motivo


# Verifica con gemma: una risposta che copre entrambe le parti e' giudicata coerente.
def test_prova_reale_revisore_risposta_completa(revisore_llm):
    from app.revisore import valuta
    decisione = valuta(revisore_llm, DUE_PARTI, "A Tokyo sono le ore 20 in punto. A New York "
                       "oggi è il 9 novembre del 2026.")
    assert decisione.coerente is True, decisione.motivo


# Verifica con gemma: il riassunto di una conversazione conserva il nome detto dall'utente.
def test_prova_reale_riassunto_conserva_il_nome():
    from langchain_core.messages import AIMessage
    from app.config import load_settings
    from app.llm import build_riassunto_llm
    from app.riassunto import riassumi
    messaggi = [HumanMessage("Ciao, mi chiamo Luigi"), AIMessage("Piacere Luigi! Come posso "
                "aiutarti?"), HumanMessage("Che ore sono a Tokyo?"),
                AIMessage("A Tokyo sono le ore 20 in punto.")]
    testo = riassumi(build_riassunto_llm(load_settings()), "", messaggi)
    assert testo is not None and "Luigi" in testo, testo


# Verifica con gemma (evidenza 1): "Che ore sono?" senza luogo usa il fuso delle preferenze,
# America/New_York, senza chiederlo all'utente.
def test_prova_reale_fuso_delle_preferenze():
    from app.config import load_settings
    from app.preferenze import valida
    p = valida('{"fuso": "America/New_York"}', load_settings().fuso_predefinito)
    grafo, _ = _grafo_vero(p)
    out = _chiedi(grafo, "Che ore sono?")
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert risultati and risultati[0].content.startswith("New York:")
    assert "New York" in out["messages"][-1].content


# Verifica con gemma (evidenza 2): con lingua inglese la risposta e' in inglese, anche se il
# risultato di tooltime e' in italiano.
def test_prova_reale_lingua_inglese():
    from app.config import load_settings
    from app.preferenze import valida
    p = valida('{"lingua": "inglese", "stile": "sintetico"}', load_settings().fuso_predefinito)
    grafo, _ = _grafo_vero(p)
    risposta = str(_chiedi(grafo, "Che ore sono a Tokyo?")["messages"][-1].content)
    testo = risposta.lower()
    assert "sono le ore" not in testo
    assert any(parola in testo for parola in ("it is", "it's", "time", "o'clock")), risposta


# --- prompt MCP (step 5): messaggi ottenuti dal server vero, poi grafo vero ---

# messaggi di un prompt chiesti al server vero (prompts/get)
def _prompt(nome, **argomenti):
    from app.adattatore_mcp import ottieni_prompt
    return ottieni_prompt(nome, argomenti)


# Verifica con gemma (evidenza 1): spiega su MCP a livello base passa il router e ha risposta.
def test_prova_reale_prompt_spiega_in_ambito(grafo_e_ambito):
    grafo, _ = grafo_e_ambito
    out = grafo.invoke({"messages": _prompt("spiega", argomento="Model Context Protocol",
                                            livello="base"),
                        "steps": 0, "revisioni": 0, "riassunto": ""})
    assert out["categoria"] == "conversazione", out.get("motivo")
    assert str(out["messages"][-1].content).strip()


# Verifica con gemma (evidenza 2): riassumi_conversazione dopo due turni passa il router e
# riassume la sessione (cita Tokyo).
def test_prova_reale_prompt_riassumi(grafo_e_ambito):
    grafo, _ = grafo_e_ambito
    stato = {"messages": [], "riassunto": ""}
    for domanda in ("Ciao, mi chiamo Luigi", "Che ore sono a Tokyo?"):
        stato = grafo.invoke({"messages": stato["messages"] + [HumanMessage(domanda)],
                              "steps": 0, "revisioni": 0, "riassunto": stato["riassunto"]})
    out = grafo.invoke({"messages": stato["messages"] + _prompt("riassumi_conversazione"),
                        "steps": 0, "revisioni": 0, "riassunto": stato["riassunto"]})
    assert out["categoria"] == "conversazione", out.get("motivo")
    assert "Tokyo" in str(out["messages"][-1].content)


# Verifica con gemma: spiega su un argomento fuori tema riceve il rifiuto fisso.
def test_prova_reale_spiega_fuori_ambito(grafo_e_ambito):
    grafo, ambito = grafo_e_ambito
    out = grafo.invoke({"messages": _prompt("spiega",
                                            argomento="la storia dell'Impero romano"),
                        "steps": 0, "revisioni": 0, "riassunto": ""})
    assert out["categoria"] == "fuori_ambito"
    assert out["messages"][-1].content == ambito.rifiuto


# Verifica (step 6) POST /chat con il servizio vero (server MCP e LM Studio): la domanda usa
# tooltime e la risposta lo dice in strumenti_usati.
def test_prova_reale_chat_http_con_tooltime():
    from fastapi.testclient import TestClient
    from app.agente import prepara
    from app.api import crea_app
    from app.config import load_ambito, load_settings
    s = load_settings()
    ambito = load_ambito(s.ambito_file)
    with TestClient(crea_app(lambda: prepara(s, ambito))) as client:
        r = client.post("/chat", json={"messaggio": "Che ore sono a Tokyo?"})
    assert r.status_code == 200, r.text
    dati = r.json()
    assert [u["nome"] for u in dati["strumenti_usati"]] == ["tooltime"]
    assert dati["categoria"] == "conversazione" and dati["risposta"].strip()
