# Test della logica del catalogo (mcp_catalogo/catalogo.py): lettura del CSV, ricerca
# per parole e dettaglio per codice, senza il server MCP.

import pytest

# il codice da verificare
from mcp_catalogo.catalogo import (ErroreCatalogo, carica_catalogo, cerca, cerca_con_totale,
                                   dettaglio)

# intestazione corretta del CSV, per costruire file di prova malformati
INTESTAZIONE = ("ID_Prodotto,Nome_Prodotto,Categoria,Prezzo_Euro,Quantita_Magazzino,Stato,"
                "Sede_Magazzino")


# il catalogo vero (prodotti.csv), letto una sola volta per tutto il modulo
@pytest.fixture(scope="module")
def c():
    return carica_catalogo()


# solo i codici dei risultati, per confronti brevi
def _codici(risultati):
    return [r["codice"] for r in risultati]


# il CSV vero ha 50 prodotti; prezzo e quantita' diventano numeri
def test_cinquanta_prodotti(c):
    assert len(c) == 50
    primo = c[0]
    assert primo["codice"] == "PRD001"
    assert primo["prezzo_euro"] == 499.99  # float, non testo
    assert primo["quantita_magazzino"] == 45  # int, non testo


# la ricerca restituisce solo codice, nome e categoria (il resto lo da' get_item)
def test_ricerca_per_nome(c):
    assert cerca(c, "nuoto") == [
        {"codice": "PRD030", "nome": "Occhialini Nuoto", "categoria": "Sport"}]


# le parole possono stare in campi diversi: categoria e sede del magazzino
def test_ricerca_su_campi_diversi(c):
    risultati = cerca(c, "elettronica milano", 20)
    assert len(risultati) == 6
    assert all(r["categoria"] == "Elettronica" for r in risultati)


# la ricerca ignora maiuscole e accenti: "CAFFE" trova "Caffè"
def test_maiuscole_e_accenti(c):
    assert _codici(cerca(c, "CAFFE")) == ["PRD005", "PRD046"]


# si cercano parole intere: un pezzo di parola non basta
def test_parola_parziale_non_trova(c):
    assert cerca(c, "smartphon") == []


# nessun prodotto trovato: lista vuota, non un errore
def test_nessun_risultato_lista_vuota(c):
    assert cerca(c, "pattini a rotelle") == []


# il punto interrogativo della domanda non impedisce di trovare il prodotto
def test_punteggiatura_ignorata(c):
    assert cerca(c, "smartphone?")[0]["codice"] == "PRD001"


# un prodotto che corrisponde in piu' campi compare una sola volta
def test_nessun_duplicato(c):
    codici = _codici(cerca(c, "cucina", 20))
    assert len(codici) == len(set(codici))  # nessun codice ripetuto
    assert "PRD015" in codici


# risultati nell'ordine del CSV; senza max_results al massimo 5
def test_ordine_e_limite(c):
    libri = [p["codice"] for p in c if p["categoria"] == "Libri"]
    assert _codici(cerca(c, "libri", 2)) == libri[:2]
    assert len(cerca(c, "libri")) == 5  # limite predefinito
    assert len(libri) > 5  # i libri sono di piu': il limite ha davvero tagliato


# max_results fuori da 1-20: errore con il valore ricevuto
@pytest.mark.parametrize("n", [0, -1, 21, 50])
def test_max_results_fuori_intervallo(c, n):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, "libri", n)
    assert str(e.value) == f"max_results deve essere tra 1 e 20, ricevuto {n}."


# gli estremi 1 e 20 sono accettati e rispettati
@pytest.mark.parametrize("n", [1, 20])
def test_max_results_agli_estremi(c, n):
    assert 1 <= len(cerca(c, "libri", n)) <= n


# query vuota, di soli spazi o di sola punteggiatura: errore che dice cosa fare
@pytest.mark.parametrize("query", ["", "   ", "?!&"])
def test_query_vuota(c, query):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, query)
    assert str(e.value) == "La query è vuota: indica almeno una parola da cercare."


# dettaglio accetta il codice con spazi e minuscole e restituisce tutti i campi
def test_dettaglio(c):
    p = dettaglio(c, " prd004 ")
    assert p["codice"] == "PRD004"
    assert p["nome"] == "Jeans Slim Fit"
    assert p["stato"] == "Esaurito"
    assert p["quantita_magazzino"] == 0
    assert p["sede"] == "Roma Logistica"
    # esattamente i 7 campi previsti, con nomi in italiano
    assert set(p) == {"codice", "nome", "categoria", "prezzo_euro", "quantita_magazzino",
                      "stato", "sede"}


# codice inesistente o scritto male: errore che suggerisce al modello search_catalog
@pytest.mark.parametrize("code", ["PRD999", "prd4", "PRD0004"])
def test_codice_inesistente(c, code):
    with pytest.raises(ErroreCatalogo) as e:
        dettaglio(c, code)
    atteso = code.strip().upper()  # il messaggio mostra il codice normalizzato
    assert str(e.value) == (f"Codice {atteso} non presente nel catalogo. "
                            "Usa search_catalog per trovare il codice giusto.")


