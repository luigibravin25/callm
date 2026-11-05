import json  # per leggere l'elenco delle note restituito da list_notes
import logging
import re  # per riconoscere gli elenchi Markdown nelle risposte
import sys
import threading

from langchain_core.messages import HumanMessage, ToolMessage
from openai import APIConnectionError, APIError, APIStatusError

from app.adattatore_mcp import carica_tutti_mcp
from app.graph import build_graph
from app.llm import HISTORY, LOG_GRAFO, LOG_HTTP, STREAM, SYSTEM_PROMPT
from app.tools import STRUMENTI

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


def _messaggio_errore_generico(errore: APIError) -> str:
    """Errore di LM Studio senza codice HTTP; per il contesto pieno, cosa fare."""
    dettaglio = " ".join(str(errore.message).split())[:MAX_DETTAGLIO]
    testo = f"Errore da LM Studio: {dettaglio}"
    if "context" in dettaglio.lower():
        testo += (" La conversazione ha superato il contesto del modello: aumenta la Context "
                  "Length del modello in LM Studio, oppure scrivi 'exit' e riparti con una "
                  "cronologia vuota.")
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


class FiltroMarkdown:
    """Toglie il Markdown che il terminale mostrerebbe cosi' com'e': il grassetto (**testo**)
    e gli elenchi con l'asterisco a inizio riga ("*   voce" diventa "- voce").

    Funziona anche in streaming, dove "**" puo' arrivare spezzato in due pezzi: gli asterischi
    in fondo a un pezzo restano in sospeso finche' non arriva il pezzo dopo. Un asterisco
    singolo dentro la riga (es. 2*3) resta com'e'.
    """

    def __init__(self):
        self._sospeso = ""  # asterischi finali non ancora scritti
        self._inizio_riga = True  # il prossimo carattere e' a inizio riga?

    def aggiungi(self, testo: str) -> str:
        """Riceve un pezzo di testo e restituisce la parte gia' ripulita da scrivere."""
        testo = self._sospeso + testo
        senza_finali = testo.rstrip("*")
        self._sospeso = testo[len(senza_finali):]  # es. "*" o "**" in fondo al pezzo
        testo = senza_finali
        if not testo:
            return ""
        # elenchi: "* " a inizio riga (anche all'inizio del pezzo, se la riga e' appena iniziata)
        if self._inizio_riga and re.match(r"\* +", testo):
            testo = re.sub(r"^\* +", "- ", testo)
        testo = re.sub(r"\n\* +", "\n- ", testo)
        testo = testo.replace("**", "")  # grassetto
        self._inizio_riga = testo.endswith("\n")
        return testo

    def fine(self) -> str:
        """Fine della risposta: gli asterischi rimasti in sospeso (un "**" isolato sparisce)."""
        resto, self._sospeso = self._sospeso.replace("**", ""), ""
        self._inizio_riga = True
        return resto


RISPOSTE_SI = {"s", "si", "sì"}  # uniche risposte che confermano un'eliminazione


def risposta_affermativa(testo: str) -> bool:
    """Vero solo per "s", "si" o "sì" (senza spazi esterni e maiuscole): tutto il resto e' no."""
    return testo.strip().lower() in RISPOSTE_SI


def _testo_della_nota(note_id, strumenti: list) -> str | None:
    """Testo della nota `note_id` letto con il tool list_notes (le 50 piu' recenti).

    La CLI non importa mcp_note/: usa lo stesso tool del modello. Nota non trovata o errore
    -> None (la domanda mostrera' solo l'ID)."""
    elenco = next((t for t in strumenti if t.name == "list_notes"), None)
    if elenco is None:
        return None
    try:
        testo = str(elenco.invoke({"limit": 50}))
        prima_riga = testo.split("\n")[0]  # la riga "Mostrate N di M" non serve
        if not prima_riga.startswith("Note: "):  # "Nessuna nota salvata." o un errore
            return None
        note = json.loads(prima_riga.removeprefix("Note: "))
        cercato = int(str(note_id).strip())  # il modello puo' passare "3" come stringa
    except Exception:  # elenco non disponibile o non leggibile: si chiede solo con l'ID
        return None
    return next((n["testo"] for n in note if n.get("id") == cercato), None)


