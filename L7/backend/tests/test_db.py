# test dei modelli SQLAlchemy su PostgreSQL vero: predefiniti, JSONB, cascata, vincoli, ordine
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db import TITOLO_INIZIALE, Chat, Messaggio, ora

CRONOLOGIA = [{"role": "user", "content": "Ore a Tokyo?"},
              {"role": "assistant", "content": "", "tool_calls": [
                  {"id": "c1", "type": "function",
                   "function": {"name": "tooltime", "arguments": "{\"fuso\": \"Asia/Tokyo\"}"}}]},
              {"role": "tool", "content": "01:12", "tool_call_id": "c1", "name": "tooltime"}]


# nuova chat salvata con i soli campi obbligatori
def _chat(s):
    chat = Chat(titolo=TITOLO_INIZIALE, creata_il=ora())
    s.add(chat)
    s.commit()
    return chat


# Verifica i predefiniti di una chat nuova.
def test_chat_con_predefiniti(fabbrica):
    with fabbrica() as s:
        chat = _chat(s)
        s.refresh(chat)
        assert TITOLO_INIZIALE == "Nuova chat"
        assert (chat.riassunto, chat.cronologia_agente, chat.ultimo_messaggio_il) == ("", [], None)
        assert chat.creata_il.tzinfo is not None


# Verifica che il JSONB conservi la cronologia con tool_calls annidati.
def test_jsonb_conserva_la_cronologia(fabbrica):
    with fabbrica() as s:
        chat = _chat(s)
        chat.cronologia_agente = CRONOLOGIA
        s.commit()
        chat_id = chat.id
    with fabbrica() as s:
        assert s.get(Chat, chat_id).cronologia_agente == CRONOLOGIA


# Verifica che eliminare una chat elimini i suoi messaggi (cascata nel database).
def test_cascata(fabbrica):
    with fabbrica() as s:
        chat = _chat(s)
        for ruolo in ("utente", "assistente"):
            s.add(Messaggio(chat_id=chat.id, ruolo=ruolo, testo="x", creato_il=ora()))
        s.commit()
        s.execute(delete(Chat).where(Chat.id == chat.id))
        s.commit()
        assert s.scalars(select(Messaggio)).all() == []


# Verifica il vincolo sul ruolo.
def test_ruolo_non_ammesso(fabbrica):
    with fabbrica() as s:
        chat = _chat(s)
        s.add(Messaggio(chat_id=chat.id, ruolo="system", testo="x", creato_il=ora()))
        with pytest.raises(IntegrityError):
            s.commit()


# Verifica l'ordine dei messaggi: a parita' di istante decide l'id.
def test_ordine_dei_messaggi(fabbrica):
    istante = ora()
    with fabbrica() as s:
        chat = _chat(s)
        for testo in ("primo", "secondo", "terzo"):
            s.add(Messaggio(chat_id=chat.id, ruolo="utente", testo=testo, creato_il=istante))
            s.flush()
        s.commit()
        chat_id = chat.id
    with fabbrica() as s:
        assert [m.testo for m in s.get(Chat, chat_id).messaggi] == ["primo", "secondo", "terzo"]
        assert s.get(Chat, chat_id).messaggi[0].strumenti is None


# Verifica che un database spento dia errore in pochi secondi (su Windows una porta chiusa,
# senza timeout di connessione, blocca per oltre due minuti).
def test_timeout_di_connessione():
    import time

    from sqlalchemy.exc import OperationalError

    from app.db import TIMEOUT_CONNESSIONE, crea_motore
    assert TIMEOUT_CONNESSIONE == 5
    motore = crea_motore("postgresql+psycopg://x:y@127.0.0.1:1/nessuno_test")
    inizio = time.perf_counter()
    with pytest.raises(OperationalError):
        motore.connect()
    assert time.perf_counter() - inizio < TIMEOUT_CONNESSIONE * 3
    motore.dispose()
