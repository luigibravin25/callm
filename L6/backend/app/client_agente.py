"""Client HTTP del back-end verso l'agente (POST /chat dello step 6).

Il back-end conosce l'agente solo tramite AGENTE_URL e questo contratto. Ogni problema diventa
ErroreAgente(status, errore, messaggio), pronto per la risposta al front-end: agente spento o
lento hanno codici propri; gli errori che l'agente usa per /chat sono inoltrati come sono; tutto
il resto (risposta illeggibile, AGENTE_URL sbagliato) e' 502 risposta_agente_non_valida.
"""
# librerie standard: JSON degli eventi, tipi
import json
import threading
import time
from collections.abc import Iterable, Iterator

# client HTTP sincrono
import httpx
# validazione della risposta dell'agente
from pydantic import BaseModel, ConfigDict, ValidationError

MSG_NON_RAGGIUNGIBILE = "L'agente non è raggiungibile su {url}: è avviato?"
MSG_TIMEOUT = "L'agente non ha risposto entro {secondi} secondi."
MSG_NON_VALIDA = "L'agente ha risposto in modo non valido (codice {status})."
MSG_FLUSSO_INTERROTTO = "Il flusso dell'agente si è interrotto prima della fine della risposta."
MSG_INATTESA = ("L'agente ha risposto in modo inatteso (codice {status}: {messaggio}). "
                "Controllare AGENTE_URL.")

# errori che l'agente restituisce per POST /chat: inoltrati con lo stesso status e corpo
ERRORI_INOLTRATI = frozenset({
    (422, "richiesta_non_valida"), (502, "errore_del_modello"),
    (503, "modello_non_raggiungibile"), (503, "mcp_non_disponibile"),
    (504, "modello_in_timeout"), (500, "errore_interno"),
})


# errore della chiamata all'agente, gia' nella forma della risposta al front-end
class ErroreAgente(Exception):
    def __init__(self, status: int, errore: str, messaggio: str):
        super().__init__(messaggio)
        self.status = status
        self.errore = errore
        self.messaggio = messaggio


# risposta 200 dell'agente: solo i campi che il back-end usa (categoria e argomento ignorati)
class RispostaAgente(BaseModel):
    model_config = ConfigDict(extra="ignore")
    risposta: str
    strumenti_usati: list[dict]
    cronologia: list[dict]
    riassunto: str


