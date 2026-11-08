# Test dello strumento orologio `tooltime` (tools.ora_corrente) con un istante controllato.
# datetime e timezone servono a costruire istanti fissi in UTC
from datetime import datetime, timezone

# il modulo degli strumenti dell'app
from app import tools


# Supporto: sostituisce l'orologio vero (_adesso) con un istante fisso, 1 marzo 2026 11:00 UTC,
# cosi' i risultati non dipendono dal momento in cui gira il test.
def _fissa(monkeypatch):
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


# Verifica ora e data a parole in due fusi: 11 UTC e' mezzogiorno a Roma, le 20 a Tokyo.
def test_orologio_istante_controllato(monkeypatch):
    _fissa(monkeypatch)
    assert tools.ora_corrente.invoke({"fuso": "Europe/Rome"}) == \
        "Rome: 1 marzo del 2026, è mezzogiorno"
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo"}) == \
        "Tokyo: 1 marzo del 2026, sono le ore 20 in punto"


# Verifica l'argomento "parte": solo l'ora, solo la data, oppure entrambe.
def test_parte_ora_e_data(monkeypatch):
    _fissa(monkeypatch)
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "ora"}) == \
        "Tokyo: sono le ore 20 in punto"
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "data"}) == \
        "Tokyo: 1 marzo del 2026"
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "entrambe"}) == \
        "Tokyo: 1 marzo del 2026, sono le ore 20 in punto"


# Verifica che senza "parte" lo strumento dia data e ora insieme (valore predefinito).
def test_parte_predefinita_entrambe(monkeypatch):
    _fissa(monkeypatch)
    # controllo: la risposta senza "parte" e' uguale a quella con parte="entrambe"
    assert tools.ora_corrente.invoke({"fuso": "Europe/Rome"}) ==         tools.ora_corrente.invoke({"fuso": "Europe/Rome", "parte": "entrambe"})


# Verifica che la data dipenda dal fuso: vicino a mezzanotte due luoghi hanno giorni diversi.
def test_la_data_cambia_col_fuso(monkeypatch):
    # 23:30 UTC del 1 marzo: a Tokyo e' gia' il 2 marzo
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 23, 30, 0, tzinfo=timezone.utc))
    assert tools.ora_corrente.invoke({"fuso": "Asia/Tokyo", "parte": "data"}) == \
        "Tokyo: 2 marzo del 2026"
    assert tools.ora_corrente.invoke({"fuso": "Europe/London", "parte": "data"}) == \
        "London: 1 marzo del 2026"


# Verifica lo schema mandato al modello: "parte" ha 3 valori ammessi e un predefinito,
# e nessun argomento e' obbligatorio (fuso e parte si possono omettere).
def test_schema_dello_strumento_espone_parte():
    schema = tools.ora_corrente.args
    assert schema["parte"]["enum"] == ["ora", "data", "entrambe"]
    assert schema["parte"]["default"] == "entrambe"
    # controllo: "fuso" e "parte" non compaiono tra gli argomenti richiesti
    assert "fuso" not in tools.ora_corrente.get_input_schema().model_json_schema().get("required", [])
    assert "parte" not in tools.ora_corrente.get_input_schema().model_json_schema().get("required", [])


# Verifica la riserva: senza fuso (o con soli spazi) e senza FUSO_PREDEFINITO si usa Roma.
def test_fuso_omesso_usa_roma(monkeypatch):
    _fissa(monkeypatch)
    # preparazione: toglie la variabile d'ambiente, se c'e'
    monkeypatch.delenv("FUSO_PREDEFINITO", raising=False)
    assert tools.ora_corrente.invoke({}) == "Rome: 1 marzo del 2026, è mezzogiorno"
    assert tools.ora_corrente.invoke({"fuso": "  "}) == "Rome: 1 marzo del 2026, è mezzogiorno"


# Verifica che senza fuso si usi la variabile FUSO_PREDEFINITO (requisito della configurazione).
def test_fuso_omesso_usa_la_variabile(monkeypatch):
    _fissa(monkeypatch)
    # preparazione: il fuso predefinito diventa Tokyo solo per questo test
    monkeypatch.setenv("FUSO_PREDEFINITO", "Asia/Tokyo")
    assert tools.ora_corrente.invoke({"parte": "ora"}) == "Tokyo: sono le ore 20 in punto"
    # un fuso esplicito ha la precedenza sul predefinito
    assert tools.ora_corrente.invoke({"fuso": "Europe/Rome", "parte": "ora"}) == "Rome: è mezzogiorno"


