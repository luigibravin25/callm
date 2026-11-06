# Test del wrapper `toolcalc` (tools.calcola_espressione) che chiama il servizio FastAPI.
# Nessuna rete: httpx.MockTransport risponde al posto del servizio vero.
# json legge il corpo inviato; httpx e' il client HTTP del wrapper
import json

import httpx
import pytest

from app import tools


# Fixture: servizio HTTP finto. Restituisce la funzione "installa(handler)": l'handler decide
# la risposta, e ogni richiesta del wrapper viene registrata nella lista restituita.
@pytest.fixture
def servizio_finto(monkeypatch):
    """Sostituisce il client HTTP del wrapper con uno che risponde tramite `handler`.
    Restituisce l'elenco delle richieste ricevute."""
    richieste = []

    def installa(handler):
        # registra la richiesta, poi lascia rispondere l'handler del test
        def registra(request):
            richieste.append(request)
            return handler(request)
        # il wrapper crea il client con tools._client(): qui ne riceve uno con il trasporto finto
        monkeypatch.setattr(tools, "_client",
                            lambda: httpx.Client(transport=httpx.MockTransport(registra)))
        return richieste
    # senza CALC_BASE_URL il wrapper usa l'indirizzo predefinito
    monkeypatch.delenv("CALC_BASE_URL", raising=False)
    return installa


# Supporto: chiama lo strumento come farebbe il grafo, con l'argomento "espressione".
def chiama(espressione):
    return tools.calcola_espressione.invoke({"espressione": espressione})


# Supporto: handler che risponde sempre con la stessa risposta HTTP (codice, json, testo...).
def risposta(*args, **kwargs):
    return lambda request: httpx.Response(*args, **kwargs)


# Supporto: handler che simula un errore di rete (timeout, connessione rifiutata...).
def solleva(eccezione):
    def handler(request):
        raise eccezione("simulato", request=request)
    return handler


# Verifica che il risultato sia scritto all'italiana: virgola e 6 cifre significative.
def test_risultato_formattato(servizio_finto):
    servizio_finto(risposta(200, json={"espressione": "2^0.5", "risultato": 1.4142135623730951}))
    assert chiama("2^0.5") == "2^0.5 = 1,41421"


# Verifica che un numero grande sia scritto in notazione "× 10^", non come 1e+20.
def test_risultato_grande(servizio_finto):
    servizio_finto(risposta(200, json={"espressione": "10^20", "risultato": 1e20}))
    assert chiama("10^20") == "10^20 = 1 × 10^20"


# Verifica che il rifiuto del servizio (400) arrivi al modello con il motivo.
def test_rifiuto_del_servizio(servizio_finto):
    servizio_finto(risposta(400, json={"errore": "divisione per zero"}))
    assert chiama("1/0") == "Espressione rifiutata: divisione per zero"


# Verifica che un 422 (richiesta malformata) sia riportato con il suo codice.
def test_422(servizio_finto):
    servizio_finto(risposta(422, json={"detail": []}))
    assert "HTTP 422" in chiama("1+1")


# Verifica che un errore interno del servizio (500) diventi un messaggio chiaro.
def test_errore_500(servizio_finto):
    servizio_finto(risposta(500, text="Internal Server Error"))
    assert chiama("1+1") == "Il servizio HTTP ha risposto con l'errore HTTP 500."


# Verifica il timeout: il wrapper attende al massimo 5 secondi e poi lo dice.
def test_timeout(servizio_finto):
    servizio_finto(solleva(httpx.ReadTimeout))
    assert chiama("1+1") == "Il servizio HTTP non ha risposto entro 5 secondi."


# Verifica il servizio spento: messaggio con l'indirizzo provato e nessun Traceback.
def test_non_raggiungibile(servizio_finto, monkeypatch):
    servizio_finto(solleva(httpx.ConnectError))
    monkeypatch.setenv("CALC_BASE_URL", "http://spento:9")
    testo = chiama("1+1")
    assert "non raggiungibile a http://spento:9" in testo
    assert "Traceback" not in testo