# client verso l'agente; `transport` permette ai test di usare un agente finto
class ClientAgente:
    def __init__(self, url: str, timeout: float, transport: httpx.BaseTransport | None = None):
        self.url = url
        self.timeout = timeout
        self._http = httpx.Client(base_url=url, timeout=timeout, transport=transport)

    # un turno: domanda, cronologia e riassunto dell'agente -> risposta validata
    def turno(self, messaggio: str, cronologia: list[dict], riassunto: str) -> RispostaAgente:
        corpo = {"messaggio": messaggio, "cronologia": cronologia, "riassunto": riassunto}
        try:
            risposta = self._http.post("/chat", json=corpo)
        # il timeout prima: e' anche lui un errore di trasporto
        except httpx.TimeoutException:
            raise ErroreAgente(504, "agente_in_timeout",
                               MSG_TIMEOUT.format(secondi=int(self.timeout))) from None
        except httpx.TransportError:
            raise ErroreAgente(503, "agente_non_raggiungibile",
                               MSG_NON_RAGGIUNGIBILE.format(url=self.url)) from None
        # altri errori della richiesta (corpo non decodificabile, troppi redirect): l'agente
        # risponde, ma in modo non valido
        except httpx.RequestError:
            raise ErroreAgente(502, "risposta_agente_non_valida",
                               MSG_NON_VALIDA.format(status="nessuno")) from None
        return self._leggi(risposta)

    # interpreta la risposta: 200 valida, errore dell'agente inoltrato, o 502
    @staticmethod
    def _leggi(risposta: httpx.Response) -> RispostaAgente:
        non_valida = ErroreAgente(502, "risposta_agente_non_valida",
                                  MSG_NON_VALIDA.format(status=risposta.status_code))
        try:
            corpo = risposta.json()
        except ValueError:
            raise non_valida from None
        if risposta.status_code == 200:
            try:
                return RispostaAgente.model_validate(corpo)
            except ValidationError:
                raise non_valida from None
        # errore con il corpo dell'agente {errore, messaggio}
        if (isinstance(corpo, dict) and isinstance(corpo.get("errore"), str)
                and isinstance(corpo.get("messaggio"), str)):
            if (risposta.status_code, corpo["errore"]) in ERRORI_INOLTRATI:
                raise ErroreAgente(risposta.status_code, corpo["errore"], corpo["messaggio"])
            # es. 404 dell'agente con AGENTE_URL sbagliato: non deve sembrare un 404 del back-end
            raise ErroreAgente(502, "risposta_agente_non_valida", MSG_INATTESA.format(
                status=risposta.status_code, messaggio=corpo["messaggio"]))
        raise non_valida

    # lo stesso turno in streaming (step 10): eventi (tipo, dati) dell'agente; "fine" porta la
    # RispostaAgente validata; un evento "errore" dell'agente passa cosi' com'e'. Errori prima dello
    # stream come turno(); connessione persa o stream finito senza fine/errore → 502 flusso_interrotto
    # annullato: impostato quando il browser chiude; si controlla a ogni riga dell'agente (anche i
    # suoi ping ogni 5 s), poi Annullato
    def turno_in_flusso(self, messaggio: str, cronologia: list[dict], riassunto: str,
                        annullato: threading.Event | None = None) -> Iterator[tuple[str, object]]:
        corpo = {"messaggio": messaggio, "cronologia": cronologia, "riassunto": riassunto}
        aperto = False  # True quando l'agente ha risposto 200 e lo stream e' partito
        # AGENTE_TIMEOUT vale per tutto il turno: i ping tengono viva la connessione, ma un turno
        # bloccato (es. un ciclo) non deve restare aperto per sempre
        scadenza = time.monotonic() + self.timeout
        try:
            with self._http.stream("POST", "/chat/stream", json=corpo) as risposta:
                if risposta.status_code != 200:
                    risposta.read()
                    self._leggi(risposta)  # solleva l'ErroreAgente giusto
                aperto = True
                for tipo, dati in leggi_eventi(_controllate(risposta.iter_lines(), annullato,
                                                            scadenza)):
                    if tipo == "fine":
                        try:
                            yield tipo, RispostaAgente.model_validate(dati)
                        except ValidationError:
                            raise ErroreAgente(502, "risposta_agente_non_valida",
                                               MSG_NON_VALIDA.format(status=200)) from None
                        return
                    yield tipo, dati
                    if tipo == "errore":
                        return
        except (httpx.TimeoutException, TempoScaduto):
            raise ErroreAgente(504, "agente_in_timeout",
                               MSG_TIMEOUT.format(secondi=int(self.timeout))) from None
        except ValueError:
            # dati di un evento che non sono JSON: risposta dell'agente non valida
            raise ErroreAgente(502, "risposta_agente_non_valida",
                               MSG_NON_VALIDA.format(status=200)) from None
        except httpx.TransportError:
            if aperto:
                raise ErroreAgente(502, "flusso_interrotto", MSG_FLUSSO_INTERROTTO) from None
            raise ErroreAgente(503, "agente_non_raggiungibile",
                               MSG_NON_RAGGIUNGIBILE.format(url=self.url)) from None
        except httpx.RequestError:
            raise ErroreAgente(502, "risposta_agente_non_valida",
                               MSG_NON_VALIDA.format(status="nessuno")) from None
        # stream finito senza fine ne' errore
        raise ErroreAgente(502, "flusso_interrotto", MSG_FLUSSO_INTERROTTO)

    # chiude le connessioni aperte
    def chiudi(self) -> None:
        self._http.close()


# turno interrotto perche' chi leggeva lo stream (il browser) ha chiuso
class Annullato(Exception):
    pass


# turno oltre AGENTE_TIMEOUT (controllato a ogni riga, ping compresi)
class TempoScaduto(Exception):
    pass


# righe dell'agente con il controllo della chiusura del browser e del tempo massimo a ogni riga
def _controllate(righe: Iterable[str], annullato: threading.Event | None,
                 scadenza: float | None = None) -> Iterator[str]:
    for riga in righe:
        if annullato is not None and annullato.is_set():
            raise Annullato()
        if scadenza is not None and time.monotonic() > scadenza:
            raise TempoScaduto()
        yield riga


# eventi SSE da righe di testo: (tipo, dati JSON); i commenti (": ping") e le righe vuote in piu'
# si ignorano; un blocco finisce con una riga vuota
def leggi_eventi(righe: Iterable[str]) -> Iterator[tuple[str, dict]]:
    tipo, dati = None, []
    for riga in righe:
        riga = riga.rstrip("\r")
        if not riga:
            if tipo is not None:
                yield tipo, json.loads("\n".join(dati) or "{}")
            tipo, dati = None, []
        elif riga.startswith(":"):
            continue
        elif riga.startswith("event:"):
            tipo = riga[len("event:"):].strip()
        elif riga.startswith("data:"):
            dati.append(riga[len("data:"):].strip())
    if tipo is not None:
        yield tipo, json.loads("\n".join(dati) or "{}")
