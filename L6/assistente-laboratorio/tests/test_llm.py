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


# Verifica che il modello del revisore non riceva strumenti.
def test_revisore_llm_senza_strumenti():
    from app.llm import build_revisore_llm
    assert "tooltime" not in repr(build_revisore_llm(IMPOSTAZIONI))


# Verifica che il prompt dell'agente spieghi i messaggi [Revisore].
def test_system_prompt_spiega_il_revisore():
    from app.llm import FRASE_REVISORE, SYSTEM_PROMPT
    assert FRASE_REVISORE in SYSTEM_PROMPT


# Verifica che il modello del riassunto non riceva strumenti.
def test_riassunto_llm_senza_strumenti():
    from app.llm import build_riassunto_llm
    assert "tooltime" not in repr(build_riassunto_llm(IMPOSTAZIONI))
