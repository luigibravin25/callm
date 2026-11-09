# librerie standard: log, tipi per descrivere lo stato
import logging
from typing import Annotated, Literal, TypedDict

# messaggi della conversazione; grafo LangGraph; nodo che esegue gli strumenti
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# parti del progetto: ambito, prompt dell'agente, decisione del router, strumenti
from app.config import Ambito
from app.llm import SYSTEM_PROMPT
from app.router import decidi
from app.tools import STRUMENTI

# un logger per ruolo: nel terminale compaiono come [router], [agente], [rifiuto]
log_router = logging.getLogger("router")
log_agente = logging.getLogger("agente")
log_rifiuto = logging.getLogger("rifiuto")

# risposta usata quando il modello non restituisce ne' testo ne' chiamate
MSG_VUOTO = (
    "Il modello ha restituito una risposta vuota: i token sono finiti nel "
    "ragionamento. Prova ad aumentare il budget di token."
)


# stato del grafo: passa da un nodo all'altro
class State(TypedDict):
    # add_messages: i messaggi restituiti da un nodo si aggiungono in coda, non sostituiscono
    messages: Annotated[list, add_messages]
    steps: int  # quante volte sono stati eseguiti strumenti in questa domanda
    categoria: str  # decisione del router: conversazione o fuori_ambito
    motivo: str  # motivo della decisione del router (solo per i log, mai all'utente)


# dopo il modello: strumenti, limite oppure fine (come in L5)
def instrada(state: State, max_steps: int = 5) -> Literal["strumenti", "limite", "__end__"]:
    # getattr con valore None: funziona anche con messaggi che non hanno tool_calls
    if getattr(state["messages"][-1], "tool_calls", None):
        return "strumenti" if state["steps"] < max_steps else "limite"
    return END  # nessuna chiamata a strumenti: la risposta e' finale


# dopo il router: l'agente per le domande in ambito, il rifiuto per le altre
def dopo_router(state: State) -> Literal["modello", "rifiuto"]:
    return "rifiuto" if state["categoria"] == "fuori_ambito" else "modello"


# costruisce il grafo: router, rifiuto e i nodi dell'agente (modello, strumenti, limite)
def build_graph(llm, router_llm, ambito: Ambito, max_steps: int = 5, strumenti=STRUMENTI,
                system_prompt: str = SYSTEM_PROMPT):
    """`llm`: modello dell'agente con gli strumenti; `router_llm`: modello del router con
    output strutturato. Input: {"messages": [...], "steps": 0}."""
    nodo_strumenti = ToolNode(strumenti)

    # nodo "router": decide se la domanda e' in ambito; non valuta gli strumenti
    def router(state: State) -> dict:
        decisione = decidi(router_llm, ambito, state["messages"])
        destinazione = "rifiuto" if decisione.categoria == "fuori_ambito" else "agente"
        log_router.info('categoria=%s motivo="%s" → %s',
                        decisione.categoria, decisione.motivo, destinazione)
        return {"categoria": decisione.categoria, "motivo": decisione.motivo}

    # nodo "rifiuto": risposta fissa dal file dell'ambito, nessuna chiamata al modello
    def rifiuto(state: State) -> dict:
        log_rifiuto.info("risposta fissa inviata")
        return {"messages": [AIMessage(ambito.rifiuto)]}

    # nodo "modello": chiede al modello la prossima mossa (risposta o chiamata a strumenti)
    def modello(state: State) -> dict:
        log_agente.info("nodo modello")
        # il prompt di sistema viene anteposto a ogni richiesta, non entra nella cronologia
        risposta = llm.invoke([SystemMessage(system_prompt)] + state["messages"])
        # niente testo e niente chiamate: i token sono finiti nel ragionamento, lo si dice
        if not risposta.tool_calls and not str(risposta.content).strip():
            return {"messages": [AIMessage(MSG_VUOTO)]}
        return {"messages": [risposta]}

    # nodo "strumenti": esegue le chiamate chieste dal modello
    def strumenti_(state: State, config) -> dict:
        for c in state["messages"][-1].tool_calls:
            log_agente.info("chiamata strumento %s con argomenti %s", c["name"], c["args"])
        out = nodo_strumenti.invoke(state, config)
        for m in out["messages"]:
            log_agente.info("risultato strumento %s: %s", m.name, m.content)
        # un passaggio in piu': serve a instrada per fermarsi a max_steps
        return {"messages": out["messages"], "steps": state["steps"] + 1}

    # nodo "limite": il modello chiede ancora strumenti ma i passaggi sono finiti
    def limite(state: State) -> dict:
        log_agente.warning("limite di passaggi raggiunto (%d)", max_steps)
        # ogni tool_call pendente riceve una risposta, cosi' la cronologia resta valida
        chiuse = [ToolMessage("Chiamata non eseguita: raggiunto il limite di passaggi.",
                              tool_call_id=c["id"], name=c["name"], status="error")
                  for c in state["messages"][-1].tool_calls]
        testo = (f"Ho raggiunto il limite di {max_steps} passaggi con gli strumenti "
                 "e mi fermo qui senza una risposta completa.")
        return {"messages": chiuse + [AIMessage(testo)]}

    # montaggio del grafo
    g = StateGraph(State)
    g.add_node("router", router)
    g.add_node("rifiuto", rifiuto)
    g.add_node("modello", modello)
    g.add_node("strumenti", strumenti_)
    g.add_node("limite", limite)
    # si parte sempre dal router
    g.add_edge(START, "router")
    # conversazione -> agente; fuori ambito -> rifiuto
    g.add_conditional_edges("router", dopo_router, {"modello": "modello", "rifiuto": "rifiuto"})
    g.add_edge("rifiuto", END)
    # ciclo dell'agente come in L5
    g.add_conditional_edges("modello", lambda s: instrada(s, max_steps),
                            {"strumenti": "strumenti", "limite": "limite", END: END})
    g.add_edge("strumenti", "modello")
    g.add_edge("limite", END)
    # compile() controlla il grafo e lo rende eseguibile con invoke()
    return g.compile()
