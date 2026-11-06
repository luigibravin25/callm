"""Server MCP del catalogo prodotti (FastMCP, trasporto stdio).

Avvio: python -m mcp_catalogo.server  (di solito lo avvia l'adattatore, all'avvio di app.cli).
Su stdout passa solo il protocollo MCP: avvisi ed errori vanno su stderr.
"""
# json: risultati in formato JSON; sys: uscita con messaggio su stderr;
# Annotated: aggiunge un controllo extra al tipo di un argomento
import json
import sys
from typing import Annotated

# FastMCP crea il server MCP; ToolError e' l'errore che arriva al modello come risultato del tool;
# BeforeValidator esegue una funzione di controllo prima della validazione di pydantic
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BeforeValidator

# La logica del catalogo (lettura del CSV, ricerca, dettaglio) sta in catalogo.py
from mcp_catalogo.catalogo import (MAX_RISULTATI, MIN_RISULTATI, RISULTATI_PREDEFINITI,
                                   ErroreCatalogo, carica_catalogo, cerca_con_totale, dettaglio)

# Il catalogo si legge una sola volta, all'avvio del server
try:
    CATALOGO = carica_catalogo()
except ErroreCatalogo as errore:
    # Importato da un altro modulo (es. nei test): l'errore si rilancia normalmente
    if __name__ != "__main__":
        raise
    # avviato come server: niente traceback, solo il motivo su stderr
    sys.exit(f"Catalogo non valido: {errore}")

# Il server MCP: "catalogo" e' il nome con cui si presenta al client
mcp = FastMCP("catalogo")


# Controllo su max_results: rifiuta True/False prima che diventino 1/0
def _niente_booleani(valore):
    # la validazione di FastMCP convertirebbe True in 1: un booleano non e' un numero di risultati
    if isinstance(valore, bool):
        raise ValueError(f"max_results deve essere un intero tra {MIN_RISULTATI} e "
                         f"{MAX_RISULTATI}, ricevuto {valore!r}.")
    return valore


# nello schema resta {"type": "integer"} (niente anyOf, per il template di gemma)
NumeroRisultati = Annotated[int, BeforeValidator(_niente_booleani)]


# Trasforma i dati in testo JSON; ensure_ascii=False lascia leggibili le lettere accentate
def _json(dati) -> str:
    # testo JSON gia' pronto: una lista vuota arriva al modello come "[]"
    return json.dumps(dati, ensure_ascii=False)


# Tool MCP "search_catalog": cerca prodotti per parole quando il codice non e' noto.
# @mcp.tool lo registra nel server; la docstring e' la descrizione letta dal modello
@mcp.tool
def search_catalog(query: str, max_results: NumeroRisultati = RISULTATI_PREDEFINITI) -> str:
    """Trova prodotti nel catalogo quando NON conosci il codice.

    Ricerca esatta per parole intere (nome, categoria, stato, sede o codice), senza distinzione
    di maiuscole e accenti; articoli e preposizioni (il, la, di, per, e...) sono ignorati;
    non e' una ricerca per somiglianza. max_results: da 1 a 20.
    Restituisce "Trovati N prodotti:" seguito da una lista JSON con solo codice, nome e
    categoria; rispondi all'utente con una frase, non ripetere il JSON. Il risultato [] significa che
    nessun prodotto corrisponde: dillo all'utente e non inventare prodotti. Se dopo la lista c'e'
    la riga "Mostrati N di M risultati", i prodotti sono di piu': richiama con il max_results
    indicato oppure di' all'utente quanti ce ne sono in tutto.
    Per prezzo, disponibilita', quantita' o sede chiama poi get_item con il codice trovato.
    """
    try:
        risultati, totale = cerca_con_totale(CATALOGO, query, max_results)
    # Query non valida: il motivo torna al modello come errore del tool
    except ErroreCatalogo as e:
        raise ToolError(str(e)) from None
    if not risultati:
        return "[]"  # ricerca vuota: lista vuota esplicita, come chiede la consegna
    # una riga di testo davanti alla lista: con un risultato che inizia con "[" gemma, dopo un
    # turno precedente con un tool, ripeteva il risultato grezzo ("[TOOL_RESULT][...]")
    testo = f"Trovati {len(risultati)} prodotti: {_json(risultati)}"
    if totale > len(risultati):
        # il modello deve sapere che la lista e' tagliata, altrimenti la presenta come completa
        if totale <= MAX_RISULTATI:
            # Tutti i risultati stanno in una chiamata: si indica il max_results giusto
            testo += (f"\nMostrati {len(risultati)} di {totale} risultati: richiama "
                      f"search_catalog con max_results={totale} per vederli tutti.")
        else:
            # Troppi anche per il massimo: si chiede una query piu' precisa
            testo += (f"\nMostrati {len(risultati)} di {totale} risultati (massimo "
                      f"{MAX_RISULTATI} per chiamata): rendi la query più precisa per trovare "
                      "gli altri.")
    return testo


# Tool MCP "get_item": tutti i dettagli di un prodotto dato il suo codice
@mcp.tool
def get_item(code: str) -> str:
    """Legge i dettagli di UN prodotto di cui conosci gia' il codice (formato PRD + 3 cifre).

    Restituisce codice, nome, categoria, prezzo in euro, quantita' in magazzino, stato e sede.
    Non cerca per nome: se non hai il codice usa prima search_catalog.
    """
    try:
        return _json(dettaglio(CATALOGO, code))
    # Codice sconosciuto: il messaggio torna al modello come errore del tool
    except ErroreCatalogo as e:
        raise ToolError(str(e)) from None


# Risorsa MCP (dati da leggere, non un'azione): l'intero catalogo all'indirizzo catalog://prodotti
@mcp.resource("catalog://prodotti", mime_type="application/json")
def catalogo_completo() -> str:
    """Tutti i prodotti del catalogo, con tutti i campi."""
    return _json(CATALOGO)


# Avvio diretto (python -m mcp_catalogo.server): server su stdin/stdout.
# show_banner=False: niente scritte su stdout, che e' riservato al protocollo MCP
if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
