import logging
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.llm import SYSTEM_PROMPT
from app.tools import STRUMENTI

logger = logging.getLogger("app.graph")

RISPOSTA_FISSA = "Sono l'assistente del laboratorio. Per ora rispondo sempre così."


class State(TypedDict):
    messages: Annotated[list, add_messages]
    steps: int


MSG_VUOTO = (
    "Il modello ha restituito una risposta vuota: i token sono finiti nel "
    "ragionamento. Prova ad aumentare il budget di token."
)


def instrada(state: State, max_steps: int = 5) -> Literal["strumenti", "limite", "__end__"]:
    """Dopo il modello: strumenti se chiede una chiamata e c'e' margine,
    limite se la chiede ma i passaggi sono finiti, altrimenti fine."""
    if getattr(state["messages"][-1], "tool_calls", None):
        return "strumenti" if state["steps"] < max_steps else "limite"
    return END


def build_graph(llm=None, max_steps: int = 5, on_token=None):
    """Con `on_token` il testo arriva token per token (llm.stream), altrimenti in blocco."""
    # il modello va gia' associato agli strumenti da build_llm
    nodo_strumenti = ToolNode(STRUMENTI)

    def emetti(testo: str) -> None:
        if on_token and testo:
            on_token(testo)

    def chiedi_al_modello(messaggi: list) -> AIMessage:
        if on_token is None:
            return llm.invoke(messaggi)
        risposta = None
        for pezzo in llm.stream(messaggi):
            if isinstance(pezzo.content, str):
                emetti(pezzo.content)
            risposta = pezzo if risposta is None else risposta + pezzo
        return risposta if risposta is not None else AIMessage("")

    def modello(state: State) -> dict:
        if llm is None:
            emetti(RISPOSTA_FISSA)
            return {"messages": [AIMessage(RISPOSTA_FISSA)]}
        # il prompt di sistema viene anteposto a ogni richiesta, non entra nella cronologia
        risposta = chiedi_al_modello([SystemMessage(SYSTEM_PROMPT)] + state["messages"])
        if not risposta.tool_calls and not str(risposta.content).strip():
            emetti(MSG_VUOTO)
            return {"messages": [AIMessage(MSG_VUOTO)]}
        return {"messages": [risposta]}

    def strumenti(state: State, config) -> dict:
        for c in state["messages"][-1].tool_calls:
            logger.info("Chiamata strumento %s con argomenti %s", c["name"], c["args"])
        out = nodo_strumenti.invoke(state, config)
        for m in out["messages"]:
            logger.info("Risultato strumento %s: %s", m.name, m.content)
        return {"messages": out["messages"], "steps": state["steps"] + 1}

    def limite(state: State) -> dict:
        logger.warning("Limite di passaggi raggiunto (%d)", max_steps)
        # ogni tool_call pendente riceve una risposta, cosi' la cronologia resta valida
        chiuse = [ToolMessage(
            "Chiamata non eseguita: raggiunto il limite di passaggi.",
            tool_call_id=c["id"], name=c["name"], status="error")
            for c in state["messages"][-1].tool_calls]
        testo = (f"Ho raggiunto il limite di {max_steps} passaggi con gli strumenti "
                 "e mi fermo qui senza una risposta completa.")
        emetti(testo)
        return {"messages": chiuse + [AIMessage(testo)]}

    g = StateGraph(State)
    g.add_node("modello", modello)
    g.add_node("strumenti", strumenti)
    g.add_node("limite", limite)
    g.add_edge(START, "modello")
    g.add_conditional_edges(
        "modello", lambda s: instrada(s, max_steps),
        {"strumenti": "strumenti", "limite": "limite", END: END})
    g.add_edge("strumenti", "modello")
    g.add_edge("limite", END)
    return g.compile()
