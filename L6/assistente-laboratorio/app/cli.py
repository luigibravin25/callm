"""Chat da terminale, client dell'agente HTTP (step 6).

La CLI non costruisce piu' il grafo: parla con il servizio (python -m app.api) via HTTP.
Cronologia e riassunto stanno solo in memoria (mai su disco) e viaggiano a ogni turno; le righe
che iniziano con "/" sono comandi dei prompt MCP, controllati qui con l'elenco di GET /prompts.
"""
# librerie standard: ambiente, flussi del processo (stdin), thread di lavoro per la chiamata
import os
import sys
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as AttesaScaduta

# client HTTP verso l'agente
import httpx

# comandi dei prompt (step 5), tipi dei prompt, conversione del JSON di /prompts, log
from app.comandi import RichiestaPrompt, interpreta
from app.info_prompt import InfoPrompt
from app.log import LOG_HTTP, configura_log
from app.schemi import a_info

AGENTE_URL_PREDEFINITO = "http://127.0.0.1:8000"
AGENTE_TIMEOUT_PREDEFINITO = 300  # secondi: un turno con revisioni puo' durare minuti

# messaggi fissi della chat
MSG_INIZIO = "Scrivi un messaggio, /prompts per i prompt, 'esci' per uscire."
MSG_ATTESA = "(attendi la risposta...)"
MSG_PROMPT = "(prompt {nome} chiesto all'agente)"
MSG_AGENTE_NON_RAGGIUNGIBILE = ("Impossibile raggiungere l'agente su {url}. Avvialo in un altro "
                                "terminale con: & ..\\venv\\Scripts\\python.exe -m app.api")
MSG_RISPOSTA_NON_VALIDA = "L'agente ha risposto con il codice {codice} senza un messaggio leggibile."
MSG_STATO = "(attenzione: {parte} non pronto: {messaggio})"
COMANDI_USCITA = {"esci", "exit"}  # maiuscole indifferenti

# etichette delle righe della chat nel terminale
PROMPT_UTENTE = "Tu: "
ETICHETTA_ASSISTENTE = "Assistente: "


# errore della chiamata all'agente, con il messaggio da mostrare all'utente
class ErroreAgente(Exception):
    def __init__(self, messaggio: str):
        super().__init__(messaggio)
        self.messaggio = messaggio


# client dell'API dell'agente: tre chiamate, errori trasformati in ErroreAgente
class ClientAgente:
    def __init__(self, url: str, timeout: float, transport: httpx.BaseTransport | None = None):
        self.url = url
        # transport: i test passano un agente finto (httpx.MockTransport)
        self._http = httpx.Client(base_url=url, timeout=timeout, transport=transport)

    # una richiesta all'agente: rete e timeout diventano ErroreAgente (KeyboardInterrupt sale)
    def _chiama(self, metodo: str, percorso: str, **opzioni) -> httpx.Response:
        try:
            return self._http.request(metodo, percorso, **opzioni)
        except httpx.HTTPError:
            raise ErroreAgente(MSG_AGENTE_NON_RAGGIUNGIBILE.format(url=self.url)) from None

    # corpo JSON di una risposta; errore con {errore, messaggio} -> ErroreAgente(messaggio)
    @staticmethod
    def _json(risposta: httpx.Response, codici_ok=(200,)) -> dict | list:
        try:
            corpo = risposta.json()
        except ValueError:
            corpo = None
        if risposta.status_code in codici_ok and corpo is not None:
            return corpo
        if isinstance(corpo, dict) and isinstance(corpo.get("messaggio"), str):
            raise ErroreAgente(corpo["messaggio"])
        raise ErroreAgente(MSG_RISPOSTA_NON_VALIDA.format(codice=risposta.status_code))

    # GET /stato: 200 o 503 hanno lo stesso corpo (cosa e' pronto e cosa no)
    def stato(self) -> tuple[int, dict]:
        risposta = self._chiama("GET", "/stato")
        return risposta.status_code, self._json(risposta, codici_ok=(200, 503))

    # GET /prompts: elenco dei prompt per i comandi
    def prompts(self) -> list[InfoPrompt]:
        return [a_info(p) for p in self._json(self._chiama("GET", "/prompts"))]

    # POST /chat: un turno
    def chat(self, corpo: dict) -> dict:
        return self._json(self._chiama("POST", "/chat", json=corpo))


# toglie i caratteri non validi e i BOM iniziali da una riga letta dal terminale o da una pipe
def _testo_valido(testo: str) -> str:
    # surrogateescape riporta i surrogati ai byte originali; "replace" mette U+FFFD sui non validi
    testo = testo.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    # BOM iniziali (pipe di PowerShell, anche due): senza toglierli "esci" e "/prompts" non si
    # riconoscono
    return testo.lstrip("﻿")


# esegue funzione(*argomenti) in un thread daemon e restituisce il Future del risultato.
# Daemon: all'uscita dopo un Ctrl+C Python non aspetta la chiamata ancora in corso (i thread di
# ThreadPoolExecutor invece verrebbero attesi, e l'uscita arriverebbe solo con la risposta)
def _in_sottofondo(funzione, *argomenti) -> Future:
    futuro = Future()

    # corpo del thread: risultato o eccezione passati al Future
    def esegui():
        try:
            futuro.set_result(funzione(*argomenti))
        except BaseException as errore:
            futuro.set_exception(errore)
    threading.Thread(target=esegui, daemon=True).start()
    return futuro


