r"""Confronto delle quattro configurazioni del recupero (lezione 8, esercizio 3) sulle stesse domande.

Uso, da L8\ricerca (Qdrant e LM Studio accesi, $env:EMBEDDING_MODEL e $env:LM_MODEL impostate):
  & ..\venv\Scripts\python.exe confronta.py [-k N]
Cambia solo la modalità (base, riscrittura, reranking, entrambe): stesso indice, stesso k, stessi candidati e
tetto, temperatura 0. Con --soglie (esercizio 4) confronta base senza e con le soglie della configurazione sugli
stessi risultati (LM_MODEL non serve). Le tabelle Markdown vanno copiate in docs/rag-agente.md.
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
from app.soglie import filtra
from app.valutazione import leggi_domande
from valuta import DOMANDE

log = logging.getLogger("ricerca")


def leggi_argomenti(argv: list[str] | None) -> argparse.Namespace:
    """k (None = TOP_K della configurazione, deciso dopo)."""
    parser = argparse.ArgumentParser(description="Confronto delle quattro configurazioni del recupero")
    parser.add_argument("-k", type=int, default=None, help="passaggi per domanda (predefinito TOP_K, cioè 5)")
    parser.add_argument("--soglie", action="store_true",
                        help="confronta base senza e con le soglie SOGLIA_ALTA/SOGLIA_BASSA (esercizio 4)")
    return parser.parse_args(argv)


def _con_e_senza_soglie(domande, indice, k, conf) -> dict[str, list[EsitoDomanda]]:
    """Base una sola volta; la colonna «base + soglie» filtra gli stessi risultati (un solo fattore cambiato)."""
    esiti: dict[str, list[EsitoDomanda]] = {"base": [], "base + soglie": []}
    log.info("configurazione base con e senza soglie: %d domande", len(domande))
    for domanda in domande:
        inizio = time.perf_counter()
        esito = recupera(domanda.testo, k, None, indice=indice, chat=None, modalita="base",
                         candidati=conf.candidati, tetto=conf.tetto_rerank)
        latenza = time.perf_counter() - inizio
        # stessi risultati, con e senza i passaggi sotto la soglia bassa
        rimasti, _ = filtra(esito.risultati, conf.soglia_alta, conf.soglia_bassa)
        esiti["base"].append(EsitoDomanda(domanda, [r.numero for r in esito.risultati], 0, latenza, 0))
        esiti["base + soglie"].append(EsitoDomanda(domanda, [r.numero for r, _ in rimasti], 0, latenza, 0))
    return esiti


def main(argv: list[str] | None = None) -> None:
    configura_log()

    # corpo dello script: configurazione, quattro configurazioni sulle stesse domande, tabelle su stdout
    def principale() -> None:
        # argomenti prima della configurazione: --help funziona anche senza variabili d'ambiente
        argomenti = leggi_argomenti(argv)
        conf = carica_configurazione()
        # il confronto delle modalità usa riscrittura e reranking: il modello di chat serve anche se la modalità
        # configurata è base; con --soglie si cerca solo in base, senza gemma
        if not argomenti.soglie and not conf.modello_chat:
            raise ErroreRicerca("LM_MODEL non impostata: il confronto usa il modello di chat per riscrittura e "
                                "reranking, es. $env:LM_MODEL = \"google/gemma-4-e2b\"")
        k = argomenti.k if argomenti.k is not None else conf.top_k
        # un solo indice e un solo modello di chat per tutte le configurazioni
        indice = Indice(QdrantClient(url=conf.qdrant_url), conf.collezione, conf.modello_embedding,
                        EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))
        domande = leggi_domande(DOMANDE)
        esiti: dict[str, list[EsitoDomanda]] = {}
        if argomenti.soglie:
            esiti = _con_e_senza_soglie(domande, indice, k, conf)
        chat = None if argomenti.soglie else ChatLMStudio(conf.lm_base_url, conf.modello_chat)
        for configurazione in ([] if argomenti.soglie else CONFIGURAZIONI):
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
            **({"soglie (alta/bassa)": f"{conf.soglia_alta:.2f}/{conf.soglia_bassa:.2f}"} if argomenti.soglie
               else {}),
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
