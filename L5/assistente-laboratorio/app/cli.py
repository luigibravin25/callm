# librerie standard: JSON, log, espressioni regolari, terminale, thread per l'animazione
import json  # per leggere l'elenco delle note restituito da list_notes
import logging
import re  # per riconoscere gli elenchi Markdown nelle risposte
import sys
import threading
from contextlib import contextmanager  # per log_con_attesa (with ...: e ripristino alla fine)

# messaggi della conversazione e gli errori che il client OpenAI solleva verso LM Studio
from langchain_core.messages import HumanMessage, ToolMessage
from openai import APIConnectionError, APIError, APIStatusError

# parti del progetto: server MCP, grafo, interruttori e prompt, strumenti locali
from app.adattatore_mcp import carica_tutti_mcp
from app.graph import build_graph
from app.llm import HISTORY, LOG_GRAFO, LOG_HTTP, STREAM, SYSTEM_PROMPT
from app.tools import STRUMENTI

# messaggio mostrato quando LM Studio non risponde affatto
MSG_CONNESSIONE = (
    "Impossibile raggiungere LM Studio. Controlla che il server sia avviato "
    "e che LM_BASE_URL sia corretto."
)

MAX_DETTAGLIO = 300  # caratteri massimi del messaggio del server: evita muri di testo

# etichette delle righe della chat nel terminale
PROMPT_UTENTE = "Tu: "
ETICHETTA_ASSISTENTE = "Assistente: "


# trasforma un errore HTTP di LM Studio in un messaggio comprensibile
def _messaggio_errore_http(errore: APIStatusError) -> str:
    """Codice di stato, testo del server e, dove serve, un suggerimento."""
    # split/join riduce a capo e spazi multipli a uno spazio solo
    dettaglio = " ".join(str(errore.message).split())
    if len(dettaglio) > MAX_DETTAGLIO:
        dettaglio = dettaglio[:MAX_DETTAGLIO] + "..."
    testo = (f"Il server di LM Studio ha risposto con errore {errore.status_code}: "
             f"{dettaglio}")
    # per i due errori piu' comuni si aggiunge cosa controllare
    if errore.status_code == 400:
        testo += (" Potrebbe dipendere dal template di prompt del modello o dalla "
                  "gestione degli strumenti in LM Studio (vedi docs/DIAGNOSI.md).")
    elif errore.status_code == 404:
        testo += " Controlla che il modello sia caricato e che LM_MODEL sia corretto."
    return testo


# come sopra, per gli errori di LM Studio che non hanno un codice HTTP
def _messaggio_errore_generico(errore: APIError) -> str:
    """Errore di LM Studio senza codice HTTP; per il contesto pieno, cosa fare."""
    dettaglio = " ".join(str(errore.message).split())[:MAX_DETTAGLIO]
    testo = f"Errore da LM Studio: {dettaglio}"
    # la parola "context" indica che la conversazione e' diventata troppo lunga
    if "context" in dettaglio.lower():
        testo += (" La conversazione ha superato il contesto del modello: aumenta la Context "
                  "Length del modello in LM Studio, oppure scrivi 'exit' e riparti con una "
                  "cronologia vuota.")
    return testo


# ripulisce il testo digitato nel terminale dai caratteri che non si possono inviare
def _testo_valido(testo: str) -> str:
    """Python legge i byte non UTF-8 del terminale come surrogati (U+DCC3 per il byte 0xC3):
    il JSON della richiesta non li puo' codificare. Si sostituiscono con U+FFFD invece di
    far cadere l'app."""
    # surrogateescape riporta i surrogati ai byte originali; "replace" mette U+FFFD sui non validi
    return testo.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


# scrive un pezzo di risposta senza andare a capo; flush lo mostra subito
def _scrivi_token(testo: str) -> None:
    print(testo, end="", flush=True)


