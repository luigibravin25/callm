"""Richieste HTTP a Open-Meteo (geocoding e meteo) e traduzione degli errori di trasporto.

Questo modulo non interpreta i dati meteo: invia la richiesta, controlla che la risposta sia
un oggetto JSON e trasforma ogni problema in una categoria di mcp_meteo.errori. La logica di
dominio (previsioni, coordinate) resta nel servizio esterno; la traduzione per l'utente sta in
mcp_meteo.meteo.

Ogni richiesta passa prima dal contatore del limite giornaliero: se il limite e' raggiunto la
richiesta non parte.
"""
# httpx: libreria per le richieste HTTP (sincrone) verso Open-Meteo
import httpx

# categorie di errore in cui si traducono i problemi di rete e di risposta
from mcp_meteo.errori import (ReteNonRaggiungibile, RispostaNonValida, ServizioNonDisponibile,
                              TimeoutMeteo)

URL_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"  # citta' -> coordinate
URL_METEO = "https://api.open-meteo.com/v1/forecast"  # coordinate -> meteo attuale e previsioni
TIMEOUT_S = 5.0  # per richiesta: meglio un errore chiaro che un'attesa lunga
RISULTATI_GEOCODING = 10  # quanti luoghi chiedere: bastano per trovare gli omonimi
PAESE = "IT"  # il meteo e' solo per le citta' italiane: il geocoding cerca solo in Italia
# valori giornalieri richiesti quando servono le previsioni
VALORI_GIORNALIERI = ("weather_code,temperature_2m_max,temperature_2m_min,"
                      "precipitation_probability_max")


# Crea il client HTTP usato per tutte le richieste di una chiamata del tool
def crea_client() -> httpx.Client:
    """Client HTTP con il timeout di 5 secondi (nei test si usa un client finto)."""
    return httpx.Client(timeout=TIMEOUT_S)


# Unico punto da cui partono le richieste: conteggio, invio e traduzione degli errori
def _get(client: httpx.Client, contatore, url: str, params: dict) -> dict:
    """GET verso Open-Meteo: conta la richiesta, la invia, restituisce il JSON (un dict).

    Errori tradotti:
    - timeout (connessione o lettura) -> TimeoutMeteo;
    - altro errore di trasporto (rete assente, DNS) -> ReteNonRaggiungibile;
    - HTTP 429 o >= 500 -> ServizioNonDisponibile;
    - altro HTTP diverso da 200, JSON non valido o non oggetto -> RispostaNonValida.
    """
    contatore.registra()  # prima di partire: limite raggiunto -> LimiteRaggiunto, nessun invio
    try:
        # params diventano la query string dell'URL (es. ?name=Roma&count=10)
        risposta = client.get(url, params=params)
    except httpx.TimeoutException:
        # va prima di TransportError: ConnectTimeout e ReadTimeout sono anche errori di trasporto
        raise TimeoutMeteo(f"il servizio meteo non ha risposto entro {TIMEOUT_S:g} secondi: "
                           "problema di connessione, non riguarda la città.") from None
    except httpx.TransportError as errore:
        # nessuna risposta: rete assente, nome del server non risolto, connessione rifiutata
        raise ReteNonRaggiungibile(f"impossibile collegarsi al servizio meteo ({errore}): "
                                   "problema di connessione, non riguarda la città.") from None
    if risposta.status_code == 429:
        # limite del servizio (anche orario o al minuto): diverso dal limite giornaliero locale
        raise ServizioNonDisponibile("il servizio meteo ha rifiutato per troppe richieste, "
                                     "riprova più tardi.")
    if risposta.status_code >= 500:
        # errori 5xx: problema del server di Open-Meteo, non della richiesta
        raise ServizioNonDisponibile(f"il servizio meteo ha risposto con l'errore HTTP "
                                     f"{risposta.status_code}, riprova più tardi.")
    dati = _json(risposta)  # il corpo letto come JSON (None per un errore HTTP senza JSON)
    if risposta.status_code != 200:
        # es. 400 con {"error": true, "reason": "..."}: la richiesta e' stata rifiutata
        motivo = dati.get("reason") if isinstance(dati, dict) else None
        raise RispostaNonValida(f"HTTP {risposta.status_code}"
                                + (f": {motivo}" if motivo else ""))
    # ci si aspetta un oggetto JSON ({...}): una lista o un numero non vanno bene
    if not isinstance(dati, dict):
        raise RispostaNonValida("la risposta del servizio meteo non è un oggetto JSON.")
    return dati


# Legge il corpo della risposta come JSON, gestendo il caso di testo non JSON
def _json(risposta: httpx.Response):
    """Corpo JSON della risposta; per un errore HTTP senza JSON restituisce None."""
    try:
        return risposta.json()
    except ValueError:  # json.JSONDecodeError e UnicodeDecodeError sono ValueError
        if risposta.status_code != 200:
            return None  # l'errore HTTP verra' segnalato con il suo codice
        raise RispostaNonValida("la risposta del servizio meteo non è JSON valido.") from None


# Prima richiesta del tool: dal nome della citta' alle sue coordinate (geocoding)
def cerca_citta(client: httpx.Client, contatore, nome: str) -> list[dict]:
    """Geocoding: i luoghi italiani che si chiamano `nome` (o iniziano cosi'); [] se nessuno.

    countryCode=IT limita la ricerca all'Italia; language=it da' i nomi di regioni e province
    in italiano.
    """
    dati = _get(client, contatore, URL_GEOCODING,
                {"name": nome, "count": RISULTATI_GEOCODING, "language": "it", "format": "json",
                 "countryCode": PAESE})
    risultati = dati.get("results", [])  # nessuna citta': Open-Meteo omette "results"
    # results deve essere una lista di oggetti (un luogo ciascuno)
    if not isinstance(risultati, list) or not all(isinstance(r, dict) for r in risultati):
        raise RispostaNonValida("il campo results del geocoding non è un elenco di luoghi.")
    return risultati


# Seconda richiesta: meteo attuale (ed eventuali previsioni) per le coordinate trovate
def meteo(client: httpx.Client, contatore, latitudine: float, longitudine: float,
          giorni: int) -> dict:
    """Meteo attuale (temperatura e codice WMO) e, con giorni >= 1, le previsioni giornaliere.

    timezone=auto: ora e date sono quelle locali della citta'.
    """
    # parametri sempre presenti: coordinate e valori del meteo attuale
    params = {"latitude": latitudine, "longitude": longitudine,
              "current": "temperature_2m,weather_code", "timezone": "auto"}
    # le previsioni si chiedono solo se servono (days o date)
    if giorni >= 1:
        params["daily"] = VALORI_GIORNALIERI
        params["forecast_days"] = giorni  # oggi compreso
    return _get(client, contatore, URL_METEO, params)
