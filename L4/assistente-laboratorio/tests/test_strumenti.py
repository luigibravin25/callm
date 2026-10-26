from datetime import datetime, timezone

from app import tools


def _fissa(monkeypatch):
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


def test_orologio_istante_controllato(monkeypatch):
    _fissa(monkeypatch)
    assert tools.ora_corrente.invoke({"fuso": "Europe/Rome"}) == \
        "2026-03-01 12:00:00 CET (Europe/Rome)"
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo"}) == \
        "2026-03-01 20:00:00 JST (Asia/Tokyo)"


def test_fuso_non_valido(monkeypatch):
    _fissa(monkeypatch)
    for fuso in ("Marte/Olimpo", "", "   ", "../etc"):
        risultato = tools.ora_corrente.invoke({"fuso": fuso})
        assert isinstance(risultato, str)
        assert "fuso orario non valido" in risultato.lower()
