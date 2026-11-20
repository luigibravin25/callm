"""Oggetti finti per i test: embedder deterministico senza LM Studio."""
# librerie standard: impronte dei testi
import hashlib

from app.errori import ErroreRicerca


# embedder finto: stesso testo → stesso vettore, testi diversi → vettori diversi; registra le chiamate
class EmbedderFinto:
    def __init__(self, dimensione: int = 8, fallisci_alla_chiamata: int | None = None):
        self.dimensione = dimensione
        self.fallisci_alla_chiamata = fallisci_alla_chiamata  # numero della chiamata (da 1) che fallisce
        self.chiamate: list[list[str]] = []

    # vettore dai byte dell'impronta SHA-256 del testo, valori tra -1 e 1
    def _vettore(self, testo: str) -> list[float]:
        impronta = hashlib.sha256(testo.encode("utf-8")).digest()
        return [impronta[i % len(impronta)] / 127.5 - 1 for i in range(self.dimensione)]

    def incorpora(self, testi: list[str]) -> list[list[float]]:
        self.chiamate.append(list(testi))
        # simula LM Studio che smette di rispondere a metà
        if self.fallisci_alla_chiamata == len(self.chiamate):
            raise ErroreRicerca("LM Studio non risponde (embedder finto)")
        return [self._vettore(t) for t in testi]


# modello di chat finto (lezione 8, esercizio 3): restituisce o solleva le risposte preparate, in ordine,
# e registra ogni chiamata come (sistema, utente, nome dello schema)
class ChatFinta:
    def __init__(self, risposte: list):
        self.risposte = list(risposte)
        self.chiamate: list[tuple[str, str, str]] = []

    def completa_json(self, sistema: str, utente: str, nome_schema: str, schema: dict) -> str:
        self.chiamate.append((sistema, utente, nome_schema))
        # più chiamate delle risposte preparate: il test è sbagliato
        assert self.risposte, "ChatFinta: nessuna risposta preparata per questa chiamata"
        risposta = self.risposte.pop(0)
        # un'eccezione preparata simula LM Studio che non risponde
        if isinstance(risposta, Exception):
            raise risposta
        return risposta
