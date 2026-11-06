# librerie standard: log, espressioni regolari, tipi per descrivere lo stato
import logging
import re  # per riconoscere "tra/fra N giorni" nella domanda dell'utente
from typing import Annotated, Literal, TypedDict

# tipi di messaggio della conversazione (utente, modello, sistema, risultato di uno strumento)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
# LangGraph: il grafo con i suoi nodi, la regola che accoda i messaggi, il nodo degli strumenti
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# parti del progetto: riconoscere i tool distruttivi, prompt di sistema, strumenti locali
from app.adattatore_mcp import è_distruttivo
from app.llm import SYSTEM_PROMPT
from app.tools import STRUMENTI

# logger del grafo: i suoi messaggi compaiono nel terminale se LOG_GRAFO e' True
logger = logging.getLogger("app.graph")

# risposta usata quando non c'e' un modello (llm=None), per esempio in alcuni test
RISPOSTA_FISSA = "Sono l'assistente del laboratorio. Per ora rispondo sempre così."


# stato del grafo: passa da un nodo all'altro e cresce a ogni passaggio
class State(TypedDict):
    # add_messages: i messaggi restituiti da un nodo si aggiungono in coda, non sostituiscono
    messages: Annotated[list, add_messages]
    steps: int  # quante volte sono stati eseguiti strumenti in questa domanda


# messaggi fissi del grafo
MSG_VUOTO = (
    "Il modello ha restituito una risposta vuota: i token sono finiti nel "
    "ragionamento. Prova ad aumentare il budget di token."
)


MSG_ANNULLATA = "Eliminazione annullata dall'utente: nessuna nota eliminata."
MSG_DOPPIONE = "Nota già salvata in questa richiesta: non la salvo di nuovo."
MSG_RIPETUTA = "Chiamata ripetuta nella stessa risposta: add_note eseguita una sola volta."
SEMPRE_DA_CONFERMARE = {"delete_note"}  # confermati anche senza l'annotazione MCP


# rende confrontabili due testi di nota ("Comprare il latte " = "comprare il latte")
def _normalizza(testo) -> str:
    """Testo di una nota per il confronto dei doppioni: senza spazi esterni e maiuscole."""
    return str(testo).strip().lower()


# raccoglie le note gia' salvate per la domanda in corso, per bloccare i doppioni
def _note_salvate_nella_domanda(messaggi: list) -> set[str]:
    """Testi di add_note riusciti dopo l'ultimo messaggio dell'utente (la domanda in corso)."""
    # posizione dell'ultima domanda dell'utente (-1 se non ce n'e' nessuna)
    inizio = max((i for i, m in enumerate(messaggi) if isinstance(m, HumanMessage)), default=-1)
    testi = {}  # tool_call_id -> testo
    salvati = set()
    for m in messaggi[inizio + 1:]:
        # il modello chiede add_note: si ricorda il testo, collegato all'id della chiamata
        if isinstance(m, AIMessage):
            for c in m.tool_calls:
                if c["name"] == "add_note":
                    testi[c["id"]] = c["args"].get("text", "")
        # il risultato di quella chiamata e' arrivato senza errore: la nota e' davvero salvata
        elif isinstance(m, ToolMessage) and m.tool_call_id in testi and m.status != "error":
            salvati.add(_normalizza(testi[m.tool_call_id]))
    return salvati


# "tra 3 giorni", "fra due giorni", "tra un giorno" dentro la domanda (stessa forma che legge
# il server meteo): parole intere, maiuscole indifferenti
_TRA_N_GIORNI = re.compile(r"\b(?:tra|fra)\s+\w+\s+giorn[oi]\b", re.IGNORECASE)


# cerca "tra/fra N giorni" nell'ultima domanda, per correggere la chiamata del meteo
def _tra_n_giorni_nella_domanda(messaggi: list) -> str | None:
    """"tra/fra N giorni" scritto nell'ultima domanda dell'utente (minuscolo), oppure None."""
    # solo la domanda in corso: una domanda precedente non deve cambiare questa chiamata
    domanda = next((m for m in reversed(messaggi) if isinstance(m, HumanMessage)), None)
    if domanda is None:
        return None
    # search trova la prima occorrenza in qualunque punto del testo
    trovato = _TRA_N_GIORNI.search(str(domanda.content))
    # spazi multipli ridotti a uno: il server legge "tra 3 giorni" con spazi singoli
    return " ".join(trovato[0].lower().split()) if trovato else None


