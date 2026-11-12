# agente finto per i test del back-end: risponde a POST /chat come l'agente dello step 6
import json

import httpx

from app.client_agente import ClientAgente

URL_AGENTE = "http://agente.finto:8000"


# agente finto per httpx.MockTransport: risposte programmate, corpi ricevuti registrati
class AgenteFinto:
    def __init__(self, risposte=None):
        # ogni elemento: (codice, corpo) | eccezione da sollevare | funzione richiesta -> (codice, corpo)
        self.risposte = list(risposte or [])
        self.corpi = []  # corpi JSON ricevuti da POST /chat
        self.percorsi = []  # percorsi chiamati

    def __call__(self, richiesta: httpx.Request) -> httpx.Response:
        self.percorsi.append((richiesta.method, richiesta.url.path))
        self.corpi.append(json.loads(richiesta.content))
        risposta = self.risposte.pop(0)
        if isinstance(risposta, BaseException):
            # le eccezioni di rete di httpx vogliono la richiesta
            if isinstance(risposta, httpx.RequestError):
                risposta.request = richiesta
            raise risposta
        if callable(risposta):
            risposta = risposta(richiesta)
        codice, corpo = risposta
        if isinstance(corpo, str):
            return httpx.Response(codice, text=corpo)
        return httpx.Response(codice, json=corpo)


# risposta 200 di POST /chat con i campi dell'agente (categoria e argomento compresi)
def risposta_ok(testo, cronologia=None, riassunto="", strumenti=None):
    return (200, {"risposta": testo, "strumenti_usati": strumenti or [],
                  "categoria": "conversazione", "argomento": "ora_data_fusi",
                  "cronologia": cronologia if cronologia is not None else [
                      {"role": "user", "content": "domanda"},
                      {"role": "assistant", "content": testo}],
                  "riassunto": riassunto})


# client vero del back-end collegato all'agente finto
def client_finto(agente, timeout=5):
    return ClientAgente(URL_AGENTE, timeout, transport=httpx.MockTransport(agente))
