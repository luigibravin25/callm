"""Controlli dal vivo per GET /stato (step 6): LM Studio raggiungibile con il modello caricato,
server MCP raggiungibile. Ogni chiamata a /stato li ripete."""
# client HTTP per chiedere a LM Studio l'elenco dei modelli
import httpx

# errori e tipi dello stato
from app.errori import MAX_DETTAGLIO
from app.schemi import StatoMCP, StatoModello

TIMEOUT_STATO_S = 5  # secondi: /stato deve rispondere in fretta anche con LM Studio bloccato
MSG_MCP_NON_PARTITO = "server MCP non partito all'avvio: riavviare l'agente"


# LM Studio risponde e ha il modello? GET {base_url}/models e controllo dell'id
def verifica_modello(base_url: str, modello: str,
                     client: httpx.Client | None = None) -> StatoModello:
    client = client or httpx.Client(timeout=TIMEOUT_STATO_S)
    try:
        risposta = client.get(base_url.rstrip("/") + "/models")
    except httpx.HTTPError:
        # connessione rifiutata o timeout
        return StatoModello(stato="non_raggiungibile", nome=modello,
                            messaggio=f"LM Studio non raggiungibile su {base_url}")
    if risposta.status_code != 200:
        return StatoModello(stato="non_raggiungibile", nome=modello,
                            messaggio=f"LM Studio ha risposto con il codice {risposta.status_code}")
    # elenco degli id dei modelli disponibili (risposta inattesa = elenco vuoto)
    try:
        disponibili = [m.get("id", "") for m in risposta.json().get("data", [])]
    except (ValueError, AttributeError):
        disponibili = []
    if modello in disponibili:
        return StatoModello(stato="ok", nome=modello)
    elenco = ", ".join(disponibili) or "nessuno"
    return StatoModello(stato="modello_assente", nome=modello,
                        messaggio=f"{modello} non caricato; disponibili: {elenco}"[:MAX_DETTAGLIO])


# il server MCP risponde? solo se era partito all'avvio: altrimenti serve un riavvio
def verifica_mcp(partito: bool, carica=None) -> StatoMCP:
    if not partito:
        return StatoMCP(stato="non_disponibile", messaggio=MSG_MCP_NON_PARTITO)
    # import come modulo: i test passano un finto al posto della discovery vera
    from app import adattatore_mcp
    carica = carica or adattatore_mcp.carica_strumenti
    try:
        carica()  # una sessione breve con tools/list
    except adattatore_mcp.ErroreMCP as errore:
        return StatoMCP(stato="non_disponibile", messaggio=str(errore))
    return StatoMCP(stato="ok")
