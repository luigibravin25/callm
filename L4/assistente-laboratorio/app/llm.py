from langchain_openai import ChatOpenAI

from app.config import Settings
from app.tools import STRUMENTI

SYSTEM_PROMPT = "Sei un assistente utile"
STREAM = True  # True = token per token, False = risposta in blocco
HISTORY = True  # True = il modello ricorda i messaggi precedenti, False = ogni domanda parte da zero
LOG_HTTP = True  # True = mostra nel terminale le richieste HTTP verso LM Studio
LOG_GRAFO = True  # True = mostra nel terminale i log del grafo (chiamate agli strumenti, limite)


def build_llm(settings: Settings):
    modello = ChatOpenAI(
        base_url=settings.base_url,
        model=settings.model,
        api_key="lm-studio",  # LM Studio ignora la chiave: valore fittizio, non un segreto
        temperature=0.2,
        timeout=300,
        max_tokens=4096,  # il modello ragiona prima di rispondere: servono token a sufficienza
    )
    return modello.bind_tools(STRUMENTI)