# animazione dei puntini mentre il modello ragiona
class Attesa:
    """Riga animata 'Assistente: ...' (puntini in movimento) finche' il modello non risponde.
    Attiva solo su un terminale: in pipe (es. docker compose run -T) resta muta."""

    # prepara l'animazione senza avviarla
    def __init__(self, scrivi=_scrivi_token, intervallo: float = 0.4, attiva=None):
        self._scrivi = scrivi  # funzione che scrive sul terminale (sostituibile nei test)
        self._intervallo = intervallo  # secondi tra un fotogramma e l'altro
        # isatty() e' vero solo su un terminale interattivo
        self._attiva = sys.stdout.isatty() if attiva is None else attiva
        self._stop = None  # segnale per fermare il thread
        self._thread = None  # thread dell'animazione (None = ferma)

    # ciclo eseguito nel thread: 1, 2, 3 puntini e poi di nuovo 1
    def _ciclo(self, stop: threading.Event) -> None:
        n = 0
        while not stop.is_set():
            n = n % 3 + 1
            # "\r" torna a inizio riga: la riga si riscrive sopra se stessa; gli spazi finali
            # cancellano i puntini del fotogramma precedente
            self._scrivi(f"\r{ETICHETTA_ASSISTENTE}{'.' * n}{' ' * (3 - n)}")
            # attende l'intervallo, ma si sveglia subito se arriva il segnale di stop
            stop.wait(self._intervallo)

    # fa partire i puntini (non fa nulla se e' disattivata o gia' in corso)
    def avvia(self) -> None:
        if not self._attiva or self._thread is not None:
            return
        self._stop = threading.Event()
        # daemon=True: il thread non impedisce al programma di chiudersi
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
        # segnala lo stop e aspetta che il thread finisca davvero
        self._stop.set()
        self._thread.join()
        self._thread = None
        # copre con spazi "Assistente: ..." e torna a inizio riga
        larghezza = len(ETICHETTA_ASSISTENTE) + 3
        self._scrivi("\r" + " " * larghezza + "\r")


# ripulisce le risposte del modello dagli asterischi del Markdown
class FiltroMarkdown:
    """Toglie il Markdown che il terminale mostrerebbe cosi' com'e': il grassetto (**testo**)
    e gli elenchi con l'asterisco a inizio riga ("*   voce" diventa "- voce").

    Funziona anche in streaming, dove "**" puo' arrivare spezzato in due pezzi: gli asterischi
    in fondo a un pezzo restano in sospeso finche' non arriva il pezzo dopo. Un asterisco
    singolo dentro la riga (es. 2*3) resta com'e'.
    """

    # stato del filtro, conservato tra un pezzo di testo e il successivo
    def __init__(self):
        self._sospeso = ""  # asterischi finali non ancora scritti
        self._inizio_riga = True  # il prossimo carattere e' a inizio riga?
        self._ultimo = ""  # ultimo carattere gia' scritto (per riconoscere le potenze 2**10)

    # toglie le coppie di asterischi del grassetto da un pezzo di testo
    def _togli_grassetto(self, testo: str) -> str:
        """Toglie i "**" del grassetto ma non quelli delle potenze: un "**" tra un operando
        (cifra o ")") e un altro operando (cifra o "(") resta, es. 2**10, (1+2)**2."""
        # pezzi: parti di testo da rimettere insieme; inizio: dove riprende il testo dopo "**"
        pezzi, inizio = [], 0
        for trovato in re.finditer(r"\*\*", testo):
            i, j = trovato.start(), trovato.end()
            # carattere prima e dopo "**"; a inizio pezzo vale l'ultimo gia' scritto
            prima = testo[i - 1] if i > 0 else self._ultimo
            dopo = testo[j] if j < len(testo) else ""
            pezzi.append(testo[inizio:i])
            if (prima.isdigit() or prima == ")") and (dopo.isdigit() or dopo == "("):
                pezzi.append("**")  # potenza: si lascia
            inizio = j
        pezzi.append(testo[inizio:])
        return "".join(pezzi)

    # usata a ogni pezzo di risposta (streaming) o una volta sola (risposta in blocco)
    def aggiungi(self, testo: str) -> str:
        """Riceve un pezzo di testo e restituisce la parte gia' ripulita da scrivere."""
        # rimette davanti gli asterischi rimasti in sospeso dal pezzo precedente
        testo = self._sospeso + testo
        # gli asterischi in fondo si tengono da parte: potrebbero essere meta' di un "**"
        senza_finali = testo.rstrip("*")
        self._sospeso = testo[len(senza_finali):]  # es. "*" o "**" in fondo al pezzo
        testo = senza_finali
        if not testo:
            return ""
        # elenchi: "* " a inizio riga (anche all'inizio del pezzo, se la riga e' appena iniziata)
        # (anche annidati: "  * voce" diventa "  - voce", il rientro resta)
        if self._inizio_riga and re.match(r"[ \t]*\* +", testo):
            testo = re.sub(r"^([ \t]*)\* +", r"\1- ", testo)
        # stessa sostituzione per le righe che iniziano dentro il pezzo, dopo un a capo
        testo = re.sub(r"\n([ \t]*)\* +", r"\n\1- ", testo)
        testo = self._togli_grassetto(testo)  # grassetto (le potenze restano)
        # si ricorda come finisce il pezzo, per il controllo del pezzo successivo
        self._inizio_riga = testo.endswith("\n")
        if testo:
            self._ultimo = testo[-1]
        return testo

    # chiude una risposta e riporta il filtro allo stato iniziale
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


