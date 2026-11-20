# client LangChain per le API compatibili con OpenAI (come quella di LM Studio)
from langchain_openai import ChatOpenAI

# configurazione, schemi delle decisioni di router e revisore, preferenze dell'utente
from app.config import Settings
from app.revisore import DecisioneRevisore
from app.router import schema_router
from app.preferenze import Preferenze, blocco_preferenze

# l'agente deve sapere che i messaggi [Revisore] non vengono dall'utente (step 2)
FRASE_REVISORE = ("Un messaggio che inizia con [Revisore] non viene dall'utente: è "
                  "un'indicazione per correggere la tua risposta; seguila senza citarla.")
# prompt di sistema dell'agente: regola dell'orologio come in L5 e testo senza Markdown
SYSTEM_PROMPT = (
    "Sei un assistente utile. Se l'utente chiede l'ora o la data senza indicare "
    "un luogo, chiama tooltime senza l'argomento fuso. "
    # il terminale non interpreta il Markdown: gli asterischi resterebbero visibili
    "Rispondi in testo semplice, senza asterischi e senza grassetto. " + FRASE_REVISORE)
# senza server MCP l'agente non ha l'orologio: non deve inventare l'ora (step 4)
FRASE_SENZA_STRUMENTI = ("Non hai strumenti: se ti chiedono l'ora o la data, di' che "
                         "l'orologio non è disponibile.")


# crea il modello di LM Studio con i parametri comuni ad agente e router; senza_streaming: il modello
# risponde sempre in un colpo solo, anche quando il grafo gira in streaming (step 10)
def _chat(settings: Settings, temperature: float, max_tokens: int,
          senza_streaming: bool = False) -> ChatOpenAI:
    return ChatOpenAI(
        disable_streaming=senza_streaming,
        base_url=settings.base_url,
        model=settings.model,
        api_key="lm-studio",  # LM Studio ignora la chiave: valore fittizio, non un segreto
        temperature=temperature,
        timeout=300,  # secondi di attesa massima: un modello locale puo' essere lento
        # il modello ragiona prima di rispondere: servono token a sufficienza
        max_tokens=max_tokens,
    )


# prompt di sistema dell'agente: blocco delle preferenze in cima, poi le regole di sempre
def prompt_agente(preferenze: Preferenze, ha_strumenti: bool) -> str:
    prompt = blocco_preferenze(preferenze) + "\n\n" + SYSTEM_PROMPT
    # senza strumenti (server MCP non partito) si aggiunge la frase che evita ore inventate
    return prompt if ha_strumenti else prompt + " " + FRASE_SENZA_STRUMENTI


# modello dell'agente: conosce gli strumenti del server MCP (bind_tools manda nome, descrizione e
# argomenti; la resource delle preferenze non e' uno strumento e non passa da qui)
def build_llm(settings: Settings, strumenti: list, max_tokens: int = 8192):
    llm = _chat(settings, temperature=0.2, max_tokens=max_tokens)
    # nessuno strumento: niente bind_tools (una lista vuota di tools non serve al modello)
    return llm.bind_tools(strumenti) if strumenti else llm


# modello del router: stesso modello, nessuno strumento, risposta vincolata allo schema; senza
# streaming: con response_format ChatOpenAI userebbe un'altra chiamata, mai provata con LM Studio
def build_router_llm(settings: Settings, ambito, max_tokens: int = 2048):
    # json_schema: LM Studio riceve lo schema come response_format e vincola l'output; lo schema
    # elenca gli argomenti dell'ambito (step 5)
    llm = _chat(settings, temperature=0, max_tokens=max_tokens, senza_streaming=True)
    return llm.with_structured_output(schema_router(ambito), method="json_schema")


# modello del revisore: stesso modello, nessuno strumento, risposta vincolata allo schema
def build_revisore_llm(settings: Settings, max_tokens: int = 2048):
    llm = _chat(settings, temperature=0, max_tokens=max_tokens, senza_streaming=True)
    return llm.with_structured_output(DecisioneRevisore, method="json_schema")


# modello del riassunto: stesso modello, nessuno strumento, risposta in testo semplice
def build_riassunto_llm(settings: Settings, max_tokens: int = 2048):
    return _chat(settings, temperature=0, max_tokens=max_tokens, senza_streaming=True)
