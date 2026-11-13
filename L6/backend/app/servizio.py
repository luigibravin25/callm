"""Operazioni sulle chat e turno con l'agente (tutto o niente).

Le funzioni ricevono una sessione SQLAlchemy e fanno loro il commit. invia_messaggio usa invece
la fabbrica: la domanda si salva e si fa commit PRIMA di chiamare l'agente, e durante la
chiamata (anche minuti con gemma) non resta aperta nessuna transazione; se l'agente fallisce la
domanda si cancella, cosi' la chat resta coerente e il riprovo non crea doppioni.
"""
# librerie standard: log, tipi
import logging
import threading
from collections.abc import Iterator

# SQLAlchemy: interrogazioni, funzioni SQL, caricamento dei messaggi, sessioni
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

# parti del back-end: modelli, client dell'agente
from app.client_agente import Annullato, ClientAgente, ErroreAgente
from app.db import TITOLO_INIZIALE, Chat, Messaggio, ora

# logger del back-end: nel terminale compare come [backend]
log = logging.getLogger("backend")

# messaggi degli eventi d'errore dello streaming (step 10)
MSG_CHAT_NON_TROVATA = "La chat non esiste più."
MSG_INTERNO_FLUSSO = "Errore interno del back-end: dettagli nel log."


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


# 1. domanda salvata e committata; si legge lo stato da ripassare all'agente
def _salva_domanda(fabbrica: sessionmaker, chat_id: int, testo: str):
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
    return domanda, cronologia, riassunto, primo_turno


# un turno: salva la domanda, chiama l'agente, salva la risposta e il nuovo stato dell'agente
def invia_messaggio(fabbrica: sessionmaker, client: ClientAgente, chat_id: int,
                    testo: str) -> tuple[Messaggio, Messaggio]:
    testo = testo.strip()
    domanda, cronologia, riassunto, primo_turno = _salva_domanda(fabbrica, chat_id, testo)

    # 2-3. chiamata all'agente e salvataggio della risposta: qualsiasi errore (agente, database,
    # imprevisto) cancella la domanda, cosi' la chat non resta con una domanda senza risposta
    try:
        return _completa_turno(fabbrica, client, domanda, cronologia, riassunto, primo_turno)
    except ErroreAgente as errore:
        log.warning("chat %d: agente in errore (%s, %d), cancello la domanda %d", chat_id,
                    errore.errore, errore.status, domanda.id)
        _cancella_domanda(fabbrica, domanda.id)
        raise
    except ChatNonTrovata:
        raise  # chat eliminata durante il turno: la domanda e' gia' sparita con la cascata
    except Exception:
        log.exception("chat %d: turno non completato, cancello la domanda %d", chat_id,
                      domanda.id)
        _cancella_domanda(fabbrica, domanda.id)
        raise


# cancella la domanda di un turno fallito; un errore qui non deve nascondere quello originale
def _cancella_domanda(fabbrica: sessionmaker, domanda_id: int) -> None:
    try:
        with fabbrica() as s:
            s.execute(delete(Messaggio).where(Messaggio.id == domanda_id))
            s.commit()
    except Exception:
        log.error("domanda %d non cancellata: resta senza risposta", domanda_id)


# chiamata all'agente (nessuna sessione aperta) e salvataggio della risposta
def _completa_turno(fabbrica: sessionmaker, client: ClientAgente, domanda: Messaggio,
                    cronologia: list, riassunto: str,
                    primo_turno: bool) -> tuple[Messaggio, Messaggio]:
    esito = client.turno(domanda.testo, cronologia, riassunto)
    return _salva_risposta(fabbrica, domanda, esito, primo_turno)


# risposta salvata con il nuovo stato dell'agente (cronologia, riassunto, titolo al primo turno)
def _salva_risposta(fabbrica: sessionmaker, domanda: Messaggio, esito,
                    primo_turno: bool) -> tuple[Messaggio, Messaggio]:
    chat_id, testo = domanda.chat_id, domanda.testo
    with fabbrica() as s:
        # riga della chat bloccata fino al commit: un DELETE in parallelo aspetta, e se la chat
        # e' gia' stata eliminata si ottiene None (404) invece di un errore di chiave esterna
        chat = s.get(Chat, chat_id, with_for_update=True)
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


# un turno in streaming (step 10): eventi (tipo, dati) per il front-end. Domanda salvata subito;
# gli eventi dell'agente passano cosi' come sono; a "fine" si salva la risposta (come
# invia_messaggio) e l'evento porta {"domanda", "risposta"}; con un errore, o se chi legge chiude
# il generatore (browser chiuso), la domanda si cancella: tutto o niente come senza streaming
def invia_in_flusso(fabbrica: sessionmaker, client: ClientAgente, chat_id: int, testo: str,
                    annullato: threading.Event | None = None) -> Iterator[tuple[str, object]]:
    testo = testo.strip()
    try:
        domanda, cronologia, riassunto, primo_turno = _salva_domanda(fabbrica, chat_id, testo)
    except ChatNonTrovata:
        # eliminata tra il controllo dell'API e l'inizio dello stream
        yield "errore", {"errore": "chat_non_trovata", "messaggio": MSG_CHAT_NON_TROVATA}
        return
    salvata = False
    try:
        for tipo, dati in client.turno_in_flusso(testo, cronologia, riassunto, annullato):
            if tipo == "fine":
                # browser gia' andato via: niente salvataggio (la domanda si cancella sotto)
                if annullato is not None and annullato.is_set():
                    return
                domanda, risposta = _salva_risposta(fabbrica, domanda, dati, primo_turno)
                salvata = True
                yield "fine", {"domanda": domanda, "risposta": risposta}
                return
            if tipo == "errore":
                log.warning("chat %d: agente in errore nel flusso (%s), cancello la domanda %d",
                            chat_id, dati.get("errore"), domanda.id)
            yield tipo, dati
            if tipo == "errore":
                return
    except Annullato:
        log.info("chat %d: browser chiuso durante il turno", chat_id)
    except ErroreAgente as errore:
        log.warning("chat %d: agente in errore (%s, %d), cancello la domanda %d", chat_id,
                    errore.errore, errore.status, domanda.id)
        yield "errore", {"errore": errore.errore, "messaggio": errore.messaggio}
    except ChatNonTrovata:
        # eliminata durante il turno: la domanda e' sparita con la cascata
        yield "errore", {"errore": "chat_non_trovata", "messaggio": MSG_CHAT_NON_TROVATA}
    except Exception:
        log.exception("chat %d: turno in streaming non completato, cancello la domanda %d",
                      chat_id, domanda.id)
        yield "errore", {"errore": "errore_interno", "messaggio": MSG_INTERNO_FLUSSO}
    finally:
        # errore, stream interrotto o generatore chiuso (browser andato via): niente domanda orfana
        if not salvata:
            log.info("chat %d: turno in streaming non completato, domanda %d cancellata",
                     chat_id, domanda.id)
            _cancella_domanda(fabbrica, domanda.id)
