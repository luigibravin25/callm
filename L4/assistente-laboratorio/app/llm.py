from langchain_openai import ChatOpenAI

from app.config import Settings
from app.tools import STRUMENTI


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
