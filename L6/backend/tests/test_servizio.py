# test delle operazioni sulle chat e del turno tutto o niente (PostgreSQL vero, agente finto)
import httpx
import pytest
from sqlalchemy import func, select

from app.client_agente import ErroreAgente
from app.db import TITOLO_INIZIALE, Chat, Messaggio
from app.servizio import (ChatNonTrovata, crea_chat, elenca_chat, elimina_chat, invia_messaggio,
                          leggi_chat, titolo_da_domanda)
from tests.finti import AgenteFinto, client_finto, risposta_ok

STRUMENTI = [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}]
# cronologia del primo turno con uno strumento (come la restituisce l'agente)
CRONOLOGIA_1 = [
    {"role": "user", "content": "Ore a Tokyo?"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "tooltime", "arguments": "{\"fuso\": \"Asia/Tokyo\"}"}}]},
    {"role": "tool", "content": "20:00", "tool_call_id": "c1", "name": "tooltime"},
    {"role": "assistant", "content": "A Tokyo sono le 20."},
]


# numero di righe della tabella messaggi
def _messaggi_totali(fabbrica):
    with fabbrica() as s:
        return s.scalar(select(func.count()).select_from(Messaggio))


# --- titolo ---

# Verifica il titolo dalla prima domanda.
@pytest.mark.parametrize("testo, atteso", [
    ("Che ore sono?", "Che ore sono?"),
    ("a" * 50, "a" * 50),
    ("a" * 60, "a" * 50 + "…"),
    ("a  b\n c", "a b c"),
    ("parola " * 10, "parola parola parola parola parola parola parola…"),
    ("Città è più già 😀 " * 5, "Città è più già 😀 Città è più già 😀 Città è più…"),
])
def test_titolo_da_domanda(testo, atteso):
    assert titolo_da_domanda(testo) == atteso
    assert len(titolo_da_domanda(testo)) <= 51


# --- operazioni ---

# Verifica la creazione con il titolo iniziale.
def test_crea_chat(fabbrica):
    with fabbrica() as s:
        chat = crea_chat(s)
    assert chat.id is not None and chat.titolo == TITOLO_INIZIALE


# Verifica l'ordine dell'elenco: data dell'ultimo messaggio (o di creazione), poi id.
def test_elenca_chat_ordine(fabbrica):
    with fabbrica() as s:
        a, b = crea_chat(s), crea_chat(s)
        assert [c.id for c in elenca_chat(s)] == [b.id, a.id]
    invia_messaggio(fabbrica, client_finto(AgenteFinto([risposta_ok("ok")])), a.id, "ciao")
    with fabbrica() as s:
        assert [c.id for c in elenca_chat(s)] == [a.id, b.id]


# Verifica le operazioni su una chat che non esiste.
def test_chat_non_trovata(fabbrica):
    with fabbrica() as s:
        with pytest.raises(ChatNonTrovata):
            leggi_chat(s, 999)
        with pytest.raises(ChatNonTrovata):
            elimina_chat(s, 999)
    with pytest.raises(ChatNonTrovata):
        invia_messaggio(fabbrica, client_finto(AgenteFinto()), 999, "ciao")


# Verifica l'eliminazione: numero di messaggi tolti, nessuna riga residua.
def test_elimina_chat(fabbrica):
    with fabbrica() as s:
        chat = crea_chat(s)
    invia_messaggio(fabbrica, client_finto(AgenteFinto([risposta_ok("ok")])), chat.id, "ciao")
    with fabbrica() as s:
        assert elimina_chat(s, chat.id) == 2
        assert s.get(Chat, chat.id) is None
    assert _messaggi_totali(fabbrica) == 0


# --- turno ---

