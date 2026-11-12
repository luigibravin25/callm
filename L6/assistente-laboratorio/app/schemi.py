"""Schemi dell'API dell'agente (step 6): richieste, risposte, errori, stato.

La cronologia viaggia nel formato dei messaggi OpenAI (role, content, tool_calls, tool_call_id,
name): e' uno standard, non lega chi chiama a LangChain e conserva le chiamate agli strumenti.
Qui c'e' anche la conversione tra quel formato e i messaggi LangChain usati dal grafo.
"""
# librerie standard: lettura degli argomenti JSON delle chiamate
import json
from typing import Literal

# messaggi LangChain e conversione da e verso il formato OpenAI
from langchain_core.messages import (BaseMessage, convert_to_messages,
                                     convert_to_openai_messages)
# modelli Pydantic: validazione dei dati e schema OpenAPI per /docs
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# tipi dei prompt pubblicati dal server MCP
from app.info_prompt import InfoArgomento, InfoPrompt

# name riservato ai messaggi del revisore: li toglie il grafo, un client non li puo' mandare
NOME_REVISORE = "revisore"
# esempio di domanda per la documentazione /docs
DOMANDA_ESEMPIO = "Che ore sono a Tokyo?"


# --- formato dei messaggi OpenAI ---

# funzione chiamata dal modello: nome e argomenti in testo JSON (come in OpenAI)
class FunzioneChiamata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: str

    # gli argomenti devono essere un oggetto JSON: altrimenti il grafo non li saprebbe usare
    @field_validator("arguments")
    @classmethod
    def _oggetto_json(cls, valore: str) -> str:
        try:
            dati = json.loads(valore)
        except json.JSONDecodeError:
            raise ValueError("arguments non è un oggetto JSON") from None
        if not isinstance(dati, dict):
            raise ValueError("arguments non è un oggetto JSON")
        return valore


# una chiamata a uno strumento chiesta dal modello
class ChiamataStrumento(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["function"] = "function"
    function: FunzioneChiamata


# un messaggio della cronologia nel formato OpenAI
class MessaggioOpenAI(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # "system" non e' tra i valori: il prompt di sistema lo mette il grafo (gemma ne vuole uno)
    role: Literal["user", "assistant", "tool"]
    content: str = ""

    # il prompt di sistema lo mette il grafo: un messaggio "system" ha il suo errore chiaro
    @model_validator(mode="before")
    @classmethod
    def _niente_system(cls, dati):
        if isinstance(dati, dict) and dati.get("role") == "system":
            raise ValueError("messaggi di sistema non ammessi")
        return dati

    # formato OpenAI standard: content null (assistant con tool_calls) o a blocchi -> testo
    @field_validator("content", mode="before")
    @classmethod
    def _contenuto_in_testo(cls, valore):
        if valore is None:
            return ""
        if isinstance(valore, list):
            return _testo(valore)
        return valore
    tool_calls: list[ChiamataStrumento] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    # la risposta di uno strumento deve dire a quale chiamata risponde
    @model_validator(mode="after")
    def _tool_con_id(self):
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("un messaggio 'tool' vuole tool_call_id")
        return self


# --- richiesta e risposta di POST /chat ---

# prompt del server MCP da usare al posto del messaggio (comando /prompt della CLI)
class RichiestaPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str
    argomenti: dict[str, str] = {}


# richiesta di POST /chat: messaggio OPPURE prompt, piu' cronologia e riassunto del chiamante
class RichiestaChat(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"messaggio": DOMANDA_ESEMPIO, "cronologia": [], "riassunto": ""},
        {"prompt": {"nome": "spiega", "argomenti": {"argomento": "MCP", "livello": "base"}},
         "cronologia": [], "riassunto": ""},
    ]})
    messaggio: str | None = None
    prompt: RichiestaPrompt | None = None
    cronologia: list[MessaggioOpenAI] = []
    riassunto: str = ""

    # controlli che coinvolgono piu' campi: uno solo tra messaggio e prompt, cronologia pulita
    @model_validator(mode="after")
    def _controlla(self):
        if self.messaggio is None and self.prompt is None:
            raise ValueError("serve messaggio oppure prompt")
        if self.messaggio is not None and self.prompt is not None:
            raise ValueError("messaggio e prompt insieme non sono ammessi")
        if self.messaggio is not None and not self.messaggio.strip():
            raise ValueError("messaggio vuoto")
        for i, m in enumerate(self.cronologia):
            # i messaggi del revisore non tornano mai al chiamante: non si possono iniettare
            if m.name == NOME_REVISORE:
                raise ValueError(f"cronologia[{i}]: name '{NOME_REVISORE}' riservato")
        return self


