# test del grafo: router prima dell'agente, rifiuto fisso, ciclo agente-strumenti, limite,
# revisore dopo l'agente e pulizia a fine turno
import logging
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import tools
from app.config import Ambito
from app.graph import MSG_VUOTO, build_graph, messaggi_da_pulire
from app.revisore import DecisioneRevisore
from app.router import DecisioneRouter
from tests.finti import ModelloFinto, RevisoreFinto, RouterFinto

AMBITO = Ambito(descrizione="Solo ora, data e fusi orari.", rifiuto="Fuori dal mio ambito.")
IN_AMBITO = DecisioneRouter(categoria="conversazione", motivo="chiede l'ora")
FUORI = DecisioneRouter(categoria="fuori_ambito", motivo="ricetta")
OK = DecisioneRevisore(motivo="risponde", coerente=True)


# decisione negativa del revisore con il motivo dato
def NO(motivo="incompleta"):
    return DecisioneRevisore(motivo=motivo, coerente=False)


# tutti i log di router, agente e rifiuto finiscono in caplog
@pytest.fixture(autouse=True)
def log(caplog):
    for nome in ("router", "agente", "rifiuto", "revisore"):
        caplog.set_level(logging.INFO, logger=nome)
    return caplog


# orologio fisso: 1 marzo 2026 11:00 UTC
@pytest.fixture(autouse=True)
def orologio(monkeypatch):
    monkeypatch.setattr(tools, "_adesso",
                        lambda: datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc))


# chiamata a tooltime come la scriverebbe il modello
def _chiamata(id_="c1"):
    return {"name": "tooltime", "args": {"fuso": "Asia/Tokyo"}, "id": id_}


# esegue il grafo con una domanda e restituisce lo stato finale
# (revisore predefinito: approva sempre)
def _esegui(agente, router, domanda="Che ore sono?", max_steps=5, revisore=None,
            max_revisioni=2):
    revisore = revisore or RevisoreFinto([OK])
    grafo = build_graph(agente, router, revisore, AMBITO, max_steps=max_steps,
                        max_revisioni=max_revisioni)
    return grafo.invoke({"messages": [HumanMessage(domanda)], "steps": 0, "revisioni": 0})


# messaggi del revisore rimasti nello stato
def _del_revisore(out):
    return [m for m in out["messages"] if getattr(m, "name", None) == "revisore"]


# Verifica il percorso in ambito: log del router con categoria e motivo, poi nodo modello.
def test_in_ambito_passa_all_agente(log):
    agente = ModelloFinto([AIMessage("Sono le 10")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]))
    assert out["messages"][-1].content == "Sono le 10"
    assert len(agente.chiamate) == 1
    assert 'categoria=conversazione motivo="chiede l\'ora" → agente' in log.text
    assert "nodo modello" in log.text


# Verifica il percorso fuori ambito: rifiuto fisso e nessuna esecuzione del nodo modello.
def test_fuori_ambito_non_raggiunge_l_agente(log):
    agente = ModelloFinto([AIMessage("non dovrei rispondere")])
    out = _esegui(agente, RouterFinto([FUORI]), "Ricetta della carbonara")
    assert out["messages"][-1].content == AMBITO.rifiuto
    assert agente.chiamate == []
    assert 'categoria=fuori_ambito motivo="ricetta" → rifiuto' in log.text
    assert "risposta fissa inviata" in log.text
    assert "nodo modello" not in log.text


# Verifica che con un output non valido del router risponda l'agente.
def test_output_non_valido_passa_all_agente(log):
    agente = ModelloFinto([AIMessage("Ciao!")])
    out = _esegui(agente, RouterFinto([None]))
    assert out["messages"][-1].content == "Ciao!"
    assert len(agente.chiamate) == 1
    assert "la domanda passa all'agente" in log.text


# Verifica che in ambito l'agente usi tooltime e risponda con il risultato.
def test_in_ambito_con_strumento(log):
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()]),
                           AIMessage("A Tokyo sono le 20")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), "Che ore sono a Tokyo?")
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(risultati) == 1 and "Tokyo" in risultati[0].content
    assert out["messages"][-1].content == "A Tokyo sono le 20"
    assert "chiamata strumento tooltime" in log.text


# Verifica che il prompt mandato al router non nomini tooltime.
def test_router_non_riceve_strumenti():
    router = RouterFinto([IN_AMBITO])
    _esegui(ModelloFinto([AIMessage("ok")]), router)
    assert "tooltime" not in router.chiamate[0][0].content


# Verifica il limite di passaggi e che ogni tool_call abbia la sua risposta.
def test_limite_passaggi():
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()])])  # chiede sempre tooltime
    out = _esegui(agente, RouterFinto([IN_AMBITO]), max_steps=2)
    assert "limite di 2 passaggi" in out["messages"][-1].content
    # ogni tool_call ha la sua risposta: la cronologia resta valida
    chiamate = {c["id"] for m in out["messages"] if isinstance(m, AIMessage) for c in m.tool_calls}
    risposte = {m.tool_call_id for m in out["messages"] if isinstance(m, ToolMessage)}
    assert chiamate == risposte


# Verifica il messaggio fisso quando il modello non restituisce niente.
def test_risposta_vuota():
    out = _esegui(ModelloFinto([AIMessage("")]), RouterFinto([IN_AMBITO]))
    assert out["messages"][-1].content == MSG_VUOTO


# Verifica che categoria e motivo del router restino nello stato.
def test_stato_contiene_categoria_e_motivo():
    out = _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]))
    assert out["categoria"] == "fuori_ambito"
    assert out["motivo"] == "ricetta"


