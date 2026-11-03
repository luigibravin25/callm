"""Servizio HTTP della calcolatrice sicura.

Avvio locale, da L5\\assistente-laboratorio:
    python -m uvicorn servizio.main:app --port 8001
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from servizio.calcolatrice import ErroreCalcolo, calcola

app = FastAPI(title="Calcolatrice sicura")


class Richiesta(BaseModel):
    # strict: un numero al posto del testo e' un 422, non viene convertito in stringa
    espressione: str = Field(strict=True)


@app.post("/calcola")
def calcola_endpoint(richiesta: Richiesta):
    try:
        risultato = calcola(richiesta.espressione)
    except ErroreCalcolo as errore:
        return JSONResponse(status_code=400, content={"errore": str(errore)})
    return {"espressione": richiesta.espressione, "risultato": risultato}


@app.get("/salute")
def salute():
    return {"stato": "ok"}
