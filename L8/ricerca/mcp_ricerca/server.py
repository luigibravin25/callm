"""Server MCP della ricerca (lezione 8): tool search_documents e resource ricettario://capitoli.

Avvio in stdio, da L8\\ricerca:  & ..\\venv\\Scripts\\python.exe -m mcp_ricerca.server
Configurazione dalle variabili d'ambiente della ricerca (EMBEDDING_MODEL, QDRANT_URL, ...).
"""
# librerie standard: cache, JSON, log, variabili d'ambiente, misura del tempo
import functools
import json
import logging
import os
import sys
import time

# server MCP e client di Qdrant
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.chat import Chat, ChatLMStudio
from app.config import Configurazione, carica_configurazione
from app.corpus import CAPITOLI
from app.embedding import EmbedderLMStudio
from app.errori import ErroreRicerca
from app.indice import Indice
from app.recupero import EsitoRecupero, recupera
from app.soglie import MEDIA, filtra
from mcp_ricerca.risultato import NOTA_MEDIA, RisultatoRicerca, limita_top_k, nota_lista_vuota, passaggio

# URI della resource con i valori del filtro per capitolo
URI_CAPITOLI = "ricettario://capitoli"
# descrizione del tool letta dal modello (specifica, §5.2)
DESCRIZIONE_TOOL = (
    "Cerca passaggi nel ricettario di Pellegrino Artusi («La scienza in cucina e l'arte di mangiar bene»). "
    "Usalo per domande su ricette, ingredienti, dosi e procedimenti. Ogni passaggio ha un id da citare tra "
    "parentesi quadre, per esempio [R89-1]. top_k: quanti passaggi (massimo 10). capitolo: facoltativo, uno dei "
    "valori della resource ricettario://capitoli."
)

# lunghezza massima della query nella riga di log e numero massimo di id con score mostrati
QUERY_MASSIMA_LOG = 80
ID_MASSIMI_LOG = 5

# logger del server: una riga per chiamata del tool
log = logging.getLogger("mcp_ricerca")
# il logger di FastMCP stamperebbe «Error calling tool …» e, per un errore non previsto, la traceback
logging.getLogger("fastmcp").setLevel(logging.CRITICAL)

# mask_error_details: un errore non previsto arriva al client senza dettagli interni
mcp = FastMCP("ricerca", mask_error_details=True)


def configura_log() -> None:
    """Log su stderr (stdout è il canale MCP in stdio): solo le righe del server e gli avvisi delle librerie."""
    # su Windows lo stderr reindirizzato usa la codifica locale: «→» e le lettere accentate in UTF-8
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="[%(name)s] %(message)s", stream=sys.stderr)
    # le righe delle chiamate del tool
    log.setLevel(logging.INFO)
    # fuori le richieste HTTP di httpx e le righe «Processing request …» della libreria mcp
    for nome in ("httpx", "httpx2", "mcp"):
        logging.getLogger(nome).setLevel(logging.WARNING)


@functools.cache
def client_qdrant(url: str) -> QdrantClient:
    """Un solo client per indirizzo, riusato tra le chiamate (niente connessioni lasciate aperte a ogni ricerca)."""
    return QdrantClient(url=url)


def crea_indice() -> Indice:
    """Indice sopra la collezione della configurazione (letta a ogni chiamata); i test la sostituiscono."""
    conf = carica_configurazione()
    return Indice(client_qdrant(conf.qdrant_url), conf.collezione, conf.modello_embedding,
                  EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))


def crea_chat(conf: Configurazione) -> Chat | None:
    """Modello di chat per riscrittura e reranking (nessuno in modalità base); i test lo sostituiscono."""
    if conf.modalita == "base":
        return None
    return ChatLMStudio(conf.lm_base_url, conf.modello_chat)


def _qdrant_url() -> str:
    """Indirizzo di Qdrant per il messaggio d'errore (dalla configurazione, se è valida)."""
    try:
        return carica_configurazione().qdrant_url
    except ErroreRicerca:
        return os.environ.get("QDRANT_URL", "")


def _testa_riga(query: str, top_k: int, capitolo: str) -> str:
    """Parte iniziale della riga di log: query troncata, top_k e capitolo della chiamata."""
    breve = query if len(query) <= QUERY_MASSIMA_LOG else query[:QUERY_MASSIMA_LOG] + "…"
    return f'query="{breve}" top_k={top_k} capitolo={capitolo.strip() or "-"}'


