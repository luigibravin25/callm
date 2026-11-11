# Test dei comandi della CLI (/prompts, /prompt): solo funzioni pure, nessun server MCP.
import pytest

from app.adattatore_mcp import InfoArgomento, InfoPrompt
from app.comandi import (MSG_ARG_SCONOSCIUTO, MSG_MANCANTE, MSG_NESSUN_PROMPT, MSG_NON_LEGGIBILI,
                         MSG_PROMPT_SCONOSCIUTO, MSG_SCONOSCIUTO, MSG_USO, RichiestaPrompt,
                         elenco_prompt, interpreta)

# elenco finto, come lo darebbe prompts/list del server
SPIEGA = InfoPrompt("spiega", "Spiega.", (InfoArgomento("argomento", True),
                                          InfoArgomento("livello", False)))
RIASSUMI = InfoPrompt("riassumi_conversazione", "Riassume.", (InfoArgomento("stile", False),))
PROMPTS = [SPIEGA, RIASSUMI]


# Verifica che le virgolette doppie tengano insieme un valore con spazi.
def test_prompt_con_virgolette_doppie():
    assert interpreta('/prompt spiega argomento="Model Context Protocol" livello=base',
                      PROMPTS) == RichiestaPrompt("spiega", {"argomento": "Model Context Protocol",
                                                             "livello": "base"})


# Verifica le virgolette singole e gli accenti nel valore.
def test_virgolette_singole_e_accenti():
    assert interpreta("/prompt spiega argomento='perché i fusi orari'", PROMPTS) == \
        RichiestaPrompt("spiega", {"argomento": "perché i fusi orari"})


# Verifica che i comandi valgano anche in maiuscolo.
def test_maiuscole_nel_comando():
    assert interpreta("/PROMPTS", PROMPTS) == elenco_prompt(PROMPTS)
    assert interpreta("/Prompt spiega argomento=x", PROMPTS) == \
        RichiestaPrompt("spiega", {"argomento": "x"})


# Verifica che un argomento facoltativo si possa omettere.
def test_facoltativo_omesso():
    assert interpreta("/prompt spiega argomento=MCP", PROMPTS) == \
        RichiestaPrompt("spiega", {"argomento": "MCP"})


# Verifica un prompt senza argomenti obbligatori richiamato senza argomenti.
def test_riassumi_senza_argomenti():
    assert interpreta("/prompt riassumi_conversazione", PROMPTS) == \
        RichiestaPrompt("riassumi_conversazione", {})


# Verifica ogni errore: messaggio fisso, nessuna richiesta al server.
@pytest.mark.parametrize("riga,atteso", [
    ("/xyz", MSG_SCONOSCIUTO.format(comando="/xyz")),
    ("/prompt", MSG_USO),
    ("/prompt meteo", MSG_PROMPT_SCONOSCIUTO.format(nome="meteo")),
    ("/prompt spiega livello=base", MSG_MANCANTE.format(argomento="argomento", nome="spiega")),
    ("/prompt spiega argomento=MCP colore=blu",
     MSG_ARG_SCONOSCIUTO.format(argomento="colore", nome="spiega", ammessi="argomento, livello")),
    ("/prompt spiega Model Context Protocol",
     MSG_NON_LEGGIBILI.format(dettaglio="'Model' senza =")),
    ("/prompt spiega argomento=l'agente",
     MSG_NON_LEGGIBILI.format(dettaglio="virgolette non chiuse")),
    ("/prompt spiega argomento=a argomento=b",
     MSG_NON_LEGGIBILI.format(dettaglio="chiave 'argomento' ripetuta")),
    ("/prompt spiega argomento=", MSG_NON_LEGGIBILI.format(dettaglio="valore vuoto per 'argomento'")),
    ("/prompt spiega =x", MSG_NON_LEGGIBILI.format(dettaglio="'=x' senza =")),
])
def test_errori(riga, atteso):
    assert interpreta(riga, PROMPTS) == atteso


# Verifica che senza server (elenco vuoto) entrambi i comandi lo dicano.
def test_server_non_avviato():
    assert interpreta("/prompts", []) == MSG_NESSUN_PROMPT
    assert interpreta("/prompt spiega argomento=x", []) == MSG_NESSUN_PROMPT


# Verifica il testo di /prompts: nome, descrizione e argomenti di ogni prompt.
def test_testo_dell_elenco():
    senza = InfoPrompt("vuoto", "Niente.", ())
    assert elenco_prompt(PROMPTS + [senza]) == (
        "Prompt disponibili:\n"
        "- spiega: Spiega.\n"
        "  argomenti: argomento (obbligatorio), livello (facoltativo)\n"
        "- riassumi_conversazione: Riassume.\n"
        "  argomenti: stile (facoltativo)\n"
        "- vuoto: Niente.\n"
        "  argomenti: nessuno")
