from langchain_core.messages import HumanMessage

from app.cli import main
from app.graph import RISPOSTA_FISSA, build_graph


def test_risposta_fissa():
    out = build_graph().invoke({"messages": [HumanMessage("ciao")], "steps": 0})
    assert out["messages"][-1].content == RISPOSTA_FISSA


def test_cronologia_cresce():
    grafo = build_graph()
    cronologia = []
    for testo in ("uno", "due"):
        cronologia.append(HumanMessage(testo))
        out = grafo.invoke({"messages": cronologia, "steps": 0})
        cronologia = out["messages"]
    assert len(cronologia) == 4


def _esegui(righe):
    it = iter(righe)

    def input_fn(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    uscite = []
    main(input_fn=input_fn, output_fn=uscite.append)
    return uscite


def test_input_vuoto_ignorato():
    uscite = _esegui(["", "   ", "exit"])
    assert RISPOSTA_FISSA not in uscite


def test_uscita_pulita():
    _esegui(["exit"])
    _esegui([])  # EOF subito
    assert _esegui(["ciao", "exit"]).count(RISPOSTA_FISSA) == 1
