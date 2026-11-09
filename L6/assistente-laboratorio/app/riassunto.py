# libreria standard: log nel terminale
import logging

# messaggi della conversazione; errori di LM Studio (connessione, HTTP)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai import APIError

# name dei messaggi del revisore: non sono domande vere, quindi non sono confini di turno
from app.revisore import REVISORE

# logger del riassunto: i suoi messaggi compaiono come "[riassunto] ..."
logger = logging.getLogger("riassunto")

MAX_ERRORE = 100  # caratteri massimi dell'errore riportato nel log

# regole del riassunto (costanti: i test controllano che siano nel prompt)
FRASE_CONSERVA = ("Conserva i nomi, le preferenze e i fatti detti dall'utente e le risposte "
                  "date.")
FRASE_LUNGHEZZA = "Scrivi in italiano, al massimo 150 parole, in testo semplice."


# prompt di sistema del modello che riassume
def prompt_riassunto() -> str:
    return "\n".join([
        "Riassumi una conversazione tra un utente e un assistente. Ricevi il riassunto "
        "precedente (se c'e') e la parte di conversazione da aggiungere: scrivi un solo "
        "riassunto aggiornato che li unisce.",
        FRASE_CONSERVA,
        FRASE_LUNGHEZZA,
    ])


# trasforma i messaggi in testo: una riga per messaggio, con chi parla
def trascrizione(messages: list) -> str:
    righe = []
    for m in messages:
        if isinstance(m, HumanMessage):
            righe.append(f"Utente: {m.content}")
        elif isinstance(m, ToolMessage):
            righe.append(f"Strumento {m.name}: {m.content}")
        elif isinstance(m, AIMessage):
            if str(m.content).strip():
                righe.append(f"Assistente: {m.content}")
            else:
                # risposta fatta solo di chiamate: si dice quali strumenti ha usato
                nomi = ", ".join(c["name"] for c in m.tool_calls)
                righe.append(f"Assistente: (usa lo strumento {nomi})")
    return "\n".join(righe)


# messaggi mandati al modello: riassunto vecchio + conversazione che esce dalla cronologia
def messaggi_per_riassunto(riassunto_vecchio: str, messages: list) -> list:
    precedente = riassunto_vecchio.strip() or "nessuno"
    testo = (f"Riassunto precedente: {precedente}\n\n"
             f"Conversazione da aggiungere:\n{trascrizione(messages)}")
    return [SystemMessage(prompt_riassunto()), HumanMessage(testo)]


# dove tagliare: i messaggi prima dell'indice si riassumono, gli altri restano interi
def indice_di_taglio(messages: list, recenti: int) -> int:
    """Si parte da len - recenti e si arretra fino all'inizio di un turno (una domanda vera
    dell'utente), cosi' restano almeno `recenti` messaggi e nessuna coppia strumento si rompe.
    Se arretrando non resta niente da riassumere, si avanza alla domanda successiva."""
    confini = [i for i, m in enumerate(messages)
               if isinstance(m, HumanMessage) and m.name != REVISORE]
    punto = len(messages) - recenti
    indietro = [i for i in confini if 0 < i <= punto]
    if indietro:
        return max(indietro)
    avanti = [i for i in confini if i > 0]  # un solo turno lungo: si avanza
    return min(avanti) if avanti else 0


# chiede il riassunto al modello; None se non riesce (i messaggi allora restano)
def riassumi(riassunto_llm, riassunto_vecchio: str, messages: list) -> str | None:
    # i messaggi si costruiscono fuori dal try: un errore di programmazione non va nascosto
    messaggi = messaggi_per_riassunto(riassunto_vecchio, messages)
    try:
        risposta = riassunto_llm.invoke(messaggi)
    except APIError:
        raise  # LM Studio irraggiungibile o errore HTTP: sale alla CLI
    except Exception as errore:
        problema = f"{type(errore).__name__}: {errore}"[:MAX_ERRORE]
    else:
        testo = str(risposta.content).strip()
        if testo:
            return testo
        problema = "risposta vuota"  # per esempio token finiti nel ragionamento
    logger.warning("riassunto non riuscito (%s): messaggi conservati", problema)
    return None