# Verifica che risposte con forma inattesa diano tutte lo stesso messaggio, senza eccezioni:
# testo non JSON, campo mancante, risultato come testo o booleano, errore senza "errore",
# lista al posto dell'oggetto, 400 non JSON.
@pytest.mark.parametrize("finta", [
    httpx.Response(200, text="non json"), httpx.Response(200, json={}),
    httpx.Response(200, json={"risultato": "7"}), httpx.Response(200, json={"risultato": True}),
    httpx.Response(400, json={"messaggio": "x"}), httpx.Response(200, json=[1]),
    httpx.Response(400, text="rotto"),
])
def test_risposta_non_valida(servizio_finto, finta):
    servizio_finto(lambda request: finta)
    assert chiama("1+1") == "Risposta non valida dal servizio HTTP."


# Verifica che CALC_BASE_URL sia letta a ogni chiamata, non una volta sola all'avvio.
def test_url_letta_a_ogni_chiamata(servizio_finto, monkeypatch):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    # due chiamate con indirizzi diversi
    monkeypatch.setenv("CALC_BASE_URL", "http://primo:8001")
    chiama("1+1")
    monkeypatch.setenv("CALC_BASE_URL", "http://secondo:8001")
    chiama("1+1")
    # controllo: ogni richiesta e' andata all'indirizzo in vigore in quel momento
    assert [str(r.url) for r in richieste] == [
        "http://primo:8001/calcola", "http://secondo:8001/calcola"]


# Verifica che una barra finale nell'indirizzo non produca "//calcola".
def test_url_senza_doppia_barra(servizio_finto, monkeypatch):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    monkeypatch.setenv("CALC_BASE_URL", "http://host:8001/")
    chiama("1+1")
    assert str(richieste[0].url) == "http://host:8001/calcola"


# Verifica l'indirizzo predefinito senza CALC_BASE_URL: il servizio locale sulla porta 8001.
def test_url_predefinita(servizio_finto):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    chiama("1+1")
    assert str(richieste[0].url) == "http://127.0.0.1:8001/calcola"


# Verifica la richiesta inviata: metodo POST e corpo JSON con la sola espressione.
def test_corpo_inviato(servizio_finto):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    chiama("1+1")
    assert richieste[0].method == "POST"
    assert json.loads(richieste[0].content) == {"espressione": "1+1"}


# Verifica nome e argomenti visti dal modello; la descrizione spiega l'operatore "^".
def test_nome_e_schema():
    assert tools.calcola_espressione.name == "toolcalc"
    assert set(tools.calcola_espressione.args) == {"espressione"}
    assert "^" in tools.calcola_espressione.description


# Verifica che toolcalc sia registrato tra gli strumenti locali, nell'ordine previsto.
def test_strumenti_registrati():
    assert [t.name for t in tools.STRUMENTI] == ["tooltime", "toolconvert", "toolcalc", "tooldate"]


# --- correzioni della revisione finale: il wrapper non solleva mai ---

# Verifica che un indirizzo malformato (lettera O al posto dello zero) dia un messaggio chiaro.
def test_url_non_valida(servizio_finto, monkeypatch):
    servizio_finto(risposta(200, json={"risultato": 2}))
    monkeypatch.setenv("CALC_BASE_URL", "http://localhost:80O1")
    testo = chiama("1+1")
    assert "CALC_BASE_URL non valida" in testo and "80O1" in testo


# Verifica che un corpo dichiarato gzip ma illeggibile non faccia sollevare il wrapper.
def test_corpo_compresso_rotto(servizio_finto):
    servizio_finto(risposta(200, headers={"content-encoding": "gzip"}, content=b"spazzatura"))
    assert chiama("1+1") == "Risposta non valida dal servizio HTTP."


# Verifica che un intero troppo grande per essere scritto come float sia trattato come non valido.
def test_risultato_intero_enorme(servizio_finto):
    servizio_finto(risposta(200, json={"risultato": 10**400}))
    assert chiama("1+1") == "Risposta non valida dal servizio HTTP."


# Verifica che la descrizione chieda al modello risposte in testo semplice, senza LaTeX.
def test_descrizione_chiede_testo_semplice():
    # il modello tende a rispondere in LaTeX ("$5$ alla seconda fa $25$"): il terminale non lo rende
    descrizione = tools.calcola_espressione.description
    assert "senza LaTeX" in descrizione and "$" in descrizione
