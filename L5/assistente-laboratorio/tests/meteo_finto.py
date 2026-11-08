"""Client HTTP finto e risposte finte di Open-Meteo per i test del meteo (nessuna rete).

client_finto risponde al posto di Open-Meteo con httpx.MockTransport: per ogni richiesta
sceglie la voce del geocoding o del meteo in base all'host. Una voce puo' essere:
- un dict: risposta 200 con quel JSON;
- un httpx.Response: risposta usata cosi' com'e' (stato, corpo);
- un'eccezione: sollevata come farebbe il trasporto (timeout, rete assente);
- una funzione: chiamata con la richiesta, restituisce la risposta.

I dati imitano le risposte vere del geocoding con countryCode=IT (solo luoghi italiani,
admin1 = regione, admin2 = provincia), viste il 2026-11-05.
"""
import copy  # copie profonde dei dati finti, cosi' un test non sporca gli altri

import httpx  # client HTTP; MockTransport risponde senza rete


# costruisce un luogo come quelli del geocoding vero (solo i campi letti dal server)
def _luogo(nome: str, regione: str, provincia: str | None, abitanti: int | None,
           latitudine: float = 41.9, longitudine: float = 12.5) -> dict:
    """Un luogo del geocoding italiano con i soli campi usati dal server."""
    luogo = {"name": nome, "latitude": latitudine, "longitude": longitudine,
             "country_code": "IT", "country": "Italia", "admin1": regione,
             "timezone": "Europe/Rome"}
    if provincia is not None:
        luogo["admin2"] = provincia  # alcune frazioni non hanno la provincia
    if abitanti is not None:
        luogo["population"] = abitanti  # alcune frazioni non hanno gli abitanti
    return luogo


# "Roma": la capitale, una frazione omonima di 87 abitanti e "Romana" (trovata per prefisso)
GEO_ROMA = {"results": [
    _luogo("Roma", "Lazio", "Provincia di Roma", 2318895),
    _luogo("Roma", "Lombardia", "Provincia di Mantova", 87, 45.2, 10.8),
    _luogo("Romana", "Sardegna", "Provincia di Sassari", 578, 40.5, 8.8),
]}

# "San Giovanni": davvero ambigua; Open-Meteo NON la ordina per abitanti (prima la ligure)
GEO_SAN_GIOVANNI = {"results": [
    _luogo("San Giovanni", "Liguria", "Provincia di Savona", 316, 44.3, 8.4),
    _luogo("San Giovanni", "Sicilia", "Provincia di Catania", 1789, 37.6, 15.0),
    _luogo("San Giovanni", "Friuli Venezia Giulia", "Provincia di Pordenone", 1356, 46.0, 12.6),
    _luogo("San Giovanni", "Emilia-Romagna", "Ferrara", 844, 44.8, 11.6),
    _luogo("San Giovanni", "Abruzzo", "Provincia di Teramo", 788, 42.7, 13.7),
    _luogo("San Giovanni", "Trentino-Alto Adige", "Bolzano", 759, 46.5, 11.3),
]}

# "Paris" cercata solo in Italia: frazioni con nomi simili, nessuna si chiama "Paris"
GEO_PARIS_IT = {"results": [
    _luogo("Parise", "Trentino-Alto Adige", "Trento", 23, 46.1, 11.1),
    _luogo("Parisia", "Piemonte", "Provincia di Cuneo", 28, 44.4, 7.5),
]}

# nessuna citta': Open-Meteo risponde 200 senza la chiave "results"
GEO_VUOTO = {"generationtime_ms": 0.05}

# meteo attuale (ora di Roma) piu' 7 giorni di previsione dal 2026-11-05
METEO_ESEMPIO = {
    "latitude": 41.89, "longitude": 12.51, "utc_offset_seconds": 3600,
    "timezone": "Europe/Rome", "timezone_abbreviation": "GMT+1", "elevation": 20.0,
    "current_units": {"time": "iso8601", "interval": "seconds", "temperature_2m": "°C",
                      "weather_code": "wmo code"},
    "current": {"time": "2026-11-05T19:45", "interval": 900, "temperature_2m": 10.5,
                "weather_code": 3},
    "daily_units": {"time": "iso8601", "weather_code": "wmo code",
                    "temperature_2m_max": "°C", "temperature_2m_min": "°C",
                    "precipitation_probability_max": "%"},
    "daily": {
        "time": ["2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09",
                 "2026-11-10", "2026-11-11"],
        "weather_code": [3, 61, 61, 0, 1, 2, 80],
        "temperature_2m_max": [17.4, 15.0, 11.8, 12.0, 13.1, 14.2, 9.9],
        "temperature_2m_min": [9.1, 10.3, 7.4, 5.0, 6.2, 7.3, 4.4],
        "precipitation_probability_max": [10, 80, 75, 0, 5, 20, 60],
    },
}


# funzioni pubbliche per i test: luoghi, geocoding e meteo su misura

def luogo(nome: str, regione: str, provincia: str | None = None,
          abitanti: int | None = None) -> dict:
    """Un luogo italiano per i test che costruiscono un geocoding su misura."""
    return _luogo(nome, regione, provincia, abitanti)


def geo_con(*luoghi: dict) -> dict:
    """Risposta di geocoding con i luoghi indicati (copiati: i test possono modificarli)."""
    return {"results": [copy.deepcopy(l) for l in luoghi]}


def meteo_copia() -> dict:
    """Copia profonda di METEO_ESEMPIO da modificare in un test senza toccare l'originale."""
    return copy.deepcopy(METEO_ESEMPIO)


# sceglie il comportamento del trasporto finto in base al tipo della voce
def _risposta(voce, richiesta: httpx.Request) -> httpx.Response:
    """Traduce una voce (dict, Response, eccezione, funzione) nella risposta del trasporto."""
    if isinstance(voce, BaseException):
        raise voce  # come un trasporto vero: timeout, connessione rifiutata...
    if isinstance(voce, httpx.Response):
        return voce  # stato e corpo scelti dal test (es. 503, 429, testo non JSON)
    if callable(voce):
        return voce(richiesta)  # risposta costruita dal test in base alla richiesta
    return httpx.Response(200, json=voce)  # un dict: risposta riuscita con quel JSON


# il client da passare al server al posto di quello vero: nessuna richiesta esce in rete
def client_finto(geo=None, meteo=None, richieste: list | None = None) -> httpx.Client:
    """httpx.Client che risponde con `geo` al geocoding e con `meteo` all'API meteo.

    Se `richieste` e' una lista, ogni richiesta ricevuta vi viene aggiunta (per contarle o
    leggerne i parametri).
    """
    def gestore(richiesta: httpx.Request) -> httpx.Response:
        """Registra la richiesta e risponde con la voce del geocoding o del meteo."""
        if richieste is not None:
            richieste.append(richiesta)
        # geocoding-api.open-meteo.com oppure api.open-meteo.com
        voce = geo if richiesta.url.host.startswith("geocoding") else meteo
        if voce is None:
            # il test non si aspettava questa richiesta (es. il meteo dopo un errore)
            raise AssertionError(f"richiesta inattesa: {richiesta.url}")
        return _risposta(voce, richiesta)

    # MockTransport chiama gestore per ogni richiesta invece di aprire una connessione
    return httpx.Client(transport=httpx.MockTransport(gestore), timeout=5)
