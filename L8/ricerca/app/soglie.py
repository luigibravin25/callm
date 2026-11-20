"""Soglie di confidenza sullo score (lezione 8, esercizio 4): fascia di ogni passaggio e filtro (funzioni pure)."""
from app.indice import Risultato

# fasce dei passaggi inviati al modello; sotto la soglia bassa il passaggio è escluso
AFFIDABILE = "affidabile"
MEDIA = "media"


# decimali dello score usati per la fascia: gli stessi mostrati nel risultato del tool
DECIMALI = 4


def fascia(score: float, alta: float, bassa: float) -> str | None:
    """Fascia dello score coseno a 4 decimali: affidabile da `alta` in su, media da `bassa` in su, None sotto."""
    # Qdrant calcola lo score in float32 (0.51 diventa 0.50999999): si confronta il valore mostrato nel risultato
    score = round(score, DECIMALI)
    if score >= alta:
        return AFFIDABILE
    if score >= bassa:
        return MEDIA
    # sotto la soglia bassa: escluso, non inviato al modello
    return None


def filtra(risultati: list[Risultato], alta: float, bassa: float) -> tuple[list[tuple[Risultato, str]], int]:
    """Risultati rimasti con la loro fascia, nell'ordine ricevuto, e numero dei risultati esclusi."""
    rimasti: list[tuple[Risultato, str]] = []
    for r in risultati:
        f = fascia(r.score, alta, bassa)
        if f is not None:
            rimasti.append((r, f))
    return rimasti, len(risultati) - len(rimasti)
