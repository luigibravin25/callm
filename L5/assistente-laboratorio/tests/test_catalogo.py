import pytest

from mcp_catalogo.catalogo import (ErroreCatalogo, carica_catalogo, cerca, cerca_con_totale,
                                   dettaglio)

INTESTAZIONE = ("ID_Prodotto,Nome_Prodotto,Categoria,Prezzo_Euro,Quantita_Magazzino,Stato,"
                "Sede_Magazzino")


@pytest.fixture(scope="module")
def c():
    return carica_catalogo()


def _codici(risultati):
    return [r["codice"] for r in risultati]


def test_cinquanta_prodotti(c):
    assert len(c) == 50
    primo = c[0]
    assert primo["codice"] == "PRD001"
    assert primo["prezzo_euro"] == 499.99
    assert primo["quantita_magazzino"] == 45


def test_ricerca_per_nome(c):
    assert cerca(c, "nuoto") == [
        {"codice": "PRD030", "nome": "Occhialini Nuoto", "categoria": "Sport"}]


def test_ricerca_su_campi_diversi(c):
    risultati = cerca(c, "elettronica milano", 20)
    assert len(risultati) == 6
    assert all(r["categoria"] == "Elettronica" for r in risultati)


def test_maiuscole_e_accenti(c):
    assert _codici(cerca(c, "CAFFE")) == ["PRD005", "PRD046"]


def test_parola_parziale_non_trova(c):
    assert cerca(c, "smartphon") == []


def test_nessun_risultato_lista_vuota(c):
    assert cerca(c, "pattini a rotelle") == []


def test_punteggiatura_ignorata(c):
    assert cerca(c, "smartphone?")[0]["codice"] == "PRD001"


def test_nessun_duplicato(c):
    codici = _codici(cerca(c, "cucina", 20))
    assert len(codici) == len(set(codici))
    assert "PRD015" in codici


def test_ordine_e_limite(c):
    libri = [p["codice"] for p in c if p["categoria"] == "Libri"]
    assert _codici(cerca(c, "libri", 2)) == libri[:2]
    assert len(cerca(c, "libri")) == 5
    assert len(libri) > 5


@pytest.mark.parametrize("n", [0, -1, 21, 50])
def test_max_results_fuori_intervallo(c, n):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, "libri", n)
    assert str(e.value) == f"max_results deve essere tra 1 e 20, ricevuto {n}."


@pytest.mark.parametrize("n", [1, 20])
def test_max_results_agli_estremi(c, n):
    assert 1 <= len(cerca(c, "libri", n)) <= n


@pytest.mark.parametrize("query", ["", "   ", "?!&"])
def test_query_vuota(c, query):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, query)
    assert str(e.value) == "La query è vuota: indica almeno una parola da cercare."


def test_dettaglio(c):
    p = dettaglio(c, " prd004 ")
    assert p["codice"] == "PRD004"
    assert p["nome"] == "Jeans Slim Fit"
    assert p["stato"] == "Esaurito"
    assert p["quantita_magazzino"] == 0
    assert p["sede"] == "Roma Logistica"
    assert set(p) == {"codice", "nome", "categoria", "prezzo_euro", "quantita_magazzino",
                      "stato", "sede"}


@pytest.mark.parametrize("code", ["PRD999", "prd4", "PRD0004"])
def test_codice_inesistente(c, code):
    with pytest.raises(ErroreCatalogo) as e:
        dettaglio(c, code)
    atteso = code.strip().upper()
    assert str(e.value) == (f"Codice {atteso} non presente nel catalogo. "
                            "Usa search_catalog per trovare il codice giusto.")


@pytest.mark.parametrize("righe, indizio", [
    ([INTESTAZIONE, "PRD001,A,B,1.0,1,Disponibile"], "riga 2"),
    ([INTESTAZIONE, "PRD001,A,B,1.0,1,Disponibile,X", "PRD001,C,D,2.0,2,Esaurito,Y"], "riga 3"),
    ([INTESTAZIONE, "PRD001,A,B,abc,1,Disponibile,X"], "Prezzo_Euro"),
    ([INTESTAZIONE, "PRD001,A,B,1.0,uno,Disponibile,X"], "Quantita_Magazzino"),
    (["Codice,Nome", "PRD001,A"], "intestazione"),
])
def test_csv_malformato(tmp_path, righe, indizio):
    percorso = tmp_path / "prodotti.csv"
    percorso.write_text("\n".join(righe) + "\n", encoding="utf-8")
    with pytest.raises(ErroreCatalogo) as e:
        carica_catalogo(percorso)
    assert indizio in str(e.value)


