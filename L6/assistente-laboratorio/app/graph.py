# librerie standard: log, tipi per descrivere lo stato
import logging
from typing import Annotated, Literal, TypedDict

# messaggi della conversazione; grafo LangGraph; nodo che esegue gli strumenti
from langchain_core.messages import (AIMessage, HumanMessage, RemoveMessage, SystemMessage,
                                     ToolMessage)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# parti del progetto: ambito, prompt dell'agente, decisione del router, strumenti
from app.config import Ambito
from app.llm import SYSTEM_PROMPT
from app.revisore import MSG_REVISORE, REVISORE, valuta
from app.riassunto import indice_di_taglio, riassumi
from app.router import decidi
from app.tools import STRUMENTI

# un logger per ruolo: nel terminale compaiono come [router], [agente], [rifiuto], [revisore]
log_router = logging.getLogger("router")
log_agente = logging.getLogger("agente")
log_rifiuto = logging.getLogger("rifiuto")
log_revisore = logging.getLogger("revisore")
log_riassunto = logging.getLogger("riassunto")

# name delle risposte fisse del programma (risposta vuota, limite): non sono del modello
PROGRAMMA = "programma"
# blocco aggiunto in fondo al prompt di sistema dell'agente quando c'e' un riassunto
BLOCCO_RIASSUNTO = "\n\nRiassunto della conversazione precedente: "

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
    revisioni: int  # quante volte il revisore ha gia' rimandato la risposta all'agente
    riassunto: str  # riassunto dei messaggi tolti dalla cronologia (sostituito, non accumulato)


# e' un messaggio del revisore? (HumanMessage con name="revisore")
def _del_revisore(m) -> bool:
    return isinstance(m, HumanMessage) and m.name == REVISORE


# posizione dell'ultima domanda vera dell'utente (i messaggi del revisore non contano)
def _ultima_domanda(messages: list) -> int:
    return max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage)
               and not _del_revisore(m))


# dopo il modello: strumenti, limite, revisore oppure pulizia
def instrada(state: State, max_steps: int = 5) -> Literal["strumenti", "limite", "revisore",
                                                           "pulizia"]:
    ultimo = state["messages"][-1]
    # getattr con valore None: funziona anche con messaggi che non hanno tool_calls
    if getattr(ultimo, "tool_calls", None):
        return "strumenti" if state["steps"] < max_steps else "limite"
    # il messaggio fisso di risposta vuota non e' una risposta del modello: niente revisione
    if ultimo.content == MSG_VUOTO:
        return "pulizia"
    return "revisore"  # risposta vera del modello: la controlla il revisore


# dopo il revisore: di nuovo all'agente se ha lasciato un'indicazione, altrimenti pulizia
def dopo_revisore(state: State) -> Literal["modello", "pulizia"]:
    return "modello" if _del_revisore(state["messages"][-1]) else "pulizia"


# id dei messaggi da togliere a fine turno: indicazioni del revisore e bozze rifiutate
def messaggi_da_pulire(messages: list) -> list[str]:
    """Nei messaggi dopo l'ultima domanda vera: ogni messaggio del revisore e ogni AIMessage
    senza tool_calls seguito subito da un messaggio del revisore (la bozza rifiutata)."""
    turno = messages[_ultima_domanda(messages) + 1:]
    ids = []
    for i, m in enumerate(turno):
        seguito_dal_revisore = i + 1 < len(turno) and _del_revisore(turno[i + 1])
        if _del_revisore(m) or (isinstance(m, AIMessage) and not m.tool_calls
                                and seguito_dal_revisore):
            ids.append(m.id)
    return ids


# dopo il router: l'agente per le domande in ambito, il rifiuto per le altre
def dopo_router(state: State) -> Literal["modello", "rifiuto"]:
    return "rifiuto" if state["categoria"] == "fuori_ambito" else "modello"


