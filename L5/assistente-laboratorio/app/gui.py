# Interfaccia grafica (pagina web locale) per l'agente di L5 con tutti i suoi strumenti.
#
# Avvio, da assistente-laboratorio/ con le stesse variabili d'ambiente della CLI:
#     & ..\venv\Scripts\python.exe -m app.gui
#
# Il server usa solo la libreria standard (http.server): nessuna dipendenza in piu'.
# Ogni risposta a POST /chat e' un flusso di righe JSON (una per evento):
#     {"t": "token",   "v": testo}     pezzo di risposta (solo in streaming)
#     {"t": "tool",    "v": {"nome": ..., "icona": ...}}  il modello sta usando uno strumento
#     {"t": "confirm", "v": domanda}   serve un si'/no dell'utente (risposta con POST /confirm)
#     {"t": "error",   "v": messaggio} errore da mostrare
#     {"t": "done",    "v": testo}     risposta finale completa
# librerie standard: JSON, code tra thread, lock, browser, server HTTP, percorsi
import json
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# messaggi della conversazione e gli errori che il client OpenAI solleva verso LM Studio
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIConnectionError, APIError, APIStatusError

# parti del progetto riusate dalla CLI: messaggi d'errore, filtro Markdown, conferma, strumenti
from app.cli import (MSG_CONNESSIONE, FiltroMarkdown, _messaggio_errore_generico,
                     _messaggio_errore_http, carica_strumenti, domanda_conferma, imposta_log,
                     risposta_affermativa)
from app.graph import build_graph

# indirizzo del server locale (solo questo computer)
HOST, PORT = "127.0.0.1", 8765
# cartella con index.html, style.css e app.js
WEB_DIR = Path(__file__).parent / "web"
# percorso richiesto dal browser -> (file, tipo di contenuto)
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
ATTESA_CONFERMA = 300  # secondi massimi per rispondere alla domanda di conferma; poi e' un no

# icone per gruppo: gli strumenti dello stesso servizio (catalogo, note) hanno la stessa icona
ICONA_CATALOGO = "\U0001F6D2"  # carrello
ICONA_NOTE = "\U0001F4DD"  # blocco note
ICONA_PREDEFINITA = "\U0001F527"  # chiave inglese, per uno strumento nuovo senza voce

# nome e icona mostrati nella pagina al posto dei nomi interni degli strumenti; i nomi
# interni restano invariati perche' sono quelli che il modello usa nelle chiamate
STRUMENTI_PAGINA = {
    "tooltime": ("Orologio", "\U0001F552"),  # orologio
    "toolconvert": ("Convertitore di unità", "\U0001F4CF"),  # righello
    "toolcalc": ("Calcolatrice", "\U0001F9EE"),  # abaco
    "tooldate": ("Giorni e scadenze", "\U0001F4C5"),  # calendario
    "search_catalog": ("Ricerca nel catalogo", ICONA_CATALOGO),
    "get_item": ("Dettagli prodotto", ICONA_CATALOGO),
    "add_note": ("Aggiungi nota", ICONA_NOTE),
    "list_notes": ("Elenco note", ICONA_NOTE),
    "delete_note": ("Elimina nota", ICONA_NOTE),
    "get_weather": ("Meteo", "\U0001F324️"),  # sole tra le nuvole
}


# nome leggibile e icona di uno strumento, come li legge app.js
def per_la_pagina(nome: str) -> dict:
    # uno strumento nuovo senza voce mostra il nome interno e la chiave inglese
    leggibile, icona = STRUMENTI_PAGINA.get(nome, (nome, ICONA_PREDEFINITA))
    return {"nome": leggibile, "icona": icona}

# preparati una volta sola all'avvio (avvia): modello, strumenti, limite di passaggi
STATO = {"llm": None, "strumenti": [], "max_steps": 5}
# una sola chat alla volta: i server MCP e la coda della conferma sono condivisi
chat_lock = threading.Lock()
# risposte dell'utente alle domande di conferma (riempita da POST /confirm)
risposte_conferma = queue.Queue()
# vero solo mentre il grafo aspetta un si'/no: altrimenti /confirm viene rifiutata
in_attesa_conferma = threading.Event()


# trasforma i turni mandati dal browser nei messaggi di LangChain
def _messaggi(turni: list) -> list:
    """{"role": "user"|"assistant", "content": ...} -> HumanMessage / AIMessage.
    Il contenuto puo' essere testo o lista di parti (testo + immagini), come lo manda app.js."""
    return [HumanMessage(t["content"]) if t["role"] == "user" else AIMessage(t["content"])
            for t in turni]