# decide se la risposta dell'utente alla domanda di conferma e' un si'
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
    # la frase intera, con un solo spazio tra le parole, si confronta con l'elenco dei si'
    frase = " ".join(parole)
    if frase in RISPOSTE_SI:
        return True  # es. "ok", "va bene", "elimina pure"
    # 3. "sì" seguito da una frase dell'elenco: "si vai", "si grazie", "si va bene"
    return parole[0] in ("s", "si") and " ".join(parole[1:]) in _DOPO_SI


# recupera il testo della nota da eliminare, per mostrarlo nella domanda di conferma
def _testo_della_nota(note_id, strumenti: list) -> str | None:
    """Testo della nota `note_id` letto con il tool list_notes (le 50 piu' recenti).

    La CLI non importa mcp_note/: usa lo stesso tool del modello. Nota non trovata o errore
    -> None (la domanda mostrera' solo l'ID)."""
    # cerca il tool list_notes tra gli strumenti caricati (manca se il server note non parte)
    elenco = next((t for t in strumenti if t.name == "list_notes"), None)
    if elenco is None:
        return None
    try:
        # chiama il tool direttamente, senza passare dal modello
        testo = str(elenco.invoke({"limit": 50}))
        prima_riga = testo.split("\n")[0]  # la riga "Mostrate N di M" non serve
        if not prima_riga.startswith("Note: "):  # "Nessuna nota salvata." o un errore
            return None
        # dopo "Note: " c'e' l'elenco in JSON: diventa una lista di dizionari
        note = json.loads(prima_riga.removeprefix("Note: "))
        cercato = int(str(note_id).strip())  # il modello puo' passare "3" come stringa
    except Exception:  # elenco non disponibile o non leggibile: si chiede solo con l'ID
        return None
    # testo della prima nota con l'ID cercato; None se non e' tra le 50 lette
    return next((n["testo"] for n in note if n.get("id") == cercato), None)


