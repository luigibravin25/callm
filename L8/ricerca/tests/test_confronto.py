# test del confronto delle quattro configurazioni (lezione 8, esercizio 3): metriche su esiti preparati a mano
import pytest

from app.confronto import CONFIGURAZIONI, EsitoDomanda, confronto_con_base, riepilogo, tabelle_markdown
from app.valutazione import Domanda

SEMPLICE = Domanda("vino?", (208,), ("vino rosso",))
COMPOSTA = Domanda("a e b?", (126, 231), ("due torli", "Uova, N. 2."))
VUOTA = Domanda("sushi?", (), ())


# esito preparato: numeri di ricetta dei passaggi in ordine, chiamate all'LLM, latenza, ripieghi
def es(domanda, numeri, chiamate=0, latenza=1.0, ripieghi=0):
    return EsitoDomanda(domanda, numeri, chiamate, latenza, ripieghi)


# Verifica fonte nei primi k, MRR, copertura delle composte e astensioni.
def test_metriche_di_base():
    esiti = [es(SEMPLICE, [7, 208]), es(COMPOSTA, [126, 5]), es(VUOTA, [])]
    r = riepilogo(esiti)
    assert r["fonte nei primi k"] == "2/2" and r["MRR"] == "0.750"
    assert r["copertura delle composte"] == "1/2"
    assert r["astensioni corrette"] == "1/1" and r["astensioni errate"] == "0/2"


# Verifica chiamate all'LLM, latenza e ripieghi.
def test_costo_e_ripieghi():
    r = riepilogo([es(SEMPLICE, [208], 2, 1.0, 1), es(VUOTA, [5], 1, 3.0, 0)])
    assert r["chiamate LLM (media/max)"] == "1.5/2" and r["latenza s (media/max)"] == "2.00/3.00"
    assert r["ripieghi"] == "1"


# Verifica che una lista vuota su una domanda con fonte sia un'astensione errata.
def test_astensione_errata():
    assert riepilogo([es(SEMPLICE, [])])["astensioni errate"] == "1/1"


# Verifica il criterio migliorata/peggiorata rispetto a base.
@pytest.mark.parametrize("base, altro, atteso", [
    (es(SEMPLICE, [7, 208]), es(SEMPLICE, [208]), "migliorata"),
    (es(SEMPLICE, [208]), es(SEMPLICE, [7]), "peggiorata"),
    (es(SEMPLICE, [208]), es(SEMPLICE, [208, 7]), ""),
    (es(COMPOSTA, [126]), es(COMPOSTA, [231, 126]), "migliorata"),
    (es(COMPOSTA, [5, 126, 231]), es(COMPOSTA, [126, 231]), "migliorata"),
    (es(VUOTA, [5]), es(VUOTA, []), "migliorata"),
    (es(VUOTA, []), es(VUOTA, [5]), "peggiorata"),
])
def test_confronto_con_base(base, altro, atteso):
    assert confronto_con_base(base, altro) == atteso


# Verifica che le tabelle siano riproducibili, con una colonna per configurazione.
def test_tabelle_riproducibili():
    esiti = {c: [es(SEMPLICE, [208]), es(VUOTA, [])] for c in CONFIGURAZIONI}
    testo = tabelle_markdown(esiti, {"k": "5"})
    assert testo == tabelle_markdown(esiti, {"k": "5"})
    assert "| base | riscrittura | reranking | entrambe |" in testo and "astensione" in testo
    assert "- k: 5" in testo


# Verifica le celle della tabella domanda per domanda.
def test_celle_domanda_per_domanda():
    esiti = {"base": [es(SEMPLICE, [7, 208]), es(COMPOSTA, [126]), es(VUOTA, [5, 6])],
             "riscrittura": [es(SEMPLICE, [208]), es(COMPOSTA, [231, 126]), es(VUOTA, [])],
             "reranking": [es(SEMPLICE, [7]), es(COMPOSTA, [126]), es(VUOTA, [5])],
             "entrambe": [es(SEMPLICE, []), es(COMPOSTA, []), es(VUOTA, [])]}
    testo = tabelle_markdown(esiti, {})
    assert "| vino? | 2 | 1 migliorata | assente peggiorata | astensione peggiorata |" in testo
    assert "| a e b? | 1/2 (pos. 1) | 2/2 (pos. 1) migliorata | 1/2 (pos. 1) | astensione peggiorata |" in testo
    assert "| sushi? | 2 passaggi | astensione migliorata | 1 passaggi | astensione migliorata |" in testo


# --- lezione 8, esercizio 4: confronto con e senza soglie ---

# Verifica la colonna «base + soglie» accanto a base, con le astensioni dovute alle soglie.
def test_colonna_base_con_soglie():
    esiti = {"base": [es(SEMPLICE, [208]), es(VUOTA, [5])], "base + soglie": [es(SEMPLICE, []), es(VUOTA, [])]}
    testo = tabelle_markdown(esiti, {})
    assert "| metrica | base | base + soglie |" in testo
    assert "| astensioni corrette | 0/1 | 1/1 |" in testo and "| astensioni errate | 0/1 | 1/1 |" in testo
    assert "| sushi? | 1 passaggi | astensione migliorata |" in testo
