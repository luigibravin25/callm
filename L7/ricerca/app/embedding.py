"""Embedding da LM Studio (/v1/embeddings): lo stesso modello e la stessa funzione per chunk e domande."""
# librerie standard: interfacce per i tipi
from typing import Protocol

# client compatibile con l'API OpenAI, usato verso LM Studio
import openai

from app.errori import ErroreRicerca


# interfaccia minima: i test usano un embedder finto con lo stesso metodo
class Embedder(Protocol):
    def incorpora(self, testi: list[str]) -> list[list[float]]: ...


# embedder reale: LM Studio sull'host, testi mandati a lotti
class EmbedderLMStudio:
    def __init__(self, base_url: str, modello: str, lotto: int = 32, client=None):
        self.base_url = base_url
        self.modello = modello
        self.lotto = lotto
        # LM Studio non controlla la chiave, ma il client ne vuole una
        self.client = client if client is not None else openai.OpenAI(base_url=base_url, api_key="lm-studio")

    def incorpora(self, testi: list[str]) -> list[list[float]]:
        """Un vettore per testo, nell'ordine dei testi."""
        vettori: list[list[float]] = []
        for inizio in range(0, len(testi), self.lotto):
            lotto = testi[inizio:inizio + self.lotto]
            try:
                risposta = self.client.embeddings.create(model=self.modello, input=lotto)
            except openai.OpenAIError as errore:
                # LM Studio spento, modello non caricato, errore HTTP
                raise ErroreRicerca(f"embedding non riuscito da LM Studio ({self.base_url}, modello "
                                    f"{self.modello}): {errore}. Avviare LM Studio e caricare il modello "
                                    "indicato in EMBEDDING_MODEL") from errore
            ricevuti = [elemento.embedding for elemento in risposta.data]
            # un vettore per ogni testo mandato, altrimenti la risposta non è affidabile
            if len(ricevuti) != len(lotto):
                raise ErroreRicerca(f"risposta inattesa da LM Studio ({self.base_url}, modello {self.modello}): "
                                    f"{len(ricevuti)} vettori per {len(lotto)} testi")
            vettori.extend(ricevuti)
        return vettori
