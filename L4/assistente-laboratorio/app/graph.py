from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

RISPOSTA_FISSA = "Sono l'assistente del laboratorio. Per ora rispondo sempre così."


class State(TypedDict):
    messages: Annotated[list, add_messages]
    steps: int


def build_graph(llm=None, max_steps: int = 5):
    # llm e max_steps serviranno nei prossimi passi; ora non sono usati
    def risposta(state: State) -> dict:
        return {"messages": [AIMessage(RISPOSTA_FISSA)]}

    g = StateGraph(State)
    g.add_node("risposta", risposta)
    g.add_edge(START, "risposta")
    g.add_edge("risposta", END)
    return g.compile()
