"""Server MCP dell'assistente (FastMCP, trasporto stdio).

Tool `tooltime` (lo chiama il modello: tools/call), resource `utente://preferenze` (la legge
l'host all'avvio della sessione: resources/read) e prompt `spiega` e `riassumi_conversazione` (li
richiama l'utente con /prompt: prompts/get). Avvio: python -m mcp_assistente.server
"""
# librerie standard: variabili d'ambiente, percorsi, tipi con valori fissi
import os
from pathlib import Path
from typing import Literal

# FastMCP crea il server MCP; ResourceError e PromptError sono gli errori restituiti al client
from fastmcp import FastMCP
from fastmcp.exceptions import PromptError, ResourceError

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


# --- prompt (step 5): modelli di istruzioni richiamati dall'utente ---

# descrizioni pubblicate in prompts/list: elencano i valori ammessi (gli argomenti non hanno
# descrizione propria, perche' FastMCP vi aggiungerebbe "Provide as a JSON string...")
DESCRIZIONE_SPIEGA = ("Spiega un argomento al livello scelto. livello: base, intermedio o avanzato "
                      "(predefinito base).")
DESCRIZIONE_RIASSUMI = ("Riassume la conversazione della sessione corrente. stile: sintetico o "
                        "dettagliato (predefinito sintetico).")

# una frase fissa per ogni livello di spiega
LIVELLI = {
    "base": ("Livello base: usa parole semplici, niente gergo tecnico, un esempio concreto di "
             "tutti i giorni, al massimo 5 frasi."),
    "intermedio": ("Livello intermedio: spiega i termini tecnici principali, come funziona e fai "
                   "un esempio."),
    "avanzato": ("Livello avanzato: entra nei dettagli tecnici, nei componenti, nel funzionamento "
                 "interno e nei limiti."),
}

# istruzione del riassunto: la conversazione la vede gia' l'agente nella cronologia
TESTO_RIASSUMI = ("Riassumi la conversazione che abbiamo avuto finora in questa sessione, senza "
                  "chiamare strumenti. Se non c'è ancora nulla da riassumere, dillo.")
# una frase fissa per ogni stile del riassunto
STILI = {
    "sintetico": "Stile sintetico: 3-5 punti brevi.",
    "dettagliato": ("Stile dettagliato: per ogni argomento trattato, cosa ho chiesto e cosa hai "
                    "risposto."),
}


# controlla un valore contro quelli ammessi; maiuscole e spazi non contano (come lo stile delle
# preferenze); un valore non ammesso diventa un errore leggibile per il client
def _ammesso(nome: str, valore: str, ammessi: dict) -> str:
    normale = valore.strip().lower()
    if normale not in ammessi:
        raise PromptError(f"{nome} non valido: {valore!r} (ammessi: {', '.join(ammessi)})")
    return normale


# prompt spiega: una domanda fissa con la frase del livello
@mcp.prompt(name="spiega", description=DESCRIZIONE_SPIEGA)
def spiega(argomento: str, livello: str = "base") -> str:
    # argomento vuoto: niente da spiegare (l'host lo blocca gia', qui e' una seconda sicurezza)
    if not argomento.strip():
        raise PromptError("argomento vuoto: scrivi cosa spiegare")
    return f"Spiegami {argomento.strip()}. " + LIVELLI[_ammesso("livello", livello, LIVELLI)]


# prompt riassumi_conversazione: solo l'istruzione, il server non conosce la cronologia
@mcp.prompt(name="riassumi_conversazione", description=DESCRIZIONE_RIASSUMI)
def riassumi_conversazione(stile: str = "sintetico") -> str:
    return f"{TESTO_RIASSUMI} " + STILI[_ammesso("stile", stile, STILI)]


# avvio come processo: il client MCP parla con il server su stdin/stdout;
# show_banner=False: niente riquadro di FastMCP nel terminale della chat (come L5)
if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
