"""Confronto delle quattro configurazioni del recupero (lezione 8, esercizio 3) sulle stesse domande.

Uso, da L8\ricerca (Qdrant e LM Studio accesi, $env:EMBEDDING_MODEL e $env:LM_MODEL impostate):
  & ..\venv\Scripts\python.exe confronta.py [-k N]
Cambia solo la modalità (base, riscrittura, reranking, entrambe): stesso indice, stesso k, stessi candidati e
tetto, temperatura 0. Le tabelle Markdown vanno copiate in docs/rag-agente.md.
"""
# librerie standard: argomenti da riga di comando, log, misura del tempo
import argparse
import logging
import time

# client di Qdrant (server avviato con docker compose start qdrant)
from qdrant_client import QdrantClient

from app.avvio import configura_log, esegui as esegui_script
from app.chat import ChatLMStudio
from app.config import carica_configurazione
from app.confronto import CONFIGURAZIONI, EsitoDomanda, tabelle_markdown
from app.embedding import EmbedderLMStudio
from app.errori import ErroreRicerca
from app.indice import Indice
from app.recupero import recupera
from app.valutazione import leggi_domande
from valuta import DOMANDE

log = logging.getLogger("ricerca")


def leggi_argomenti(argv: list[str] | None) -> argparse.Namespace:
    """k (None = TOP_K della configurazione, deciso dopo)."""
    parser = argparse.ArgumentParser(description="Confronto delle quattro configurazioni del recupero")
    parser.add_argument("-k", type=int, default=None, help="passaggi per domanda (predefinito TOP_K, cioè 5)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    configura_log()

    # corpo dello script: configurazione, quattro configurazioni sulle stesse domande, tabelle su stdout
    def principale() -> None:
        # argomenti prima della configurazione: --help funziona anche senza variabili d'ambiente
        argomenti = leggi_argomenti(argv)
        conf = carica_configurazione()
        # il confronto usa sempre riscrittura e reranking: il modello di chat serve anche se la modalità è base
        if not conf.modello_chat:
            raise ErroreRicerca("LM_MODEL non impostata: il confronto usa il modello di chat per riscrittura e "
                                "reranking, es. $env:LM_MODEL = \"google/gemma-4-e2b\"")
        k = argomenti.k if argomenti.k is not None else conf.top_k
        # un solo indice e un solo modello di chat per tutte le configurazioni
        indice = Indice(QdrantClient(url=conf.qdrant_url), conf.collezione, conf.modello_embedding,
                        EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))
        chat = ChatLMStudio(conf.lm_base_url, conf.modello_chat)
        domande = leggi_domande(DOMANDE)
        esiti: dict[str, list[EsitoDomanda]] = {}
        for configurazione in CONFIGURAZIONI:
            log.info("configurazione %s: %d domande", configurazione, len(domande))
            esiti[configurazione] = []
            for domanda in domande:
                # latenza della sola ricerca, con riscrittura e reranking compresi
                inizio = time.perf_counter()
                esito = recupera(domanda.testo, k, None, indice=indice, chat=chat, modalita=configurazione,
                                 candidati=conf.candidati, tetto=conf.tetto_rerank)
                latenza = time.perf_counter() - inizio
                esiti[configurazione].append(EsitoDomanda(domanda, [r.numero for r in esito.risultati],
                                                          esito.chiamate_llm, latenza, len(esito.ripieghi)))
        # parametri della prova: dicono che cosa è rimasto fisso tra le configurazioni
        intestazione = {
            "modello di embedding": conf.modello_embedding,
            "modello di chat": conf.modello_chat,
            "collezione": f"{conf.collezione} ({indice.conta_punti()} punti)",
            "k": str(k),
            "candidati per query": str(conf.candidati),
            "tetto del reranking": str(conf.tetto_rerank),
            "temperatura": "0",
        }
        print(tabelle_markdown(esiti, intestazione))

    esegui_script(principale)


if __name__ == "__main__":
    main()
