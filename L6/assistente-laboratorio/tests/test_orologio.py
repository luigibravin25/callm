# Test dello strumento orologio `tooltime` (orologio.ora_corrente) con un istante controllato.
# datetime e timezone servono a costruire istanti fissi in UTC
from datetime import datetime, timezone

# logica dell'orologio del server MCP (la usa tooltime)
from mcp_assistente import orologio


# Supporto: sostituisce l'orologio vero (_adesso) con un istante fisso, 1 marzo 2026 11:00 UTC,
# cosi' i risultati non dipendono dal momento in cui gira il test.
def _fissa(monkeypatch):
    monkeypatch.setattr(
        orologio, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


# Verifica ora e data a parole in due fusi: 11 UTC e' mezzogiorno a Roma, le 20 a Tokyo.
def test_orologio_istante_controllato(monkeypatch):
    _fissa(monkeypatch)
    assert orologio.ora_corrente(**{"fuso": "Europe/Rome"}) == \
        "Rome: 1 marzo del 2026, è mezzogiorno"
    assert orologio.ora_corrente(**{"fuso": "Asia/Tokyo"}) == \
        "Tokyo: 1 marzo del 2026, sono le ore 20 in punto"


# Verifica l'argomento "parte": solo l'ora, solo la data, oppure entrambe.
def test_parte_ora_e_data(monkeypatch):
    _fissa(monkeypatch)
    assert orologio.ora_corrente(**{"fuso": "Asia/Tokyo", "parte": "ora"}) == \
        "Tokyo: sono le ore 20 in punto"
    assert orologio.ora_corrente(**{"fuso": "Asia/Tokyo", "parte": "data"}) == \
        "Tokyo: 1 marzo del 2026"
    assert orologio.ora_corrente(**{"fuso": "Asia/Tokyo", "parte": "entrambe"}) == \
        "Tokyo: 1 marzo del 2026, sono le ore 20 in punto"


# Verifica che senza "parte" lo strumento dia data e ora insieme (valore predefinito).
def test_parte_predefinita_entrambe(monkeypatch):
    _fissa(monkeypatch)
    # controllo: la risposta senza "parte" e' uguale a quella con parte="entrambe"
    assert orologio.ora_corrente(**{"fuso": "Europe/Rome"}) == \
        orologio.ora_corrente(**{"fuso": "Europe/Rome", "parte": "entrambe"})


# Verifica che la data dipenda dal fuso: vicino a mezzanotte due luoghi hanno giorni diversi.
def test_la_data_cambia_col_fuso(monkeypatch):
    # 23:30 UTC del 1 marzo: a Tokyo e' gia' il 2 marzo
    monkeypatch.setattr(
        orologio, "_adesso",
        lambda: datetime(2026, 3, 1, 23, 30, 0, tzinfo=timezone.utc))
    assert orologio.ora_corrente(**{"fuso": "Asia/Tokyo", "parte": "data"}) == \
        "Tokyo: 2 marzo del 2026"
    assert orologio.ora_corrente(**{"fuso": "Europe/London", "parte": "data"}) == \
        "London: 1 marzo del 2026"


# Verifica la riserva: senza fuso (o con soli spazi) e senza FUSO_PREDEFINITO si usa Roma.
def test_fuso_omesso_usa_roma(monkeypatch):
    _fissa(monkeypatch)
    # preparazione: toglie la variabile d'ambiente, se c'e'
    monkeypatch.delenv("FUSO_PREDEFINITO", raising=False)
    assert orologio.ora_corrente(**{}) == "Rome: 1 marzo del 2026, è mezzogiorno"
    assert orologio.ora_corrente(**{"fuso": "  "}) == "Rome: 1 marzo del 2026, è mezzogiorno"


# Verifica che senza fuso si usi la variabile FUSO_PREDEFINITO (requisito della configurazione).
def test_fuso_omesso_usa_la_variabile(monkeypatch):
    _fissa(monkeypatch)
    # preparazione: il fuso predefinito diventa Tokyo solo per questo test
    monkeypatch.setenv("FUSO_PREDEFINITO", "Asia/Tokyo")
    assert orologio.ora_corrente(**{"parte": "ora"}) == "Tokyo: sono le ore 20 in punto"
    # un fuso esplicito ha la precedenza sul predefinito
    assert orologio.ora_corrente(**{"fuso": "Europe/Rome", "parte": "ora"}) == "Rome: è mezzogiorno"


# Verifica i nomi dei 12 mesi in italiano: per ogni mese fissa il 27 e controlla la data.
def test_mese_in_italiano(monkeypatch):
    # "mese=mese" nella lambda blocca il valore del giro corrente del ciclo
    for mese, nome in enumerate(orologio.MESI, start=1):
        monkeypatch.setattr(
            orologio, "_adesso",
            lambda mese=mese: datetime(2026, mese, 27, 12, 0, 0, tzinfo=timezone.utc))
        assert orologio.ora_corrente(**{"fuso": "UTC", "parte": "data"}) == \
            f"UTC: 27 {nome} del 2026"
    assert orologio.MESI[9] == "ottobre"


# Verifica l'ora a parole senza secondi: "minuto" al singolare e "in punto" a zero minuti.
def test_ora_senza_secondi(monkeypatch):
    # supporto: fissa l'istante alle h:m:sec UTC e chiede solo l'ora
    def a(h, m, sec):
        monkeypatch.setattr(
            orologio, "_adesso",
            lambda: datetime(2026, 10, 27, h, m, sec, tzinfo=timezone.utc))
        return orologio.ora_corrente(**{"fuso": "UTC", "parte": "ora"})

    assert a(17, 12, 50) == "UTC: sono le ore 17 e 12 minuti"
    assert a(17, 1, 30) == "UTC: sono le ore 17 e 1 minuto"
    assert a(17, 0, 59) == "UTC: sono le ore 17 in punto"
    assert "17:12" not in a(17, 12, 50)  # niente secondi, niente formato 17:12:50


# Verifica i casi speciali dell'italiano: "l'una", "mezzanotte", "mezzogiorno" (solo alle 12:00).
def test_ore_particolari(monkeypatch):
    # supporto: fissa l'istante alle h:m (secondi 40, da ignorare) e chiede solo l'ora
    def a(h, m):
        monkeypatch.setattr(
            orologio, "_adesso",
            lambda: datetime(2026, 10, 27, h, m, 40, tzinfo=timezone.utc))
        return orologio.ora_corrente(**{"fuso": "UTC", "parte": "ora"})

    assert a(1, 14) == "UTC: è l'una e 14 minuti"
    assert a(1, 1) == "UTC: è l'una e 1 minuto"
    assert a(1, 0) == "UTC: è l'una in punto"
    assert a(0, 14) == "UTC: è mezzanotte e 14 minuti"
    assert a(0, 0) == "UTC: è mezzanotte"
    assert a(12, 0) == "UTC: è mezzogiorno"
    assert a(12, 5) == "UTC: sono le ore 12 e 5 minuti"  # mezzogiorno solo alle 12:00
    assert a(13, 0) == "UTC: sono le ore 13 in punto"
    assert a(2, 30) == "UTC: sono le ore 2 e 30 minuti"


# Verifica che la risposta mostri un nome di luogo leggibile, non l'identificativo IANA.
def test_nome_del_luogo_senza_nome_iana(monkeypatch):
    _fissa(monkeypatch)
    ny = orologio.ora_corrente(**{"fuso": "America/New_York"})
    # controllo: "New York" senza "America/", barre o trattini bassi
    assert ny.startswith("New York: ")
    assert "/" not in ny and "_" not in ny and "America" not in ny
    assert orologio.ora_corrente(**{"fuso": "America/Argentina/Buenos_Aires", "parte": "ora"}) \
        .startswith("Buenos Aires: ")
    assert orologio.ora_corrente(**{"fuso": "UTC", "parte": "ora"}).startswith("UTC: ")


# Verifica che un fuso inesistente (o un percorso di file) dia un messaggio, non un'eccezione:
# il modello riceve un testo da riferire all'utente.
def test_fuso_non_valido(monkeypatch):
    _fissa(monkeypatch)
    for fuso in ("Marte/Olimpo", "../etc"):  # vuoto = fuso predefinito
        risultato = orologio.ora_corrente(**{"fuso": fuso})
        # controllo: risultato testuale con la spiegazione dell'errore
        assert isinstance(risultato, str)
        assert "fuso orario non valido" in risultato.lower()
