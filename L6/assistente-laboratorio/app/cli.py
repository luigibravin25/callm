# librerie standard: log nel terminale, flussi del processo (stdin)
import logging
import sys

# messaggio dell'utente; errori di LM Studio (connessione, HTTP, altri)
from langchain_core.messages import HumanMessage
from openai import APIConnectionError, APIError, APIStatusError

# interruttori dei log (app/llm.py)
from app.llm import LOG_GRAFO, LOG_HTTP
# comandi dei prompt MCP (step 5): lettura delle righe "/..." e messaggio d'errore di prompts/get
from app.comandi import MSG_ERRORE_PROMPT, RichiestaPrompt, interpreta
# preferenze dell'utente in uso nella sessione (step 4)
from app.preferenze import Preferenze

# logger della CLI: avvisi dell'avvio (server MCP non disponibile)
log = logging.getLogger("mcp")

# messaggi fissi della chat
MSG_CONNESSIONE = (
    "Impossibile raggiungere LM Studio. Controlla che il server sia avviato "
    "e che LM_BASE_URL sia corretto."
)
MSG_INIZIO = "Scrivi un messaggio, /prompts per i prompt, 'esci' per uscire."
# riga mostrata quando arrivano i messaggi di un prompt dal server
MSG_PROMPT = "(prompt {nome}: {n} {parola} dal server)"
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
    testo = testo.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    # BOM iniziali (pipe di PowerShell, anche due): senza toglierli "esci" e "/prompts" non si
    # riconoscono
    return testo.lstrip("\ufeff")


# un turno del grafo: cronologia piu' i messaggi nuovi (domanda o prompt). Restituisce cronologia e
# riassunto aggiornati; con un errore di LM Studio li restituisce invariati (i messaggi nuovi non
# entrano nella cronologia). KeyboardInterrupt sale al chiamante.
def _turno(grafo, cronologia: list, nuovi: list, riassunto: str, output_fn) -> tuple[list, str]:
    try:
        # contatori da 0 a ogni turno
        out = grafo.invoke({"messages": cronologia + nuovi, "steps": 0, "revisioni": 0,
                            "riassunto": riassunto})
    except APIStatusError as errore:
        output_fn(_messaggio_errore_http(errore))
        return cronologia, riassunto
    except APIConnectionError:
        output_fn(MSG_CONNESSIONE)
        return cronologia, riassunto
    except APIError as errore:
        output_fn(_messaggio_errore_generico(errore))
        return cronologia, riassunto
    # la cronologia diventa tutta la conversazione, strumenti e rifiuti compresi
    cronologia = out["messages"]
    output_fn(ETICHETTA_ASSISTENTE + str(cronologia[-1].content))
    # il riassunto aggiornato dal grafo passa al turno successivo
    return cronologia, out.get("riassunto", riassunto)


# un comando "/...": testo da mostrare, oppure i messaggi del prompt chiesti al server
def _comando(riga: str, prompts: list, ottieni, output_fn) -> list | None:
    """Restituisce i messaggi del prompt da mandare al grafo, o None se non c'e' nulla da mandare
    (elenco, errore del comando o del server: mai in cronologia, modello mai chiamato)."""
    esito = interpreta(riga, prompts)
    if not isinstance(esito, RichiestaPrompt):
        output_fn(esito)
        return None
    # import qui: l'adattatore si legge come modulo, cosi' i test lo possono sostituire
    from app.adattatore_mcp import ErroreMCP
    try:
        messaggi = ottieni(esito.nome, esito.argomenti)
    except ErroreMCP as errore:
        output_fn(MSG_ERRORE_PROMPT.format(motivo=errore))
        return None
    parola = "messaggio" if len(messaggi) == 1 else "messaggi"
    output_fn(MSG_PROMPT.format(nome=esito.nome, n=len(messaggi), parola=parola))
    return messaggi


# ciclo della chat: una domanda alla volta, cronologia solo in memoria
def main(grafo, input_fn=input, output_fn=print, prompts=None, ottieni=None) -> None:
    """Chat da terminale. Ogni domanda passa dal grafo (router, poi agente o rifiuto); le righe
    che iniziano con "/" sono comandi: /prompts mostra l'elenco, /prompt manda al grafo i messaggi
    del prompt chiesto al server. `prompts` e' l'elenco letto all'avvio (prompts/list); `ottieni`
    chiede un prompt al server (i test passano un finto)."""
    prompts = prompts or []
    if ottieni is None:
        # import qui: serve solo con il server vero
        from app.adattatore_mcp import ottieni_prompt as ottieni
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
        if testo.startswith("/"):
            # comando: i messaggi del prompt vanno al grafo come una domanda
            nuovi = _comando(testo, prompts, ottieni, output_fn)
            if nuovi is None:
                continue
        else:
            nuovi = [HumanMessage(testo)]
        output_fn(MSG_ATTESA)
        try:
            cronologia, riassunto = _turno(grafo, cronologia, nuovi, riassunto, output_fn)
        except KeyboardInterrupt:
            break