# corregge una chiamata del meteo in cui il modello ha usato days invece di date
def _correggi_meteo(c: dict, messaggi: list) -> dict:
    """Chiamata get_weather con "tra/fra N giorni" della domanda in date, se il modello non
    ha passato date.

    Il modello piccolo a volte usa days=N (oggi compreso) invece di date="tra N giorni" (gli
    N giorni da domani): il programma corregge la chiamata e lo scrive nel log. Ogni altra
    chiamata resta com'e'."""
    if c["name"] != "get_weather" or str(c["args"].get("date") or "").strip():
        return c  # altro strumento, oppure date gia' scelta dal modello: nessuna correzione
    testo = _tra_n_giorni_nella_domanda(messaggi)
    if testo is None:
        return c  # la domanda non dice "tra/fra N giorni"
    # con date presente il server ignora days: days resta com'era, solo per il log
    logger.info("get_weather: date=%r presa dalla domanda (il modello aveva usato days=%s)",
                testo, c["args"].get("days"))
    return {**c, "args": {**c["args"], "date": testo}}  # copia: il messaggio originale resta


# decide dove va il grafo dopo la risposta del modello (arco condizionale)
def instrada(state: State, max_steps: int = 5) -> Literal["strumenti", "limite", "__end__"]:
    """Dopo il modello: strumenti se chiede una chiamata e c'e' margine,
    limite se la chiede ma i passaggi sono finiti, altrimenti fine."""
    # getattr con valore None: funziona anche con messaggi che non hanno tool_calls
    if getattr(state["messages"][-1], "tool_calls", None):
        return "strumenti" if state["steps"] < max_steps else "limite"
    # nessuna chiamata a strumenti: la risposta e' finale
    return END


