"""Configurazione dei log nel terminale del back-end (stessa forma dell'agente: [nome] messaggio).

Copia piccola del modulo dell'agente: il back-end non importa codice dell'agente.
"""
# librerie standard: log, flussi del processo
import logging
import sys

LOG_HTTP = True  # True = mostra nel terminale le richieste HTTP verso l'agente


# un carattere che la codifica del flusso non conosce diventa \uXXXX invece di un errore
# (su Windows uno stderr rediretto usa cp1252 e "→" o le emoji lo romperebbero)
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
