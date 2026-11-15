# test dei requisiti divisi: ogni immagine installa solo le sue dipendenze, il venv le include tutte
# librerie standard: percorsi
from pathlib import Path

# cartella L6 (sopra tests_compose)
L6 = Path(__file__).resolve().parents[1]
COMUNE = L6 / "requirements.txt"
AGENTE = L6 / "assistente-laboratorio" / "requirements.txt"
BACKEND = L6 / "backend" / "requirements.txt"

# versioni di oggi (step 1-8): nessuna cambia con la divisione
VERSIONI = {
    "langgraph": "1.2.17", "langchain-openai": "1.7.2", "tzdata": "2026.5", "fastmcp": "3.4.11",
    "langchain-mcp-adapters": "0.3.2", "fastapi": "0.162.5", "uvicorn": "0.54.0", "httpx": "0.28.1",
    "sqlalchemy": "2.1.8", "psycopg[binary]": "3.3.9", "pytest": "9.1.1",
}


# righe utili di un file di requisiti (senza commenti e righe vuote)
def righe(file: Path) -> list[str]:
    return [r.strip() for r in file.read_text(encoding="utf-8").splitlines()
            if r.strip() and not r.strip().startswith("#")]


# pacchetti "nome==versione" di un file → {nome: versione}
def pacchetti(file: Path) -> dict[str, str]:
    return dict(r.split("==", 1) for r in righe(file) if "==" in r)


def test_requisiti_comuni_includono_i_componenti():
    assert righe(COMUNE) == ["-r assistente-laboratorio/requirements.txt",
                             "-r backend/requirements.txt", "pytest==9.1.1"]


def test_agente_senza_database_ne_pytest():
    assert set(pacchetti(AGENTE)) == {"langgraph", "langchain-openai", "tzdata", "fastmcp",
                                      "langchain-mcp-adapters", "fastapi", "uvicorn", "httpx"}


def test_backend_senza_langchain_ne_pytest():
    assert set(pacchetti(BACKEND)) == {"fastapi", "uvicorn", "httpx", "sqlalchemy", "psycopg[binary]"}


def test_stesse_versioni():
    # ogni pacchetto ha la versione di oggi, anche se compare in più file
    for file in (COMUNE, AGENTE, BACKEND):
        for nome, versione in pacchetti(file).items():
            assert versione == VERSIONI[nome], f"{file.name}: {nome}=={versione}"