# attende il risultato della chiamata a intervalli brevi: tra un intervallo e l'altro il thread
# principale puo' ricevere Ctrl+C (su Windows una lettura di rete bloccata non lo riceve)
def _attendi(futuro: Future, intervallo: float = 0.2):
    while True:
        try:
            return futuro.result(timeout=intervallo)
        except AttesaScaduta:
            continue


# avvio: stato dell'agente (avvisi per cio' che non e' pronto) ed elenco dei prompt
def _avvio(client: ClientAgente, output_fn) -> list[InfoPrompt] | None:
    """Restituisce l'elenco dei prompt, o None se l'agente non risponde."""
    try:
        _, stato = client.stato()
        for parte in ("modello", "mcp"):
            dati = stato.get(parte, {})
            if dati.get("stato") != "ok":
                output_fn(MSG_STATO.format(parte=parte, messaggio=dati.get("messaggio", "")))
        return client.prompts()
    except ErroreAgente as errore:
        output_fn(errore.messaggio)
        return None
    # Ctrl+C durante l'avvio (/stato puo' durare qualche secondo): uscita pulita, niente traceback
    except KeyboardInterrupt:
        return None


# ciclo della chat: una domanda alla volta, cronologia solo in memoria
def main(client: ClientAgente, input_fn=input, output_fn=print) -> None:
    """Chat da terminale con l'agente HTTP. Le righe che iniziano con "/" sono comandi:
    /prompts mostra l'elenco, /prompt chiede all'agente di usare un prompt del server MCP."""
    prompts = _avvio(client, output_fn)
    if prompts is None:
        return  # agente non raggiungibile: il messaggio dice come avviarlo
    cronologia = []  # messaggi nel formato OpenAI, solo in memoria
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
            continue  # riga vuota: si chiede di nuovo, senza disturbare l'agente
        corpo = {"cronologia": cronologia, "riassunto": riassunto}
        if testo.startswith("/"):
            # elenco riletto a ogni comando: un agente riavviato (es. con il server MCP
            # ripartito) si vede senza riavviare la CLI
            try:
                prompts = client.prompts()
            except ErroreAgente as errore:
                output_fn(errore.messaggio)  # agente spento: nessuna chiamata a /chat
                continue
            except KeyboardInterrupt:
                break
            esito = interpreta(testo, prompts)
            if not isinstance(esito, RichiestaPrompt):
                output_fn(esito)  # elenco o errore del comando: nessuna chiamata
                continue
            output_fn(MSG_PROMPT.format(nome=esito.nome))
            corpo = {"prompt": {"nome": esito.nome, "argomenti": esito.argomenti}, **corpo}
        else:
            corpo = {"messaggio": testo, **corpo}
        output_fn(MSG_ATTESA)
        try:
            # la chiamata gira nel thread di lavoro; il principale attende e resta interrompibile
            risposta = _attendi(_in_sottofondo(client.chat, corpo))
        except ErroreAgente as errore:
            # errore dell'agente o agente spento: cronologia invariata, la chat continua
            output_fn(errore.messaggio)
            continue
        # Ctrl+C durante la chiamata: si esce subito senza traceback; il turno in corso
        # sull'agente finisce da solo e la risposta si scarta
        except KeyboardInterrupt:
            break
        cronologia, riassunto = risposta["cronologia"], risposta["riassunto"]
        output_fn(ETICHETTA_ASSISTENTE + risposta["risposta"])


# legge AGENTE_URL e AGENTE_TIMEOUT (intero > 0)
def leggi_configurazione() -> tuple[str, float]:
    url = os.environ.get("AGENTE_URL", "").strip() or AGENTE_URL_PREDEFINITO
    grezzo = os.environ.get("AGENTE_TIMEOUT", str(AGENTE_TIMEOUT_PREDEFINITO)).strip()
    if not grezzo.isdigit() or int(grezzo) <= 0:
        raise SystemExit(f"Configurazione non valida: AGENTE_TIMEOUT deve essere un intero "
                         f"maggiore di 0, trovato: {grezzo!r}")
    return url.rstrip("/"), int(grezzo)


# avvio del programma (python -m app.cli)
def avvia(input_fn=input, output_fn=print) -> None:
    """Legge la configurazione, accende i log delle richieste verso l'agente e avvia la chat."""
    url, timeout = leggi_configurazione()
    # richieste HTTP verso l'agente visibili con LOG_HTTP; httpcore (dettagli interni) spento
    configura_log(("httpx",) if LOG_HTTP else (), spenti=("httpcore",) if LOG_HTTP
                  else ("httpx", "httpcore"))
    # input da una pipe (non da tastiera): letto sempre in UTF-8, cosi' il BOM e gli accenti
    # arrivano giusti anche senza PYTHONIOENCODING (Windows altrimenti usa cp1252)
    # (stdin senza reconfigure, come quello finto di pytest: si lascia com'e')
    riconfigura = getattr(sys.stdin, "reconfigure", None)
    if riconfigura is not None and not sys.stdin.isatty():
        riconfigura(encoding="utf-8", errors="surrogateescape")
    main(ClientAgente(url, timeout), input_fn=input_fn, output_fn=output_fn)


if __name__ == "__main__":
    avvia()
