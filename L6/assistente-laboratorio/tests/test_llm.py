# test dei collegamenti a LM Studio: l'agente conosce tooltime, il router nessuno strumento
from pathlib import Path

from app.config import Settings
from app.llm import build_llm, build_router_llm

# impostazioni di prova: nessuna richiesta parte durante la costruzione dei modelli
IMPOSTAZIONI = Settings(base_url="http://127.0.0.1:1234/v1", model="google/gemma-4-e2b",
                        max_steps=5, fuso_predefinito="Europe/Rome",
                        ambito_file=Path("config/ambito.toml"))


# Verifica che il modello dell'agente conosca tooltime.
def test_agente_llm_con_tooltime():
    llm = build_llm(IMPOSTAZIONI)
    assert llm.kwargs["tools"][0]["function"]["name"] == "tooltime"


# Verifica che il modello del router non riceva strumenti.
def test_router_llm_senza_strumenti():
    router_llm = build_router_llm(IMPOSTAZIONI)
    assert "tooltime" not in repr(router_llm)
