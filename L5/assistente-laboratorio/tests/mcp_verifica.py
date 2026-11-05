"""Verifica dei server MCP SENZA l'assistente: un client MCP che usa il protocollo vero.

Un processo acceso non dimostra che il server MCP funzioni: questo script si collega come
farebbe un client (trasporto stdio), chiede l'elenco dei tool (tools/list) e li chiama
(tools/call), controllando le risposte. Nessun modello, nessun grafo.

Uso (da assistente-laboratorio/):
    python -m tests.mcp_verifica catalogo
    python -m tests.mcp_verifica note      # usa SEMPRE un archivio temporaneo: le note vere restano
    python -m tests.mcp_verifica meteo     # serve la rete (Open-Meteo); contatore temporaneo
Codice d'uscita 0 solo se tutti i passi sono OK.
"""
import asyncio  # il client di FastMCP e' asincrono
import os  # ambiente del processo del server
import sys  # interprete da usare e codice d'uscita
import tempfile  # cartella temporanea per l'archivio delle note
from pathlib import Path

from fastmcp import Client  # client MCP
from fastmcp.client.transports import StdioTransport  # avvia il server come processo figlio

# assistente-laboratorio/ (lo script sta in tests/): da qui si avviano i server
CARTELLA = Path(__file__).resolve().parent.parent
MODULI = {"catalogo": "mcp_catalogo.server", "note": "mcp_note.server",
          "meteo": "mcp_meteo.server"}  # server verificabili


class Verifica:
    """Raccoglie l'esito dei passi e li stampa uno per riga."""

    def __init__(self):
        """Nessun errore all'inizio."""
        self.errori = 0

    def passo(self, nome: str, riuscito: bool, dettaglio: str = "") -> None:
        """Stampa "OK <passo>" oppure "ERRORE <passo>: <dettaglio>" e conta gli errori."""
        if riuscito:
            print(f"OK      {nome}")
        else:
            self.errori += 1
            print(f"ERRORE  {nome}: {dettaglio}")


def _testo(risultato) -> str:
    """Testo di una risposta tools/call (uno o piu' blocchi di testo)."""
    return "".join(b.text for b in risultato.content if getattr(b, "type", "") == "text")


def _schemi_senza_anyof(tools) -> bool:
    """Ogni argomento di ogni tool ha "type" e nessun "anyOf" (serve al template di gemma)."""
    return all("type" in s and "anyOf" not in s
               for t in tools for s in t.inputSchema.get("properties", {}).values())


async def _verifica_catalogo(client: Client, v: Verifica) -> None:
    """tools/list e tools/call sul server del catalogo prodotti."""
    tools = await client.list_tools()
    nomi = {t.name for t in tools}
    v.passo("tools/list: search_catalog e get_item", nomi == {"search_catalog", "get_item"},
            str(nomi))
    v.passo("schemi senza anyOf", _schemi_senza_anyof(tools))
    r = await client.call_tool("search_catalog", {"query": "smartphone"}, raise_on_error=False)
    v.passo("tools/call search_catalog(smartphone) trova PRD001",
            not r.is_error and "PRD001" in _testo(r), _testo(r))
    r = await client.call_tool("get_item", {"code": "PRD001"}, raise_on_error=False)
    v.passo("tools/call get_item(PRD001) restituisce il prezzo 499.99",
            not r.is_error and "499.99" in _testo(r), _testo(r))
    r = await client.call_tool("get_item", {"code": "PRD999"}, raise_on_error=False)
    v.passo("tools/call get_item(PRD999) e' un errore (isError)", r.is_error, _testo(r))


async def _verifica_note(client: Client, v: Verifica) -> None:
    """tools/list con annotazioni e ciclo completo add -> list -> delete -> list."""
    tools = {t.name: t for t in await client.list_tools()}
    v.passo("tools/list: add_note, list_notes, delete_note",
            set(tools) == {"add_note", "list_notes", "delete_note"}, str(set(tools)))
    v.passo("annotazioni: list_notes sola lettura, delete_note distruttivo",
            tools["list_notes"].annotations.readOnlyHint is True
            and tools["delete_note"].annotations.destructiveHint is True)
    v.passo("schemi senza anyOf", _schemi_senza_anyof(tools.values()))
    # 1. creazione: la risposta contiene l'ID della nota
    r = await client.call_tool("add_note", {"text": "nota di verifica"}, raise_on_error=False)
    testo = _testo(r)
    v.passo("add_note crea una nota con ID e data", not r.is_error and testo.startswith("Nota "),
            testo)
    note_id = int(testo.split()[1]) if testo.startswith("Nota ") else 0
    # 2. verifica della modifica: la nota compare nell'elenco
    r = await client.call_tool("list_notes", {}, raise_on_error=False)
    v.passo("list_notes mostra la nota creata", "nota di verifica" in _testo(r), _testo(r))
    # 3. eliminazione (qui senza conferma: la conferma la chiede l'assistente, non il server)
    r = await client.call_tool("delete_note", {"note_id": note_id}, raise_on_error=False)
    v.passo("delete_note elimina la nota", not r.is_error and "eliminata" in _testo(r),
            _testo(r))
    # 4. verifica dell'eliminazione: la nota non c'e' piu'
    r = await client.call_tool("list_notes", {}, raise_on_error=False)
    v.passo("list_notes non mostra piu' la nota", "nota di verifica" not in _testo(r), _testo(r))
    # 5. errori del contratto
    r = await client.call_tool("delete_note", {"note_id": note_id}, raise_on_error=False)
    v.passo("delete_note sullo stesso ID e' un errore", r.is_error and "non esiste" in _testo(r),
            _testo(r))
    r = await client.call_tool("add_note", {"text": "   "}, raise_on_error=False)
    v.passo("add_note con testo vuoto e' un errore", r.is_error, _testo(r))


