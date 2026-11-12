"""Operazioni sulle chat e turno con l'agente (tutto o niente).

Le funzioni ricevono una sessione SQLAlchemy e fanno loro il commit. invia_messaggio usa invece
la fabbrica: la domanda si salva e si fa commit PRIMA di chiamare l'agente, e durante la
chiamata (anche minuti con gemma) non resta aperta nessuna transazione; se l'agente fallisce la
domanda si cancella, cosi' la chat resta coerente e il riprovo non crea doppioni.
"""
# librerie standard: log
import logging

# SQLAlchemy: interrogazioni, funzioni SQL, caricamento dei messaggi, sessioni
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

# parti del back-end: modelli, client dell'agente
from app.client_agente import ClientAgente, ErroreAgente
from app.db import TITOLO_INIZIALE, Chat, Messaggio, ora

# logger del back-end: nel terminale compare come [backend]
log = logging.getLogger("backend")


# chat richiesta che non esiste (o eliminata durante un turno)
class ChatNonTrovata(Exception):
    def __init__(self, chat_id: int):
        super().__init__(f"Chat {chat_id} non trovata.")
        self.chat_id = chat_id


# titolo dalla prima domanda: spazi compressi, al massimo `massimo` caratteri sul confine di parola
def titolo_da_domanda(testo: str, massimo: int = 50) -> str:
    pulito = " ".join(testo.split())
    if len(pulito) <= massimo:
        return pulito
    taglio = pulito[:massimo]
    # ultimo spazio entro il limite; senza spazi (una parola lunghissima) taglio secco
    spazio = taglio.rfind(" ")
    if spazio > 0:
        taglio = taglio[:spazio]
    return taglio.rstrip() + "…"


# crea una chat vuota con il titolo iniziale
def crea_chat(s: Session) -> Chat:
    chat = Chat(titolo=TITOLO_INIZIALE, creata_il=ora())
    s.add(chat)
    s.commit()
    log.info("chat %d creata", chat.id)
    return chat


# chat in ordine: prima quelle con l'attivita' piu' recente (ultimo messaggio o creazione)
def elenca_chat(s: Session) -> list[Chat]:
    recente = func.coalesce(Chat.ultimo_messaggio_il, Chat.creata_il)
    return list(s.scalars(select(Chat).order_by(recente.desc(), Chat.id.desc())))


# una chat con i messaggi in ordine cronologico
def leggi_chat(s: Session, chat_id: int) -> Chat:
    chat = s.scalar(select(Chat).where(Chat.id == chat_id)
                    .options(selectinload(Chat.messaggi)))
    if chat is None:
        raise ChatNonTrovata(chat_id)
    return chat


# elimina la chat (i messaggi li toglie la cascata del database); restituisce quanti erano
def elimina_chat(s: Session, chat_id: int) -> int:
    if s.get(Chat, chat_id) is None:
        raise ChatNonTrovata(chat_id)
    numero = s.scalar(select(func.count()).select_from(Messaggio)
                      .where(Messaggio.chat_id == chat_id))
    s.execute(delete(Chat).where(Chat.id == chat_id))
    s.commit()
    log.info("chat %d eliminata (%d messaggi)", chat_id, numero)
    return numero


# un turno: salva la domanda, chiama l'agente, salva la risposta e il nuovo stato dell'agente
def invia_messaggio(fabbrica: sessionmaker, client: ClientAgente, chat_id: int,
                    testo: str) -> tuple[Messaggio, Messaggio]:
    testo = testo.strip()
    # 1. domanda salvata e committata; si legge lo stato da ripassare all'agente
    with fabbrica() as s:
        chat = s.get(Chat, chat_id)
        if chat is None:
            raise ChatNonTrovata(chat_id)
        primo_turno = s.scalar(select(func.count()).select_from(Messaggio)
                               .where(Messaggio.chat_id == chat_id)) == 0
        cronologia, riassunto = list(chat.cronologia_agente), chat.riassunto
        domanda = Messaggio(chat_id=chat_id, ruolo="utente", testo=testo, creato_il=ora())
        s.add(domanda)
        s.commit()
    log.info("chat %d: domanda %d salvata, chiamo l'agente (cronologia %d messaggi, "
             "riassunto %s)", chat_id, domanda.id, len(cronologia), "sì" if riassunto else "no")

    # 2. chiamata all'agente senza sessioni aperte
    try:
        esito = client.turno(testo, cronologia, riassunto)
    except ErroreAgente as errore:
        # 3a. tutto o niente: la domanda si cancella (se la chat c'e' ancora)
        with fabbrica() as s:
            s.execute(delete(Messaggio).where(Messaggio.id == domanda.id))
            s.commit()
        log.warning("chat %d: agente in errore (%s, %d), domanda %d cancellata", chat_id,
                    errore.errore, errore.status, domanda.id)
        raise

    # 3b. risposta salvata con il nuovo stato dell'agente
    with fabbrica() as s:
        chat = s.get(Chat, chat_id)
        if chat is None:
            # eliminata durante la chiamata: la domanda e' sparita con la cascata
            log.warning("chat %d: eliminata durante il turno, risposta scartata", chat_id)
            raise ChatNonTrovata(chat_id)
        risposta = Messaggio(chat_id=chat_id, ruolo="assistente", testo=esito.risposta,
                             strumenti=esito.strumenti_usati, creato_il=ora())
        s.add(risposta)
        chat.cronologia_agente = esito.cronologia
        chat.riassunto = esito.riassunto
        chat.ultimo_messaggio_il = risposta.creato_il
        if primo_turno:
            chat.titolo = titolo_da_domanda(testo)
        s.commit()
        titolo = chat.titolo
    nomi = ", ".join(st.get("nome", "?") for st in esito.strumenti_usati) or "nessuno"
    log.info("chat %d: risposta %d salvata (strumenti: %s)%s", chat_id, risposta.id, nomi,
             f", titolo «{titolo}»" if primo_turno else "")
    return domanda, risposta
