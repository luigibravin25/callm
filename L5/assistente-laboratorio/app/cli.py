import json  # per leggere l'elenco delle note restituito da list_notes
import logging
import re  # per riconoscere gli elenchi Markdown nelle risposte
import sys
import threading
from contextlib import contextmanager  # per log_con_attesa (with ...: e ripristino alla fine)

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

    @property
    def in_corso(self) -> bool:
        """Vero se i puntini si stanno muovendo (thread dell'animazione avviato)."""
        return self._thread is not None

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
        self._ultimo = ""  # ultimo carattere gia' scritto (per riconoscere le potenze 2**10)

    def _togli_grassetto(self, testo: str) -> str:
        """Toglie i "**" del grassetto ma non quelli delle potenze: un "**" tra un operando
        (cifra o ")") e un altro operando (cifra o "(") resta, es. 2**10, (1+2)**2."""
        pezzi, inizio = [], 0
        for trovato in re.finditer(r"\*\*", testo):
            i, j = trovato.start(), trovato.end()
            prima = testo[i - 1] if i > 0 else self._ultimo
            dopo = testo[j] if j < len(testo) else ""
            pezzi.append(testo[inizio:i])
            if (prima.isdigit() or prima == ")") and (dopo.isdigit() or dopo == "("):
                pezzi.append("**")  # potenza: si lascia
            inizio = j
        pezzi.append(testo[inizio:])
        return "".join(pezzi)

    def aggiungi(self, testo: str) -> str:
        """Riceve un pezzo di testo e restituisce la parte gia' ripulita da scrivere."""
        testo = self._sospeso + testo
        senza_finali = testo.rstrip("*")
        self._sospeso = testo[len(senza_finali):]  # es. "*" o "**" in fondo al pezzo
        testo = senza_finali
        if not testo:
            return ""
        # elenchi: "* " a inizio riga (anche all'inizio del pezzo, se la riga e' appena iniziata)
        # (anche annidati: "  * voce" diventa "  - voce", il rientro resta)
        if self._inizio_riga and re.match(r"[ \t]*\* +", testo):
            testo = re.sub(r"^([ \t]*)\* +", r"\1- ", testo)
        testo = re.sub(r"\n([ \t]*)\* +", r"\n\1- ", testo)
        testo = self._togli_grassetto(testo)  # grassetto (le potenze restano)
        self._inizio_riga = testo.endswith("\n")
        if testo:
            self._ultimo = testo[-1]
        return testo

    def fine(self) -> str:
        """Fine della risposta: gli asterischi rimasti in sospeso (un "**" isolato sparisce)."""
        resto, self._sospeso = self._sospeso.replace("**", ""), ""
        self._inizio_riga = True
        self._ultimo = ""
        return resto


# frasi intere che confermano un'eliminazione (elenco concordato con l'utente il 2026-11-06);
# valgono anche precedute da "sì" ("sì vai", "sì, va bene"). Tutto il resto e' no.
RISPOSTE_SI = {"s", "si", "ok", "okay", "certo", "va bene", "d'accordo", "vai", "procedi",
               "conferma", "confermo", "elimina", "elimina pure", "cancella", "cancella pure",
               "esatto"}
# dopo "sì" vale anche "grazie" ("sì grazie"), che da solo non e' una conferma
_DOPO_SI = RISPOSTE_SI | {"grazie"}
# parole di dubbio o di rifiuto: anche insieme a un sì ("sì ma aspetta") la risposta e' no
PAROLE_DI_DUBBIO = {"no", "non", "ma", "però", "pero", "aspetta", "annulla", "lascia", "stare",
                    "forse", "anzi", "ferma"}


def risposta_affermativa(testo: str) -> bool:
    """Vero solo se la risposta e' una frase dell'elenco dei sì (anche preceduta da "sì").

    Maiuscole, spazi e punteggiatura non contano; una parola di dubbio o di rifiuto rende
    la risposta no. Il codice non cerca un sì dentro frasi lunghe: nel dubbio non cancella."""
    # 1. minuscole, "sì" -> "si", punteggiatura tolta ("Sì, va bene!" -> "si va bene")
    norma = testo.strip().lower().replace("sì", "si")
    parole = re.sub(r"[.,;:!?]", " ", norma).split()
    # 2. una parola di dubbio basta per dire no
    if not parole or any(p in PAROLE_DI_DUBBIO for p in parole):
        return False
    frase = " ".join(parole)
    if frase in RISPOSTE_SI:
        return True  # es. "ok", "va bene", "elimina pure"
    # 3. "sì" seguito da una frase dell'elenco: "si vai", "si grazie", "si va bene"
    return parole[0] in ("s", "si") and " ".join(parole[1:]) in _DOPO_SI


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
    """Domanda colloquiale, detta dall'assistente, prima di un tool distruttivo.

    La frase la scrive il codice (numero e testo della nota sono sempre quelli veri); la
    risposta dell'utente la legge risposta_affermativa."""
    if nome == "delete_note":
        note_id = str(argomenti.get("note_id", "?")).strip()
        testo = _testo_della_nota(note_id, strumenti)
        if testo is not None:
            return f'Vuoi che elimini la nota {note_id} "{testo}"? Rispondimi sì o no.'
        return f"Vuoi che elimini la nota {note_id}? Rispondimi sì o no."
    # altri tool distruttivi futuri: nome e argomenti cosi' come li ha passati il modello
    return f"Vuoi che esegua {nome} con {argomenti}? Rispondimi sì o no."


