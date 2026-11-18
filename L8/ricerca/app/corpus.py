"""Lettura del ricettario di Artusi (Project Gutenberg n. 59047): 790 ricette con numero, titolo e capitolo.

Il file si legge direttamente come testo, senza conversione in Markdown (specifica, §7).
"""
# librerie standard: espressioni regolari, classi di dati, percorsi
import re
from dataclasses import dataclass
from pathlib import Path

from app.errori import ErroreRicerca

# i 23 capitoli nell'ordine del libro (elenco fisso, decisione dell'utente); per le minestre il
# capitolo di una ricetta è il sottocapitolo
CAPITOLI = (
    "BRODI, GELATINA E SUGHI", "MINESTRE IN BRODO", "MINESTRE ASCIUTTE E DI MAGRO", "PRINCIPII", "SALSE",
    "UOVA", "PASTE E PASTELLE", "RIPIENI", "FRITTI", "LESSO", "TRAMESSI", "UMIDI", "RIFREDDI",
    "ERBAGGI E LEGUMI", "PIATTI DI PESCE", "ARROSTI", "PASTICCERIA", "TORTE E DOLCI AL CUCCHIAIO",
    "SIROPPI", "CONSERVE", "LIQUORI", "GELATI", "COSE DIVERSE",
)
# intestazioni seguite solo da un'introduzione: chiudono la ricetta in corso
INTESTAZIONI_INTRODUZIONE = ("MINESTRE",)
# dopo l'appendice non ci sono più ricette
APPENDICE = "APPENDICE"
# numero di ricette atteso nel libro
TOTALE_RICETTE = 790

# titolo di ricetta: "7. Cappelletti all'uso di Romagna"
_TITOLO = re.compile(r"^(\d+)\. (.+)$")
# richiamo di nota nel testo: "vicini[2] con"
_RICHIAMO = re.compile(r"\[\d+\]")
# spazi ripetuti dentro una riga
_SPAZI = re.compile(r" {2,}")


# una ricetta: il testo è pulito (§7), senza il titolo
@dataclass(frozen=True)
class Ricetta:
    numero: int
    titolo: str
    capitolo: str
    testo: str
    # righe di ingrediente pulite (rientrate di 2 spazi nel file), nell'ordine; vuota se non c'è elenco
    ingredienti: tuple[str, ...] = ()


# quanti spazi apre una riga
def _rientro(riga: str) -> int:
    return len(riga) - len(riga.lstrip(" "))


# toglie i segnaposto delle illustrazioni: da "   [Illustrazione:" fino alla riga che chiude "]"
def _senza_illustrazioni(righe: list[str]) -> list[str]:
    tenute: list[str] = []
    dentro = False
    for riga in righe:
        if not dentro and riga.lstrip().startswith("[Illustrazione"):
            dentro = True
        if dentro:
            # la riga con "]" chiude il segnaposto (anche se è la prima)
            if "]" in riga:
                dentro = False
            continue
        tenute.append(riga)
    return tenute


# pulizia di una riga del testo finale: corsivo, richiami di nota, spazi
def _pulisci_riga(riga: str) -> str:
    riga = _RICHIAMO.sub("", riga.replace("_", ""))
    return _SPAZI.sub(" ", riga).strip()


# un paragrafo (righe senza righe vuote in mezzo) → righe del testo pulito
def _paragrafo(righe: list[str]) -> list[tuple[str, bool]]:
    uscita: list[str] = []
    ingrediente: list[bool] = []  # per ogni riga di uscita: nata da una riga a 2 spazi?
    tipo_precedente = None  # "prosa", "ingrediente" (anche continuazione), "altro"
    for riga in righe:
        rientro = _rientro(riga)
        contenuto = riga.strip()
        if rientro == 2:
            # riga di ingrediente: su una riga propria
            uscita.append(contenuto)
            ingrediente.append(True)
            tipo_precedente = "ingrediente"
        elif rientro >= 4 and tipo_precedente == "ingrediente":
            # continuazione dell'ingrediente: si unisce alla sua riga
            uscita[-1] += " " + contenuto
        elif rientro >= 3:
            # versi, etichette (_Prima:_): ognuna su una riga propria
            uscita.append(contenuto)
            ingrediente.append(False)
            tipo_precedente = "altro"
        elif tipo_precedente == "prosa":
            # prosa spezzata a ~70 caratteri: si unisce con uno spazio
            uscita[-1] += " " + contenuto
        else:
            uscita.append(contenuto)
            ingrediente.append(False)
            tipo_precedente = "prosa"
    # pulizia riga per riga; righe rimaste vuote scartate
    pulite = ((_pulisci_riga(r), e) for r, e in zip(uscita, ingrediente))
    return [(r, e) for r, e in pulite if r]


