"""Servizio HTTP della calcolatrice sicura e di giorni e scadenze.

Avvio locale, da L5\\assistente-laboratorio:
    python -m uvicorn servizio.main:app --port 8001
"""
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from servizio.calcolatrice import ErroreCalcolo, calcola
from servizio.date_lavoro import ErroreData, calcola_scadenza, conta_giorni, info_giorno

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


class RichiestaGiorni(BaseModel):
    # gli argomenti obbligatori per l'operazione si controllano nella logica (400 con il motivo);
    # quelli che l'operazione non usa vengono ignorati
    operazione: Literal["giorni", "scadenza", "giorno"]
    data: str | None = Field(default=None, strict=True)
    da: str | None = Field(default=None, strict=True)
    giorni: int | None = Field(default=None, strict=True)
    tipo: Literal["lavorativi", "calendario"] = "lavorativi"


@app.post("/giorni")
def giorni_endpoint(richiesta: RichiestaGiorni):
    try:
        if richiesta.operazione == "giorni":
            return conta_giorni(richiesta.data, richiesta.da)
        if richiesta.operazione == "scadenza":
            return calcola_scadenza(richiesta.giorni, richiesta.da, richiesta.tipo)
        return info_giorno(richiesta.data)
    except ErroreData as errore:
        return JSONResponse(status_code=400, content={"errore": str(errore)})


@app.get("/salute")
def salute():
    return {"stato": "ok"}