class _GestoreConAttesa(logging.Handler):
    """Gestore di log che avvolge quelli veri: ogni log ([app.graph], [httpx], [httpx2]...)
    esce su una riga sua, senza mescolarsi con la riga animata 'Assistente: ...'."""

    def __init__(self, attesa: Attesa, gestori: list):
        super().__init__()
        self._attesa = attesa  # l'animazione dei puntini da fermare
        self._gestori = gestori  # i gestori veri (es. quello di basicConfig su stderr)

    def emit(self, record: logging.LogRecord) -> None:
        # le finte usate nei test possono non avere in_corso: si considerano ferme
        in_corso = getattr(self._attesa, "in_corso", False)
        # 1. cancella la riga dei puntini, cosi' il log parte da inizio riga
        self._attesa.ferma()
        # 2. il log passa ai gestori veri, rispettando il loro livello (come fa logging)
        for gestore in self._gestori:
            if record.levelno >= gestore.level:
                gestore.handle(record)
        # 3. il modello sta ancora ragionando: i puntini ripartono sulla riga dopo il log.
        #    Se erano fermi (es. la risposta e' gia' iniziata) restano fermi.
        if in_corso:
            self._attesa.avvia()


def _installa_gestore_con_attesa(attesa: Attesa) -> list:
    """Mette _GestoreConAttesa al posto dei gestori della radice; restituisce quelli di prima.

    I log di app.graph, httpx e httpx2 arrivano alla radice (propagate), quindi basta
    cambiare i suoi gestori."""
    radice = logging.getLogger()
    gestori = radice.handlers[:]  # copia: questa lista va rimessa alla fine
    radice.handlers = [_GestoreConAttesa(attesa, gestori)]
    return gestori


@contextmanager
def log_con_attesa(attesa: Attesa):
    """Come _installa_gestore_con_attesa, dentro un with: alla fine tornano i gestori di prima."""
    gestori = _installa_gestore_con_attesa(attesa)
    try:
        yield
    finally:
        logging.getLogger().handlers = gestori  # anche con errori o Ctrl+C


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
                # dopo il risultato di uno strumento (anche un errore o un'eliminazione
                # annullata) il modello ragiona di nuovo: l'animazione riparte
                if nuova_risposta[0] and isinstance(ultimo, ToolMessage):
                    attesa.avvia()
        finally:
            attesa.ferma()  # anche con errori o Ctrl+C: la riga animata sparisce
        return stato

    def conferma(nome: str, argomenti: dict) -> bool:
        """Chiesta dal grafo prima di un tool distruttivo: domanda dell'assistente e risposta
        dell'utente alla riga "Tu: " (sì solo con le frasi di RISPOSTE_SI)."""
        attesa.ferma()  # la riga animata non deve coprire la domanda
        if stream and not nuova_risposta[0]:
            resto = markdown.fine()  # asterischi in sospeso del testo gia' scritto
            token_fn(resto + "\n")  # il testo gia' scritto dal modello resta sulla sua riga
        # come in una chat: dopo la risposta dell'utente il modello parla di nuovo, quindi la
        # sua prossima frase riparte con l'etichetta "Assistente: " (e i puntini d'attesa)
        nuova_risposta[0] = True
        # la domanda la dice l'assistente, sulla sua riga; l'utente risponde a "Tu: "
        output_fn(ETICHETTA_ASSISTENTE + domanda_conferma(nome, argomenti, strumenti))
        try:
            risposta = input_fn(PROMPT_UTENTE)
        except (EOFError, KeyboardInterrupt):
            return False  # nessuna risposta = nessuna eliminazione
        return risposta_affermativa(_testo_valido(risposta))

    grafo = build_graph(llm, max_steps, on_token=scrivi_token if stream else None,
                        strumenti=strumenti, system_prompt=system_prompt, conferma=conferma)
    # ogni log (grafo, httpx, httpx2) ferma i puntini, esce su una riga sua e li fa ripartire;
    # i gestori di prima si rimettono nel finally in fondo
    gestori_di_prima = _installa_gestore_con_attesa(attesa)
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
        logging.getLogger().handlers = gestori_di_prima  # log di nuovo ai gestori veri
        attesa.ferma()


def imposta_log(log_http: bool = LOG_HTTP, log_grafo: bool = LOG_GRAFO) -> None:
    """Un logger spento resta muto (CRITICAL); acceso mostra il livello INFO."""
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    livello_http = logging.INFO if log_http else logging.CRITICAL
    for nome in ("httpx", "httpx2"):
        logging.getLogger(nome).setLevel(livello_http)
    logging.getLogger("app.graph").setLevel(logging.INFO if log_grafo else logging.CRITICAL)


def carica_strumenti() -> list:
    """I 4 strumenti locali e HTTP piu' i tool scoperti dai server MCP (catalogo, note, meteo).
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
