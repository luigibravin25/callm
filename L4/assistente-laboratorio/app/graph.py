from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

RISPOSTA_FISSA = "Sono l'assistente del laboratorio. Per ora rispondo sempre così."


class State(TypedDict):
    messages: Annotated[list, add_messages]
    steps: int


MSG_VUOTO = (
    "Il modello ha restituito una risposta vuota: i token sono finiti nel "
    "ragionamento. Prova ad aumentare il budget di token."
)


def build_graph(llm=None, max_steps: int = 5):
    # max_steps servira' con i tool; ora non e' usato
    def modello(state: State) -> dict:
        if llm is None:
            return {"messages": [AIMessage(RISPOSTA_FISSA)]}
        risposta = llm.invoke(state["messages"])
        if not str(risposta.content).strip():
            return {"messages": [AIMessage(MSG_VUOTO)]}
        return {"messages": [risposta]}

    g = StateGraph(State)
    g.add_node("modello", modello)
    g.add_edge(START, "modello")
    g.add_edge("modello", END)
    return g.compile()