async def _verifica_meteo(client: Client, v: Verifica) -> None:
    """tools/list con annotazioni e chiamate vere a Open-Meteo (serve la rete)."""
    tools = await client.list_tools()
    nomi = {t.name for t in tools}
    v.passo("tools/list: get_weather", nomi == {"get_weather"}, str(nomi))
    if "get_weather" not in nomi:
        return  # senza il tool i passi successivi non hanno senso
    tool = next(t for t in tools if t.name == "get_weather")
    v.passo("annotazioni: sola lettura, mondo aperto",
            tool.annotations.readOnlyHint is True and tool.annotations.openWorldHint is True)
    v.passo("schemi senza anyOf", _schemi_senza_anyof(tools))
    # chiamata vera: dimostra anche che da qui (o dal container) Open-Meteo e' raggiungibile
    r = await client.call_tool("get_weather", {"city": "Roma", "days": 1}, raise_on_error=False)
    v.passo("tools/call get_weather(Roma) con temperatura in °C e fonte",
            not r.is_error and "°C" in _testo(r) and "Open-Meteo" in _testo(r), _testo(r))
    r = await client.call_tool("get_weather", {"city": "Xyzqwk"}, raise_on_error=False)
    v.passo("tools/call get_weather(Xyzqwk) e' un errore \"Città non trovata\"",
            r.is_error and _testo(r).startswith("Città non trovata"), _testo(r))
    # solo citta' italiane: una citta' estera non deve diventare una frazione dal nome simile
    r = await client.call_tool("get_weather", {"city": "Paris"}, raise_on_error=False)
    v.passo("tools/call get_weather(Paris) e' un errore: solo città italiane",
            r.is_error and "solo per le città italiane" in _testo(r), _testo(r))
    r = await client.call_tool("get_weather", {"days": 8}, raise_on_error=False)
    v.passo("tools/call get_weather(days=8) e' un errore (isError)", r.is_error, _testo(r))


async def _verifica(server: str) -> bool:
    """Avvia il server via stdio, esegue i passi e restituisce True se tutti sono OK."""
    # come l'adattatore: niente righe di FastMCP ("Error calling tool ..."), log in UTF-8
    ambiente = dict(os.environ, FASTMCP_LOG_LEVEL="CRITICAL", PYTHONIOENCODING="utf-8")
    temporanea = None
    if server == "note":
        # archivio temporaneo: la verifica crea ed elimina note, quelle vere non si toccano
        temporanea = tempfile.TemporaryDirectory(prefix="verifica-note-")
        ambiente["NOTE_DB"] = str(Path(temporanea.name) / "note.sqlite")
    elif server == "meteo":
        # contatore temporaneo: la verifica non consuma il limite giornaliero vero
        temporanea = tempfile.TemporaryDirectory(prefix="verifica-meteo-")
        ambiente["METEO_CONTATORE"] = str(Path(temporanea.name) / "meteo_richieste.sqlite")
    trasporto = StdioTransport(command=sys.executable, args=["-m", MODULI[server]],
                               env=ambiente, cwd=str(CARTELLA))
    v = Verifica()
    print(f"Verifica del server MCP '{server}' ({MODULI[server]}, stdio)")
    try:
        async with Client(trasporto) as client:  # handshake MCP (initialize)
            v.passo("connessione e handshake MCP", True)
            if server == "catalogo":
                await _verifica_catalogo(client, v)
            elif server == "note":
                await _verifica_note(client, v)
            else:
                await _verifica_meteo(client, v)
    except Exception as errore:  # server che non parte o protocollo rotto
        v.passo("connessione e handshake MCP", False, str(errore) or type(errore).__name__)
    finally:
        if temporanea is not None:
            temporanea.cleanup()
    print("Esito: tutto OK" if v.errori == 0 else f"Esito: {v.errori} errori")
    return v.errori == 0


def verifica(server: str) -> bool:
    """Versione sincrona di _verifica, per chi la usa da Python."""
    return asyncio.run(_verifica(server))


def main(argomenti: list[str]) -> int:
    """Legge il nome del server dalla riga di comando e restituisce il codice d'uscita."""
    if len(argomenti) != 1 or argomenti[0] not in MODULI:
        print(f"Uso: python -m tests.mcp_verifica <{'|'.join(MODULI)}>", file=sys.stderr)
        return 2
    return 0 if verifica(argomenti[0]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
