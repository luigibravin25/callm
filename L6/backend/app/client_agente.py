"""Client HTTP del back-end verso l'agente (POST /chat dello step 6).

Il back-end conosce l'agente solo tramite AGENTE_URL e questo contratto. Ogni problema diventa
ErroreAgente(status, errore, messaggio), pronto per la risposta al front-end: agente spento o
lento hanno codici propri; gli errori che l'agente usa per /chat sono inoltrati come sono; tutto
il resto (risposta illeggibile, AGENTE_URL sbagliato) e' 502 risposta_agente_non_valida.
"""
# client HTTP sincrono
import httpx
# validazione della risposta dell'agente
from pydantic import BaseModel, ConfigDict, ValidationError

MSG_NON_RAGGIUNGIBILE = "L'agente non è raggiungibile su {url}: è avviato?"
MSG_TIMEOUT = "L'agente non ha risposto entro {secondi} secondi."
MSG_NON_VALIDA = "L'agente ha risposto in modo non valido (codice {status})."
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

    # chiude le connessioni aperte
    def chiudi(self) -> None:
        self._http.close()