class Handler(BaseHTTPRequestHandler):
    # manda un evento al browser: una riga JSON, scritta e spedita subito
    # (valore: testo, oppure {"nome", "icona"} per l'evento "tool")
    def _evento(self, tipo: str, valore) -> None:
        riga = json.dumps({"t": tipo, "v": valore}, ensure_ascii=False) + "\n"
        self.wfile.write(riga.encode("utf-8"))
        self.wfile.flush()

    # legge il corpo JSON della richiesta POST
    def _corpo(self) -> dict:
        lunghezza = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(lunghezza) or b"{}")

    # risposta JSON semplice (per /strumenti e /confirm)
    def _json(self, dati, stato: int = 200) -> None:
        corpo = json.dumps(dati, ensure_ascii=False).encode("utf-8")
        self.send_response(stato)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        # elenco dei nomi degli strumenti, mostrato nel menu della pagina
        if self.path == "/strumenti":
            self._json([per_la_pagina(t.name) for t in STATO["strumenti"]])
            return
        # file statici della pagina
        voce = FILES.get(self.path)
        if not voce:
            self.send_error(404)
            return
        corpo = (WEB_DIR / voce[0]).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", voce[1])
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        if self.path == "/chat":
            self._chat()
        elif self.path == "/confirm":
            self._conferma()
        else:
            self.send_error(404)

    # risposta dell'utente alla domanda di conferma: passa al grafo in attesa
    def _conferma(self) -> None:
        if not in_attesa_conferma.is_set():
            self._json({"ok": False, "motivo": "nessuna conferma in attesa"}, 409)
            return
        testo = str(self._corpo().get("answer", ""))
        # decide il codice (stesso elenco di sì della CLI), non il modello
        risposte_conferma.put(risposta_affermativa(testo))
        self._json({"ok": True})

    # esegue il grafo per una domanda e manda gli eventi al browser
    def _chat(self) -> None:
        corpo = self._corpo()
        messaggi = _messaggi(corpo["messages"])
        stream = bool(corpo.get("stream", False))
        markdown = FiltroMarkdown()  # niente asterischi del Markdown, come nel terminale

        # intestazioni: flusso di righe JSON, la connessione si chiude a fine risposta
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # riceve dal grafo ogni pezzo di risposta (solo in streaming) e lo manda ripulito
        def scrivi_token(testo: str) -> None:
            pulito = markdown.aggiungi(testo)
            if pulito:
                self._evento("token", pulito)

        # chiesta dal grafo prima di un tool distruttivo (delete_note): domanda e attesa
        def conferma(nome: str, argomenti: dict) -> bool:
            # asterischi rimasti in sospeso del testo gia' mandato
            resto = markdown.fine()
            if resto:
                self._evento("token", resto)
            # svuota la coda da risposte arrivate fuori tempo
            while not risposte_conferma.empty():
                risposte_conferma.get_nowait()
            in_attesa_conferma.set()
            try:
                self._evento("confirm", domanda_conferma(nome, argomenti, STATO["strumenti"]))
                # aspetta la risposta da POST /confirm; nessuna risposta in tempo = no
                return risposte_conferma.get(timeout=ATTESA_CONFERMA)
            except queue.Empty:
                return False
            finally:
                in_attesa_conferma.clear()

        with chat_lock:
            try:
                grafo = build_graph(STATO["llm"], STATO["max_steps"],
                                    on_token=scrivi_token if stream else None,
                                    strumenti=STATO["strumenti"], conferma=conferma)
                stato = None
                # stream_mode="values": dopo ogni nodo arriva lo stato completo
                for stato in grafo.stream({"messages": messaggi, "steps": 0},
                                          stream_mode="values"):
                    ultimo = stato["messages"][-1]
                    # il modello chiede strumenti: la pagina mostra quali, con nome e icona
                    for chiamata in getattr(ultimo, "tool_calls", None) or []:
                        self._evento("tool", per_la_pagina(chiamata["name"]))
                # l'ultimo messaggio dello stato finale e' la risposta dell'assistente
                risposta = str(stato["messages"][-1].content)
                pulita = FiltroMarkdown()
                self._evento("done", pulita.aggiungi(risposta) + pulita.fine())
            except APIStatusError as errore:
                self._evento("error", _messaggio_errore_http(errore))
            except APIConnectionError:
                self._evento("error", MSG_CONNESSIONE)
            except APIError as errore:
                self._evento("error", _messaggio_errore_generico(errore))
            except (BrokenPipeError, ConnectionResetError):
                pass  # pagina chiusa durante la risposta

    def log_message(self, *args):
        pass  # niente log delle richieste della pagina nel terminale


# avvio del programma (python -m app.gui)
def avvia() -> None:
    """Configurazione dall'ambiente, server MCP, modello; poi il server della pagina."""
    # import qui dentro, come in app.cli: servono solo all'avvio vero
    from app import llm
    from app.config import load_settings

    imposta_log()  # stessi log della CLI nel terminale (HTTP, chiamate agli strumenti)
    try:
        impostazioni = load_settings()
    except ValueError as errore:
        raise SystemExit(f"Configurazione non valida: {errore}")
    # avvia i server MCP e scopre i loro tool, poi mostra l'elenco
    STATO["strumenti"] = carica_strumenti()
    print(f"Strumenti ({len(STATO['strumenti'])}): "
          + ", ".join(t.name for t in STATO["strumenti"]))
    # il modello riceve gli stessi strumenti che il grafo sapra' eseguire
    STATO["llm"] = llm.build_llm(impostazioni, STATO["strumenti"])
    STATO["max_steps"] = impostazioni.max_steps

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Interfaccia su {url}  (Ctrl+C per chiudere)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# eseguito solo se il file e' lanciato come programma, non quando viene importato
if __name__ == "__main__":
    avvia()
