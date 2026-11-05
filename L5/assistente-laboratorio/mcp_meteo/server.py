"""Server MCP del meteo (FastMCP, trasporto stdio) sopra l'API pubblica Open-Meteo.

Avvio: python -m mcp_meteo.server  (di solito lo avvia l'adattatore, all'avvio di app.cli).
Su stdout passa solo il protocollo MCP: avvisi ed errori vanno su stderr.

Il tool get_weather traduce argomenti, risposte ed errori; la logica meteo resta nel servizio
esterno. Ogni errore arriva al client come isError, con la categoria in testa al messaggio.
"""
from typing import Annotated  # tipo con validatore aggiunto

from fastmcp import FastMCP  # libreria per scrivere server MCP con decoratori
from fastmcp.exceptions import ToolError  # errore restituito al client come isError
from mcp.types import ToolAnnotations  # annotazioni MCP: sola lettura, mondo aperto
from pydantic import BeforeValidator  # controllo eseguito prima della conversione del tipo

from mcp_meteo.contatore import Contatore, limite_giornaliero, percorso_contatore
from mcp_meteo.errori import ErroreMeteo
from mcp_meteo.meteo import _adesso, testo_meteo
from mcp_meteo.open_meteo import crea_client

# il server: nome "meteo", pubblica il tool con tools/list
mcp = FastMCP("meteo")


def _niente_booleani(valore):
    """Rifiuta true/false al posto del numero di giorni (FastMCP convertirebbe True in 1)."""
    if isinstance(valore, bool):
        raise ValueError(f"days deve essere un numero intero da 0 a 7, ricevuto {valore!r}.")
    return valore


# nello schema resta {"type": "integer"} (niente anyOf, per il template di gemma)
GiorniPrevisione = Annotated[int, BeforeValidator(_niente_booleani)]


def crea_contatore() -> Contatore:
    """Contatore del limite giornaliero, con file e limite letti dall'ambiente a ogni chiamata."""
    return Contatore(percorso_contatore(), limite_giornaliero(), _adesso)


# @mcp.tool registra la funzione come tool MCP: nome, schema degli argomenti (dai tipi) e
# descrizione (dalla docstring) arrivano al client con tools/list. Annotazioni MCP:
# - readOnlyHint=True: il tool legge soltanto, non modifica nulla (niente conferma nel grafo);
# - openWorldHint=True: interroga un servizio esterno (Open-Meteo), i dati cambiano nel tempo.
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def get_weather(city: str = "", days: GiorniPrevisione = 0, date: str = "") -> str:
    """Meteo di una città italiana dal servizio pubblico Open-Meteo: temperatura, condizioni e
    ora di riferimento, con le unità; a richiesta anche le previsioni giornaliere.
    Solo città italiane: per una città estera il risultato è "Città non trovata".

    city: nome della città; vuoto = città predefinita (dichiarata nel risultato). Se il
    risultato elenca altre località con lo stesso nome, l'utente può scegliere scrivendo la
    città seguita da virgola e regione o provincia, per esempio "San Giovanni, Pordenone".
    days: 0 = solo meteo attuale; da 1 a 7 = anche le previsioni, oggi compreso (1 = oggi,
    2 = oggi e domani).
    date: un giorno preciso scritto come l'ha scritto l'utente ("sabato", "15 novembre",
    "domani"), senza calcolare la data; se presente, days è ignorato. Oltre 7 giorni il
    risultato dice che non ci sono previsioni affidabili.
    Presenta il risultato con parole tue, non ripeterlo come dati grezzi. Un errore di rete o
    di timeout riguarda la connessione, non la città.
    """
    try:
        # un client per chiamata, chiuso alla fine (with): nessuna connessione lasciata aperta
        with crea_client() as client:
            return testo_meteo(city, days, date, client, crea_contatore())
    except ErroreMeteo as errore:
        # il messaggio ("Città non trovata: ...", "Timeout: ...") arriva al modello
        raise ToolError(str(errore)) from None


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