def domanda_conferma(nome: str, argomenti: dict, strumenti: list) -> str:
    """Testo della domanda (s/n) prima di un tool distruttivo."""
    if nome == "delete_note":
        note_id = str(argomenti.get("note_id", "?")).strip()
        testo = _testo_della_nota(note_id, strumenti)
        if testo is not None:
            return f'Eliminare la nota {note_id} "{testo}"? (s/n) '
        return f"Eliminare la nota {note_id}? (s/n) "
    # altri tool distruttivi futuri: nome e argomenti cosi' come li ha passati il modello
    return f"Eseguire {nome} con {argomenti}? (s/n) "


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
         attesa: Attesa | None = None, strumenti=STRUMENTI,
         system_prompt: str = SYSTEM_PROMPT) -> None:
    nuova_risposta = [True]
    if attesa is None:
        attesa = Attesa(scrivi=token_fn)

    markdown = FiltroMarkdown()  # niente asterischi del Markdown nel terminale

    def scrivi_token(testo: str) -> None:
        # l'etichetta esce col primo token, cosi' i log degli strumenti non la spezzano
        if nuova_risposta[0]:
            nuova_risposta[0] = False
            attesa.ferma()
            token_fn(ETICHETTA_ASSISTENTE)
        pulito = markdown.aggiungi(testo)
        if pulito:
            token_fn(pulito)

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

    def conferma(nome: str, argomenti: dict) -> bool:
        """Chiesta dal grafo prima di un tool distruttivo: domanda (s/n) nel terminale."""
        attesa.ferma()  # la riga animata non deve coprire la domanda
        if stream and not nuova_risposta[0]:
            token_fn("\n")  # il testo gia' scritto dal modello resta sulla sua riga
        try:
            risposta = input_fn(domanda_conferma(nome, argomenti, strumenti))
        except (EOFError, KeyboardInterrupt):
            return False  # nessuna risposta = nessuna eliminazione
        return risposta_affermativa(_testo_valido(risposta))

    grafo = build_graph(llm, max_steps, on_token=scrivi_token if stream else None,
                        strumenti=strumenti, system_prompt=system_prompt, conferma=conferma)
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
            markdown.fine()  # nuova domanda: niente asterischi in sospeso da una risposta interrotta
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
            except APIError as errore:
                # errore senza codice HTTP, es. arrivato durante lo streaming
                # ("Context size has been exceeded."): la sessione continua
                if stream and not nuova_risposta[0]:
                    token_fn("\n")  # chiude la riga del testo parziale
                output_fn(_messaggio_errore_generico(errore))
                continue
            risposta = out["messages"][-1].content
            if history:
                cronologia = out["messages"]
            if stream:
                if not nuova_risposta[0]:
                    resto = markdown.fine()  # asterischi rimasti in sospeso
                    if resto:
                        token_fn(resto)
                    token_fn("\n")  # il testo e' gia' stato scritto token per token
            else:
                # risposta in blocco: stesso filtro, in una volta sola
                output_fn(ETICHETTA_ASSISTENTE + markdown.aggiungi(risposta) + markdown.fine())
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


def carica_strumenti() -> list:
    """I 4 strumenti locali e HTTP piu' i tool scoperti dai server MCP (catalogo e note).
    Un server MCP che non parte stampa un avviso; l'agente continua con gli altri strumenti."""
    return list(STRUMENTI) + carica_tutti_mcp()


def avvia() -> None:
    """Punto d'ingresso: legge la configurazione dall'ambiente e avvia il ciclo."""
    from app.config import load_settings
    from app import llm

    imposta_log()
    try:
        impostazioni = load_settings()
    except ValueError as errore:
        raise SystemExit(f"Configurazione non valida: {errore}")
    strumenti = carica_strumenti()
    print("Strumenti: " + ", ".join(t.name for t in strumenti))
    main(llm=llm.build_llm(impostazioni, strumenti), max_steps=impostazioni.max_steps,
         strumenti=strumenti)


if __name__ == "__main__":
    avvia()
