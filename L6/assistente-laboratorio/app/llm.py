# client LangChain per le API compatibili con OpenAI (come quella di LM Studio)
from langchain_openai import ChatOpenAI

# configurazione, schema della decisione del router, strumenti dell'agente
from app.config import Settings
from app.revisore import DecisioneRevisore
from app.router import DecisioneRouter
from app.tools import STRUMENTI

# l'agente deve sapere che i messaggi [Revisore] non vengono dall'utente (step 2)
FRASE_REVISORE = ("Un messaggio che inizia con [Revisore] non viene dall'utente: è "
                  "un'indicazione per correggere la tua risposta; seguila senza citarla.")
# prompt di sistema dell'agente: regola dell'orologio come in L5 e testo senza Markdown
SYSTEM_PROMPT = (
    "Sei un assistente utile. Se l'utente chiede l'ora o la data senza indicare "
    "un luogo, chiama tooltime senza l'argomento fuso. "
    # il terminale non interpreta il Markdown: gli asterischi resterebbero visibili
    "Rispondi in testo semplice, senza asterischi e senza grassetto. " + FRASE_REVISORE)
LOG_HTTP = True  # True = mostra nel terminale le richieste HTTP verso LM Studio
LOG_GRAFO = True  # True = mostra nel terminale i log di router, agente, rifiuto e revisore


# crea il modello di LM Studio con i parametri comuni ad agente e router
def _chat(settings: Settings, temperature: float, max_tokens: int) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.base_url,
        model=settings.model,
        api_key="lm-studio",  # LM Studio ignora la chiave: valore fittizio, non un segreto
        temperature=temperature,
        timeout=300,  # secondi di attesa massima: un modello locale puo' essere lento
        # il modello ragiona prima di rispondere: servono token a sufficienza
        max_tokens=max_tokens,
    )


# modello dell'agente: conosce gli strumenti (bind_tools manda nome, descrizione e argomenti)
def build_llm(settings: Settings, strumenti=STRUMENTI, max_tokens: int = 8192):
    return _chat(settings, temperature=0.2, max_tokens=max_tokens).bind_tools(strumenti)


# modello del router: stesso modello, nessuno strumento, risposta vincolata allo schema
def build_router_llm(settings: Settings, max_tokens: int = 2048):
    # json_schema: LM Studio riceve lo schema come response_format e vincola l'output
    return _chat(settings, temperature=0, max_tokens=max_tokens).with_structured_output(
        DecisioneRouter, method="json_schema")


# modello del revisore: stesso modello, nessuno strumento, risposta vincolata allo schema
def build_revisore_llm(settings: Settings, max_tokens: int = 2048):
    return _chat(settings, temperature=0, max_tokens=max_tokens).with_structured_output(
        DecisioneRevisore, method="json_schema")
