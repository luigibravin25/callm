# test del client HTTP verso l'agente: corpo inviato, risposta valida, errori tradotti o inoltrati
import httpx
import pytest

from app.client_agente import (ERRORI_INOLTRATI, MSG_INATTESA, MSG_NON_RAGGIUNGIBILE,
                               MSG_NON_VALIDA, MSG_TIMEOUT, ErroreAgente)
from tests.finti import URL_AGENTE, AgenteFinto, client_finto, risposta_ok

CRONOLOGIA = [{"role": "user", "content": "Ciao"}, {"role": "assistant", "content": "Ciao!"}]


# un turno con l'agente finto che risponde `risposta`; restituisce l'errore sollevato
def _errore(risposta) -> ErroreAgente:
    with pytest.raises(ErroreAgente) as e:
        client_finto(AgenteFinto([risposta])).turno("domanda", [], "")
    return e.value


# Verifica il corpo di POST /chat e la lettura della risposta.
def test_corpo_e_risposta():
    agente = AgenteFinto([risposta_ok("Sono le 20", CRONOLOGIA, "riass",
                                      [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}])])
    r = client_finto(agente).turno("Ore a Tokyo?", CRONOLOGIA, "prima")
    assert agente.percorsi == [("POST", "/chat")]
    assert agente.corpi == [{"messaggio": "Ore a Tokyo?", "cronologia": CRONOLOGIA,
                             "riassunto": "prima"}]
    assert (r.risposta, r.cronologia, r.riassunto) == ("Sono le 20", CRONOLOGIA, "riass")
    assert r.strumenti_usati == [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}]


# Verifica che campi in piu' e argomento assente siano accettati.
def test_risposta_con_campi_in_piu():
    codice, corpo = risposta_ok("ok")
    del corpo["argomento"]
    corpo["nuovo"] = 1
    assert client_finto(AgenteFinto([(codice, corpo)])).turno("d", [], "").risposta == "ok"


# Verifica agente spento e timeout.
def test_rete_e_timeout():
    e = _errore(httpx.ConnectError("rifiutata"))
    assert (e.status, e.errore) == (503, "agente_non_raggiungibile")
    assert e.messaggio == MSG_NON_RAGGIUNGIBILE.format(url=URL_AGENTE)
    assert MSG_NON_RAGGIUNGIBILE == "L'agente non è raggiungibile su {url}: è avviato?"
    e = _errore(httpx.ReadTimeout("lento"))
    assert (e.status, e.errore) == (504, "agente_in_timeout")
    assert e.messaggio == "L'agente non ha risposto entro 5 secondi."
    assert MSG_TIMEOUT.format(secondi=5) == e.messaggio


# Verifica l'inoltro degli errori dell'agente per POST /chat (stesso status, codice, messaggio).
@pytest.mark.parametrize("codice, errore", sorted(ERRORI_INOLTRATI))
def test_errori_inoltrati(codice, errore):
    e = _errore((codice, {"errore": errore, "messaggio": "Spiegazione dell'agente."}))
    assert (e.status, e.errore, e.messaggio) == (codice, errore, "Spiegazione dell'agente.")


# Verifica l'elenco degli errori inoltrati.
def test_elenco_inoltrati():
    assert ERRORI_INOLTRATI == {(422, "richiesta_non_valida"), (502, "errore_del_modello"),
                                (503, "modello_non_raggiungibile"), (503, "mcp_non_disponibile"),
                                (504, "modello_in_timeout"), (500, "errore_interno")}


# Verifica un errore dell'agente che non riguarda /chat (AGENTE_URL sbagliato): 502 con consiglio.
def test_errore_inatteso():
    e = _errore((404, {"errore": "percorso_non_trovato", "messaggio": "Percorso non trovato."}))
    assert (e.status, e.errore) == (502, "risposta_agente_non_valida")
    assert e.messaggio == MSG_INATTESA.format(status=404, messaggio="Percorso non trovato.")
    assert "Controllare AGENTE_URL." in e.messaggio


# Verifica le risposte illeggibili o incomplete: 502 con il codice.
@pytest.mark.parametrize("risposta, status", [
    ((500, "Internal Server Error"), 500),
    ((200, "non json"), 200),
    ((200, {**risposta_ok("x")[1], "risposta": 3}), 200),
    ((200, {"risposta": "x"}), 200),
    ((200, [1, 2]), 200),
])
def test_risposte_non_valide(risposta, status):
    e = _errore(risposta)
    assert (e.status, e.errore) == (502, "risposta_agente_non_valida")
    assert e.messaggio == MSG_NON_VALIDA.format(status=status)
