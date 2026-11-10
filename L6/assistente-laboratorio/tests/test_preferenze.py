# Test delle preferenze dell'utente nell'host: validazione campo per campo e blocco del prompt.
import json
import logging

import pytest

from app.preferenze import Preferenze, blocco_preferenze, predefinite, valida

RISERVA = "Europe/Rome"  # fuso di riserva (FUSO_PREDEFINITO o Europe/Rome)
# file completo e valido, diverso in ogni campo dai predefiniti
VALIDO = {"lingua": "inglese", "fuso": "America/New_York", "stile": "dettagliato"}


# Verifica che un file valido dia esattamente i suoi valori.
def test_file_valido():
    assert valida(json.dumps(VALIDO), RISERVA) == Preferenze("inglese", "America/New_York",
                                                              "dettagliato")


# Verifica che un campo non valido torni al predefinito senza toccare gli altri due.
@pytest.mark.parametrize("campo,valore", [("lingua", ""), ("lingua", 3), ("fuso", "Marte/Base"),
                                          ("fuso", 5), ("stile", "poetico"), ("stile", None)])
def test_campo_non_valido_solo_lui_predefinito(campo, valore, caplog):
    dati = dict(VALIDO, **{campo: valore})
    with caplog.at_level(logging.WARNING, logger="preferenze"):
        p = valida(json.dumps(dati), RISERVA)
    attesi = dict(VALIDO, **{campo: getattr(predefinite(RISERVA), campo)})
    assert p == Preferenze(**attesi)
    assert any(campo in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


# Verifica che un campo mancante prenda il predefinito con un avviso che lo nomina.
@pytest.mark.parametrize("campo", ["lingua", "fuso", "stile"])
def test_campo_mancante(campo, caplog):
    dati = {k: v for k, v in VALIDO.items() if k != campo}
    with caplog.at_level(logging.WARNING, logger="preferenze"):
        p = valida(json.dumps(dati), RISERVA)
    assert getattr(p, campo) == getattr(predefinite(RISERVA), campo)
    assert any(campo in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


# Verifica che maiuscole e spazi nello stile non facciano scartare il campo.
def test_stile_maiuscole_e_spazi():
    assert valida(json.dumps(dict(VALIDO, stile=" Sintetico ")), RISERVA).stile == "sintetico"


# Verifica che un JSON illeggibile dia tutti i predefiniti con un avviso.
def test_json_illeggibile(caplog):
    with caplog.at_level(logging.WARNING, logger="preferenze"):
        assert valida("{lingua", RISERVA) == predefinite(RISERVA)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# Verifica che un JSON che non e' un oggetto (lista) dia tutti i predefiniti con un avviso.
def test_json_non_oggetto(caplog):
    with caplog.at_level(logging.WARNING, logger="preferenze"):
        assert valida("[1, 2]", RISERVA) == predefinite(RISERVA)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# Verifica che la resource non disponibile (None) dia i predefiniti, detto nei log.
def test_none_resource_non_disponibile(caplog):
    with caplog.at_level(logging.WARNING, logger="preferenze"):
        assert valida(None, RISERVA) == predefinite(RISERVA)
    assert any("preferenze predefinite" in r.getMessage() for r in caplog.records)


# Verifica i predefiniti: italiano, sintetico, fuso di riserva passato dall'host.
def test_predefiniti_e_riserva_del_fuso():
    assert predefinite("Asia/Tokyo") == Preferenze("italiano", "Asia/Tokyo", "sintetico")
    assert valida(None, "Asia/Tokyo").fuso == "Asia/Tokyo"


# Verifica che i campi in piu' siano ignorati.
def test_campi_in_piu_ignorati():
    assert valida(json.dumps(dict(VALIDO, colore="blu")), RISERVA) == Preferenze(**VALIDO)


# Verifica il log delle preferenze in uso (evidenza: cosa usa la sessione).
def test_log_preferenze_in_uso(caplog):
    with caplog.at_level(logging.INFO, logger="preferenze"):
        valida(json.dumps(VALIDO), RISERVA)
    assert any("lingua=inglese fuso=America/New_York stile=dettagliato" in r.getMessage()
               for r in caplog.records)


# Verifica il testo esatto del blocco con lo stile sintetico.
def test_blocco_sintetico():
    assert blocco_preferenze(Preferenze("inglese", "America/New_York", "sintetico")) == (
        "Preferenze dell'utente (valgono per tutta la conversazione):\n"
        "- Rispondi sempre in inglese, anche se i risultati degli strumenti sono in un'altra "
        "lingua: traducili.\n"
        "- Fuso orario predefinito: America/New_York (New York). Ora e data senza un luogo si "
        "riferiscono a questo fuso.\n"
        "- Stile sintetico: rispondi in una o due frasi, solo con ciò che è stato chiesto.")


# Verifica la frase dello stile dettagliato.
def test_blocco_dettagliato():
    blocco = blocco_preferenze(Preferenze("italiano", "Europe/Rome", "dettagliato"))
    assert blocco.endswith("\n- Stile dettagliato: rispondi in modo completo, con qualche "
                           "spiegazione in più.")
    assert "(Rome)" in blocco
