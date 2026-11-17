"""Server MCP della ricerca (lezione 8): tool search_documents e resource ricettario://capitoli.

Avvio in stdio, da L8\\ricerca:  & ..\\venv\\Scripts\\python.exe -m mcp_ricerca.server
Configurazione dalle variabili d'ambiente della ricerca (EMBEDDING_MODEL, QDRANT_URL, ...).
"""
# librerie standard: JSON
import json

# server MCP e client di Qdrant
from fastmcp import FastMCP
from qdrant_client import QdrantClient

from app.config import carica_configurazione
from app.corpus import CAPITOLI
from app.embedding import EmbedderLMStudio
from app.indice import Indice
from mcp_ricerca.risultato import MODALITA, RisultatoRicerca, limita_top_k, passaggio

# URI della resource con i valori del filtro per capitolo
URI_CAPITOLI = "ricettario://capitoli"
# descrizione del tool letta dal modello (specifica, §5.2)
DESCRIZIONE_TOOL = (
    "Cerca passaggi nel ricettario di Pellegrino Artusi («La scienza in cucina e l'arte di mangiar bene»). "
    "Usalo per domande su ricette, ingredienti, dosi e procedimenti. Ogni passaggio ha un id da citare tra "
    "parentesi quadre, per esempio [R89-1]. top_k: quanti passaggi (massimo 10). capitolo: facoltativo, uno dei "
    "valori della resource ricettario://capitoli."
)

# mask_error_details: un errore non previsto arriva al client senza dettagli interni
mcp = FastMCP("ricerca", mask_error_details=True)


def crea_indice() -> Indice:
    """Indice sopra la collezione della configurazione (letta a ogni chiamata); i test la sostituiscono."""
    conf = carica_configurazione()
    return Indice(QdrantClient(url=conf.qdrant_url), conf.collezione, conf.modello_embedding,
                  EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))


@mcp.tool(name="search_documents", description=DESCRIZIONE_TOOL)
def search_documents(query: str, top_k: int = 5, capitolo: str = "") -> RisultatoRicerca:
    # top_k entro il massimo del codice (oltre: ridotto, con nota)
    k, nota = limita_top_k(top_k)
    # stringa vuota = nessun filtro; il confronto senza maiuscole lo fa la ricerca della lezione 7
    risultati = crea_indice().cerca(query, capitolo=capitolo or None, k=k)
    return RisultatoRicerca(modalita=MODALITA, query=query, top_k=k,
                            capitolo=capitolo.strip().upper() if capitolo.strip() else "", nota=nota,
                            passaggi=[passaggio(r) for r in risultati])


@mcp.resource(URI_CAPITOLI, name="capitoli", mime_type="application/json")
def capitoli() -> str:
    # i 23 capitoli nell'ordine del libro: i valori ammessi dal filtro capitolo
    return json.dumps(list(CAPITOLI), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
