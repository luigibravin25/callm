# prova reale di Compose (RUN_COMPOSE=1, Docker e LM Studio accesi): avvio dei quattro servizi, chat con
# tooltime attraverso nginx, agente non esposto, dati ancora presenti dopo down e up. Lenta (build e modello).
# librerie standard: JSON, ambiente, percorsi, esecuzione di docker, attese; httpx per le chiamate HTTP
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

L6 = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8080"
# cinque servizi: dalla lezione 7 «docker compose up -d --build» avvia anche qdrant (la ricerca dell'agente)
SERVIZI = {"frontend", "backend", "agente", "database", "qdrant"}

pytestmark = pytest.mark.skipif(os.environ.get("RUN_COMPOSE") != "1",
                                reason='imposta $env:RUN_COMPOSE = "1" con Docker e LM Studio accesi')


# docker compose <argomenti> da L6 (legge L6/.env); fallisce il test se il comando fallisce
def compose(*argomenti: str, timeout: int = 900, controlla: bool = True) -> subprocess.CompletedProcess:
    esito = subprocess.run(["docker", "compose", *argomenti], cwd=L6, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    if controlla:
        assert esito.returncode == 0, esito.stderr
    return esito


# attende che i quattro servizi siano "healthy" (massimo 180 s); restituisce lo stato visto
def attendi_salute(massimo: float = 180) -> dict[str, str]:
    fine = time.monotonic() + massimo
    stati: dict[str, str] = {}
    while time.monotonic() < fine:
        # ps --format json: un oggetto JSON per riga
        righe = compose("ps", "--format", "json").stdout.splitlines()
        stati = {o["Service"]: o.get("Health", "") for o in map(json.loads, filter(None, righe))}
        if set(stati) == SERVIZI and all(v == "healthy" for v in stati.values()):
            return stati
        time.sleep(3)
    pytest.fail(f"servizi non healthy entro {massimo} s: {stati}")


def test_avvio_chat_e_dati_dopo_down():
    compose("up", "-d", "--build")
    id_chat = None
    try:
        attendi_salute()
        # configurazione di nginx valida dentro la rete di Compose
        assert compose("exec", "-T", "frontend", "nginx", "-t").returncode == 0
        with httpx.Client(base_url=BASE, timeout=330) as http:
            # interfaccia servita da nginx
            pagina = http.get("/")
            assert pagina.status_code == 200 and '<div id="app">' in pagina.text
            # chat attraverso il proxy /api: back-end → agente → LM Studio, con tooltime
            creata = http.post("/api/chat")
            assert creata.status_code == 201
            id_chat = creata.json()["id"]
            turno = http.post(f"/api/chat/{id_chat}/messaggi", json={"testo": "Che ore sono a Tokyo?"})
            assert turno.status_code == 200, turno.text
            nomi = [s["nome"] for s in turno.json()["risposta"]["strumenti"] or []]
            assert "tooltime" in nomi
        assert "tools/call tooltime" in compose("logs", "agente").stdout + compose("logs", "agente").stderr
        # agente non esposto: nessuna porta pubblicata
        porta = compose("port", "agente", "8000", controlla=False)
        assert porta.returncode != 0 or not porta.stdout.strip()
        # down (volume conservato) e di nuovo up: la chat c'è ancora
        compose("down")
        compose("up", "-d")
        attendi_salute()
        with httpx.Client(base_url=BASE, timeout=30) as http:
            letta = http.get(f"/api/chat/{id_chat}")
            assert letta.status_code == 200
            assert len(letta.json()["messaggi"]) == 2
    finally:
        # pulizia: chat di prova cancellata, servizi fermi, volume conservato
        if id_chat is not None:
            try:
                httpx.delete(f"{BASE}/api/chat/{id_chat}", timeout=10)
            except httpx.HTTPError:
                pass
        compose("down", controlla=False)
