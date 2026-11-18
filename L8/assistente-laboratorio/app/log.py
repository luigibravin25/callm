"""Configurazione dei log nel terminale, comune al servizio dell'agente e alla CLI client.

Senza dipendenze da LangChain: la CLI client la usa senza caricare il modello. Il flusso dei log
(stderr) viene reso sicuro: su Windows, se e' rediretto, usa cp1252 e "→" lo romperebbe.
"""
# librerie standard: log, flussi del processo
import logging
import sys

LOG_HTTP = True  # True = mostra nel terminale le richieste HTTP (verso LM Studio o verso l'agente)
LOG_GRAFO = True  # True = mostra nel terminale i log di router, agente, rifiuto, revisore, api
# logger del grafo e del servizio: nel terminale compaiono come [router], [agente], ...
LOGGER_GRAFO = ("router", "agente", "rifiuto", "revisore", "riassunto", "mcp", "preferenze", "api")


# un carattere che la codifica del flusso non conosce diventa \uXXXX invece di un errore
def rendi_sicuro(flusso) -> None:
    riconfigura = getattr(flusso, "reconfigure", None)
    # flussi senza reconfigure (come quelli finti di pytest): si lasciano come sono
    if riconfigura is not None:
        riconfigura(errors="backslashreplace")


# accende a livello INFO i logger in `nomi_info` e spegne (CRITICAL) quelli in `spenti`
def configura_log(nomi_info: tuple[str, ...], spenti: tuple[str, ...] = (), flusso=None) -> None:
    flusso = flusso if flusso is not None else sys.stderr
    rendi_sicuro(flusso)
    # formato: nome del logger tra parentesi quadre, poi il messaggio
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=flusso)
    for nome in nomi_info:
        logging.getLogger(nome).setLevel(logging.INFO)
    for nome in spenti:
        logging.getLogger(nome).setLevel(logging.CRITICAL)
