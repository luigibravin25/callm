from datetime import datetime, timezone

from app import tools


def _fissa(monkeypatch):
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


def test_orologio_istante_controllato(monkeypatch):
    _fissa(monkeypatch)
    assert tools.ora_corrente.invoke({"fuso": "Europe/Rome"}) == \
        "Rome: 1 marzo del 2026, è mezzogiorno"
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo"}) == \
        "Tokyo: 1 marzo del 2026, sono le ore 20 in punto"


def test_parte_ora_e_data(monkeypatch):
    _fissa(monkeypatch)
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "ora"}) == \
        "Tokyo: sono le ore 20 in punto"
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "data"}) == \
        "Tokyo: 1 marzo del 2026"
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "entrambe"}) == \
        "Tokyo: 1 marzo del 2026, sono le ore 20 in punto"


def test_parte_predefinita_entrambe(monkeypatch):
    _fissa(monkeypatch)
    assert tools.ora_corrente.invoke({"fuso": "Europe/Rome"}) ==         tools.ora_corrente.invoke({"fuso": "Europe/Rome", "parte": "entrambe"})


def test_la_data_cambia_col_fuso(monkeypatch):
    # 23:30 UTC del 1 marzo: a Tokyo e' gia' il 2 marzo
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 23, 30, 0, tzinfo=timezone.utc))
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "data"}) == \
        "Tokyo: 2 marzo del 2026"
    assert tools.ora_corrente.invoke({"fuso": "Europe/London", "parte": "data"}) == \
        "London: 1 marzo del 2026"


def test_schema_dello_strumento_espone_parte():
    schema = tools.ora_corrente.args
    assert schema["parte"]["enum"] == ["ora", "data", "entrambe"]
    assert schema["parte"]["default"] == "entrambe"
    assert "fuso" not in tools.ora_corrente.get_input_schema().model_json_schema().get("required", [])
    assert "parte" not in tools.ora_corrente.get_input_schema().model_json_schema().get("required", [])


def test_fuso_omesso_usa_roma(monkeypatch):
    _fissa(monkeypatch)
    monkeypatch.delenv("FUSO_PREDEFINITO", raising=False)
    assert tools.ora_corrente.invoke({}) == "Rome: 1 marzo del 2026, è mezzogiorno"
    assert tools.ora_corrente.invoke({"fuso": "  "}) == "Rome: 1 marzo del 2026, è mezzogiorno"


def test_fuso_omesso_usa_la_variabile(monkeypatch):
    _fissa(monkeypatch)
    monkeypatch.setenv("FUSO_PREDEFINITO", "Asia/Tokyo")
    assert tools.ora_corrente.invoke({"parte": "ora"}) == "Tokyo: sono le ore 20 in punto"
    # un fuso esplicito ha la precedenza sul predefinito
    assert tools.ora_corrente.invoke({"fuso": "Europe/Rome", "parte": "ora"}) == "Rome: è mezzogiorno"


def test_mese_in_italiano(monkeypatch):
    for mese, nome in enumerate(tools.MESI, start=1):
        monkeypatch.setattr(
            tools, "_adesso",
            lambda mese=mese: datetime(2026, mese, 27, 12, 0, 0, tzinfo=timezone.utc))
        assert tools.ora_corrente.invoke({"fuso": "UTC", "parte": "data"}) ==             f"UTC: 27 {nome} del 2026"
    assert tools.MESI[9] == "ottobre"


def test_ora_senza_secondi(monkeypatch):
    def a(h, m, sec):
        monkeypatch.setattr(
            tools, "_adesso",
            lambda: datetime(2026, 10, 27, h, m, sec, tzinfo=timezone.utc))
        return tools.ora_corrente.invoke({"fuso": "UTC", "parte": "ora"})

    assert a(17, 12, 50) == "UTC: sono le ore 17 e 12 minuti"
    assert a(17, 1, 30) == "UTC: sono le ore 17 e 1 minuto"
    assert a(17, 0, 59) == "UTC: sono le ore 17 in punto"
    assert "17:12" not in a(17, 12, 50)  # niente secondi, niente formato 17:12:50


def test_ore_particolari(monkeypatch):
    def a(h, m):
        monkeypatch.setattr(
            tools, "_adesso",
            lambda: datetime(2026, 10, 27, h, m, 40, tzinfo=timezone.utc))
        return tools.ora_corrente.invoke({"fuso": "UTC", "parte": "ora"})

    assert a(1, 14) == "UTC: è l'una e 14 minuti"
    assert a(1, 1) == "UTC: è l'una e 1 minuto"
    assert a(1, 0) == "UTC: è l'una in punto"
    assert a(0, 14) == "UTC: è mezzanotte e 14 minuti"
    assert a(0, 0) == "UTC: è mezzanotte"
    assert a(12, 0) == "UTC: è mezzogiorno"
    assert a(12, 5) == "UTC: sono le ore 12 e 5 minuti"  # mezzogiorno solo alle 12:00
    assert a(13, 0) == "UTC: sono le ore 13 in punto"
    assert a(2, 30) == "UTC: sono le ore 2 e 30 minuti"


def test_nome_del_luogo_senza_nome_iana(monkeypatch):
    _fissa(monkeypatch)
    ny = tools.ora_corrente.invoke({"fuso": "America/New_York"})
    assert ny.startswith("New York: ")
    assert "/" not in ny and "_" not in ny and "America" not in ny
    assert tools.ora_corrente.invoke({"fuso": "America/Argentina/Buenos_Aires", "parte": "ora"})         .startswith("Buenos Aires: ")
    assert tools.ora_corrente.invoke({"fuso": "UTC", "parte": "ora"}).startswith("UTC: ")


def test_nome_dello_strumento():
    assert tools.ora_corrente.name == "tooltime"
    assert [t.name for t in tools.STRUMENTI] == ["tooltime"]


def test_fuso_non_valido(monkeypatch):
    _fissa(monkeypatch)
    for fuso in ("Marte/Olimpo", "../etc"):  # vuoto = fuso predefinito
        risultato = tools.ora_corrente.invoke({"fuso": fuso})
        assert isinstance(risultato, str)
        assert "fuso orario non valido" in risultato.lower()


def test_descrizione_chiede_ora_a_parole():
    descrizione = tools.ora_corrente.description
    assert "sono le ore 10 e 32 minuti" in descrizione
    assert "due punti" in descrizione
