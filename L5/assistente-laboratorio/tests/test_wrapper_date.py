# Test del wrapper `tooldate` (tools.date_e_scadenze) che chiama POST /giorni del servizio.
# Nessuna rete: httpx.MockTransport risponde al posto del servizio vero.
# json legge il corpo inviato; httpx e' il client HTTP del wrapper
import json

import httpx
import pytest

from app import tools

# avviso di risultato non normativo, come lo manda il servizio
AVVISO = "Calcolo indicativo, non ha valore legale."

# Risposte finte del servizio, una per operazione: giorni lavorativi di dicembre 2026,
# scadenza di 5 giorni di calendario slittata dalla domenica al lunedi', Natale 2026.
DICEMBRE = {
    "operazione": "giorni", "da": "2026-12-01", "da_giorno": "martedì", "a": "2026-12-31",
    "a_giorno": "giovedì", "conteggio": "estremi compresi", "giorni_calendario": 31,
    "giorni_lavorativi": 21,
    "festivita": [{"data": "2026-12-08", "nome": "Immacolata Concezione"},
                  {"data": "2026-12-25", "nome": "Natale"}],
    "avviso": AVVISO,
}
SCADENZA = {
    "operazione": "scadenza", "da": "2026-11-03", "da_giorno": "martedì", "giorni": 5,
    "tipo": "calendario", "scadenza": "2026-11-09", "scadenza_giorno": "lunedì",
    "slittata_da": "2026-11-08", "motivo_slittamento": "domenica", "avviso": AVVISO,
}
GIORNO = {
    "operazione": "giorno", "data": "2026-12-25", "giorno_settimana": "venerdì",
    "lavorativo": False, "fine_settimana": False, "festivita": ["Natale"], "avviso": AVVISO,
}


# Fixture: servizio HTTP finto (come in test_wrapper_calcolatrice.py). "installa(handler)"
# sceglie la risposta e restituisce la lista delle richieste fatte dal wrapper.
@pytest.fixture
def servizio_finto(monkeypatch):
    richieste = []

    def installa(handler):
        # registra la richiesta, poi lascia rispondere l'handler del test
        def registra(request):
            richieste.append(request)
            return handler(request)
        # il wrapper riceve un client httpx con il trasporto finto
        monkeypatch.setattr(tools, "_client",
                            lambda: httpx.Client(transport=httpx.MockTransport(registra)))
        return richieste
    # senza CALC_BASE_URL il wrapper usa l'indirizzo predefinito
    monkeypatch.delenv("CALC_BASE_URL", raising=False)
    return installa


# Supporto: handler che risponde sempre con la stessa risposta HTTP.
def risposta(*args, **kwargs):
    return lambda request: httpx.Response(*args, **kwargs)


# Supporto: chiama lo strumento con argomenti per nome, come farebbe il grafo.
def chiama(**argomenti):
    return tools.date_e_scadenze.invoke(argomenti)


# Verifica la frase completa per l'operazione "giorni": periodo, conteggi, festivita', avviso.
def test_testo_giorni(servizio_finto):
    servizio_finto(risposta(200, json=DICEMBRE))
    assert chiama(operazione="giorni", data="31/12/2026", da="1/12/2026") == (
        "Dal 2026-12-01 (martedì) al 2026-12-31 (giovedì), estremi compresi: "
        "giorni lavorativi 21, giorni di calendario 31. Festività in giorni feriali: "
        "2026-12-08 Immacolata Concezione, 2026-12-25 Natale. " + AVVISO)


# Verifica che una lista di festivita' vuota si legga "nessuna".
def test_testo_giorni_senza_festivita(servizio_finto):
    # {**DICEMBRE, ...}: copia della risposta con il solo campo "festivita" cambiato
    servizio_finto(risposta(200, json={**DICEMBRE, "festivita": []}))
    assert "Festività in giorni feriali: nessuna." in chiama(operazione="giorni", data="x")


# Verifica la frase della scadenza slittata: spiega perche' la data e' stata spostata.
def test_testo_scadenza_slittata(servizio_finto):
    servizio_finto(risposta(200, json=SCADENZA))
    assert chiama(operazione="scadenza", giorni=5, tipo="calendario") == (
        "Scadenza: 2026-11-09 (lunedì), 5 giorni di calendario da 2026-11-03 (martedì). "
        "La data calcolata 2026-11-08 cade di domenica: slitta al primo giorno lavorativo. "
        + AVVISO)


# Verifica la frase della scadenza senza slittamento: nessuna spiegazione in piu'.
def test_testo_scadenza_non_slittata(servizio_finto):
    servizio_finto(risposta(200, json={**SCADENZA, "tipo": "lavorativi", "giorni": 3,
                                       "slittata_da": None, "motivo_slittamento": None}))
    assert chiama(operazione="scadenza", giorni=3) == (
        "Scadenza: 2026-11-09 (lunedì), 3 giorni lavorativi da 2026-11-03 (martedì). " + AVVISO)


