# test della configurazione del back-end: variabili d'ambiente, predefiniti, errori, URL mascherato
import pytest

from app.config import (AGENTE_TIMEOUT_PREDEFINITO, AGENTE_URL_PREDEFINITO, HOST_PREDEFINITO,
                        PORTA_PREDEFINITA, leggi_impostazioni, maschera_url)

URL_DB = "postgresql+psycopg://assistente:segreta@127.0.0.1:5433/assistente"
VARIABILI = ("DATABASE_URL", "AGENTE_URL", "AGENTE_TIMEOUT", "BACKEND_HOST", "BACKEND_PORTA",
             "STREAMING")


# ambiente pulito: solo le variabili che il test imposta
@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    for nome in VARIABILI:
        monkeypatch.delenv(nome, raising=False)
    return monkeypatch


# Verifica i predefiniti con la sola DATABASE_URL.
def test_predefiniti(ambiente):
    ambiente.setenv("DATABASE_URL", URL_DB)
    i = leggi_impostazioni()
    assert i.database_url == URL_DB
    assert (i.agente_url, i.agente_timeout) == (AGENTE_URL_PREDEFINITO, AGENTE_TIMEOUT_PREDEFINITO)
    assert (i.host, i.porta) == (HOST_PREDEFINITO, PORTA_PREDEFINITA)
    assert (AGENTE_URL_PREDEFINITO, AGENTE_TIMEOUT_PREDEFINITO) == ("http://127.0.0.1:8000", 300)
    assert (HOST_PREDEFINITO, PORTA_PREDEFINITA) == ("127.0.0.1", 8001)


# Verifica valori impostati e la barra finale di AGENTE_URL tolta.
def test_valori_impostati(ambiente):
    ambiente.setenv("DATABASE_URL", URL_DB)
    ambiente.setenv("AGENTE_URL", "http://agente:8000/")
    ambiente.setenv("AGENTE_TIMEOUT", "600")
    ambiente.setenv("BACKEND_HOST", "0.0.0.0")
    ambiente.setenv("BACKEND_PORTA", "9000")
    i = leggi_impostazioni()
    assert (i.agente_url, i.agente_timeout, i.host, i.porta) == (
        "http://agente:8000", 600, "0.0.0.0", 9000)


# Verifica gli errori: variabile nominata, password mai nel messaggio.
@pytest.mark.parametrize("variabili, testo", [
    ({}, "DATABASE_URL"),
    ({"DATABASE_URL": "  "}, "DATABASE_URL"),
    ({"DATABASE_URL": "postgresql://assistente:segreta@127.0.0.1:5433/a"}, "postgresql+psycopg://"),
    ({"DATABASE_URL": URL_DB, "AGENTE_TIMEOUT": "0"}, "AGENTE_TIMEOUT"),
    ({"DATABASE_URL": URL_DB, "AGENTE_TIMEOUT": "abc"}, "AGENTE_TIMEOUT"),
    ({"DATABASE_URL": URL_DB, "BACKEND_PORTA": "0"}, "BACKEND_PORTA"),
    ({"DATABASE_URL": URL_DB, "BACKEND_PORTA": "70000"}, "BACKEND_PORTA"),
])
def test_errori(ambiente, variabili, testo):
    for nome, valore in variabili.items():
        ambiente.setenv(nome, valore)
    with pytest.raises(ValueError) as errore:
        leggi_impostazioni()
    assert testo in str(errore.value)
    assert "segreta" not in str(errore.value)


# Verifica l'URL mascherato per log e messaggi.
def test_maschera_url():
    assert maschera_url(URL_DB) == "postgresql+psycopg://assistente:***@127.0.0.1:5433/assistente"
    senza = "postgresql+psycopg://assistente@127.0.0.1:5433/assistente"
    assert maschera_url(senza) == senza


# Verifica STREAMING (step 10): assente → attivo; valori ammessi senza maiuscole; altro → errore.
@pytest.mark.parametrize("valore, atteso", [(None, True), ("true", True), ("TRUE", True), ("1", True),
                                            ("sì", True), ("si", True), ("false", False),
                                            ("0", False), ("No", False), (" false ", False)])
def test_streaming(ambiente, valore, atteso):
    ambiente.setenv("DATABASE_URL", URL_DB)
    if valore is not None:
        ambiente.setenv("STREAMING", valore)
    assert leggi_impostazioni().streaming is atteso


def test_streaming_non_valido(ambiente):
    ambiente.setenv("DATABASE_URL", URL_DB)
    ambiente.setenv("STREAMING", "forse")
    with pytest.raises(ValueError, match="STREAMING"):
        leggi_impostazioni()
