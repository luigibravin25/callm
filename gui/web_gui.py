import contextlib
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

import client

HOST, PORT = "127.0.0.1", 8765
WEB_DIR = Path(__file__).parent / "web"
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
ERR = "\x1eERR:"  # marcatore di errore letto da app.js

# stdout è globale: una sola richiesta alla volta può catturarlo
chat_lock = threading.Lock()


class _Writer:
    """File-like: ciò che chat() stampa va subito al browser."""

    def __init__(self, out):
        self.out = out

    def write(self, text):
        if text:
            self.out.write(text.encode("utf-8"))
            self.out.flush()
        return len(text)

    def flush(self):
        pass


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        entry = FILES.get(self.path)
        if not entry:
            self.send_error(404)
            return
        body = (WEB_DIR / entry[0]).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", entry[1])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/chat":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        turns = body["messages"]
        stream = bool(body.get("stream", False))
        messages = [{"role": "system", "content": client.SYSTEM_PROMPT}] + turns

        # Risposta in streaming: la connessione si chiude a fine risposta
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with chat_lock:
            # True = parola per parola, False = risposta tutta insieme
            client.STREAM = stream
            try:
                with contextlib.redirect_stdout(_Writer(self.wfile)):
                    client.chat(messages)
            except requests.RequestException as e:
                self.wfile.write((ERR + str(e)).encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass  # pagina chiusa durante la risposta

    def log_message(self, *args):
        pass  # niente log delle richieste nel terminale


def run():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Interfaccia su {url}  (Ctrl+C per tornare al menu)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