# uno strumento eseguito nel turno, con gli argomenti usati
class StrumentoUsato(BaseModel):
    nome: str
    argomenti: dict


# risposta di POST /chat
class RispostaChat(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "risposta": "A Tokyo sono le 01:12.",
        "strumenti_usati": [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}],
        "categoria": "conversazione", "argomento": "ora_data_fusi",
        "cronologia": [{"role": "user", "content": DOMANDA_ESEMPIO},
                       {"role": "assistant", "content": "A Tokyo sono le 01:12."}],
        "riassunto": "",
    }]})
    risposta: str
    strumenti_usati: list[StrumentoUsato]
    categoria: str
    argomento: str | None = Field(
        description="argomento scelto dal router ('altro' = fuori ambito); null se il suo "
                    "output non era valido")
    cronologia: list[MessaggioOpenAI]
    riassunto: str


# --- prompt pubblicati (GET /prompts) ---

class ArgomentoPrompt(BaseModel):
    nome: str
    obbligatorio: bool


class PromptPubblicato(BaseModel):
    nome: str
    descrizione: str
    argomenti: list[ArgomentoPrompt]


# InfoPrompt (adattatore) -> schema JSON
def da_info(p: InfoPrompt) -> PromptPubblicato:
    return PromptPubblicato(nome=p.nome, descrizione=p.descrizione,
                            argomenti=[ArgomentoPrompt(nome=a.nome, obbligatorio=a.obbligatorio)
                                       for a in p.argomenti])


# JSON di GET /prompts -> InfoPrompt (la CLI lo usa con i comandi)
def a_info(p: dict) -> InfoPrompt:
    return InfoPrompt(p["nome"], p.get("descrizione", ""),
                      tuple(InfoArgomento(a["nome"], bool(a["obbligatorio"]))
                            for a in p.get("argomenti", [])))


# --- errori e stato ---

# corpo di ogni errore dell'API
class Errore(BaseModel):
    errore: str = Field(description="codice stabile, es. modello_non_raggiungibile")
    messaggio: str = Field(description="spiegazione in italiano")


# stato di una parte (modello o server MCP)
class ParteStato(BaseModel):
    stato: str  # ok, non_raggiungibile, modello_assente, non_disponibile
    messaggio: str = ""


class StatoMCP(ParteStato):
    strumenti: list[str] = []
    prompt: int = 0


class StatoModello(ParteStato):
    nome: str = ""


# risposta di GET /stato
class Stato(BaseModel):
    agente: str
    mcp: StatoMCP
    modello: StatoModello


# --- conversione dei messaggi ---

# contenuto a blocchi (lista) -> testo unico; il formato dell'API vuole testo
def _testo(contenuto) -> str:
    if isinstance(contenuto, str):
        return contenuto
    if isinstance(contenuto, list):
        return "".join(b if isinstance(b, str) else str(b.get("text", "")) for b in contenuto)
    return str(contenuto)


# formato OpenAI -> messaggi LangChain per il grafo
def da_openai(cronologia: list[MessaggioOpenAI]) -> list[BaseMessage]:
    return convert_to_messages([m.model_dump(exclude_none=True) for m in cronologia])


# messaggi LangChain del grafo -> formato OpenAI per il chiamante
def a_openai(messaggi: list[BaseMessage]) -> list[MessaggioOpenAI]:
    risultato = []
    for dati in convert_to_openai_messages(messaggi):
        dati["content"] = _testo(dati.get("content", ""))
        # solo i campi del formato dell'API (convert_to_openai_messages puo' aggiungerne altri)
        campi = {k: v for k, v in dati.items() if k in MessaggioOpenAI.model_fields}
        risultato.append(MessaggioOpenAI.model_validate(campi))
    return risultato
