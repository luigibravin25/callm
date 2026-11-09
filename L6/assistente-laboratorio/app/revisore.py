# libreria standard: log nel terminale
import logging

# messaggi della conversazione; errori di LM Studio (connessione, HTTP); schema dell'output
from langchain_core.messages import HumanMessage, SystemMessage
from openai import APIError
from pydantic import BaseModel, Field

# logger del revisore: i suoi messaggi compaiono come "[revisore] ..."
logger = logging.getLogger("revisore")

MAX_ERRORE = 100  # caratteri massimi dell'errore riportato nel motivo e nel log
REVISORE = "revisore"  # name dei messaggi del revisore nella cronologia (grafo e router)

# regole del revisore (costanti: i test controllano che siano nel prompt)
FRASE_TUTTE_LE_PARTI = ("Controlla che la risposta risponda a tutte le parti della domanda "
                        "e non devii dal tema.")
FRASE_NON_I_DATI = ("Non controllare se i dati sono veri: l'assistente li ha presi dai suoi "
                    "strumenti.")
FRASE_SALUTI = "Una risposta breve a un saluto o a un ringraziamento è coerente."
# ritocco 1 (prova reale con gemma): il modello scriveva "false" nel motivo e bocciava anche
# le risposte complete; il motivo deve elencare le parti coperte e quelle mancanti
FRASE_MOTIVO = ("Nel motivo elenca le parti della domanda e, per ognuna, se la risposta la "
                "copre; coerente è true se la risposta copre tutte le parti.")
# ritocco 2: con la sola regola il modello scriveva ancora "false" nel motivo; un esempio
# concreto mostra cosa va nei due campi
ESEMPIO_OUTPUT = ('Esempio per "Che ore sono a Roma e che tempo fa a Milano?" con risposta '
                  '"A Roma sono le 10.": {"motivo": "ora a Roma: coperta; tempo a Milano: '
                  'mancante", "coerente": false}')

# indicazione per l'agente quando la risposta non e' coerente (entra nella cronologia)
MSG_REVISORE = ("[Revisore] La risposta precedente non è coerente con la domanda dell'utente: "
                "{motivo}. Scrivi una nuova risposta completa alla domanda dell'utente.")


# output strutturato del revisore: LM Studio lo riceve come json_schema
class DecisioneRevisore(BaseModel):
    # motivo per primo: il modello scrive i campi in quest'ordine, cosi' ragiona prima di
    # decidere (lezione dello step 1 con il router)
    motivo: str = Field(description="parti della domanda e se la risposta le copre, in italiano")
    coerente: bool = Field(description="true se la risposta copre tutte le parti della domanda")


# prompt di sistema del revisore
def prompt_revisore() -> str:
    return "\n".join([
        "Sei il revisore di un assistente. Ricevi la domanda dell'utente e la risposta "
        "proposta dall'assistente.",
        FRASE_TUTTE_LE_PARTI,
        FRASE_NON_I_DATI,
        FRASE_SALUTI,
        FRASE_MOTIVO,
        ESEMPIO_OUTPUT,
    ])


# messaggi mandati al revisore: solo domanda e risposta, nessuna cronologia
def messaggi_per_revisore(domanda: str, risposta: str) -> list:
    return [SystemMessage(prompt_revisore()),
            HumanMessage(f"Domanda dell'utente: {domanda}\n\nRisposta proposta: {risposta}")]


# chiede la decisione al revisore; un output non valido approva la risposta
def valuta(revisore_llm, domanda: str, risposta: str) -> DecisioneRevisore:
    """Decisione del revisore. Gli errori di LM Studio (APIError) salgono al chiamante; ogni
    altro problema (JSON rotto, risposta vuota) approva la risposta con un avviso."""
    # i messaggi si costruiscono fuori dal try: un errore di programmazione qui non deve
    # diventare "output non valido" (minore della revisione dello step 1)
    messaggi = messaggi_per_revisore(domanda, risposta)
    try:
        decisione = revisore_llm.invoke(messaggi)
    except APIError:
        raise  # LM Studio irraggiungibile o errore HTTP: non e' un output non valido
    except Exception as errore:  # validazione o parsing falliti
        problema = f"{type(errore).__name__}: {errore}"[:MAX_ERRORE]
    else:
        if isinstance(decisione, DecisioneRevisore):
            return decisione
        # None: il modello non ha prodotto la risposta (per esempio token finiti nel ragionamento)
        problema = f"risposta {type(decisione).__name__}"[:MAX_ERRORE]
    logger.warning("output non valido (%s): risposta approvata", problema)
    return DecisioneRevisore(motivo=f"output del revisore non valido: {problema}",
                             coerente=True)
