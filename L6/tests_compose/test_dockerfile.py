# test dei Dockerfile dell'agente e del back-end (lettura dei file, senza Docker)
# librerie standard: percorsi
from pathlib import Path

import pytest

L6 = Path(__file__).resolve().parents[1]
CONTESTI = {"agente": L6 / "assistente-laboratorio", "backend": L6 / "backend"}


def dockerfile(nome: str) -> str:
    return (CONTESTI[nome] / "Dockerfile").read_text(encoding="utf-8")


@pytest.mark.parametrize("nome", ["agente", "backend"])
def test_immagine_python_slim_utente_non_root(nome):
    testo = dockerfile(nome)
    righe = [r.strip() for r in testo.splitlines() if r.strip() and not r.strip().startswith("#")]
    assert righe[0] == "FROM python:3.14-slim"
    for parte in ("useradd --create-home --uid 1000 utente", "USER utente", "PYTHONUNBUFFERED=1",
                  "pip install --no-cache-dir -r requirements.txt", 'CMD ["python", "-m", "app.api"]'):
        assert parte in testo, parte
    # le dipendenze prima del codice: il livello di pip resta in cache se cambia solo il codice
    copie = [r for r in righe if r.startswith("COPY")]
    assert copie[0].startswith("COPY requirements.txt")
    # nessun segreto nell'immagine
    assert ".env" not in testo


def test_agente_copia_codice_mcp_e_config():
    testo = dockerfile("agente")
    for cartella in ("app/", "mcp_assistente/", "config/"):
        assert f"COPY {cartella}" in testo, cartella


@pytest.mark.parametrize("nome", ["agente", "backend"])
def test_dockerignore(nome):
    voci = (CONTESTI[nome] / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for voce in (".env", "tests/", "__pycache__/"):
        assert voce in voci, voce