# Verifica le tre frasi dell'operazione "giorno": festivo (con il nome della festa),
# lavorativo, fine settimana.
def test_testo_giorno_festivo(servizio_finto):
    servizio_finto(risposta(200, json=GIORNO))
    assert chiama(operazione="giorno", data="natale") == (
        "2026-12-25 (venerdì): festivo (Natale). " + AVVISO)


def test_testo_giorno_lavorativo(servizio_finto):
    servizio_finto(risposta(200, json={**GIORNO, "data": "2026-11-03",
                                       "giorno_settimana": "martedì", "lavorativo": True,
                                       "festivita": []}))
    assert chiama(operazione="giorno", data="oggi") == (
        "2026-11-03 (martedì): giorno lavorativo. " + AVVISO)


def test_testo_fine_settimana(servizio_finto):
    servizio_finto(risposta(200, json={**GIORNO, "data": "2026-11-07",
                                       "giorno_settimana": "sabato", "fine_settimana": True,
                                       "festivita": []}))
    assert chiama(operazione="giorno", data="7/11/2026") == (
        "2026-11-07 (sabato): fine settimana, non lavorativo. " + AVVISO)


# Verifica che il rifiuto del servizio (400) arrivi al modello con il motivo.
def test_rifiuto_400(servizio_finto):
    servizio_finto(risposta(400, json={"errore": "il 2027 non è bisestile"}))
    assert chiama(operazione="giorno", data="29/02/2027") == (
        "Data rifiutata: il 2027 non è bisestile")


# Verifica che risposte incomplete o con tipi sbagliati diano "Risposta non valida" e non
# un'eccezione: campi mancanti, festivita' come testo invece che lista, voce non oggetto.
@pytest.mark.parametrize("corpo", [
    {"operazione": "giorni"}, {**GIORNO, "festivita": "Natale"}, {**DICEMBRE, "festivita": [1]},
])
def test_campi_mancanti_o_sbagliati(servizio_finto, corpo):
    servizio_finto(risposta(200, json=corpo))
    assert chiama(operazione=corpo["operazione"], data="x") == (
        "Risposta non valida dal servizio HTTP.")


# Verifica il corpo inviato: niente argomenti vuoti, "tipo" con il valore predefinito.
def test_corpo_inviato_senza_vuoti(servizio_finto):
    richieste = servizio_finto(risposta(200, json=GIORNO))
    chiama(operazione="giorno", data="natale")
    assert json.loads(richieste[0].content) == {
        "operazione": "giorno", "data": "natale", "tipo": "lavorativi"}


# Verifica che giorni=0 sia inviato: e' un valore valido, non un argomento vuoto da togliere.
def test_giorni_zero_inviato(servizio_finto):
    richieste = servizio_finto(risposta(200, json=SCADENZA))
    chiama(operazione="scadenza", giorni=0)
    assert json.loads(richieste[0].content)["giorni"] == 0


# Verifica l'indirizzo predefinito dell'endpoint /giorni (stesso servizio della calcolatrice).
def test_url_giorni(servizio_finto):
    richieste = servizio_finto(risposta(200, json=GIORNO))
    chiama(operazione="giorno", data="natale")
    assert str(richieste[0].url) == "http://127.0.0.1:8001/giorni"


# Verifica il timeout: il servizio finto solleva ReadTimeout, il wrapper risponde con un testo.
def test_timeout(servizio_finto):
    def handler(request):
        raise httpx.ReadTimeout("simulato", request=request)
    servizio_finto(handler)
    assert chiama(operazione="giorno", data="oggi") == (
        "Il servizio HTTP non ha risposto entro 5 secondi.")


# Verifica il servizio spento: messaggio con l'indirizzo provato.
def test_non_raggiungibile(servizio_finto, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("simulato", request=request)
    servizio_finto(handler)
    monkeypatch.setenv("CALC_BASE_URL", "http://spento:9")
    assert "non raggiungibile a http://spento:9" in chiama(operazione="giorno", data="oggi")


# Verifica nome, argomenti e descrizione visti dal modello (testo semplice e avviso).
def test_nome_e_schema():
    assert tools.date_e_scadenze.name == "tooldate"
    assert set(tools.date_e_scadenze.args) == {"operazione", "data", "da", "giorni", "tipo"}
    descrizione = tools.date_e_scadenze.description
    assert "senza LaTeX" in descrizione and AVVISO in descrizione


# Verifica che la descrizione limiti l'avviso alle sole risposte che usano tooldate.
def test_avviso_solo_per_le_risposte_sulle_date():
    # con l'agente unico (6 tool) il modello metteva l'avviso anche nelle risposte sul catalogo
    descrizione = tools.date_e_scadenze.description
    assert "solo" in descrizione and "tooldate" in descrizione
    assert "non aggiungerla alle risposte che non usano tooldate" in descrizione