# Verifica un turno riuscito: domanda e risposta salvate, strumenti, titolo, date.
def test_turno_riuscito(fabbrica):
    with fabbrica() as s:
        chat = crea_chat(s)
    agente = AgenteFinto([risposta_ok("A Tokyo sono le 20.", CRONOLOGIA_1, "", STRUMENTI)])
    domanda, risposta = invia_messaggio(fabbrica, client_finto(agente), chat.id,
                                        "  Ore a Tokyo?  ")
    assert (domanda.ruolo, domanda.testo, domanda.strumenti) == ("utente", "Ore a Tokyo?", None)
    assert (risposta.ruolo, risposta.testo) == ("assistente", "A Tokyo sono le 20.")
    assert risposta.strumenti == STRUMENTI
    with fabbrica() as s:
        letta = leggi_chat(s, chat.id)
        assert [m.id for m in letta.messaggi] == [domanda.id, risposta.id]
        assert letta.titolo == "Ore a Tokyo?"
        assert letta.ultimo_messaggio_il == risposta.creato_il
        assert letta.cronologia_agente == CRONOLOGIA_1


# Verifica che il secondo turno mandi all'agente cronologia e riassunto restituiti dal primo,
# identici (anche tool_calls e messaggi tool), e che il titolo non cambi.
def test_secondo_turno_ripassa_lo_stato(fabbrica):
    with fabbrica() as s:
        chat = crea_chat(s)
    agente = AgenteFinto([risposta_ok("A Tokyo sono le 20.", CRONOLOGIA_1, "Riassunto 1."),
                          risposta_ok("Prego")])
    client = client_finto(agente)
    invia_messaggio(fabbrica, client, chat.id, "Ore a Tokyo?")
    invia_messaggio(fabbrica, client, chat.id, "Grazie")
    assert agente.corpi[0] == {"messaggio": "Ore a Tokyo?", "cronologia": [], "riassunto": ""}
    assert agente.corpi[1] == {"messaggio": "Grazie", "cronologia": CRONOLOGIA_1,
                               "riassunto": "Riassunto 1."}
    with fabbrica() as s:
        assert leggi_chat(s, chat.id).titolo == "Ore a Tokyo?"


# Verifica il turno tutto o niente: agente spento -> errore, chat invariata.
def test_agente_in_errore(fabbrica):
    with fabbrica() as s:
        chat = crea_chat(s)
    with pytest.raises(ErroreAgente) as e:
        invia_messaggio(fabbrica, client_finto(AgenteFinto([httpx.ConnectError("no")])),
                        chat.id, "ciao")
    assert (e.value.status, e.value.errore) == (503, "agente_non_raggiungibile")
    with fabbrica() as s:
        letta = leggi_chat(s, chat.id)
        assert letta.messaggi == []
        assert (letta.titolo, letta.cronologia_agente, letta.ultimo_messaggio_il) == (
            TITOLO_INIZIALE, [], None)


# Verifica la chat eliminata mentre l'agente risponde: 404 e nessun messaggio orfano.
def test_chat_eliminata_durante_il_turno(fabbrica):
    with fabbrica() as s:
        chat = crea_chat(s)

    # l'agente "risponde" dopo che qualcuno ha eliminato la chat
    def elimina_poi_rispondi(_richiesta):
        with fabbrica() as altra:
            elimina_chat(altra, chat.id)
        return risposta_ok("tardi")
    with pytest.raises(ChatNonTrovata):
        invia_messaggio(fabbrica, client_finto(AgenteFinto([elimina_poi_rispondi])), chat.id, "x")
    assert _messaggi_totali(fabbrica) == 0


# Verifica che un testo lungo con accenti ed emoji resti intatto.
def test_testo_intatto(fabbrica):
    testo = ("Perché l'orologio di Zürich è già avanti? 😀🕒 " * 7).strip()
    assert len(testo) > 300
    with fabbrica() as s:
        chat = crea_chat(s)
    invia_messaggio(fabbrica, client_finto(AgenteFinto([risposta_ok("Così 😀")])), chat.id, testo)
    with fabbrica() as s:
        letta = leggi_chat(s, chat.id)
        assert [m.testo for m in letta.messaggi] == [testo, "Così 😀"]
        assert letta.titolo == titolo_da_domanda(testo)
