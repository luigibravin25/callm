"""Modelli SQLAlchemy delle chat e accesso a PostgreSQL.

Tabella `chat`: titolo, date e lo stato da ripassare all'agente (riassunto e cronologia nel
formato OpenAI, l'ultima restituita). Tabella `messaggi`: la storia visibile completa (domande e
risposte), che non si accorcia quando l'agente riassume. Le tabelle si creano all'avvio con
create_all (niente migrazioni: se lo schema cambia si ricrea il database).
"""
# librerie standard: date con fuso
from datetime import datetime, timezone

# SQLAlchemy: colonne, vincoli, motore, sessioni, modelli dichiarativi; JSONB di PostgreSQL
from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
                        create_engine, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column, relationship,
                            sessionmaker)

TITOLO_INIZIALE = "Nuova chat"


# ora attuale in UTC, con il fuso (le colonne sono timestamptz)
def ora() -> datetime:
    return datetime.now(timezone.utc)


# base dei modelli: Base.metadata conosce le due tabelle
class Base(DeclarativeBase):
    pass


# una chat: titolo, date e stato dell'agente (mai esposto al front-end)
class Chat(Base):
    __tablename__ = "chat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    titolo: Mapped[str] = mapped_column(Text, nullable=False, default=TITOLO_INIZIALE)
    creata_il: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # null finche' non c'e' un turno riuscito
    ultimo_messaggio_il: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ultimo riassunto e ultima cronologia (formato OpenAI) restituiti dall'agente
    riassunto: Mapped[str] = mapped_column(Text, nullable=False, default="",
                                           server_default=text("''"))
    cronologia_agente: Mapped[list] = mapped_column(JSONB, nullable=False, default=list,
                                                    server_default=text("'[]'::jsonb"))
    # messaggi visibili in ordine cronologico (a parita' di istante decide l'id);
    # passive_deletes: la cancellazione a cascata la fa il database
    messaggi: Mapped[list["Messaggio"]] = relationship(
        back_populates="chat", order_by="(Messaggio.creato_il, Messaggio.id)",
        passive_deletes=True)


# un messaggio visibile: domanda dell'utente o risposta dell'assistente
class Messaggio(Base):
    __tablename__ = "messaggi"
    __table_args__ = (CheckConstraint("ruolo IN ('utente', 'assistente')",
                                      name="messaggi_ruolo_ammesso"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chat.id", ondelete="CASCADE"),
                                         nullable=False, index=True)
    ruolo: Mapped[str] = mapped_column(String(20), nullable=False)
    testo: Mapped[str] = mapped_column(Text, nullable=False)
    # solo per l'assistente: strumenti usati nel turno ([{nome, argomenti}], anche vuota)
    strumenti: Mapped[list | None] = mapped_column(JSONB)
    creato_il: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    chat: Mapped[Chat] = relationship(back_populates="messaggi")


# motore verso PostgreSQL; pool_pre_ping ritrova il database dopo un suo riavvio
def crea_motore(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


# crea le tabelle mancanti (quelle esistenti non si toccano)
def crea_tabelle(motore: Engine) -> None:
    Base.metadata.create_all(motore)


# fabbrica di sessioni; expire_on_commit=False: gli oggetti restano leggibili dopo il commit
def fabbrica_sessioni(motore: Engine) -> sessionmaker[Session]:
    return sessionmaker(motore, expire_on_commit=False)
