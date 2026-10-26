import logging
import os
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import tools
from app.cli import main
from app.config import load_settings
from app.graph import build_graph, instrada


class ModelloCopione:
    """Modello finto: restituisce messaggi gia' pronti, in ordine.
    Finiti i messaggi, ripete l'ultimo (utile per il modello che chiede sempre lo strumento)."""

    def __init__(self, messaggi):
        self.messaggi = list(messaggi)
        self.chiamate = []

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        if len(self.messaggi) > 1:
            return self.messaggi.pop(0)
        # copia senza id, altrimenti add_messages la scambia per lo stesso messaggio
        return self.messaggi[0].model_copy(update={"id": None})


def _chiamata(nome="ora_corrente", args=None, id_="c1"):
    return AIMessage("", tool_calls=[
        {"name": nome, "args": args or {"fuso": "Asia/Tokyo"}, "id": id_}])


def _stato(testo="Che ore sono a Tokyo?"):
    return {"messages": [HumanMessage(testo)], "steps": 0}


@pytest.fixture(autouse=True)
def _orologio_fisso(monkeypatch):
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


def test_instrada_a_strumenti():
    con = {"messages": [_chiamata()], "steps": 0}
    senza = {"messages": [AIMessage("ciao")], "steps": 0}
    al_limite = {"messages": [_chiamata()], "steps": 5}
    assert instrada(con) == "strumenti"
    assert instrada(senza) == "__end__"
    assert instrada(al_limite) == "limite"


def test_risultato_torna_al_modello():
    llm = ModelloCopione([_chiamata(), AIMessage("A Tokyo sono le 20:00.")])
    out = build_graph(llm).invoke(_stato())
    assert out["messages"][-1].content == "A Tokyo sono le 20:00."
    ricevuto = llm.chiamate[1][-1]
    assert isinstance(ricevuto, ToolMessage)
    assert "20:00:00 JST" in ricevuto.content
    assert out["steps"] == 1


def test_limite_passaggi():
    llm = ModelloCopione([_chiamata()])  # chiede sempre lo strumento
    out = build_graph(llm, max_steps=3).invoke(_stato())
    assert out["steps"] == 3
    assert len(llm.chiamate) == 4
    ultimo = out["messages"][-1]
    assert isinstance(ultimo, AIMessage) and not ultimo.tool_calls
    assert "limite" in ultimo.content and "3" in ultimo.content


def test_limite_chiude_le_tool_calls_pendenti():
    llm = ModelloCopione([_chiamata(), _chiamata(id_="c2"), AIMessage("Ok, ripartiamo.")])
    grafo = build_graph(llm, max_steps=1)
    primo = grafo.invoke(_stato())
    # modello chiede lo strumento (eseguito), poi lo richiede: limite raggiunto
    secondo = grafo.invoke({"messages": primo["messages"] + [HumanMessage("e ora?")],
                            "steps": 0})
    assert secondo["messages"][-1].content == "Ok, ripartiamo."
    inviati = llm.chiamate[-1]
    richieste = {c["id"] for m in inviati if isinstance(m, AIMessage) for c in m.tool_calls}
    risposte = {m.tool_call_id for m in inviati if isinstance(m, ToolMessage)}
    assert richieste == {"c1", "c2"}
    assert richieste <= risposte  # nessuna tool_call senza ToolMessage


def test_log_chiamata_strumento(caplog):
    llm = ModelloCopione([_chiamata(), AIMessage("fatto")])
    with caplog.at_level(logging.INFO, logger="app.graph"):
        build_graph(llm).invoke(_stato())
    testo = [r.getMessage() for r in caplog.records]
    prima = next(i for i, t in enumerate(testo) if "ora_corrente" in t and "Asia/Tokyo" in t)
    dopo = next(i for i, t in enumerate(testo) if "20:00:00 JST" in t)
    assert prima < dopo


def test_strumento_sconosciuto():
    llm = ModelloCopione([_chiamata("non_esiste", {"x": 1}), AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato())
    assert out["messages"][-1].content == "Non posso."
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage)
    assert errore.status == "error"


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_strumento_lm_studio():
    from app.llm import build_llm

    impostazioni = load_settings()
    out = build_graph(build_llm(impostazioni), impostazioni.max_steps).invoke(
        _stato("Che ore sono a Tokyo?"))
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    assert "ora_corrente" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"


def test_cli_usa_max_steps():
    llm = ModelloCopione([_chiamata()])  # chiede sempre lo strumento
    righe = iter(["Che ore sono a Tokyo?", "exit"])
    uscite = []
    main(input_fn=lambda _p="": next(righe), output_fn=uscite.append,
         llm=llm, max_steps=1)
    # un solo passaggio con lo strumento, poi il limite
    assert len(llm.chiamate) == 2
    assert any("limite di 1 passaggi" in u for u in uscite)
