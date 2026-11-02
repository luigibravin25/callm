import logging
import sys
import threading

from langchain_core.messages import HumanMessage, ToolMessage
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


class Attesa:
    """Riga animata 'Assistente: ...' (puntini in movimento) finche' il modello non risponde.
    Attiva solo su un terminale: in pipe (es. docker compose run -T) resta muta."""

    def __init__(self, scrivi=_scrivi_token, intervallo: float = 0.4, attiva=None):
        self._scrivi = scrivi
        self._intervallo = intervallo
        self._attiva = sys.stdout.isatty() if attiva is None else attiva
        self._stop = None
        self._thread = None

    def _ciclo(self, stop: threading.Event) -> None:
        n = 0
        while not stop.is_set():
            n = n % 3 + 1
            self._scrivi(f"\r{ETICHETTA_ASSISTENTE}{'.' * n}{' ' * (3 - n)}")
            stop.wait(self._intervallo)

    def avvia(self) -> None:
        if not self._attiva or self._thread is not None:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._ciclo, args=(self._stop,), daemon=True)
        self._thread.start()

    def ferma(self) -> None:
        """Ferma l'animazione e cancella la riga; innocuo se non e' avviata."""
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        self._thread = None
        larghezza = len(ETICHETTA_ASSISTENTE) + 3
        self._scrivi("\r" + " " * larghezza + "\r")


class _FermaAttesa(logging.Filter):
    """Ferma l'animazione prima che un log del grafo scriva sul terminale."""

    def __init__(self, attesa: Attesa):
        super().__init__()
        self._attesa = attesa

    def filter(self, record: logging.LogRecord) -> bool:
        self._attesa.ferma()
        return True


def main(input_fn=input, output_fn=print, llm=None, max_steps: int = 5,
         stream: bool = STREAM, token_fn=_scrivi_token, history: bool = HISTORY,
         attesa: Attesa | None = None) -> None:
    nuova_risposta = [True]
    if attesa is None:
        attesa = Attesa(scrivi=token_fn)

    def scrivi_token(testo: str) -> None:
        # l'etichetta esce col primo token, cosi' i log degli strumenti non la spezzano
        if nuova_risposta[0]:
            nuova_risposta[0] = False
            attesa.ferma()
            token_fn(ETICHETTA_ASSISTENTE)
        token_fn(testo)

    def invoca(messaggi: list) -> dict:
        """Esegue il grafo passo per passo: dopo uno strumento l'attesa riparte."""
        stato = None
        attesa.avvia()
        try:
            for stato in grafo.stream({"messages": messaggi, "steps": 0},
                                      stream_mode="values"):
                ultimo = stato["messages"][-1]
                if (nuova_risposta[0] and isinstance(ultimo, ToolMessage)
                        and ultimo.status != "error"):
                    attesa.avvia()
        finally:
            attesa.ferma()  # anche con errori o Ctrl+C: la riga animata sparisce
        return stato

    grafo = build_graph(llm, max_steps, on_token=scrivi_token if stream else None)
    filtro = _FermaAttesa(attesa)
    logging.getLogger("app.graph").addFilter(filtro)
    cronologia = []  # solo in memoria, mai su disco
    output_fn("Scrivi un messaggio ('exit' per uscire).")
    try:
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
                out = invoca(cronologia + [HumanMessage(testo)])
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
    finally:
        logging.getLogger("app.graph").removeFilter(filtro)
        attesa.ferma()


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