# --- minori della revisione finale ---

def test_parole_vuote_ignorate(c):
    # "casa e cucina": la "e" non e' nel campo "Casa & Cucina", ma e' una congiunzione
    risultati = cerca(c, "casa e cucina", 20)
    assert risultati and all(r["categoria"] == "Casa & Cucina" for r in risultati)
    assert _codici(cerca(c, "occhialini per il nuoto")) == ["PRD030"]
    assert cerca(c, "pattini a rotelle") == []


def test_solo_parole_vuote_e_query_vuota(c):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, "e di la")
    assert str(e.value) == "La query è vuota: indica almeno una parola da cercare."


@pytest.mark.parametrize("n", [True, False, 3.0, "3"])
def test_max_results_non_intero_rifiutato(c, n):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, "libri", n)
    assert str(e.value) == f"max_results deve essere un intero tra 1 e 20, ricevuto {n!r}."


def test_csv_mancante(tmp_path):
    with pytest.raises(ErroreCatalogo) as e:
        carica_catalogo(tmp_path / "manca.csv")
    assert "manca.csv" in str(e.value) and "non trovato" in str(e.value)


def test_csv_non_utf8(tmp_path):
    percorso = tmp_path / "prodotti.csv"
    percorso.write_bytes((INTESTAZIONE + "\nPRD001,Caff\xe8,B,1.0,1,Disponibile,X\n")
                         .encode("latin-1"))
    with pytest.raises(ErroreCatalogo) as e:
        carica_catalogo(percorso)
    assert "UTF-8" in str(e.value)


def test_csv_con_bom_accettato(tmp_path):
    percorso = tmp_path / "prodotti.csv"
    percorso.write_text(INTESTAZIONE + "\nPRD001,A,B,1.0,1,Disponibile,X\n", encoding="utf-8-sig")
    assert carica_catalogo(percorso)[0]["codice"] == "PRD001"


# --- avviso quando il risultato e' tagliato ---

def test_cerca_con_totale(c):
    risultati, totale = cerca_con_totale(c, "casa e cucina", 5)
    assert len(risultati) == 5 and totale == 10
    assert cerca_con_totale(c, "pattini a rotelle", 5) == ([], 0)
    assert cerca_con_totale(c, "nuoto", 5)[1] == 1


# --- parole generiche della domanda (il modello le mette nella query) ---

@pytest.mark.parametrize("query, codice, totale", [
    ("prodotto per la casa", "PRD005", 10),
    ("prodotti casa", "PRD005", 10),
    ("articoli per la cucina", "PRD005", 10),
    ("qualcosa per il nuoto", "PRD030", 1),
    ("c'è qualche smartphone nel catalogo?", "PRD001", 1),
    ("avete dei libri?", "PRD007", 10),
])
def test_parole_generiche_ignorate(c, query, codice, totale):
    risultati, trovati = cerca_con_totale(c, query, 20)
    assert trovati == totale and risultati[0]["codice"] == codice


def test_parole_generiche_non_nascondono_campi(c):
    # nessuna parola generica ignorata e' una parola dei campi del CSV
    from mcp_catalogo.catalogo import CAMPI_RICERCABILI, PAROLE_GENERICHE, PAROLE_VUOTE, _parole
    vocabolario = set().union(*(_parole(p[k]) for p in c for k in CAMPI_RICERCABILI))
    assert not PAROLE_GENERICHE & vocabolario, PAROLE_GENERICHE & vocabolario
    assert PAROLE_GENERICHE <= PAROLE_VUOTE


def test_solo_parole_generiche_e_query_vuota(c):
    with pytest.raises(ErroreCatalogo):
        cerca(c, "avete qualche prodotto?")