# costruisce il grafo dell'agente: nodi modello, strumenti e limite, e gli archi tra loro
def build_graph(llm=None, max_steps: int = 5, on_token=None, strumenti=STRUMENTI,
                system_prompt: str = SYSTEM_PROMPT, conferma=None):
    """Con `on_token` il testo arriva token per token (llm.stream), altrimenti in blocco.
    `strumenti`: app.cli passa i 4 strumenti locali e HTTP piu' i tool dei server MCP.
    `conferma(nome, argomenti) -> bool`: chiesta prima di ogni tool distruttivo
    (annotazione MCP destructiveHint); senza conferma il tool distruttivo non viene eseguito."""
    # il modello va gia' associato agli stessi strumenti da build_llm
    nodo_strumenti = ToolNode(strumenti)
    # tool che richiedono conferma: annotazione MCP destructiveHint, e delete_note comunque
    # (difesa in profondita': se l'annotazione andasse persa, niente eliminazioni senza si')
    distruttivi = {t.name for t in strumenti if è_distruttivo(t) or t.name in SEMPRE_DA_CONFERMARE}

    # manda un pezzo di testo al terminale, solo se c'e' chi lo stampa (modalita' streaming)
    def emetti(testo: str) -> None:
        if on_token and testo:
            on_token(testo)

    # interroga il modello: in blocco (invoke) oppure un pezzo alla volta (stream)
    def chiedi_al_modello(messaggi: list) -> AIMessage:
        if on_token is None:
            return llm.invoke(messaggi)
        risposta = None
        for pezzo in llm.stream(messaggi):
            # il testo si mostra subito; i pezzi delle tool_call non hanno testo da stampare
            if isinstance(pezzo.content, str):
                emetti(pezzo.content)
            # i pezzi si sommano: alla fine si ottiene il messaggio completo
            risposta = pezzo if risposta is None else risposta + pezzo
        # stream senza nessun pezzo: si restituisce un messaggio vuoto
        return risposta if risposta is not None else AIMessage("")

    # nodo "modello": chiede al modello la prossima mossa (risposta o chiamata a strumenti)
    def modello(state: State) -> dict:
        if llm is None:
            emetti(RISPOSTA_FISSA)
            return {"messages": [AIMessage(RISPOSTA_FISSA)]}
        # il prompt di sistema viene anteposto a ogni richiesta, non entra nella cronologia
        risposta = chiedi_al_modello([SystemMessage(system_prompt)] + state["messages"])
        # niente testo e niente chiamate: i token sono finiti nel ragionamento, lo si dice
        if not risposta.tool_calls and not str(risposta.content).strip():
            emetti(MSG_VUOTO)
            return {"messages": [AIMessage(MSG_VUOTO)]}
        return {"messages": [risposta]}

    # crea la risposta per una chiamata che il programma ha deciso di non eseguire
    def bloccata(c, testo: str) -> ToolMessage:
        """Risposta per una tool_call NON eseguita (annullata o doppione)."""
        return ToolMessage(testo, tool_call_id=c["id"], name=c["name"], status="error")

    # nodo "strumenti": esegue le chiamate chieste dal modello, dopo i controlli del programma
    def strumenti(state: State, config) -> dict:
        """Esegue le tool_call dell'ultimo messaggio del modello, con due controlli:
        doppioni di add_note nella stessa domanda e conferma per i tool distruttivi."""
        ultimo = state["messages"][-1]
        # note gia' salvate nella domanda in corso (risposte precedenti del modello)
        salvati = _note_salvate_nella_domanda(state["messages"][:-1])
        in_questa_risposta = set()  # testi di add_note gia' ammessi in questa risposta
        ammesse, risposte = [], {}  # risposte: tool_call_id -> ToolMessage gia' deciso
        # ogni chiamata viene ammessa oppure bloccata con una risposta gia' pronta
        for c in ultimo.tool_calls:
            logger.info("Chiamata strumento %s con argomenti %s", c["name"], c["args"])
            # meteo: "tra/fra N giorni" della domanda va in date anche se il modello usa days
            c = _correggi_meteo(c, state["messages"])
            if c["name"] == "add_note":
                testo = _normalizza(c["args"].get("text", ""))
                if testo and testo in salvati:  # gia' salvata con successo in questa domanda
                    risposte[c["id"]] = bloccata(c, MSG_DOPPIONE)
                    continue
                if testo in in_questa_risposta:
                    # stessa nota due volte nella stessa risposta: la prima non e' ancora stata
                    # eseguita, quindi non si puo' dire "gia' salvata" (potrebbe fallire)
                    risposte[c["id"]] = bloccata(c, MSG_RIPETUTA)
                    continue
                in_questa_risposta.add(testo)
            # conferma chiesta all'utente tramite la funzione passata dalla CLI
            if c["name"] in distruttivi:
                # tool distruttivo: si esegue solo con il si' esplicito dell'utente
                if conferma is not None and conferma(c["name"], c["args"]):
                    logger.info("Eliminazione confermata dall'utente per %s %s",
                                c["name"], c["args"])
                else:
                    logger.info("Eliminazione annullata dall'utente per %s %s",
                                c["name"], c["args"])
                    risposte[c["id"]] = bloccata(c, MSG_ANNULLATA)
                    continue
            # superati tutti i controlli: la chiamata verra' eseguita
            ammesse.append(c)
        if ammesse:
            # il ToolNode esegue solo le chiamate ammesse (copia dell'ultimo messaggio)
            filtrato = ultimo.model_copy(update={"tool_calls": ammesse})
            out = nodo_strumenti.invoke({**state, "messages": state["messages"][:-1] + [filtrato]},
                                        config)
            # aggiunge i risultati veri a quelli gia' decisi (bloccati)
            for m in out["messages"]:
                risposte[m.tool_call_id] = m
        # i ToolMessage nell'ordine delle tool_call
        messaggi = [risposte[c["id"]] for c in ultimo.tool_calls]
        for m in messaggi:
            logger.info("Risultato strumento %s: %s", m.name, m.content)
        # un passaggio in piu': serve a instrada per fermarsi a max_steps
        return {"messages": messaggi, "steps": state["steps"] + 1}

    # nodo "limite": il modello chiede ancora strumenti ma i passaggi sono finiti
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

    # montaggio del grafo: tre nodi con i loro nomi
    g = StateGraph(State)
    g.add_node("modello", modello)
    g.add_node("strumenti", strumenti)
    g.add_node("limite", limite)
    # si parte sempre dal modello
    g.add_edge(START, "modello")
    # dopo il modello decide instrada: strumenti, limite oppure fine
    g.add_conditional_edges(
        "modello", lambda s: instrada(s, max_steps),
        {"strumenti": "strumenti", "limite": "limite", END: END})
    # dopo gli strumenti si torna al modello, che legge i risultati (ciclo dell'agente)
    g.add_edge("strumenti", "modello")
    g.add_edge("limite", END)
    # compile() controlla il grafo e lo rende eseguibile con invoke()
    return g.compile()
