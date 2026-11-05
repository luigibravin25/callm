"""Catalogo prodotti da CSV: ricerca esatta per parole intere e dettaglio per codice.

Logica pura, senza MCP: il server (server.py) la pubblica come tool.
"""
import csv
import unicodedata
from pathlib import Path

PERCORSO_CSV = Path(__file__).with_name("prodotti.csv")
MIN_RISULTATI = 1
MAX_RISULTATI = 20
RISULTATI_PREDEFINITI = 5

COLONNE = ["ID_Prodotto", "Nome_Prodotto", "Categoria", "Prezzo_Euro", "Quantita_Magazzino",
           "Stato", "Sede_Magazzino"]
# campi in cui si cerca; prezzo e quantita' no
CAMPI_RICERCABILI = ("codice", "nome", "categoria", "stato", "sede")
# parole della query ignorate (articoli, preposizioni, congiunzioni): "casa e cucina" trova
# "Casa & Cucina", "occhialini per il nuoto" trova "Occhialini Nuoto"
PAROLE_VUOTE = frozenset(
    "il lo la i gli le l un uno una d e ed o oppure di a da in con su per tra fra "
    "del dello della dei degli delle dell al allo alla ai agli alle all "
    "dal dallo dalla dai dagli dalle dall nel nello nella nei negli nelle nell "
    "sul sullo sulla sui sugli sulle sull col".split())
# parole generiche della domanda che il modello mette nella query ("prodotto per la casa",
# "c'e' qualche smartphone nel catalogo?"): non sono in nessun campo e svuoterebbero il risultato
PAROLE_GENERICHE = frozenset(
    "prodotto prodotti articolo articoli oggetto oggetti cosa cose qualcosa qualche "
    "catalogo negozio magazzino avete avere hai ci c ce sono vorrei cerco cercare trovare "
    "quale quali quanti quante tutti tutte tipo tipi genere".split())
PAROLE_VUOTE = PAROLE_VUOTE | PAROLE_GENERICHE


class ErroreCatalogo(Exception):
    """Input rifiutato o CSV non valido; il messaggio spiega il motivo."""


def _parole(testo: str) -> set[str]:
    """Parole in minuscolo e senza accenti: sequenze di lettere e cifre."""
    scomposto = unicodedata.normalize("NFKD", testo)
    senza_accenti = "".join(ch for ch in scomposto if not unicodedata.combining(ch)).lower()
    parole, corrente = set(), []
    for ch in senza_accenti + " ":
        if ch.isalnum():
            corrente.append(ch)
        elif corrente:
            parole.add("".join(corrente))
            corrente = []
    return parole


def carica_catalogo(percorso: Path = PERCORSO_CSV) -> list[dict]:
    """Legge il CSV; file mancante o non UTF-8, righe malformate, codici duplicati o numeri non
    validi sono errori. Il BOM (CSV salvato da Excel) e' accettato."""
    try:
        with open(percorso, encoding="utf-8-sig", newline="") as f:
            righe = list(csv.reader(f))
    except FileNotFoundError:
        raise ErroreCatalogo(f"{percorso.name}: file non trovato ({percorso}).") from None
    except UnicodeDecodeError:
        raise ErroreCatalogo(f"{percorso.name}: il file non è in UTF-8.") from None
    except OSError as errore:
        raise ErroreCatalogo(f"{percorso.name}: impossibile leggere il file ({errore}).") from None
    lettore = iter(righe)
    intestazione = next(lettore, [])
    if intestazione != COLONNE:
        raise ErroreCatalogo(
            f"{percorso.name}: intestazione non valida, attesa {','.join(COLONNE)}.")
    catalogo, visti = [], set()
    for numero, riga in enumerate(lettore, start=2):
        if not riga:
            continue
        if len(riga) != len(COLONNE):
            raise ErroreCatalogo(f"{percorso.name}, riga {numero}: {len(riga)} colonne "
                                 f"invece di {len(COLONNE)}.")
        codice, nome, categoria, prezzo, quantita, stato, sede = (v.strip() for v in riga)
        if codice.upper() in visti:
            raise ErroreCatalogo(f"{percorso.name}, riga {numero}: codice {codice} duplicato.")
        try:
            prezzo_euro = float(prezzo)
        except ValueError:
            raise ErroreCatalogo(f"{percorso.name}, riga {numero}: Prezzo_Euro non numerico "
                                 f"({prezzo!r}).") from None
        try:
            quantita_magazzino = int(quantita)
        except ValueError:
            raise ErroreCatalogo(f"{percorso.name}, riga {numero}: Quantita_Magazzino non "
                                 f"intera ({quantita!r}).") from None
        visti.add(codice.upper())
        catalogo.append({"codice": codice, "nome": nome, "categoria": categoria,
                         "prezzo_euro": prezzo_euro, "quantita_magazzino": quantita_magazzino,
                         "stato": stato, "sede": sede})
    return catalogo


def cerca(catalogo: list[dict], query: str, max_results: int = RISULTATI_PREDEFINITI) -> list[dict]:
    """Prodotti in cui ogni parola della query (articoli e preposizioni esclusi) e' una parola
    intera di un campo ricercabile."""
    return cerca_con_totale(catalogo, query, max_results)[0]


def cerca_con_totale(catalogo: list[dict], query: str,
                     max_results: int = RISULTATI_PREDEFINITI) -> tuple[list[dict], int]:
    """Come cerca, ma restituisce anche quanti prodotti corrispondono in tutto."""
    # bool e' una sottoclasse di int: True non deve valere 1
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ErroreCatalogo(f"max_results deve essere un intero tra {MIN_RISULTATI} e "
                             f"{MAX_RISULTATI}, ricevuto {max_results!r}.")
    if not MIN_RISULTATI <= max_results <= MAX_RISULTATI:
        raise ErroreCatalogo(f"max_results deve essere tra {MIN_RISULTATI} e {MAX_RISULTATI}, "
                             f"ricevuto {max_results}.")
    cercate = _parole(query) - PAROLE_VUOTE
    if not cercate:
        raise ErroreCatalogo("La query è vuota: indica almeno una parola da cercare.")
    trovati = []
    for p in catalogo:
        indice = set().union(*(_parole(p[campo]) for campo in CAMPI_RICERCABILI))
        if cercate <= indice:
            trovati.append({"codice": p["codice"], "nome": p["nome"], "categoria": p["categoria"]})
    return trovati[:max_results], len(trovati)


def dettaglio(catalogo: list[dict], code: str) -> dict:
    """Record completo del prodotto con quel codice (spazi esterni e maiuscole ignorati)."""
    cercato = code.strip().upper()
    for p in catalogo:
        if p["codice"].upper() == cercato:
            return dict(p)
    raise ErroreCatalogo(f"Codice {cercato} non presente nel catalogo. "
                         "Usa search_catalog per trovare il codice giusto.")
