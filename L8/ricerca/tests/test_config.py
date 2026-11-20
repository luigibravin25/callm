# test della configurazione della ricerca: predefiniti, variabile obbligatoria, valori non validi, percorsi
import pytest

from app.config import CARTELLA_L7, carica_configurazione
from app.errori import ErroreRicerca

# tutte le variabili lette dalla ricerca: si tolgono prima di ogni test per partire puliti
VARIABILI = ("LM_BASE_URL", "EMBEDDING_MODEL", "QDRANT_URL", "QDRANT_COLLEZIONE", "CORPUS_FILE",
             "CHUNK_STRATEGIA", "CHUNK_DIMENSIONE", "CHUNK_OVERLAP", "TOP_K",
             # lezione 8, esercizio 3: modalità avanzata della ricerca
             "RICERCA_MODALITA", "LM_MODEL", "RICERCA_CANDIDATI", "RERANK_TETTO",
             # lezione 8, esercizio 4: soglie sullo score
             "SOGLIA_ALTA", "SOGLIA_BASSA")


@pytest.fixture(autouse=True)
def ambiente_pulito(monkeypatch):
    for nome in VARIABILI:
        monkeypatch.delenv(nome, raising=False)
    # il modello è obbligatorio: i test che non parlano di lui lo trovano impostato
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")


def test_predefiniti():
    conf = carica_configurazione()
    assert conf.modello_embedding == "bge"
    assert conf.lm_base_url == "http://127.0.0.1:1234/v1"
    assert conf.qdrant_url == "http://127.0.0.1:6333"
    assert conf.collezione == "ricettario"
    assert conf.corpus_file == CARTELLA_L7 / "Ricettario" / "Ricettario.txt"
    assert (conf.strategia, conf.dimensione, conf.overlap, conf.top_k) == ("paragrafi", 1000, 150, 5)


@pytest.mark.parametrize("valore", [None, "   "])
def test_modello_obbligatorio(monkeypatch, valore):
    if valore is None:
        monkeypatch.delenv("EMBEDDING_MODEL")
    else:
        monkeypatch.setenv("EMBEDDING_MODEL", valore)
    with pytest.raises(ErroreRicerca, match="EMBEDDING_MODEL"):
        carica_configurazione()


@pytest.mark.parametrize("nome, valore", [
    ("CHUNK_STRATEGIA", "frasi"),
    ("CHUNK_DIMENSIONE", "0"),
    ("CHUNK_DIMENSIONE", "mille"),
    ("CHUNK_OVERLAP", "-1"),
    ("CHUNK_OVERLAP", "1000"),
    ("TOP_K", "0"),
])
def test_valori_non_validi(monkeypatch, nome, valore):
    monkeypatch.setenv(nome, valore)
    with pytest.raises(ErroreRicerca, match=nome):
        carica_configurazione()


def test_percorso_relativo_da_L7(monkeypatch, tmp_path):
    # lo script si lancia da un'altra cartella: il percorso relativo parte comunque da L7/
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CORPUS_FILE", "Ricettario/altro.txt")
    assert carica_configurazione().corpus_file == CARTELLA_L7 / "Ricettario" / "altro.txt"


def test_percorso_assoluto_invariato(monkeypatch, tmp_path):
    monkeypatch.setenv("CORPUS_FILE", str(tmp_path / "corpus.txt"))
    assert carica_configurazione().corpus_file == tmp_path / "corpus.txt"


def test_cartella_L7():
    # CARTELLA_L7 è la cartella che contiene ricerca/
    assert (CARTELLA_L7 / "ricerca" / "app" / "config.py").is_file()


# --- lezione 8, esercizio 3: modalità, modello di chat, candidati e tetto del reranking ---

# Verifica i predefiniti: modalità base, nessun modello di chat, 10 candidati e tetto 10.
def test_modalita_predefinita():
    conf = carica_configurazione()
    assert (conf.modalita, conf.modello_chat, conf.candidati, conf.tetto_rerank) == ("base", "", 10, 10)


# Verifica le modalità avanzate con il modello di chat impostato.
@pytest.mark.parametrize("modalita", ["riscrittura", "reranking", "entrambe"])
def test_modalita_avanzata(monkeypatch, modalita):
    monkeypatch.setenv("RICERCA_MODALITA", modalita)
    monkeypatch.setenv("LM_MODEL", "gemma")
    conf = carica_configurazione()
    assert (conf.modalita, conf.modello_chat) == (modalita, "gemma")


# Verifica che una modalità sconosciuta sia un errore con i valori ammessi.
def test_modalita_non_valida(monkeypatch):
    monkeypatch.setenv("RICERCA_MODALITA", "ibrida")
    with pytest.raises(ErroreRicerca, match="RICERCA_MODALITA.*base, riscrittura, reranking, entrambe"):
        carica_configurazione()


# Verifica che LM_MODEL serva solo fuori dalla modalità base.
def test_lm_model_obbligatoria_fuori_da_base(monkeypatch):
    monkeypatch.setenv("RICERCA_MODALITA", "reranking")
    with pytest.raises(ErroreRicerca, match="LM_MODEL"):
        carica_configurazione()


# Verifica i limiti 10-20 di candidati e tetto (anche per un valore non intero).
@pytest.mark.parametrize("nome", ["RICERCA_CANDIDATI", "RERANK_TETTO"])
@pytest.mark.parametrize("valore", ["9", "21", "dieci"])
def test_limiti_candidati_e_tetto(monkeypatch, nome, valore):
    monkeypatch.setenv(nome, valore)
    with pytest.raises(ErroreRicerca, match=f"{nome}.*10-20"):
        carica_configurazione()


# Verifica che i valori ai confini siano ammessi.
def test_candidati_e_tetto_ai_limiti(monkeypatch):
    monkeypatch.setenv("RICERCA_CANDIDATI", "20")
    monkeypatch.setenv("RERANK_TETTO", "10")
    conf = carica_configurazione()
    assert (conf.candidati, conf.tetto_rerank) == (20, 10)



# --- lezione 8, esercizio 4: soglie sullo score ---

# Verifica i predefiniti calibrati delle soglie.
def test_soglie_predefinite():
    conf = carica_configurazione()
    assert (conf.soglia_alta, conf.soglia_bassa) == (0.60, 0.51)


# Verifica le soglie lette dalla configurazione, anche negative (intervallo del coseno).
def test_soglie_dalla_configurazione(monkeypatch):
    monkeypatch.setenv("SOGLIA_ALTA", "0.7")
    monkeypatch.setenv("SOGLIA_BASSA", "-1")
    conf = carica_configurazione()
    assert (conf.soglia_alta, conf.soglia_bassa) == (0.7, -1.0)


# Verifica gli errori per soglie non numeriche o fuori da -1..1.
@pytest.mark.parametrize("nome, valore", [("SOGLIA_ALTA", "alta"), ("SOGLIA_ALTA", "1.5"), ("SOGLIA_BASSA", "-1.1")])
def test_soglie_non_valide(monkeypatch, nome, valore):
    monkeypatch.setenv(nome, valore)
    with pytest.raises(ErroreRicerca, match=f"{nome}.*-1.*1"):
        carica_configurazione()


# Verifica che la soglia bassa non possa superare quella alta.
def test_soglie_invertite(monkeypatch):
    monkeypatch.setenv("SOGLIA_ALTA", "0.4")
    monkeypatch.setenv("SOGLIA_BASSA", "0.5")
    with pytest.raises(ErroreRicerca, match="SOGLIA_BASSA.*SOGLIA_ALTA"):
        carica_configurazione()
