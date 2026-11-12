# libreria standard: log nel terminale; tipi con valori fissi
import logging
from typing import Literal

# messaggi della conversazione; errori di LM Studio (connessione, HTTP); schema dell'output
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import APIError
from pydantic import BaseModel, Field, create_model

# ambito dell'agente letto da config/ambito.toml; nome riservato per il fuori ambito
from app.config import ALTRO, Ambito
from app.revisore import REVISORE

# logger del router: i suoi messaggi compaiono come "[router] ..."
logger = logging.getLogger("router")

# il router decide solo l'ambito: gli strumenti li sceglie l'agente (consegna, punto 04)
FRASE_NO_STRUMENTI = "Non decidere quali strumenti usare: lo decide l'assistente dopo di te."
# con gemma il router rifiutava "Che ore sono a Tokyo?" giudicando se l'assistente avesse
# abbastanza dettagli per rispondere: conta solo l'argomento della domanda
FRASE_SOLO_ARGOMENTO = (
    "Valuta solo l'argomento della domanda, non se l'assistente ha abbastanza dettagli per "
    "rispondere: l'assistente ha strumenti per l'ora di qualunque città e usa un fuso "
    "predefinito se il luogo manca.")
# un output in dubbio deve far passare la domanda, come l'output non valido
FRASE_NEL_DUBBIO = "Nel dubbio scegli l'argomento più vicino, non altro."

MAX_ERRORE = 100  # caratteri massimi dell'errore riportato nel motivo e nel log


# decisione del router usata dal grafo: la categoria la ricava decidi() dall'argomento
class DecisioneRouter(BaseModel):
    # motivo per primo: il modello scrive i campi in quest'ordine, cosi' ragiona prima di
    # decidere (con categoria per prima gemma scriveva "rientra" e poi fuori_ambito)
    motivo: str = Field(description="motivo breve della decisione, in italiano")
    # Literal: ogni altro valore e' un errore di validazione (output non valido)
    categoria: Literal["conversazione", "fuori_ambito"] = Field(
        description="conversazione se la domanda rientra nell'ambito, altrimenti fuori_ambito")
    # argomento scelto dal modello (vuoto se la decisione non viene dallo schema per argomento)
    argomento: str = ""


# schema mandato a LM Studio (json_schema): motivo, poi un argomento tra quelli dell'ambito o
# "altro". Con gemma e2b l'elenco chiuso decide meglio di conversazione/fuori_ambito (step 5)
def schema_router(ambito: Ambito) -> type[BaseModel]:
    nomi = tuple(a.nome for a in ambito.argomenti) + (ALTRO,)
    return create_model(
        "DecisioneArgomento",
        motivo=(str, Field(description="motivo breve della decisione, in italiano")),
        argomento=(Literal[nomi], Field(description="argomento della domanda")))


# costruisce il prompt di sistema del router a partire dall'ambito
def prompt_router(ambito: Ambito) -> str:
    """Istruzioni del router: descrizione dell'ambito, esempi e formato della risposta."""
    righe = [
        "Sei il router di un assistente. Devi solo decidere se l'ultima domanda dell'utente "
        "rientra nell'ambito dell'assistente.",
        "Ambito dell'assistente:",
        ambito.descrizione,
        "Argomenti dell'assistente:",
    ]
    # un argomento per riga, poi "altro" per tutto cio' che e' fuori ambito
    righe += [f"- {a.nome}: {a.descrizione}" for a in ambito.argomenti]
    righe += [f"- {ALTRO}: tutto il resto (fuori ambito)",
              FRASE_SOLO_ARGOMENTO, FRASE_NO_STRUMENTI, FRASE_NEL_DUBBIO]
    # gli esempi sono facoltativi: si aggiungono solo se il file li contiene
    if ambito.esempi_in_ambito:
        righe.append("Esempi di argomenti dell'assistente: " + "; ".join(ambito.esempi_in_ambito))
    if ambito.esempi_fuori_ambito:
        righe.append(f"Esempi di {ALTRO}: " + "; ".join(ambito.esempi_fuori_ambito))
    righe.append("Rispondi con un motivo breve in italiano e l'argomento della domanda.")
    return "\n".join(righe)


# sceglie cosa mandare al router: l'ultima domanda e, se c'e', la risposta che la precede
def messaggi_per_router(ambito: Ambito, messages: list) -> list:
    """Prompt del router + ultima domanda, con l'ultima risposta finale dell'assistente come
    contesto (cosi' "e a Londra?" dopo l'ora di Tokyo resta in ambito). Niente ToolMessage."""
    # posizione dell'ultima domanda vera dell'utente (i messaggi del revisore non contano)
    indice = max(i for i, m in enumerate(messages)
                 if isinstance(m, HumanMessage) and m.name != REVISORE)
    domanda = str(messages[indice].content)
    # ultima risposta finale dell'assistente prima della domanda (testo, senza tool_calls)
    precedente = next((m for m in reversed(messages[:indice])
                       if isinstance(m, AIMessage) and not m.tool_calls
                       and str(m.content).strip()), None)
    if precedente is None:
        testo = domanda
    else:
        testo = (f"Risposta precedente dell'assistente: {precedente.content}"
                 f"\n\nDomanda dell'utente: {domanda}")
    return [SystemMessage(prompt_router(ambito)), HumanMessage(testo)]


# chiede la decisione al router; un output non valido manda la domanda all'agente
def decidi(router_llm, ambito: Ambito, messages: list) -> DecisioneRouter:
    """Decisione del router. Gli errori di LM Studio (APIError) salgono al chiamante; ogni
    altro problema (JSON rotto, categoria sconosciuta, risposta vuota) diventa conversazione."""
    # fuori dal try: un errore di programma qui sale, non diventa "output non valido"
    messaggi = messaggi_per_router(ambito, messages)
    try:
        decisione = router_llm.invoke(messaggi)
    except APIError:
        raise  # LM Studio irraggiungibile o errore HTTP: non e' un output non valido
    except Exception as errore:  # validazione o parsing falliti
        problema = f"{type(errore).__name__}: {errore}"[:MAX_ERRORE]
    else:
        if isinstance(decisione, DecisioneRouter):
            return decisione
        # output dello schema per argomento: "altro" = fuori ambito, ogni altro = conversazione
        argomento = getattr(decisione, "argomento", None)
        if isinstance(argomento, str) and isinstance(getattr(decisione, "motivo", None), str):
            categoria = "fuori_ambito" if argomento == ALTRO else "conversazione"
            return DecisioneRouter(motivo=decisione.motivo, categoria=categoria,
                                   argomento=argomento)
        # None: il modello non ha prodotto la risposta (per esempio token finiti nel ragionamento)
        problema = f"risposta {type(decisione).__name__}"[:MAX_ERRORE]
    logger.warning("output non valido (%s): la domanda passa all'agente", problema)
    return DecisioneRouter(categoria="conversazione",
                           motivo=f"output del router non valido: {problema}")
