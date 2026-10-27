import logging

from langchain_core.messages import HumanMessage
from openai import APIConnectionError, APIStatusError

from app.graph import build_graph
from app.llm import HISTORY, LOG_GRAFO, LOG_HTTP, STREAM

MSG_CONNESSIONE = (
    "Impossibile raggiungere LM Studio. Controlla che il server sia avviato "
    "e che LM_BASE_URL sia corretto."
)

MAX_DETTAGLIO = 300

PROMPT_UTENTE = "Tu: "
ETICHETTA_ASSISTENTE = "Assistente: "


def _messaggio_errore_http(errore: APIStatusError) -> str:
    """Codice di stato, testo del server e, dove serve, un suggerimento."""
    dettaglio = " ".join(str(errore.message).split())
    if len(dettaglio) > MAX_DETTAGLIO:
        dettaglio = dettaglio[:MAX_DETTAGLIO] + "..."
    testo = (f"Il server di LM Studio ha risposto con errore {errore.status_code}: "
             f"{dettaglio}")
    if errore.status_code == 400:
        testo += (" Potrebbe dipendere dal template di prompt del modello o dalla "
                  "gestione degli strumenti in LM Studio (vedi docs/DIAGNOSI.md).")
    elif errore.status_code == 404:
        testo += " Controlla che il modello sia caricato e che LM_MODEL sia corretto."
    return testo


def _testo_valido(testo: str) -> str:
    """Python legge i byte non UTF-8 del terminale come surrogati (U+DCC3 per il byte 0xC3):
    il JSON della richiesta non li puo' codificare. Si sostituiscono con U+FFFD invece di
    far cadere l'app."""
    return testo.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _scrivi_token(testo: str) -> None:
    print(testo, end="", flush=True)


def main(input_fn=input, output_fn=print, llm=None, max_steps: int = 5,
         stream: bool = STREAM, token_fn=_scrivi_token, history: bool = HISTORY) -> None:
    nuova_risposta = [True]

    def scrivi_token(testo: str) -> None:
        # l'etichetta esce col primo token, cosi' i log degli strumenti non la spezzano
        if nuova_risposta[0]:
            nuova_risposta[0] = False
            token_fn(ETICHETTA_ASSISTENTE)
        token_fn(testo)

    grafo = build_graph(llm, max_steps, on_token=scrivi_token if stream else None)
    cronologia = []  # solo in memoria, mai su disco
    output_fn("Scrivi un messaggio ('exit' per uscire).")
    while True:
        try:
            testo = _testo_valido(input_fn(PROMPT_UTENTE)).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if testo.lower() == "exit":
            break
        if not testo:
            continue
        nuova_risposta[0] = True
        try:
            out = grafo.invoke(
                {"messages": cronologia + [HumanMessage(testo)], "steps": 0})
        except KeyboardInterrupt:
            break
        except APIStatusError as errore:
            # la domanda fallita non entra nella cronologia
            output_fn(_messaggio_errore_http(errore))
            continue
        except APIConnectionError:
            # la domanda fallita non entra nella cronologia
            output_fn(MSG_CONNESSIONE)
            continue
        risposta = out["messages"][-1].content
        if history:
            cronologia = out["messages"]
        if stream:
            if not nuova_risposta[0]:
                token_fn("\n")  # il testo e' gia' stato scritto token per token
        else:
            output_fn(ETICHETTA_ASSISTENTE + risposta)


def imposta_log(log_http: bool = LOG_HTTP, log_grafo: bool = LOG_GRAFO) -> None:
    """Un logger spento resta muto (CRITICAL); acceso mostra il livello INFO."""
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    livello_http = logging.INFO if log_http else logging.CRITICAL
    for nome in ("httpx", "httpx2"):
        logging.getLogger(nome).setLevel(livello_http)
    logging.getLogger("app.graph").setLevel(logging.INFO if log_grafo else logging.CRITICAL)


def avvia() -> None:
    """Punto d'ingresso: legge la configurazione dall'ambiente e avvia il ciclo."""
    from app.config import load_settings
    from app.llm import build_llm

    imposta_log()
    try:
        impostazioni = load_settings()
    except ValueError as errore:
        raise SystemExit(f"Configurazione non valida: {errore}")
    main(llm=build_llm(impostazioni), max_steps=impostazioni.max_steps)


if __name__ == "__main__":
    avvia()
