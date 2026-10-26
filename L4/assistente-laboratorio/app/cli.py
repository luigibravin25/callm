from langchain_core.messages import HumanMessage
from openai import APIConnectionError, APIStatusError

from app.graph import build_graph

MSG_CONNESSIONE = (
    "Impossibile raggiungere LM Studio. Controlla che il server sia avviato "
    "e che LM_BASE_URL sia corretto."
)


def main(input_fn=input, output_fn=print, llm=None) -> None:
    grafo = build_graph(llm)
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
            output_fn(f"Il server di LM Studio ha risposto con errore {errore.status_code}. "
                      "Controlla che il modello sia caricato e che LM_MODEL sia corretto.")
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
    main(llm=build_llm(impostazioni))