# scrive la frase con cui l'assistente chiede il permesso di eliminare
def domanda_conferma(nome: str, argomenti: dict, strumenti: list) -> str:
    """Domanda colloquiale, detta dall'assistente, prima di un tool distruttivo.

    La frase la scrive il codice (numero e testo della nota sono sempre quelli veri); la
    risposta dell'utente la legge risposta_affermativa."""
    if nome == "delete_note":
        note_id = str(argomenti.get("note_id", "?")).strip()
        testo = _testo_della_nota(note_id, strumenti)
        # con il testo della nota la domanda e' piu' chiara; senza, resta solo il numero
        if testo is not None:
            return f'Vuoi che elimini la nota {note_id} "{testo}"? Rispondimi sì o no.'
        return f"Vuoi che elimini la nota {note_id}? Rispondimi sì o no."
    # altri tool distruttivi futuri: nome e argomenti cosi' come li ha passati il modello
    return f"Vuoi che esegua {nome} con {argomenti}? Rispondimi sì o no."


# gestore dei log che non fa mescolare i log con i puntini d'attesa
class _GestoreConAttesa(logging.Handler):
    """Gestore di log che avvolge quelli veri: ogni log ([app.graph], [httpx], [httpx2]...)
    esce su una riga sua, senza mescolarsi con la riga animata 'Assistente: ...'."""

    # riceve l'animazione e i gestori a cui passare davvero i log
    def __init__(self, attesa: Attesa, gestori: list):
        super().__init__()
        self._attesa = attesa  # l'animazione dei puntini da fermare
        self._gestori = gestori  # i gestori veri (es. quello di basicConfig su stderr)

    # chiamata da logging per ogni messaggio di log
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


# sostituisce i gestori dei log con _GestoreConAttesa
def _installa_gestore_con_attesa(attesa: Attesa) -> list:
    """Mette _GestoreConAttesa al posto dei gestori della radice; restituisce quelli di prima.

    I log di app.graph, httpx e httpx2 arrivano alla radice (propagate), quindi basta
    cambiare i suoi gestori."""
    radice = logging.getLogger()
    gestori = radice.handlers[:]  # copia: questa lista va rimessa alla fine
    radice.handlers = [_GestoreConAttesa(attesa, gestori)]
    return gestori


# versione da usare con "with": installa il gestore e lo toglie all'uscita
@contextmanager
def log_con_attesa(attesa: Attesa):
    """Come _installa_gestore_con_attesa, dentro un with: alla fine tornano i gestori di prima."""
    gestori = _installa_gestore_con_attesa(attesa)
    try:
        # qui si esegue il codice scritto dentro il blocco with
        yield
    finally:
        logging.getLogger().handlers = gestori  # anche con errori o Ctrl+C


