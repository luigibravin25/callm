# test di compose.yaml sulla configurazione risolta da Docker (docker compose config, nessun container
# avviato) con un .env di prova finto: porte, rete, variabili, healthcheck, volume, segreti
# librerie standard: JSON, ambiente, percorsi, ricerca ed esecuzione di docker, file temporanei
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

# cartella L6 (compose.yaml) e .env di prova con valori finti
L6 = Path(__file__).resolve().parents[1]
PROVA_ENV = Path(__file__).resolve().parent / "prova.env"

# senza docker i test della configurazione si saltano con il motivo
pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker non trovato nel PATH")


# variabili che compose.yaml legge: tolte dall'ambiente del comando, perché quelle della shell hanno
# la precedenza su --env-file (un valore vero finirebbe nell'output di un test fallito)
VARIABILI_DI_COMPOSE = ("POSTGRES_", "LM_", "MAX_", "FUSO_", "SOGLIA_", "MESSAGGI_", "AGENTE_", "AMBITO_",
                        "PREFERENZE_", "DATABASE_", "BACKEND_")


def ambiente_pulito() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(VARIABILI_DI_COMPOSE)}


# esegue docker compose config con un file di variabili; restituisce l'esito del comando
def esegui_config(env: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "--env-file", str(env), "config", "--format", "json"],
                          cwd=L6, capture_output=True, text=True, encoding="utf-8", timeout=60,
                          env=ambiente_pulito())


# configurazione risolta con il .env di prova
def config() -> dict:
    esito = esegui_config(PROVA_ENV)
    assert esito.returncode == 0, esito.stderr
    return json.loads(esito.stdout)


def servizi() -> dict:
    return config()["services"]


def test_quattro_servizi():
    s = servizi()
    assert set(s) == {"frontend", "backend", "agente", "database"}
    assert s["database"]["image"] == "postgres:18"
    for nome in ("frontend", "backend", "agente"):
        assert "build" in s[nome], nome


def test_una_sola_porta_locale():
    s = servizi()
    porte = s["frontend"]["ports"]
    assert len(porte) == 1
    assert (porte[0]["host_ip"], str(porte[0]["published"]), porte[0]["target"]) == ("127.0.0.1", "8080", 80)
    # agente, back-end e database non pubblicano porte sull'host
    for nome in ("agente", "backend", "database"):
        assert "ports" not in s[nome], nome


def test_agente():
    a = servizi()["agente"]
    env = a["environment"]
    assert env["LM_BASE_URL"] == "http://host.docker.internal:1234/v1"
    assert env["LM_MODEL"] == "modello-di-prova"
    assert env["AGENTE_HOST"] == "0.0.0.0"
    # Linux: host.docker.internal verso l'host (Docker Desktop lo conosce già)
    assert any("host.docker.internal" in h and "host-gateway" in h for h in a["extra_hosts"])
    # configurazione dall'host, in sola lettura
    config_ro = [v for v in a["volumes"] if v["target"] == "/app/config"]
    assert len(config_ro) == 1
    assert config_ro[0]["type"] == "bind" and config_ro[0]["read_only"] is True
    assert config_ro[0]["source"].replace("\\", "/").endswith("assistente-laboratorio/config")
    # nessuna credenziale del database nel container dell'agente
    assert not any(k == "DATABASE_URL" or k.startswith("POSTGRES_") for k in env)


def test_backend():
    b = servizi()["backend"]
    env = b["environment"]
    assert env["DATABASE_URL"] == "postgresql+psycopg://utente_prova:password-di-prova-123@database:5432/db_prova"
    assert env["AGENTE_URL"] == "http://agente:8000"
    assert env["BACKEND_HOST"] == "0.0.0.0"
    assert b["depends_on"]["database"]["condition"] == "service_healthy"
    assert b["depends_on"]["agente"]["condition"] == "service_started"


def test_frontend_dopo_il_backend():
    assert servizi()["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"


def test_healthcheck_e_riavvio():
    s = servizi()
    for nome, atteso in (("database", "pg_isready"), ("agente", "/openapi.json"),
                         ("backend", "/chat"), ("frontend", "http://127.0.0.1/")):
        test = " ".join(s[nome]["healthcheck"]["test"])
        assert atteso in test, nome
        assert s[nome]["restart"] == "unless-stopped", nome


def test_volume_dati():
    c = config()
    volumi = c["services"]["database"]["volumes"]
    assert any(v["type"] == "volume" and v["source"] == "dati-db" and v["target"] == "/var/lib/postgresql"
               for v in volumi)
    assert "dati-db" in c["volumes"]


def test_password_obbligatoria(tmp_path):
    # .env senza POSTGRES_PASSWORD: Compose si ferma con un messaggio che la nomina
    env = tmp_path / "senza_password.env"
    env.write_text("POSTGRES_USER=u\nPOSTGRES_DB=d\n", encoding="utf-8")
    esito = esegui_config(env)
    assert esito.returncode != 0
    assert "POSTGRES_PASSWORD" in esito.stderr


def test_nessuna_password_nei_file():
    for file in ("compose.yaml", "assistente-laboratorio/Dockerfile", "backend/Dockerfile",
                 "frontend/Dockerfile"):
        testo = (L6 / file).read_text(encoding="utf-8")
        assert "password-di-prova-123" not in testo, file
        assert "POSTGRES_PASSWORD" not in testo or file == "compose.yaml", file
        assert "POSTGRES_PASSWORD=" not in testo, file


def test_variabili_della_shell_ignorate(monkeypatch):
    # una password impostata nella shell non entra nella configurazione dei test (né nel loro output)
    monkeypatch.setenv("POSTGRES_PASSWORD", "segreto-della-shell")
    url = servizi()["backend"]["environment"]["DATABASE_URL"]
    assert "segreto-della-shell" not in url and "password-di-prova-123" in url


def test_password_solo_caratteri_sicuri_documentata():
    # la password finisce dentro DATABASE_URL e passa dall'interpolazione di Compose
    testo = (L6 / ".env.example").read_text(encoding="utf-8")
    assert "solo lettere, cifre, - e _" in testo


def test_a_capo_unix_per_i_file_docker():
    # Dockerfile, nginx.conf, compose.yaml e .dockerignore con LF anche in un clone su Windows
    righe = (L6 / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for regola in ("Dockerfile text eol=lf", "*.conf text eol=lf", "*.yaml text eol=lf",
                   ".dockerignore text eol=lf"):
        assert regola in righe, regola


def test_streaming_nel_backend():
    # STREAMING dal .env, attivo se manca (prova.env non la imposta)
    assert servizi()["backend"]["environment"]["STREAMING"] == "true"
