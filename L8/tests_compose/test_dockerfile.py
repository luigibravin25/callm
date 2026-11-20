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


# Verifica che l'immagine dell'agente contenga il server di ricerca (contesto di build aggiuntivo «ricerca»):
# requisiti installati prima del codice, app/ e mcp_ricerca/ in /ricerca, dove l'adattatore li cerca.
def test_agente_copia_la_ricerca():
    testo = dockerfile("agente")
    righe = [r.strip() for r in testo.splitlines() if r.strip() and not r.strip().startswith("#")]
    for riga in ("COPY --from=ricerca requirements.txt /ricerca/requirements.txt",
                 "RUN pip install --no-cache-dir -r /ricerca/requirements.txt",
                 "COPY --from=ricerca app/ /ricerca/app/",
                 "COPY --from=ricerca mcp_ricerca/ /ricerca/mcp_ricerca/"):
        assert riga in righe, riga
    # requisiti della ricerca installati prima di copiare il codice (livello di pip in cache)
    assert righe.index("RUN pip install --no-cache-dir -r /ricerca/requirements.txt") < righe.index("COPY app/ app/")
    # e dopo i requisiti dell'agente
    assert righe.index("RUN pip install --no-cache-dir -r requirements.txt") <         righe.index("COPY --from=ricerca requirements.txt /ricerca/requirements.txt")


# Verifica che il contesto «ricerca» escluda le cache di Python (le __pycache__ dell'host non entrano in /ricerca).
def test_dockerignore_della_ricerca():
    voci = (L6 / "ricerca" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "**/__pycache__" in voci and ".env" in voci
