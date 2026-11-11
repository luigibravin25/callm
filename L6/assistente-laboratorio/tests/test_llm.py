# test dei collegamenti a LM Studio: l'agente conosce gli strumenti MCP, il router nessuno
from pathlib import Path

from app.config import Ambito, Argomento, Settings
from app.llm import build_llm, build_router_llm
from app.preferenze import Preferenze
from tests.finti import tooltime_finto

# impostazioni di prova: nessuna richiesta parte durante la costruzione dei modelli
IMPOSTAZIONI = Settings(base_url="http://127.0.0.1:1234/v1", model="google/gemma-4-e2b",
                        max_steps=5, fuso_predefinito="Europe/Rome",
                        ambito_file=Path("config/ambito.toml"))
# ambito di prova con un argomento (lo schema del router dipende dagli argomenti)
AMBITO = Ambito(descrizione="Prova.", rifiuto="No.",
                argomenti=(Argomento("ora_data_fusi", "ora e data"),))
# preferenze di prova per il prompt dell'agente
PREFERENZE = Preferenze("inglese", "America/New_York", "sintetico")


# Verifica che il modello dell'agente conosca gli strumenti passati (quelli del server MCP).
def test_agente_llm_con_gli_strumenti_passati():
    llm = build_llm(IMPOSTAZIONI, [tooltime_finto([])])
    assert llm.kwargs["tools"][0]["function"]["name"] == "tooltime"


# Verifica che senza strumenti (server MCP non partito) il modello non riceva tools.
def test_agente_llm_senza_strumenti():
    assert "tools" not in getattr(build_llm(IMPOSTAZIONI, []), "kwargs", {})


# Verifica che il blocco delle preferenze stia in cima al prompt dell'agente.
def test_prompt_agente_blocco_in_cima():
    from app.llm import FRASE_SENZA_STRUMENTI, SYSTEM_PROMPT, prompt_agente
    prompt = prompt_agente(PREFERENZE, True)
    assert prompt.startswith("Preferenze dell'utente")
    assert prompt.endswith(SYSTEM_PROMPT)
    assert FRASE_SENZA_STRUMENTI not in prompt


# Verifica che senza strumenti il prompt dica di non inventare l'ora.
def test_prompt_agente_senza_strumenti():
    from app.llm import FRASE_SENZA_STRUMENTI, prompt_agente
    assert prompt_agente(PREFERENZE, False).endswith(FRASE_SENZA_STRUMENTI)


# Verifica che il modello del router non riceva strumenti.
def test_router_llm_senza_strumenti():
    router_llm = build_router_llm(IMPOSTAZIONI, AMBITO)
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



# Verifica che il router riceva lo schema costruito dagli argomenti dell'ambito.
def test_router_llm_usa_lo_schema_dell_ambito():
    # response_format e' la classe dello schema: i valori ammessi stanno nel suo json_schema
    schema = build_router_llm(IMPOSTAZIONI, AMBITO).first.kwargs["response_format"]
    enum = schema.model_json_schema()["properties"]["argomento"]["enum"]
    assert enum == ["ora_data_fusi", "altro"]
