"""Errore unico della ricerca: il messaggio è già pronto per chi usa gli script."""


# errore previsto (configurazione, corpus, LM Studio, Qdrant): gli script lo stampano ed escono con 1
class ErroreRicerca(Exception):
    pass