# righe grezze di una ricetta → testo pulito (paragrafi separati da una riga vuota) e righe di ingrediente
def _testo_pulito(righe: list[str]) -> tuple[str, tuple[str, ...]]:
    paragrafi: list[str] = []
    ingredienti: list[str] = []
    corrente: list[str] = []
    for riga in _senza_illustrazioni(righe) + [""]:
        if riga.strip():
            corrente.append(riga)
        elif corrente:
            # riga vuota: chiude il paragrafo in corso
            pulite = _paragrafo(corrente)
            if pulite:
                paragrafi.append("\n".join(r for r, _ in pulite))
                ingredienti.extend(r for r, e in pulite if e)
            corrente = []
    return "\n\n".join(paragrafi), tuple(ingredienti)


# solo il libro: tra "*** START OF" e "*** END OF" (intestazione e licenza Gutenberg scartate)
def _righe_del_libro(testo: str) -> list[str]:
    righe = testo.splitlines()
    inizio = next((i for i, r in enumerate(righe) if r.startswith("*** START OF")), -1)
    fine = next((i for i, r in enumerate(righe) if r.startswith("*** END OF")), len(righe))
    return righe[inizio + 1:fine]


def analizza(testo: str) -> list[Ricetta]:
    """Divide il testo del libro in ricette con numero, titolo, capitolo e testo pulito."""
    ricette: list[Ricetta] = []
    capitolo: str | None = None
    numero_atteso = 1
    aperta: tuple[int, str, str] | None = None  # (numero, titolo, capitolo) della ricetta in corso
    righe_aperte: list[str] = []

    # chiude la ricetta in corso (se c'è) e la aggiunge all'elenco
    def chiudi() -> None:
        nonlocal aperta, righe_aperte
        if aperta is not None:
            numero, titolo, cap = aperta
            testo_pulito, ingredienti = _testo_pulito(righe_aperte)
            if not testo_pulito:
                raise ErroreRicerca(f"la ricetta n. {numero} «{titolo}» ha il testo vuoto")
            ricette.append(Ricetta(numero, titolo, cap, testo_pulito, ingredienti))
        aperta, righe_aperte = None, []

    for riga in _righe_del_libro(testo):
        pulita = riga.strip()
        if pulita in CAPITOLI:
            # nuovo capitolo: segue un'introduzione, scartata fino alla prima ricetta
            chiudi()
            capitolo = pulita
        elif pulita in INTESTAZIONI_INTRODUZIONE:
            chiudi()
        elif pulita == APPENDICE and capitolo is not None:
            chiudi()
            break
        elif capitolo is not None and (titolo := _TITOLO.match(pulita)) and int(titolo[1]) == numero_atteso:
            # titolo con il numero atteso: le righe di testo che iniziano con un numero non lo sono
            chiudi()
            aperta = (numero_atteso, titolo[2].replace("_", "").strip(), capitolo)
            numero_atteso += 1
        elif aperta is not None:
            righe_aperte.append(riga)
    chiudi()
    return ricette


def carica_corpus(percorso: Path) -> list[Ricetta]:
    """Legge il file del ricettario e controlla 790 ricette senza buchi e i 23 capitoli in ordine."""
    if not percorso.is_file():
        raise ErroreRicerca(f"corpus non trovato: {percorso}. Scaricarlo da Project Gutenberg n. 59047 "
                            "(file di testo UTF-8) come indicato in ricerca/README.md")
    ricette = analizza(percorso.read_text(encoding="utf-8"))
    numeri = [r.numero for r in ricette]
    if numeri != list(range(1, TOTALE_RICETTE + 1)):
        raise ErroreRicerca(f"attese {TOTALE_RICETTE} ricette numerate da 1 a {TOTALE_RICETTE}, "
                            f"trovate {len(ricette)} in {percorso}")
    capitoli = tuple(dict.fromkeys(r.capitolo for r in ricette))
    if capitoli != CAPITOLI:
        mancanti = [c for c in CAPITOLI if c not in capitoli]
        raise ErroreRicerca(f"capitoli non trovati nell'ordine atteso in {percorso} (mancanti: {mancanti})")
    return ricette
