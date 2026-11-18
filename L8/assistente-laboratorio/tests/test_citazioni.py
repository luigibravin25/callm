# test delle funzioni pure del controllo delle citazioni: id citati nella risposta, id ricevuti
# dai risultati di search_documents, esito del turno e riga di log
import json

from langchain_core.messages import AIMessage, ToolMessage

from app.citazioni import EsitoCitazioni, controlla, id_citati, id_ricevuti, riga_log


# risultato di search_documents come lo restituisce il server dell'esercizio 1 (campi essenziali)
def risultato(*ids: str) -> str:
    return json.dumps({"modalita": "base", "query": "q", "top_k": 5, "capitolo": "", "nota": None,
                       "passaggi": [{"id": i} for i in ids]})


# messaggio dello strumento di ricerca con il contenuto dato
def ricerca(contenuto: str, status: str = "success") -> ToolMessage:
    return ToolMessage(contenuto, tool_call_id="c1", name="search_documents", status=status)


def test_id_citati_uno():
    assert id_citati("Vino bianco [R208-1].") == ["R208-1"]


def test_id_citati_gruppo_e_doppi():
    assert id_citati("a [R89-1, R89-2] b [R89-1][R90-1]") == ["R89-1", "R89-2", "R90-1"]


def test_id_citati_ignora_fuori_parentesi_e_note():
    assert id_citati("R89-1 senza parentesi [nota] [R-1]") == []


def test_id_ricevuti():
    assert id_ricevuti(risultato("R89-1", "R89-2")) == ["R89-1", "R89-2"]
    # errore del tool (testo, non JSON) e JSON senza passaggi: nessun id
    assert id_ricevuti("capitolo 'DOLCI' sconosciuto") == []
    assert id_ricevuti(json.dumps({"altro": 1})) == []


def test_controlla_verificate_e_sconosciute():
    turno = [AIMessage("", tool_calls=[{"name": "search_documents", "args": {"query": "q"}, "id": "c1"}]),
             ricerca(risultato("R89-1", "R89-2"))]
    esito = controlla(turno, "Patate [R89-1] e farina [R999-1].")
    assert esito == EsitoCitazioni(("R89-1",), ("R999-1",), 1, 2)


def test_controlla_errore_del_tool():
    esito = controlla([ricerca("capitolo 'DOLCI' sconosciuto", status="error")], "Non trovo nulla.")
    assert (esito.ricerche, esito.passaggi) == (1, 0)


def test_controlla_ignora_altri_tool():
    esito = controlla([ToolMessage("ore 10", tool_call_id="c1", name="tooltime")], "Sono le 10.")
    assert esito == EsitoCitazioni((), (), 0, 0)


def test_riga_log():
    assert riga_log(EsitoCitazioni(("R208-1",), (), 1, 5)) == \
        "verificate=R208-1 sconosciute=- ricerche=1 passaggi=5"
    assert riga_log(EsitoCitazioni(("R89-1", "R89-2"), ("R999-1",), 2, 7)) == \
        "verificate=R89-1,R89-2 sconosciute=R999-1 ricerche=2 passaggi=7"
