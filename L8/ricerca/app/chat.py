"""Modello di chat di LM Studio (/v1/chat/completions) con risposta JSON vincolata da uno schema (lezione 8)."""
# librerie standard: interfacce per i tipi
from typing import Protocol

# client compatibile con l'API OpenAI, usato verso LM Studio
import openai

from app.errori import ErroreRicerca


# interfaccia minima: i test usano un modello finto con lo stesso metodo
class Chat(Protocol):
    def completa_json(self, sistema: str, utente: str, nome_schema: str, schema: dict) -> str: ...


# modello reale: LM Studio sull'host, structured output con temperatura 0
class ChatLMStudio:
    def __init__(self, base_url: str, modello: str, client=None, timeout: float = 60.0, max_tokens: int = 1024):
        self.base_url = base_url
        self.modello = modello
        self.max_tokens = max_tokens
        # LM Studio non controlla la chiave, ma il client ne vuole una; il timeout evita attese senza fine
        self.client = client if client is not None else openai.OpenAI(base_url=base_url, api_key="lm-studio",
                                                                      timeout=timeout)

    def completa_json(self, sistema: str, utente: str, nome_schema: str, schema: dict) -> str:
        """Testo della risposta (JSON secondo `schema`); errore di LM Studio o risposta vuota → ErroreRicerca."""
        try:
            risposta = self.client.chat.completions.create(
                model=self.modello,
                messages=[{"role": "system", "content": sistema}, {"role": "user", "content": utente}],
                # temperatura 0: stesse risposte a parità di domanda (confronto riproducibile)
                temperature=0,
                max_tokens=self.max_tokens,
                # structured output di LM Studio: la risposta deve rispettare lo schema
                response_format={"type": "json_schema",
                                 "json_schema": {"name": nome_schema, "strict": True, "schema": schema}})
        except openai.OpenAIError as errore:
            # LM Studio spento, modello non caricato, timeout, errore HTTP
            raise ErroreRicerca(f"chat non riuscita da LM Studio ({self.base_url}, modello {self.modello}): "
                                f"{errore}") from errore
        contenuto = risposta.choices[0].message.content
        # nessun testo (per esempio un modello che ragiona e finisce i token): risposta inutilizzabile
        if contenuto is None:
            raise ErroreRicerca(f"risposta vuota da LM Studio ({self.base_url}, modello {self.modello})")
        return contenuto