# Verifica i nomi dei 12 mesi in italiano: per ogni mese fissa il 27 e controlla la data.
def test_mese_in_italiano(monkeypatch):
    # "mese=mese" nella lambda blocca il valore del giro corrente del ciclo
    for mese, nome in enumerate(tools.MESI, start=1):
        monkeypatch.setattr(
            tools, "_adesso",
            lambda mese=mese: datetime(2026, mese, 27, 12, 0, 0, tzinfo=timezone.utc))
        assert tools.ora_corrente.invoke({"fuso": "UTC", "parte": "data"}) ==             f"UTC: 27 {nome} del 2026"
    assert tools.MESI[9] == "ottobre"


# Verifica l'ora a parole senza secondi: "minuto" al singolare e "in punto" a zero minuti.
def test_ora_senza_secondi(monkeypatch):
    # supporto: fissa l'istante alle h:m:sec UTC e chiede solo l'ora
    def a(h, m, sec):
        monkeypatch.setattr(
            tools, "_adesso",
            lambda: datetime(2026, 10, 27, h, m, sec, tzinfo=timezone.utc))
        return tools.ora_corrente.invoke({"fuso": "UTC", "parte": "ora"})

    assert a(17, 12, 50) == "UTC: sono le ore 17 e 12 minuti"
    assert a(17, 1, 30) == "UTC: sono le ore 17 e 1 minuto"
    assert a(17, 0, 59) == "UTC: sono le ore 17 in punto"
    assert "17:12" not in a(17, 12, 50)  # niente secondi, niente formato 17:12:50


# Verifica i casi speciali dell'italiano: "l'una", "mezzanotte", "mezzogiorno" (solo alle 12:00).
def test_ore_particolari(monkeypatch):
    # supporto: fissa l'istante alle h:m (secondi 40, da ignorare) e chiede solo l'ora
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


# Verifica che la risposta mostri un nome di luogo leggibile, non l'identificativo IANA.
def test_nome_del_luogo_senza_nome_iana(monkeypatch):
    _fissa(monkeypatch)
    ny = tools.ora_corrente.invoke({"fuso": "America/New_York"})
    # controllo: "New York" senza "America/", barre o trattini bassi
    assert ny.startswith("New York: ")
    assert "/" not in ny and "_" not in ny and "America" not in ny
    assert tools.ora_corrente.invoke({"fuso": "America/Argentina/Buenos_Aires", "parte": "ora"})         .startswith("Buenos Aires: ")
    assert tools.ora_corrente.invoke({"fuso": "UTC", "parte": "ora"}).startswith("UTC: ")


# Verifica i nomi visti dal modello e l'elenco e l'ordine degli strumenti locali STRUMENTI.
def test_nome_dello_strumento():
    assert tools.ora_corrente.name == "tooltime"
    assert [t.name for t in tools.STRUMENTI] == ["tooltime", "toolconvert", "toolcalc", "tooldate"]


# Verifica che un fuso inesistente (o un percorso di file) dia un messaggio, non un'eccezione:
# il modello riceve un testo da riferire all'utente.
def test_fuso_non_valido(monkeypatch):
    _fissa(monkeypatch)
    for fuso in ("Marte/Olimpo", "../etc"):  # vuoto = fuso predefinito
        risultato = tools.ora_corrente.invoke({"fuso": fuso})
        # controllo: risultato testuale con la spiegazione dell'errore
        assert isinstance(risultato, str)
        assert "fuso orario non valido" in risultato.lower()


# Verifica che la descrizione per il modello chieda l'ora a parole, non nel formato con i due punti.
def test_descrizione_chiede_ora_a_parole():
    descrizione = tools.ora_corrente.description
    assert "sono le ore 10 e 32 minuti" in descrizione
    assert "due punti" in descrizione


# Verifica che ogni argomento di ogni strumento locale abbia "type" e nessun "anyOf".
def test_schemi_con_type_per_il_template_di_gemma():
    # il template jinja di gemma in LM Studio fallisce ("Expected iterable or object type in for
    # loop") se un argomento non ha "type" (es. anyOf prodotto da `int | None`): HTTP 400
    from langchain_core.utils.function_calling import convert_to_openai_tool
    for strumento in tools.STRUMENTI:
        proprieta = convert_to_openai_tool(strumento)["function"]["parameters"]["properties"]
        for nome, schema in proprieta.items():
            assert "type" in schema and "anyOf" not in schema, (strumento.name, nome, schema)
