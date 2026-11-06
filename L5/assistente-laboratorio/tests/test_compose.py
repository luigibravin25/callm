# Test della configurazione Docker: compose.yaml, Dockerfile e .dockerignore in L5/.
# I test con "docker compose config" sono saltati se Docker non e' installato.
# json legge la configurazione risolta; shutil cerca docker; subprocess lo esegue
import json
import shutil
import subprocess
from pathlib import Path

import pytest

# compose.yaml sta in L5/, sopra la cartella assistente-laboratorio
PROGETTO = Path(__file__).resolve().parent.parent.parent


# Verifica che compose.yaml sia valido e che l'app raggiunga LM Studio sull'host.
@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="eseguibile 'docker' non trovato nel PATH")
def test_compose_valido():
    # solo validazione della configurazione: niente LM Studio, niente container
    r = subprocess.run(["docker", "compose", "config"], cwd=PROGETTO,
                       capture_output=True, text=True, timeout=60)
    # controllo: comando riuscito, indirizzo dell'host e servizio "app" presenti
    assert r.returncode == 0, r.stderr
    assert "host.docker.internal" in r.stdout
    assert "app:" in r.stdout


def _config():
    """Configurazione di Compose risolta, in JSON (nessun container avviato)."""
    r = subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=PROGETTO,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# Verifica il servizio FastAPI in Compose e il suo collegamento con l'app.
@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="eseguibile 'docker' non trovato nel PATH")
def test_compose_servizio():
    # servizio HTTP (calcolatrice e date), rinominato da "calcolatrice" a "servizio":
    # stessa immagine, healthcheck, porta non pubblicata
    servizi = _config()["services"]
    assert "calcolatrice" not in servizi
    serv = servizi["servizio"]
    assert serv["image"] == "assistente-laboratorio-l5"
    # controllo: il comando avvia uvicorn su tutte le interfacce, porta 8001
    comando = " ".join(serv["command"])
    for parte in ("uvicorn", "servizio.main:app", "--host", "0.0.0.0", "--port", "8001"):
        assert parte in comando
    assert "/salute" in " ".join(serv["healthcheck"]["test"])
    assert "ports" not in serv
    # controllo: l'app chiama il servizio per nome e parte solo quando e' "sano"
    app = servizi["app"]
    assert app["environment"]["CALC_BASE_URL"] == "http://servizio:8001"
    assert app["depends_on"]["servizio"]["condition"] == "service_healthy"


# Verifica che l'archivio delle note stia in un volume con nome, non nel container.
@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="eseguibile 'docker' non trovato nel PATH")
def test_compose_volume_delle_note():
    # le note devono sopravvivere a "docker compose run --rm": volume con nome su /app/dati
    config = _config()
    app = config["services"]["app"]
    assert app["environment"]["NOTE_DB"] == "/app/dati/note.sqlite"
    # coppie (sorgente, destinazione) dei volumi montati nell'app
    montaggi = [(v["source"], v["target"]) for v in app["volumes"]]
    assert ("note-dati", "/app/dati") in montaggi
    assert "note-dati" in config["volumes"]


# Verifica il Dockerfile per le note (lettura del testo: non serve Docker, mai saltato).
def test_dockerfile_note():
    # il server delle note e lo script di verifica sono nell'immagine; dati/ e' dell'utente
    testo = (PROGETTO / "Dockerfile").read_text(encoding="utf-8")
    # l'ultimo controllo: la cartella cambia proprietario prima di passare all'utente normale
    assert "COPY assistente-laboratorio/mcp_note/ mcp_note/" in testo
    assert "COPY assistente-laboratorio/tests/mcp_verifica.py tests/" in testo
    assert "mkdir -p /app/dati" in testo and "chown utente:utente /app/dati" in testo
    assert testo.index("chown utente:utente /app/dati") < testo.index("USER utente")


# Verifica .dockerignore: l'eccezione "!" deve venire dopo l'esclusione, altrimenti non vale.
def test_dockerignore_lascia_lo_script_di_verifica():
    # tests/ resta fuori dal contesto di build, tranne lo script copiato nell'immagine
    righe = (PROGETTO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "assistente-laboratorio/tests/" in righe
    assert "!assistente-laboratorio/tests/mcp_verifica.py" in righe
    assert righe.index("!assistente-laboratorio/tests/mcp_verifica.py") > \
        righe.index("assistente-laboratorio/tests/")


# Verifica le variabili del meteo passate all'app in Compose.
@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="eseguibile 'docker' non trovato nel PATH")
def test_compose_meteo(monkeypatch):
    """Meteo (esercizio 6): citta' predefinita e limite dall'ambiente o da .env, con i valori
    predefiniti Roma e 1000; il contatore nel volume note-dati, come le note."""
    # preparazione: toglie le variabili del terminale, cosi' Compose usa i valori predefiniti
    monkeypatch.delenv("CITTA_PREDEFINITA", raising=False)
    monkeypatch.delenv("METEO_LIMITE_GIORNALIERO", raising=False)
    ambiente = _config()["services"]["app"]["environment"]
    assert ambiente["CITTA_PREDEFINITA"] == "Roma"
    assert ambiente["METEO_LIMITE_GIORNALIERO"] == "1000"
    assert ambiente["METEO_CONTATORE"] == "/app/dati/meteo_richieste.sqlite"


# Verifica che il Dockerfile copi il server meteo prima di passare all'utente normale.
def test_dockerfile_meteo():
    """Il server meteo e' nell'immagine (riusa servizio/date_lavoro.py, gia' copiato)."""
    testo = (PROGETTO / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY assistente-laboratorio/mcp_meteo/ mcp_meteo/" in testo
    assert "COPY assistente-laboratorio/servizio/ servizio/" in testo
    assert testo.index("COPY assistente-laboratorio/mcp_meteo/") < testo.index("USER utente")
