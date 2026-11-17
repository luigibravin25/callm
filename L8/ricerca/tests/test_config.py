# test della configurazione della ricerca: predefiniti, variabile obbligatoria, valori non validi, percorsi
import pytest

from app.config import CARTELLA_L7, carica_configurazione
from app.errori import ErroreRicerca

# tutte le variabili lette dalla ricerca: si tolgono prima di ogni test per partire puliti
VARIABILI = ("LM_BASE_URL", "EMBEDDING_MODEL", "QDRANT_URL", "QDRANT_COLLEZIONE", "CORPUS_FILE",
             "CHUNK_STRATEGIA", "CHUNK_DIMENSIONE", "CHUNK_OVERLAP", "TOP_K")


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
