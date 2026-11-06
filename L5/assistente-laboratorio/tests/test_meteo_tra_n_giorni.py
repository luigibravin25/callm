"""Grafo: "tra/fra N giorni" nella domanda dell'utente arriva a get_weather in date.

Il modello piccolo a volte chiama get_weather con days=N invece di date="tra N giorni"
(days=N vuol dire "oggi compreso", l'utente intende "gli N giorni da domani"): il grafo
corregge la chiamata prima di eseguirla. Modello finto e strumento finto: nessuna rete.
"""
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from app.graph import build_graph


class ModelloCopione:
    """Modello finto: restituisce i messaggi del copione uno dopo l'altro."""

    def __init__(self, messaggi):
        self.messaggi = list(messaggi)

    def invoke(self, _messaggi):
        return self.messaggi.pop(0)


def _esegui(domanda: str, argomenti: dict, cronologia=None):
    """Una domanda con una chiamata get_weather del modello; restituisce gli argomenti ricevuti
    dallo strumento."""
    ricevuti = []

    def get_weather(city: str = "", days: int = 0, date: str = "") -> str:
        """finto"""
        # registra gli argomenti che arrivano davvero allo strumento (dopo il grafo)
        ricevuti.append({"city": city, "days": days, "date": date})
        return "meteo finto"

    copione = [AIMessage("", tool_calls=[{"name": "get_weather", "args": argomenti,
                                          "id": "c1"}]),
               AIMessage("ecco il meteo")]
    grafo = build_graph(ModelloCopione(copione),
                        strumenti=[StructuredTool.from_function(get_weather)])
    messaggi = (cronologia or []) + [HumanMessage(domanda)]
    grafo.invoke({"messages": messaggi, "steps": 0})
    return ricevuti[0]


def test_days_corretto_in_date():
    """"tra 3 giorni" con days=3: allo strumento arriva date="tra 3 giorni"."""
    ricevuti = _esegui("che meteo farà a Milano tra 3 giorni?", {"city": "Milano", "days": 3})
    assert ricevuti["date"] == "tra 3 giorni" and ricevuti["city"] == "Milano"


def test_fra_due_giorni_maiuscole():
    """"Fra due giorni" (in lettere, con la maiuscola) senza argomenti di data."""
    ricevuti = _esegui("Fra due giorni che tempo fa a Torino?", {"city": "Torino", "days": 2})
    assert ricevuti["date"] == "fra due giorni"


def test_tra_un_giorno():
    """"tra un giorno": anche il singolare."""
    ricevuti = _esegui("che tempo farà tra un giorno a Roma?", {"city": "Roma", "days": 2})
    assert ricevuti["date"] == "tra un giorno"


def test_date_del_modello_non_cambia():
    """Se il modello ha gia' passato date, la sua scelta resta."""
    ricevuti = _esegui("che tempo fa fra due giorni a Torino?",
                       {"city": "Torino", "date": "fra due giorni"})
    assert ricevuti["date"] == "fra due giorni"
    ricevuti = _esegui("tra 3 giorni, anzi domani: che tempo fa?", {"date": "domani"})
    assert ricevuti["date"] == "domani"


def test_senza_tra_n_giorni_nessuna_correzione():
    """"i prossimi 3 giorni" non e' "tra N giorni": days resta e date resta vuota."""
    ricevuti = _esegui("che tempo fa a Milano nei prossimi 3 giorni?",
                       {"city": "Milano", "days": 4})
    assert ricevuti["days"] == 4 and ricevuti["date"] == ""


def test_solo_l_ultima_domanda():
    """"tra 3 giorni" in una domanda precedente non conta per quella in corso."""
    ricevuti = _esegui("e oggi?", {"city": "Milano", "days": 1},
                       cronologia=[HumanMessage("che tempo fa a Milano tra 3 giorni?"),
                                   AIMessage("risposta di prima")])
    assert ricevuti["date"] == ""


def test_correzione_nel_log(caplog):
    """La correzione si vede nel log del grafo."""
    with caplog.at_level(logging.INFO, logger="app.graph"):
        _esegui("che meteo farà a Milano tra 3 giorni?", {"city": "Milano", "days": 3})
    assert ("get_weather: date='tra 3 giorni' presa dalla domanda (il modello aveva usato "
            "days=3)") in caplog.text