# ciclo della chat: legge le domande, esegue il grafo, mostra le risposte.
# input_fn, output_fn, token_fn e attesa sono parametri per poterli sostituire nei test
def main(input_fn=input, output_fn=print, llm=None, max_steps: int = 5,
         stream: bool = STREAM, token_fn=_scrivi_token, history: bool = HISTORY,
         attesa: Attesa | None = None, strumenti=STRUMENTI,
         system_prompt: str = SYSTEM_PROMPT) -> None:
    # True = l'etichetta "Assistente: " non e' ancora stata scritta per questa risposta.
    # E' una lista di un elemento perche' le funzioni interne possano cambiarne il valore
    nuova_risposta = [True]
    if attesa is None:
        attesa = Attesa(scrivi=token_fn)

    markdown = FiltroMarkdown()  # niente asterischi del Markdown nel terminale

    # riceve dal grafo ogni pezzo della risposta e lo scrive ripulito
    def scrivi_token(testo: str) -> None:
        # l'etichetta esce col primo token, cosi' i log degli strumenti non la spezzano
        if nuova_risposta[0]:
            nuova_risposta[0] = False
            attesa.ferma()
            token_fn(ETICHETTA_ASSISTENTE)
        pulito = markdown.aggiungi(testo)
        if pulito:
            token_fn(pulito)

    # esegue il grafo per una domanda e restituisce lo stato finale
    def invoca(messaggi: list) -> dict:
        """Esegue il grafo passo per passo: dopo uno strumento l'attesa riparte."""
        stato = None
        attesa.avvia()
        try:
            # stream_mode="values": dopo ogni nodo arriva lo stato completo; steps riparte da 0
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

    # funzione passata al grafo: chiede all'utente il si' prima di un'eliminazione
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
        # decide il codice, non il modello
        return risposta_affermativa(_testo_valido(risposta))

    # costruisce il grafo: in streaming gli passa scrivi_token, altrimenti la risposta e' in blocco
    grafo = build_graph(llm, max_steps, on_token=scrivi_token if stream else None,
                        strumenti=strumenti, system_prompt=system_prompt, conferma=conferma)
    # ogni log (grafo, httpx, httpx2) ferma i puntini, esce su una riga sua e li fa ripartire;
    # i gestori di prima si rimettono nel finally in fondo
    gestori_di_prima = _installa_gestore_con_attesa(attesa)
    cronologia = []  # solo in memoria, mai su disco
    output_fn("Scrivi un messaggio ('exit' per uscire).")
    try:
        # un giro per ogni domanda dell'utente
        while True:
            try:
                testo = _testo_valido(input_fn(PROMPT_UTENTE)).strip()
            # fine dell'input (Ctrl+Z / Ctrl+D) o Ctrl+C: si esce dalla chat senza errori
            except (EOFError, KeyboardInterrupt):
                break
            if testo.lower() == "exit":
                break
            # riga vuota: si chiede di nuovo, senza disturbare il modello
            if not testo:
                continue
            nuova_risposta[0] = True
            markdown.fine()  # nuova domanda: niente asterischi in sospeso da una risposta interrotta
            try:
                # il grafo riceve tutta la cronologia piu' la nuova domanda
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
            # l'ultimo messaggio dello stato finale e' la risposta dell'assistente
            risposta = out["messages"][-1].content
            # con HISTORY la cronologia diventa tutta la conversazione, strumenti compresi
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


# accende o spegne i log nel terminale secondo LOG_HTTP e LOG_GRAFO (app/llm.py)
def imposta_log(log_http: bool = LOG_HTTP, log_grafo: bool = LOG_GRAFO) -> None:
    """Un logger spento resta muto (CRITICAL); acceso mostra il livello INFO."""
    # formato: nome del logger tra parentesi quadre, poi il messaggio
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    # richieste HTTP verso LM Studio (httpx e' la libreria usata dal client OpenAI)
    livello_http = logging.INFO if log_http else logging.CRITICAL
    for nome in ("httpx", "httpx2"):
        logging.getLogger(nome).setLevel(livello_http)
    # log del grafo: chiamate agli strumenti, risultati, limite
    logging.getLogger("app.graph").setLevel(logging.INFO if log_grafo else logging.CRITICAL)


# elenco completo degli strumenti dell'agente
def carica_strumenti() -> list:
    """I 4 strumenti locali e HTTP piu' i tool scoperti dai server MCP (catalogo, note, meteo).
    Un server MCP che non parte stampa un avviso; l'agente continua con gli altri strumenti."""
    return list(STRUMENTI) + carica_tutti_mcp()


# avvio del programma (python -m app.cli)
def avvia() -> None:
    """Punto d'ingresso: legge la configurazione dall'ambiente e avvia il ciclo."""
    # import qui dentro: servono solo all'avvio vero, non quando i test importano il modulo
    from app.config import load_settings
    from app import llm

    imposta_log()
    try:
        impostazioni = load_settings()
    except ValueError as errore:
        # SystemExit chiude il programma mostrando solo il messaggio, senza traceback
        raise SystemExit(f"Configurazione non valida: {errore}")
    # avvia i server MCP e scopre i loro tool, poi mostra l'elenco
    strumenti = carica_strumenti()
    print("Strumenti: " + ", ".join(t.name for t in strumenti))
    # il modello riceve gli stessi strumenti che il grafo sapra' eseguire
    main(llm=llm.build_llm(impostazioni, strumenti), max_steps=impostazioni.max_steps,
         strumenti=strumenti)


# eseguito solo se il file e' lanciato come programma, non quando viene importato
if __name__ == "__main__":
    avvia()
