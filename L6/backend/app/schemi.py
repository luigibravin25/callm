"""Modelli Pydantic dell'API del back-end (contratto per il front-end, documentato in OpenAPI).

Lo stato dell'agente (cronologia_agente, riassunto) non compare: resta interno al back-end.
"""
# librerie standard: date
from datetime import datetime
from typing import Literal

# Pydantic: modelli, configurazione, validatori
from pydantic import BaseModel, ConfigDict, Field, field_validator


# chat appena creata
class ChatCreata(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    titolo: str
    creata_il: datetime


# una riga dell'elenco delle chat
class ChatInElenco(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    titolo: str
    ultimo_messaggio_il: datetime | None = Field(
        description="ora dell'ultima risposta; null se la chat non ha ancora messaggi")


# un messaggio visibile della chat
class MessaggioChat(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ruolo: Literal["utente", "assistente"]
    testo: str
    strumenti: list[dict] | None = Field(
        description="solo per l'assistente: strumenti usati nel turno [{nome, argomenti}]")
    creato_il: datetime


# chat con tutti i messaggi in ordine cronologico
class ChatCompleta(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    titolo: str
    creata_il: datetime
    ultimo_messaggio_il: datetime | None
    messaggi: list[MessaggioChat]


# corpo di POST /chat/{id}/messaggi
class NuovoMessaggio(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"testo": "Che ore sono a Tokyo?"}]})
    testo: str

    # un testo di soli spazi non arriva all'agente
    @field_validator("testo")
    @classmethod
    def _non_vuoto(cls, valore: str) -> str:
        if not valore.strip():
            raise ValueError("testo vuoto")
        # PostgreSQL non accetta il carattere NUL nei testi: errore chiaro invece di un 500
        if "\x00" in valore:
            raise ValueError("testo con caratteri non ammessi (NUL)")
        return valore


# esito di un turno: la domanda salvata e la risposta dell'agente salvata
class Turno(BaseModel):
    domanda: MessaggioChat
    risposta: MessaggioChat


# corpo di ogni errore
class Errore(BaseModel):
    errore: str = Field(description="codice stabile, es. agente_non_raggiungibile")
    messaggio: str = Field(description="spiegazione in italiano")


# impostazioni lette dal front-end all'avvio (step 10)
class Impostazioni(BaseModel):
    streaming: bool = Field(description="risposte in streaming disponibili (variabile STREAMING)")
