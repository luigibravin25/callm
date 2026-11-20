"""Messaggi comprensibili per gli errori di LM Studio (spostati dalla CLI allo step 6: ora li usa
il servizio dell'agente per il campo "messaggio" delle risposte d'errore)."""
# errori del client OpenAI verso LM Studio
from openai import APIError, APIStatusError, LengthFinishReasonError, OpenAIError

MAX_DETTAGLIO = 300  # caratteri massimi del messaggio del server: evita muri di testo
MSG_CONNESSIONE = (
    "Impossibile raggiungere LM Studio. Controlla che il server sia avviato "
    "e che LM_BASE_URL sia corretto."
)
MSG_TOKEN_FINITI = ("Il modello ha finito i token prima di completare la risposta strutturata: "
                    "aumenta il budget di token o riprova.")


# testo dell'errore su una riga, senza spazi multipli, troncato
def _dettaglio(errore: OpenAIError) -> str:
    testo = getattr(errore, "message", None) or str(errore)
    # split/join riduce a capo e spazi multipli a uno spazio solo
    return " ".join(str(testo).split())[:MAX_DETTAGLIO]


# trasforma un errore HTTP di LM Studio in un messaggio comprensibile (come L5)
def messaggio_errore_http(errore: APIStatusError) -> str:
    testo = (f"Il server di LM Studio ha risposto con errore {errore.status_code}: "
             f"{_dettaglio(errore)}")
    # per i due errori piu' comuni si aggiunge cosa controllare
    if errore.status_code == 400:
        testo += " Controlla la Context Length del modello e il template di prompt in LM Studio."
    elif errore.status_code == 404:
        testo += " Controlla che il modello sia caricato e che LM_MODEL sia corretto."
    return testo


# errori di LM Studio senza codice HTTP; per il contesto pieno, cosa fare
def messaggio_errore_generico(errore: OpenAIError) -> str:
    # LengthFinishReasonError non e' un APIError: token finiti nell'output strutturato
    if isinstance(errore, LengthFinishReasonError):
        return MSG_TOKEN_FINITI
    dettaglio = _dettaglio(errore)
    testo = f"Errore da LM Studio: {dettaglio}"
    if isinstance(errore, APIError) and "context" in dettaglio.lower():
        testo += (" La conversazione ha superato il contesto del modello: aumenta la Context "
                  "Length in LM Studio, oppure riparti con una conversazione nuova.")
    return testo