# costruisce il grafo: router, rifiuto e i nodi dell'agente (modello, strumenti, limite)
def build_graph(llm, router_llm, revisore_llm, riassunto_llm, ambito: Ambito,
                max_steps: int = 5, max_revisioni: int = 2, soglia_riassunto: int = 16,
                messaggi_recenti: int = 6, strumenti=STRUMENTI,
                system_prompt: str = SYSTEM_PROMPT):
    """`llm`: modello dell'agente con gli strumenti; `router_llm` e `revisore_llm`: modelli con
    output strutturato; `riassunto_llm`: modello che riassume in testo. Input:
    {"messages": [...], "steps": 0, "revisioni": 0, "riassunto": "..."}."""
    nodo_strumenti = ToolNode(strumenti)

    # nodo "riassunto": oltre la soglia sostituisce i messaggi vecchi con un riassunto
    def riassunto(state: State) -> dict:
        messaggi = state["messages"]
        n = len(messaggi)
        if n <= soglia_riassunto:
            # sotto la soglia: nessuna chiamata al modello
            log_riassunto.info("%d messaggi, soglia %d: nessun riassunto", n, soglia_riassunto)
            return {}
        taglio = indice_di_taglio(messaggi, messaggi_recenti)
        if taglio == 0:
            return {}  # nessun confine di turno valido: niente da riassumere
        testo = riassumi(riassunto_llm, state.get("riassunto", ""), messaggi[:taglio])
        if testo is None:
            return {}  # riassunto fallito: i messaggi restano (avviso gia' nel log)
        log_riassunto.info("messaggi prima %d, dopo %d (riassunti %d)", n, n - taglio, taglio)
        # il testo nel log: si vede cosa ricevera' l'agente (evidenza dello step 3)
        log_riassunto.info('nuovo riassunto: "%s"', testo)
        # i messaggi riassunti escono dalla cronologia; il riassunto nuovo sostituisce il vecchio
        return {"messages": [RemoveMessage(id=m.id) for m in messaggi[:taglio]],
                "riassunto": testo}

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
        # il prompt di sistema viene anteposto a ogni richiesta, non entra nella cronologia;
        # il riassunto (se c'e') va in fondo allo stesso SystemMessage: gemma ne vuole uno solo
        sistema = system_prompt
        if state.get("riassunto", "").strip():
            sistema += BLOCCO_RIASSUNTO + state["riassunto"]
        risposta = llm.invoke([SystemMessage(sistema)] + state["messages"])
        # niente testo e niente chiamate: i token sono finiti nel ragionamento, lo si dice
        if not risposta.tool_calls and not str(risposta.content).strip():
            return {"messages": [AIMessage(MSG_VUOTO, name=PROGRAMMA)]}
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
        return {"messages": chiuse + [AIMessage(testo, name=PROGRAMMA)]}

    # nodo "revisore": la risposta risponde a tutta la domanda? se no, torna all'agente
    def revisore(state: State) -> dict:
        messaggi = state["messages"]
        domanda = str(messaggi[_ultima_domanda(messaggi)].content)
        decisione = valuta(revisore_llm, domanda, str(messaggi[-1].content))
        if decisione.coerente:
            log_revisore.info('coerente motivo="%s" → fine', decisione.motivo)
            return {}
        if state["revisioni"] >= max_revisioni:
            log_revisore.warning("limite di revisioni raggiunto (%d): restituisco l'ultima "
                                 "risposta", max_revisioni)
            return {}
        revisioni = state["revisioni"] + 1
        log_revisore.info('non coerente motivo="%s" → agente (revisione %d di %d)',
                          decisione.motivo, revisioni, max_revisioni)
        # l'indicazione entra nella cronologia come messaggio "utente" marcato revisore
        indicazione = HumanMessage(MSG_REVISORE.format(motivo=decisione.motivo), name=REVISORE)
        return {"messages": [indicazione], "revisioni": revisioni}

    # nodo "pulizia": a fine turno toglie indicazioni del revisore e bozze rifiutate
    def pulizia(state: State) -> dict:
        messaggi = state["messages"]
        ids = messaggi_da_pulire(messaggi)
        if ids:
            log_revisore.info("pulizia: tolti %d messaggi (indicazioni del revisore e bozze "
                              "rifiutate)", len(ids))
        nuovi = []
        ultimo = messaggi[-1]
        bozze = [m for m in messaggi if m.id in ids and isinstance(m, AIMessage)]
        # dopo una revisione l'agente ha finito i token o i passaggi: invece della risposta
        # fissa del programma l'utente riceve l'ultima bozza, che risponde almeno in parte
        if bozze and isinstance(ultimo, AIMessage) and ultimo.name == PROGRAMMA:
            log_revisore.warning("risposta finale non disponibile (%s): restituisco l'ultima "
                                 "bozza", ultimo.content[:40])
            ids.append(ultimo.id)
            # copia in fondo: dopo eventuali ToolMessage, cosi' la cronologia resta valida
            nuovi = [AIMessage(bozze[-1].content)]
        # RemoveMessage: add_messages toglie dallo stato il messaggio con quell'id
        return {"messages": [RemoveMessage(id=i) for i in ids] + nuovi}

    # montaggio del grafo
    g = StateGraph(State)
    g.add_node("riassunto", riassunto)
    g.add_node("router", router)
    g.add_node("rifiuto", rifiuto)
    g.add_node("modello", modello)
    g.add_node("strumenti", strumenti_)
    g.add_node("limite", limite)
    g.add_node("revisore", revisore)
    g.add_node("pulizia", pulizia)
    # si parte dal riassunto della cronologia, poi il router
    g.add_edge(START, "riassunto")
    g.add_edge("riassunto", "router")
    # conversazione -> agente; fuori ambito -> rifiuto
    g.add_conditional_edges("router", dopo_router, {"modello": "modello", "rifiuto": "rifiuto"})
    g.add_edge("rifiuto", END)
    # ciclo dell'agente come in L5; la risposta finale passa dal revisore
    g.add_conditional_edges("modello", lambda s: instrada(s, max_steps),
                            {"strumenti": "strumenti", "limite": "limite",
                             "revisore": "revisore", "pulizia": "pulizia"})
    g.add_edge("strumenti", "modello")
    # non coerente -> di nuovo all'agente; coerente o limite -> pulizia
    g.add_conditional_edges("revisore", dopo_revisore,
                            {"modello": "modello", "pulizia": "pulizia"})
    g.add_edge("limite", "pulizia")
    g.add_edge("pulizia", END)
    # compile() controlla il grafo e lo rende eseguibile con invoke()
    return g.compile()