# un CSV rovinato da' un errore che indica dove guardare (riga, colonna o intestazione)
@pytest.mark.parametrize("righe, indizio", [
    # colonna mancante, codice ripetuto, prezzo e quantita' non numerici, intestazione sbagliata
    ([INTESTAZIONE, "PRD001,A,B,1.0,1,Disponibile"], "riga 2"),
    ([INTESTAZIONE, "PRD001,A,B,1.0,1,Disponibile,X", "PRD001,C,D,2.0,2,Esaurito,Y"], "riga 3"),
    ([INTESTAZIONE, "PRD001,A,B,abc,1,Disponibile,X"], "Prezzo_Euro"),
    ([INTESTAZIONE, "PRD001,A,B,1.0,uno,Disponibile,X"], "Quantita_Magazzino"),
    (["Codice,Nome", "PRD001,A"], "intestazione"),
])
def test_csv_malformato(tmp_path, righe, indizio):
    # preparazione: CSV di prova in una cartella temporanea
    percorso = tmp_path / "prodotti.csv"
    percorso.write_text("\n".join(righe) + "\n", encoding="utf-8")
    with pytest.raises(ErroreCatalogo) as e:
        carica_catalogo(percorso)
    assert indizio in str(e.value)


# --- minori della revisione finale ---

# congiunzioni e articoli non contano: "casa e cucina" trova i prodotti di Casa & Cucina
def test_parole_vuote_ignorate(c):
    # "casa e cucina": la "e" non e' nel campo "Casa & Cucina", ma e' una congiunzione
    risultati = cerca(c, "casa e cucina", 20)
    assert risultati and all(r["categoria"] == "Casa & Cucina" for r in risultati)
    assert _codici(cerca(c, "occhialini per il nuoto")) == ["PRD030"]
    assert cerca(c, "pattini a rotelle") == []


# una query fatta solo di parole vuote equivale a una query vuota
def test_solo_parole_vuote_e_query_vuota(c):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, "e di la")
    assert str(e.value) == "La query è vuota: indica almeno una parola da cercare."


# max_results deve essere un vero intero: no booleani, decimali o testo
@pytest.mark.parametrize("n", [True, False, 3.0, "3"])
def test_max_results_non_intero_rifiutato(c, n):
    with pytest.raises(ErroreCatalogo) as e:
        cerca(c, "libri", n)
    assert str(e.value) == f"max_results deve essere un intero tra 1 e 20, ricevuto {n!r}."


# file del catalogo assente: errore con il nome del file
def test_csv_mancante(tmp_path):
    with pytest.raises(ErroreCatalogo) as e:
        carica_catalogo(tmp_path / "manca.csv")
    assert "manca.csv" in str(e.value) and "non trovato" in str(e.value)


# un CSV salvato in latin-1 invece che in UTF-8 da' un errore che nomina la codifica
def test_csv_non_utf8(tmp_path):
    percorso = tmp_path / "prodotti.csv"
    # "Caffè" scritto in latin-1: il byte della "è" non e' UTF-8 valido
    percorso.write_bytes((INTESTAZIONE + "\nPRD001,Caff\xe8,B,1.0,1,Disponibile,X\n")
                         .encode("latin-1"))
    with pytest.raises(ErroreCatalogo) as e:
        carica_catalogo(percorso)
    assert "UTF-8" in str(e.value)


# il BOM iniziale (Excel lo aggiunge) non rovina il nome della prima colonna
def test_csv_con_bom_accettato(tmp_path):
    percorso = tmp_path / "prodotti.csv"
    percorso.write_text(INTESTAZIONE + "\nPRD001,A,B,1.0,1,Disponibile,X\n", encoding="utf-8-sig")
    assert carica_catalogo(percorso)[0]["codice"] == "PRD001"


# --- avviso quando il risultato e' tagliato ---

# cerca_con_totale da' anche quanti prodotti corrispondono in tutto ("Mostrati N di M")
def test_cerca_con_totale(c):
    risultati, totale = cerca_con_totale(c, "casa e cucina", 5)
    assert len(risultati) == 5 and totale == 10  # 5 mostrati su 10
    assert cerca_con_totale(c, "pattini a rotelle", 5) == ([], 0)
    assert cerca_con_totale(c, "nuoto", 5)[1] == 1


# --- parole generiche della domanda (il modello le mette nella query) ---

# "prodotto", "articoli", "qualcosa", "avete"... si ignorano: resta la parola che conta
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
    assert trovati == totale and risultati[0]["codice"] == codice  # totale e primo risultato


# ignorare una parola generica non deve far perdere prodotti che la contengono nei campi
def test_parole_generiche_non_nascondono_campi(c):
    # nessuna parola generica ignorata e' una parola dei campi del CSV
    from mcp_catalogo.catalogo import CAMPI_RICERCABILI, PAROLE_GENERICHE, PAROLE_VUOTE, _parole
    # tutte le parole presenti nei campi ricercabili del catalogo
    vocabolario = set().union(*(_parole(p[k]) for p in c for k in CAMPI_RICERCABILI))
    assert not PAROLE_GENERICHE & vocabolario, PAROLE_GENERICHE & vocabolario  # nessuna comune
    assert PAROLE_GENERICHE <= PAROLE_VUOTE  # le generiche fanno parte delle parole vuote


# una domanda fatta solo di parole generiche non ha nulla da cercare: errore
def test_solo_parole_generiche_e_query_vuota(c):
    with pytest.raises(ErroreCatalogo):
        cerca(c, "avete qualche prodotto?")
