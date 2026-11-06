"""Servizio HTTP della calcolatrice sicura e di giorni e scadenze.

Avvio locale, da L5\\assistente-laboratorio:
    python -m uvicorn servizio.main:app --port 8001
"""
# Literal: limita un campo a un elenco chiuso di valori ammessi
from typing import Literal

# FastAPI crea il servizio HTTP; JSONResponse permette di scegliere il codice di stato;
# pydantic descrive e controlla il corpo JSON delle richieste
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# La logica vera sta in moduli separati: qui c'e' solo il collegamento HTTP
from servizio.calcolatrice import ErroreCalcolo, calcola
from servizio.date_lavoro import ErroreData, calcola_scadenza, conta_giorni, info_giorno

# L'applicazione FastAPI: uvicorn la avvia con "servizio.main:app"
app = FastAPI(title="Calcolatrice sicura")


# Corpo della richiesta a /calcola: {"espressione": "2+3*4"}
class Richiesta(BaseModel):
    # strict: un numero al posto del testo e' un 422, non viene convertito in stringa
    espressione: str = Field(strict=True)


# Endpoint POST /calcola: valuta l'espressione con la calcolatrice sicura
@app.post("/calcola")
def calcola_endpoint(richiesta: Richiesta):
    try:
        risultato = calcola(richiesta.espressione)
    # Espressione rifiutata: risposta 400 con il motivo leggibile
    except ErroreCalcolo as errore:
        return JSONResponse(status_code=400, content={"errore": str(errore)})
    # Successo: FastAPI trasforma il dizionario in JSON con codice 200
    return {"espressione": richiesta.espressione, "risultato": risultato}


# Corpo della richiesta a /giorni: l'operazione scelta e i suoi argomenti
class RichiestaGiorni(BaseModel):
    # gli argomenti obbligatori per l'operazione si controllano nella logica (400 con il motivo);
    # quelli che l'operazione non usa vengono ignorati
    operazione: Literal["giorni", "scadenza", "giorno"]
    data: str | None = Field(default=None, strict=True)
    da: str | None = Field(default=None, strict=True)
    giorni: int | None = Field(default=None, strict=True)
    tipo: Literal["lavorativi", "calendario"] = "lavorativi"


# Endpoint POST /giorni: smista la richiesta alla funzione di date_lavoro giusta
@app.post("/giorni")
def giorni_endpoint(richiesta: RichiestaGiorni):
    try:
        # "giorni": quanti giorni mancano a una data (o tra due date)
        if richiesta.operazione == "giorni":
            return conta_giorni(richiesta.data, richiesta.da)
        # "scadenza": data che si ottiene aggiungendo N giorni lavorativi o di calendario
        if richiesta.operazione == "scadenza":
            return calcola_scadenza(richiesta.giorni, richiesta.da, richiesta.tipo)
        # Resta solo "giorno": informazioni su una data (giorno della settimana, festivita')
        return info_giorno(richiesta.data)
    # Data non valida o argomento mancante: risposta 400 con il motivo
    except ErroreData as errore:
        return JSONResponse(status_code=400, content={"errore": str(errore)})


# Endpoint GET /salute: dice solo che il servizio e' acceso (usato per i controlli)
@app.get("/salute")
def salute():
    return {"stato": "ok"}