# Verifica che domanda e rifiuto restino nella cronologia della sessione.
def test_rifiuto_resta_in_cronologia():
    out = _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]), "Ricetta")
    assert [type(m) for m in out["messages"]] == [HumanMessage, AIMessage]
    assert out["messages"][0].content == "Ricetta"
    assert out["messages"][1].content == AMBITO.rifiuto


DUE_PARTI = "Che ore sono a Tokyo e che giorno è a New York?"
PARZIALE = "A Tokyo sono le 10."
COMPLETA = "A Tokyo sono le 10, a New York è il 1 marzo."


# Verifica la risposta parziale: rifiuto motivato, messaggio [Revisore] all'agente, risposta completa.
def test_risposta_parziale_torna_all_agente(log):
    agente = ModelloFinto([AIMessage(PARZIALE), AIMessage(COMPLETA)])
    revisore = RevisoreFinto([NO("manca New York"), OK])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), DUE_PARTI, revisore=revisore)
    assert len(agente.chiamate) == 2
    indicazione = agente.chiamate[1][-1]
    assert isinstance(indicazione, HumanMessage) and indicazione.name == "revisore"
    assert "manca New York" in indicazione.content
    assert out["messages"][-1].content == COMPLETA
    assert 'non coerente motivo="manca New York" → agente (revisione 1 di 2)' in log.text
    assert 'coerente motivo="risponde" → fine' in log.text


# Verifica la risposta coerente approvata al primo passaggio.
def test_coerente_al_primo_passaggio():
    agente, revisore = ModelloFinto([AIMessage(COMPLETA)]), RevisoreFinto([OK])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), DUE_PARTI, revisore=revisore)
    assert len(agente.chiamate) == 1 and len(revisore.chiamate) == 1
    assert _del_revisore(out) == []


# Verifica il limite con un revisore che rifiuta sempre: si consegna l'ultima risposta.
def test_limite_di_revisioni(log):
    agente = ModelloFinto([AIMessage("bozza 1"), AIMessage("bozza 2"), AIMessage("bozza 3")])
    revisore = RevisoreFinto([NO("x")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=revisore, max_revisioni=2)
    assert len(revisore.chiamate) == 3 and len(agente.chiamate) == 3
    assert "limite di revisioni raggiunto (2): restituisco l'ultima risposta" in log.text
    assert out["messages"][-1].content == "bozza 3"


# Verifica che la pulizia lasci solo la domanda e la risposta finale.
def test_pulizia_toglie_revisore_e_bozze(log):
    agente = ModelloFinto([AIMessage(PARZIALE), AIMessage(COMPLETA)])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), DUE_PARTI,
                  revisore=RevisoreFinto([NO(), OK]))
    assert [(type(m), m.content) for m in out["messages"]] == \
        [(HumanMessage, DUE_PARTI), (AIMessage, COMPLETA)]
    assert "pulizia: tolti 2 messaggi del revisore" in log.text


# Verifica che la pulizia non tocchi le coppie chiamata-strumento e risultato.
def test_pulizia_lascia_le_coppie_strumenti():
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()]), AIMessage("bozza"),
                           AIMessage("completa")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO(), OK]))
    chiamate = [m for m in out["messages"] if isinstance(m, AIMessage) and m.tool_calls]
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(chiamate) == 1 and len(risultati) == 1
    assert "bozza" not in [m.content for m in out["messages"]]
    assert out["messages"][-1].content == "completa"


# Verifica che il percorso fuori ambito non passi dal revisore.
def test_fuori_ambito_salta_il_revisore():
    revisore = RevisoreFinto([OK])
    _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]), revisore=revisore)
    assert revisore.chiamate == []


# Verifica che il messaggio fisso di risposta vuota non passi dal revisore.
def test_risposta_vuota_salta_il_revisore():
    revisore = RevisoreFinto([OK])
    out = _esegui(ModelloFinto([AIMessage("")]), RouterFinto([IN_AMBITO]), revisore=revisore)
    assert revisore.chiamate == []
    assert out["messages"][-1].content == MSG_VUOTO


# Verifica che dopo una revisione il limite di strumenti porti alla pulizia dei [Revisore].
def test_limite_dopo_revisione_pulisce():
    agente = ModelloFinto([AIMessage("bozza"), AIMessage("", tool_calls=[_chiamata()])])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO()]),
                  max_steps=1)
    assert _del_revisore(out) == []
    assert "limite di 1 passaggi" in out["messages"][-1].content


# Verifica MAX_REVISIONI=0: il revisore valuta e scrive il limite, ma non rimanda all'agente.
def test_max_revisioni_zero(log):
    agente = ModelloFinto([AIMessage("bozza")])
    _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO()]), max_revisioni=0)
    assert len(agente.chiamate) == 1
    assert "limite di revisioni raggiunto (0)" in log.text


# Verifica che un output non valido del revisore approvi la prima risposta.
def test_output_non_valido_del_revisore_approva():
    agente = ModelloFinto([AIMessage("prima"), AIMessage("seconda")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([None]))
    assert len(agente.chiamate) == 1
    assert out["messages"][-1].content == "prima"


# Verifica quali id toglie la pulizia: messaggi del revisore e bozze rifiutate del turno in corso.
def test_messaggi_da_pulire():
    messaggi = [HumanMessage("vecchia", id="h0"), AIMessage("vecchia bozza", id="a0"),
                HumanMessage("[Revisore] vecchio", name="revisore", id="r0"),
                HumanMessage("domanda", id="h1"),
                AIMessage("", tool_calls=[_chiamata()], id="a1"),
                ToolMessage("Tokyo", tool_call_id="c1", id="t1"),
                AIMessage("bozza", id="a2"),
                HumanMessage("[Revisore] manca", name="revisore", id="r1"),
                AIMessage("completa", id="a3")]
    assert messaggi_da_pulire(messaggi) == ["a2", "r1"]
