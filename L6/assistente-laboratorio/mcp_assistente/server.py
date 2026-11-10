"""Server MCP dell'assistente (FastMCP, trasporto stdio).

Tool `tooltime` (lo chiama il modello: tools/call) e resource `utente://preferenze` (la legge
l'host all'avvio della sessione: resources/read). Avvio: python -m mcp_assistente.server
"""
# librerie standard: variabili d'ambiente, percorsi, tipi con valori fissi
import os
from pathlib import Path
from typing import Literal

# FastMCP crea il server MCP; ResourceError e' l'errore restituito al client per una resource
from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError

# logica dell'orologio (data e ora a parole)
from mcp_assistente.orologio import ora_corrente

# cartella assistente-laboratorio/: i percorsi relativi partono da qui, non dalla cartella corrente
CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent
PREFERENZE_PREDEFINITO = "config/preferenze.json"  # usato se PREFERENZE_FILE non e' impostata
URI_PREFERENZE = "utente://preferenze"  # indirizzo della resource

# il server: il nome compare al client durante l'inizializzazione
mcp = FastMCP("assistente")


# percorso del file delle preferenze (PREFERENZE_FILE o config/preferenze.json)
def percorso_preferenze() -> Path:
    percorso = Path(os.environ.get("PREFERENZE_FILE", "").strip() or PREFERENZE_PREDEFINITO)
    # relativo: parte dalla cartella del progetto
    return percorso if percorso.is_absolute() else CARTELLA_PROGETTO / percorso


# tool orologio: il modello lo chiama con il nome "tooltime" (la docstring e' la sua descrizione)
@mcp.tool(name="tooltime")
def tooltime(fuso: str = "", parte: Literal["ora", "data", "entrambe"] = "entrambe") -> str:
    """Restituisce data e/o ora attuali in un fuso orario.

    Usala ogni volta che serve sapere che ora e' o che giorno e' in una citta' o
    in un paese. L'argomento `fuso` e' il nome IANA del fuso orario, ad esempio
    "Europe/Rome", "Asia/Tokyo" o "America/New_York" (non il nome della citta' da sola).
    Se l'utente non indica una citta' o un paese, ometti `fuso`: lo strumento usa il fuso
    predefinito. Non usare "UTC" o "GMT" se l'utente non li chiede.
    Il risultato inizia con il nome del luogo: nella risposta usa quel nome (per esempio
    "a New York"), mai il nome IANA con la barra (come "America/New_York").
    Riporta l'ora esattamente come scritta nel risultato, a parole ("sono le ore 10 e 32 minuti"):
    non convertirla in cifre con i due punti (come "10:32") e non aggiungere i secondi.
    L'argomento `parte` dice cosa restituire: "ora" se l'utente chiede solo l'ora,
    "data" se chiede solo il giorno o la data, "entrambe" negli altri casi.
    """
    return ora_corrente(fuso, parte)


# resource delle preferenze: restituisce il testo del file cosi' com'e' (la validazione e' dell'host)
@mcp.resource(URI_PREFERENZE, name="preferenze", mime_type="application/json")
def preferenze() -> str:
    """Preferenze dell'utente: lingua delle risposte, fuso orario predefinito, stile."""
    percorso = percorso_preferenze()
    try:
        # utf-8-sig: toglie il BOM che il Blocco note di Windows puo' aggiungere
        return percorso.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ResourceError(f"File delle preferenze non trovato: {percorso}") from None


# avvio come processo: il client MCP parla con il server su stdin/stdout
if __name__ == "__main__":
    mcp.run()
