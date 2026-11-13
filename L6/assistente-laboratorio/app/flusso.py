"""Eventi del turno in streaming (step 10): il grafo eseguito con grafo.stream, tradotto in eventi.

Modi di LangGraph usati: "tasks" (inizio dei nodi), "messages" (pezzi di testo del modello: con
questo modo anche llm.invoke va a pezzi), "updates" (risultato dei nodi), "values" (stato dopo ogni
passo: l'ultimo e' lo stato finale). Router, revisore e riassunto non vanno in streaming
(disable_streaming in app/llm.py): solo il testo del nodo "modello" arriva al browser.
"""
# librerie standard: espressioni regolari (parole), tipi
import re
from collections.abc import Iterator

# LangChain: pezzi di messaggio prodotti in streaming
from langchain_core.messages import AIMessageChunk

# parti dell'agente: completamento del fuso, testo del revisore, evento
from app.graph import completa_fuso
from app.revisore import MSG_REVISORE, REVISORE
from app.sse import Evento

# il messaggio del revisore e' MSG_REVISORE con il motivo dentro: prefisso e suffisso per estrarlo
_PRIMA, _DOPO = MSG_REVISORE.split("{motivo}")


# una parola completa: spazi iniziali, caratteri non spazio, spazi finali (la parola e' finita solo
# quando arriva lo spazio dopo; l'ultima si manda a fine risposta)
_PAROLA = re.compile(r"\s*\S+\s+")


# parole complete all'inizio del testo e il resto ancora incompleto
def parole_complete(testo: str) -> tuple[list[str], str]:
    parole, fine = [], 0
    for m in _PAROLA.finditer(testo):
        if m.start() != fine:
            break
        parole.append(m.group())
        fine = m.end()
    return parole, testo[fine:]


# motivo del revisore dal testo del suo messaggio (se il formato non torna, il testo intero)
def motivo_revisore(testo: str) -> str:
    if testo.startswith(_PRIMA) and testo.endswith(_DOPO):
        return testo[len(_PRIMA):len(testo) - len(_DOPO)]
    return testo


# eventi di un turno: fase, bozza, testo, strumento, revisione; l'ultimo e' "stato_finale" (uso
# interno: lo stato del grafo a fine turno). Le eccezioni del grafo risalgono al chiamante.
def eventi_turno(grafo, ingresso: dict, fuso_predefinito: str) -> Iterator[Evento]:
    yield Evento("fase", {"fase": "pensa"})
    finale = None
    # pezzi del modello non ancora diventati una parola intera (LM Studio spezza anche le parole)
    in_sospeso = ""
    for modo, dati in grafo.stream(ingresso, stream_mode=["messages", "updates", "values", "tasks"]):
        # qualsiasi passo del grafo diverso da un pezzo di testo chiude l'ultima parola
        if modo != "messages" and in_sospeso:
            yield Evento("testo", {"testo": in_sospeso})
            in_sospeso = ""
        if modo == "tasks":
            # inizio di un nodo: c'e' "input"; la fine del nodo (con "result") si ignora
            if "input" not in dati:
                continue
            nome = dati["name"]
            if nome == "modello":
                # nuova risposta del modello: la bozza precedente si scarta
                yield Evento("bozza", {})
            elif nome == "revisore":
                yield Evento("fase", {"fase": "revisore"})
            elif nome == "strumenti":
                # chiamate che stanno per partire, con il fuso completato come nel nodo
                richiesta = dati["input"]["messages"][-1]
                richiesta = completa_fuso(richiesta, fuso_predefinito) or richiesta
                for c in richiesta.tool_calls:
                    yield Evento("strumento", {"nome": c["name"], "argomenti": dict(c["args"])})
        elif modo == "messages":
            messaggio, meta = dati
            # solo i pezzi di testo del nodo modello; i messaggi interi di fine nodo (come le
            # risposte fisse del programma) arrivano con lo stato finale
            if (meta.get("langgraph_node") == "modello" and isinstance(messaggio, AIMessageChunk)
                    and isinstance(messaggio.content, str) and messaggio.content):
                # una parola alla volta: si manda solo quando e' completa
                parole, in_sospeso = parole_complete(in_sospeso + messaggio.content)
                for parola in parole:
                    yield Evento("testo", {"testo": parola})
        elif modo == "updates":
            for nodo, aggiornamento in dati.items():
                if nodo != "revisore" or not aggiornamento:
                    continue
                for m in aggiornamento.get("messages", []):
                    if getattr(m, "name", None) == REVISORE:
                        yield Evento("revisione", {"motivo": motivo_revisore(str(m.content))})
        elif modo == "values":
            finale = dati
    if in_sospeso:
        yield Evento("testo", {"testo": in_sospeso})
    yield Evento("stato_finale", finale)