def _cerca(query: str, top_k: int, capitolo: str) -> tuple[RisultatoRicerca, EsitoRecupero, str]:
    """Ricerca vera e propria: gli errori previsti sono ErroreRicerca o errori del client di Qdrant;
    riscrittura e reranking non sollevano errori (ripieghi)."""
    # top_k entro il massimo del codice (oltre: ridotto, con nota)
    k, nota = limita_top_k(top_k)
    # modalità, candidati e tetto dalla configurazione del server, letta a ogni chiamata
    conf = carica_configurazione()
    # stringa vuota o di soli spazi = nessun filtro; il confronto senza maiuscole lo fa la ricerca della lezione 7
    esito = recupera(query, k, capitolo.strip() or None, indice=crea_indice(), chat=crea_chat(conf),
                     modalita=conf.modalita, candidati=conf.candidati, tetto=conf.tetto_rerank)
    # soglie sullo score (esercizio 4): fascia di ogni passaggio, esclusi non inviati al modello
    rimasti, esclusi = filtra(esito.risultati, conf.soglia_alta, conf.soglia_bassa)
    # nessun passaggio rimasto: lista vuota dichiarata nella nota, con il motivo quando è noto
    if not rimasti:
        if esito.risultati:
            motivo = f"tutti sotto la soglia bassa {conf.soglia_bassa:.2f}"
        elif esito.vuota_dal_reranking:
            motivo = "esclusi tutti dal reranking"
        else:
            motivo = None
        nota = f"{nota}; {nota_lista_vuota(motivo)}" if nota else nota_lista_vuota(motivo)
    # almeno un passaggio di affidabilità media: la nota ricorda all'agente di dichiarare la verifica
    elif any(f == MEDIA for _, f in rimasti):
        nota = f"{nota}; {NOTA_MEDIA}" if nota else NOTA_MEDIA
    risultato = RisultatoRicerca(modalita=esito.modalita, query=query, query_usate=esito.query_usate,
                                 ripieghi=esito.ripieghi, top_k=k,
                                 capitolo=capitolo.strip().upper() if capitolo.strip() else "", nota=nota,
                                 passaggi=[passaggio(r, f) for r, f in rimasti])
    # parte della riga di log sulle soglie: valori usati e passaggi esclusi
    parte_soglie = f"soglie={conf.soglia_alta:.2f}/{conf.soglia_bassa:.2f} esclusi={esclusi}"
    return risultato, esito, parte_soglie


def _parte_recupero(esito: EsitoRecupero) -> str:
    """Parte della riga di log sul recupero: modalità, numero di query e di chiamate all'LLM, ripieghi, id scartati."""
    parte = f"modalita={esito.modalita} query={len(esito.query_usate)} llm={esito.chiamate_llm}"
    # ripieghi e id scartati solo se ci sono
    if esito.ripieghi:
        parte += f" ripieghi=[{'; '.join(esito.ripieghi)}]"
    if esito.id_scartati:
        parte += f" scartati={esito.id_scartati}"
    return parte


@mcp.tool(name="search_documents", description=DESCRIZIONE_TOOL)
def search_documents(query: str, top_k: int = 5, capitolo: str = "") -> RisultatoRicerca:
    inizio = time.perf_counter()
    try:
        risultato, esito, parte_soglie = _cerca(query, top_k, capitolo)
    except ErroreRicerca as errore:
        # errore previsto: messaggio comprensibile al modello, una riga di log senza traceback
        log.info("%s → errore: %s", _testa_riga(query, top_k, capitolo), errore)
        raise ToolError(str(errore)) from None
    except (ResponseHandlingException, UnexpectedResponse) as errore:
        # Qdrant spento o risposta inattesa: si indica l'indirizzo configurato
        messaggio = f"Qdrant non raggiungibile (QDRANT_URL={_qdrant_url()}): {errore}"
        log.info("%s → errore: %s", _testa_riga(query, top_k, capitolo), messaggio)
        raise ToolError(messaggio) from None
    except Exception as errore:
        # errore non previsto: nel log tipo e messaggio; FastMCP lo maschera verso il client
        log.info("%s → errore inatteso: %s: %s", _testa_riga(query, top_k, capitolo),
                 type(errore).__name__, errore)
        raise
    # riga della chiamata riuscita: primi id con score e durata
    primi = ", ".join(f"{p['id']} {p['score']:.4f}" for p in risultato["passaggi"][:ID_MASSIMI_LOG])
    altri = ", …" if len(risultato["passaggi"]) > ID_MASSIMI_LOG else ""
    log.info("%s %s %s → %d passaggi (%s%s) in %.2fs", _testa_riga(query, risultato["top_k"], capitolo),
             _parte_recupero(esito), parte_soglie, len(risultato["passaggi"]), primi, altri,
             time.perf_counter() - inizio)
    return risultato


@mcp.resource(URI_CAPITOLI, name="capitoli", mime_type="application/json")
def capitoli() -> str:
    # i 23 capitoli nell'ordine del libro: i valori ammessi dal filtro capitolo
    return json.dumps(list(CAPITOLI), ensure_ascii=False)


def main() -> None:
    """Avvio del server in stdio con il log su stderr."""
    configura_log()
    # senza banner: su stderr restano solo le righe di log
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
