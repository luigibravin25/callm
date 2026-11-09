# librerie standard: log nel terminale
import logging

# messaggio dell'utente; errori di LM Studio (connessione, HTTP, altri)
from langchain_core.messages import HumanMessage
from openai import APIConnectionError, APIError, APIStatusError

# interruttori dei log (app/llm.py)
from app.llm import LOG_GRAFO, LOG_HTTP

# messaggi fissi della chat
MSG_CONNESSIONE = (
    "Impossibile raggiungere LM Studio. Controlla che il server sia avviato "
    "e che LM_BASE_URL sia corretto."
)
MSG_INIZIO = "Scrivi un messaggio ('esci' per uscire)."
MSG_ATTESA = "(attendi la risposta...)"
MAX_DETTAGLIO = 300  # caratteri massimi del messaggio del server: evita muri di testo
COMANDI_USCITA = {"esci", "exit"}  # maiuscole indifferenti

# etichette delle righe della chat nel terminale
PROMPT_UTENTE = "Tu: "
ETICHETTA_ASSISTENTE = "Assistente: "


# trasforma un errore HTTP di LM Studio in un messaggio comprensibile (come L5)
def _messaggio_errore_http(errore: APIStatusError) -> str:
    # split/join riduce a capo e spazi multipli a uno spazio solo
    dettaglio = " ".join(str(errore.message).split())[:MAX_DETTAGLIO]
    testo = f"Il server di LM Studio ha risposto con errore {errore.status_code}: {dettaglio}"
    # per i due errori piu' comuni si aggiunge cosa controllare
    if errore.status_code == 400:
        testo += " Controlla la Context Length del modello e il template di prompt in LM Studio."
    elif errore.status_code == 404:
        testo += " Controlla che il modello sia caricato e che LM_MODEL sia corretto."
    return testo


# errori di LM Studio senza codice HTTP; per il contesto pieno, cosa fare
def _messaggio_errore_generico(errore: APIError) -> str:
    dettaglio = " ".join(str(errore.message).split())[:MAX_DETTAGLIO]
    testo = f"Errore da LM Studio: {dettaglio}"
    if "context" in dettaglio.lower():
        testo += (" La conversazione ha superato il contesto del modello: aumenta la Context "
                  "Length in LM Studio, oppure scrivi 'esci' e riparti.")
    return testo


# ripulisce il testo digitato dai byte non UTF-8 del terminale (come L5)
def _testo_valido(testo: str) -> str:
    # surrogateescape riporta i surrogati ai byte originali; "replace" mette U+FFFD sui non validi
    return testo.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


# ciclo della chat: una domanda alla volta, cronologia solo in memoria
def main(grafo, input_fn=input, output_fn=print) -> None:
    """Chat da terminale. Ogni domanda passa dal grafo (router, poi agente o rifiuto)."""
    cronologia = []  # solo in memoria, mai su disco
    riassunto = ""  # riassunto dei messaggi usciti dalla cronologia (solo in memoria)
    output_fn(MSG_INIZIO)
    while True:
        try:
            testo = _testo_valido(input_fn(PROMPT_UTENTE)).strip()
        # fine dell'input (Ctrl+Z / Ctrl+D) o Ctrl+C: si esce senza errori
        except (EOFError, KeyboardInterrupt):
            break
        if testo.lower() in COMANDI_USCITA:
            break
        if not testo:
            continue  # riga vuota: si chiede di nuovo, senza disturbare il modello
        output_fn(MSG_ATTESA)
        try:
            # il grafo riceve tutta la cronologia piu' la nuova domanda; contatori da 0
            out = grafo.invoke({"messages": cronologia + [HumanMessage(testo)], "steps": 0,
                                "revisioni": 0, "riassunto": riassunto})
        except KeyboardInterrupt:
            break
        # in ogni caso di errore la domanda fallita non entra nella cronologia
        except APIStatusError as errore:
            output_fn(_messaggio_errore_http(errore))
            continue
        except APIConnectionError:
            output_fn(MSG_CONNESSIONE)
            continue
        except APIError as errore:
            output_fn(_messaggio_errore_generico(errore))
            continue
        # la cronologia diventa tutta la conversazione, strumenti e rifiuti compresi
        cronologia = out["messages"]
        # il riassunto aggiornato dal grafo passa al turno successivo
        riassunto = out.get("riassunto", riassunto)
        output_fn(ETICHETTA_ASSISTENTE + str(cronologia[-1].content))


# accende o spegne i log nel terminale secondo LOG_HTTP e LOG_GRAFO
def imposta_log(log_http: bool = LOG_HTTP, log_grafo: bool = LOG_GRAFO) -> None:
    # formato: nome del logger tra parentesi quadre, poi il messaggio
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    # un logger spento resta muto (CRITICAL); acceso mostra il livello INFO
    # richieste HTTP verso LM Studio: il client OpenAI usa httpx o httpx2 secondo la versione
    for nome in ("httpx", "httpx2"):
        logging.getLogger(nome).setLevel(logging.INFO if log_http else logging.CRITICAL)
    for nome in ("router", "agente", "rifiuto", "revisore", "riassunto"):
        logging.getLogger(nome).setLevel(logging.INFO if log_grafo else logging.CRITICAL)


# avvio del programma (python -m app.cli)
def avvia() -> None:
    """Legge configurazione e ambito, costruisce i modelli (agente, router, revisore, riassunto) e il grafo,
    avvia la chat."""
    # import qui dentro: servono solo all'avvio vero, non quando i test importano il modulo
    from app.config import load_ambito, load_settings
    from app.graph import build_graph
    from app.llm import build_llm, build_revisore_llm, build_riassunto_llm, build_router_llm

    imposta_log()
    try:
        impostazioni = load_settings()
        ambito = load_ambito(impostazioni.ambito_file)
    except ValueError as errore:
        # SystemExit chiude il programma mostrando solo il messaggio, senza traceback
        raise SystemExit(f"Configurazione non valida: {errore}")
    grafo = build_graph(build_llm(impostazioni), build_router_llm(impostazioni),
                        build_revisore_llm(impostazioni), build_riassunto_llm(impostazioni),
                        ambito, impostazioni.max_steps, impostazioni.max_revisioni,
                        impostazioni.soglia_riassunto, impostazioni.messaggi_recenti)
    main(grafo)


if __name__ == "__main__":
    avvia()
