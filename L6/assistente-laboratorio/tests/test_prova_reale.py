# prova reale con LM Studio: parte solo con RUN_LM_STUDIO=1 (servono LM_BASE_URL e LM_MODEL)
import os

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

# senza la variabile i test vengono saltati: la suite normale non dipende da LM Studio
pytestmark = pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                                reason="prova reale: impostare RUN_LM_STUDIO=1")


# grafo vero: modelli di LM Studio e ambito del file config/ambito.toml
@pytest.fixture(scope="module")
def grafo_e_ambito():
    from app.config import load_ambito, load_settings
    from app.graph import build_graph
    from app.llm import build_llm, build_router_llm
    s = load_settings()
    ambito = load_ambito(s.ambito_file)
    return build_graph(build_llm(s), build_router_llm(s), ambito, s.max_steps), ambito


def test_prova_reale_in_ambito(grafo_e_ambito):
    grafo, _ = grafo_e_ambito
    out = grafo.invoke({"messages": [HumanMessage("Che ore sono a Tokyo?")], "steps": 0})
    assert out["categoria"] == "conversazione"
    assert any(isinstance(m, ToolMessage) and m.name == "tooltime" for m in out["messages"])


def test_prova_reale_fuori_ambito(grafo_e_ambito):
    grafo, ambito = grafo_e_ambito
    out = grafo.invoke({"messages": [HumanMessage("Dammi la ricetta della carbonara")],
                        "steps": 0})
    assert out["categoria"] == "fuori_ambito"
    assert out["messages"][-1].content == ambito.rifiuto