# accende o spegne i log nel terminale secondo LOG_HTTP e LOG_GRAFO
def imposta_log(log_http: bool = LOG_HTTP, log_grafo: bool = LOG_GRAFO) -> None:
    # formato: nome del logger tra parentesi quadre, poi il messaggio
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    # un logger spento resta muto (CRITICAL); acceso mostra il livello INFO
    # richieste HTTP verso LM Studio: il client OpenAI usa httpx o httpx2 secondo la versione
    for nome in ("httpx", "httpx2"):
        logging.getLogger(nome).setLevel(logging.INFO if log_http else logging.CRITICAL)
    for nome in ("router", "agente", "rifiuto", "revisore", "riassunto", "mcp", "preferenze"):
        logging.getLogger(nome).setLevel(logging.INFO if log_grafo else logging.CRITICAL)


# all'avvio della sessione: strumenti, preferenze (step 4) ed elenco dei prompt (step 5), una volta
def prepara_agente(fuso_riserva: str) -> tuple[list, Preferenze, list]:
    """tools/list, resources/read e prompts/list una volta; server che non parte: nessuno
    strumento, preferenze predefinite e nessun prompt, con avvisi nei log."""
    # import qui: adattatore_mcp si legge come modulo, cosi' i test lo possono sostituire
    from app import adattatore_mcp
    from app.preferenze import valida
    try:
        strumenti = adattatore_mcp.carica_strumenti()
    except adattatore_mcp.ErroreMCP as errore:
        log.warning("server MCP non disponibile (%s): nessuno strumento", errore)
        # resource e prompt stanno sullo stesso server: niente lettura, valida(None) usa i
        # predefiniti, nessun prompt
        return [], valida(None, fuso_riserva), []
    preferenze = valida(adattatore_mcp.leggi_preferenze(), fuso_riserva)
    return strumenti, preferenze, adattatore_mcp.elenca_prompt()


# avvio del programma (python -m app.cli)
def avvia(input_fn=input, output_fn=print) -> None:
    """Legge configurazione e ambito, avvia il server MCP (strumenti e preferenze), costruisce
    i modelli (agente, router, revisore, riassunto) e il grafo, avvia la chat."""
    # import qui dentro: servono solo all'avvio vero, non quando i test importano il modulo
    from app import llm
    from app.config import load_ambito, load_settings
    from app.graph import build_graph

    imposta_log()
    # input da una pipe (non da tastiera): letto sempre in UTF-8, cosi' il BOM e gli accenti
    # arrivano giusti anche senza PYTHONIOENCODING (Windows altrimenti usa cp1252)
    # (stdin senza reconfigure, come quello finto di pytest: si lascia com'e')
    riconfigura = getattr(sys.stdin, "reconfigure", None)
    if riconfigura is not None and not sys.stdin.isatty():
        riconfigura(encoding="utf-8", errors="surrogateescape")
    try:
        impostazioni = load_settings()
        ambito = load_ambito(impostazioni.ambito_file)
    except ValueError as errore:
        # SystemExit chiude il programma mostrando solo il messaggio, senza traceback
        raise SystemExit(f"Configurazione non valida: {errore}")
    # una sola lettura delle preferenze per sessione, prima di chiamare il modello
    strumenti, preferenze, prompts = prepara_agente(impostazioni.fuso_predefinito)
    grafo = build_graph(llm.build_llm(impostazioni, strumenti), llm.build_router_llm(impostazioni, ambito),
                        llm.build_revisore_llm(impostazioni),
                        llm.build_riassunto_llm(impostazioni),
                        ambito, impostazioni.max_steps, impostazioni.max_revisioni,
                        impostazioni.soglia_riassunto, impostazioni.messaggi_recenti,
                        strumenti=strumenti,
                        system_prompt=llm.prompt_agente(preferenze, bool(strumenti)),
                        fuso_predefinito=preferenze.fuso)
    main(grafo, input_fn=input_fn, output_fn=output_fn, prompts=prompts)


if __name__ == "__main__":
    avvia()
