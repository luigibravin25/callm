from langchain_core.messages import HumanMessage
from openai import APIConnectionError, APIStatusError

from app.graph import build_graph

MSG_CONNESSIONE = (
    "Impossibile raggiungere LM Studio. Controlla che il server sia avviato "
    "e che LM_BASE_URL sia corretto."
)

MAX_DETTAGLIO = 300


def _messaggio_errore_http(errore: APIStatusError) -> str:
    """Codice di stato, testo del server e, dove serve, un suggerimento."""
    dettaglio = " ".join(str(errore.message).split())
    if len(dettaglio) > MAX_DETTAGLIO:
        dettaglio = dettaglio[:MAX_DETTAGLIO] + "..."
    testo = (f"Il server di LM Studio ha risposto con errore {errore.status_code}: "
             f"{dettaglio}")
    if errore.status_code == 400:
        testo += (" Potrebbe dipendere dal template di prompt del modello o dalla "
                  "gestione degli strumenti in LM Studio (vedi il README, sezione Diagnosi).")
    elif errore.status_code == 404:
        testo += " Controlla che il modello sia caricato e che LM_MODEL sia corretto."
    return testo


def main(input_fn=input, output_fn=print, llm=None, max_steps: int = 5) -> None:
    grafo = build_graph(llm, max_steps)
    cronologia = []  # solo in memoria, mai su disco
    output_fn("Scrivi un messaggio ('exit' per uscire).")
    while True:
        try:
            testo = input_fn("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if testo.lower() == "exit":
            break
        if not testo:
            continue
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
        cronologia = out["messages"]
        output_fn(cronologia[-1].content)


if __name__ == "__main__":
    import logging

    from app.config import load_settings
    from app.llm import build_llm

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    # i log delle librerie HTTP coprirebbero quelli degli strumenti
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        impostazioni = load_settings()
    except ValueError as errore:
        raise SystemExit(f"Configurazione non valida: {errore}")
    main(llm=build_llm(impostazioni), max_steps=impostazioni.max_steps)
