# test della configurazione: variabili d'ambiente e file dell'ambito (config/ambito.toml)
import pytest

from app.config import CARTELLA_PROGETTO, load_ambito, load_settings

# frase di rifiuto attesa nel file vero dell'ambito
RIFIUTO = "Posso aiutarti solo con ora, data e fusi orari. Questa domanda è fuori dal mio ambito."


# imposta le due variabili obbligatorie e toglie le facoltative
@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LM_MODEL", "google/gemma-4-e2b")
    for nome in ("MAX_STEPS", "FUSO_PREDEFINITO", "AMBITO_FILE", "MAX_REVISIONI",
                 "SOGLIA_RIASSUNTO", "MESSAGGI_RECENTI"):
        monkeypatch.delenv(nome, raising=False)
    return monkeypatch


# scrive un file TOML temporaneo e restituisce il suo percorso
def _toml(tmp_path, testo: str):
    percorso = tmp_path / "ambito.toml"
    percorso.write_text(testo, encoding="utf-8")
    return percorso


# Verifica che senza LM_BASE_URL la configurazione dia un errore che la nomina.
def test_config_mancante(ambiente):
    ambiente.delenv("LM_BASE_URL")
    with pytest.raises(ValueError, match="LM_BASE_URL"):
        load_settings()


# Verifica i valori predefiniti di MAX_STEPS, del fuso e del file dell'ambito.
def test_config_valida(ambiente):
    s = load_settings()
    assert s.max_steps == 5
    assert s.fuso_predefinito == "Europe/Rome"
    assert s.ambito_file == CARTELLA_PROGETTO / "config" / "ambito.toml"


# Verifica che MAX_STEPS non numerico o zero sia rifiutato.
@pytest.mark.parametrize("valore", ["zero", "0"])
def test_max_steps_non_valido(ambiente, valore):
    ambiente.setenv("MAX_STEPS", valore)
    with pytest.raises(ValueError, match="MAX_STEPS"):
        load_settings()


# Verifica che un FUSO_PREDEFINITO inesistente sia rifiutato.
def test_fuso_non_valido(ambiente):
    ambiente.setenv("FUSO_PREDEFINITO", "Marte/Base")
    with pytest.raises(ValueError, match="FUSO_PREDEFINITO"):
        load_settings()


# Verifica che AMBITO_FILE relativo parta dalla cartella del progetto, non da quella corrente.
def test_ambito_file_relativo_alla_cartella_del_progetto(ambiente, tmp_path):
    # la cartella corrente non conta: il percorso relativo parte dal progetto
    ambiente.chdir(tmp_path)
    ambiente.setenv("AMBITO_FILE", "config/altro.toml")
    assert load_settings().ambito_file == CARTELLA_PROGETTO / "config" / "altro.toml"
    # un percorso assoluto resta com'e'
    assoluto = tmp_path / "mio.toml"
    ambiente.setenv("AMBITO_FILE", str(assoluto))
    assert load_settings().ambito_file == assoluto


# Verifica che il file vero config/ambito.toml si legga, accenti compresi.
def test_ambito_vero_si_carica():
    a = load_ambito(CARTELLA_PROGETTO / "config" / "ambito.toml")
    assert "fusi orari" in a.descrizione
    assert a.rifiuto == RIFIUTO
    assert "Che ore sono a Tokyo?" in a.esempi_in_ambito
    assert "Quanti km sono 10 miglia?" in a.esempi_fuori_ambito


# Verifica che un file dell'ambito inesistente dia un errore con il suo nome.
def test_ambito_file_mancante(tmp_path):
    with pytest.raises(ValueError, match="non_esiste.toml"):
        load_ambito(tmp_path / "non_esiste.toml")


# Verifica che un TOML scritto male dia un errore comprensibile.
def test_ambito_toml_non_valido(tmp_path):
    with pytest.raises(ValueError, match="TOML"):
        load_ambito(_toml(tmp_path, "descrizione = "))


# Verifica che descrizione e rifiuto assenti o vuoti siano rifiutati con il nome del campo.
@pytest.mark.parametrize("campo", ["descrizione", "rifiuto"])
@pytest.mark.parametrize("valore", [None, "   "])
def test_ambito_campo_obbligatorio(tmp_path, campo, valore):
    campi = {"descrizione": "ora e fusi", "rifiuto": "no"}
    if valore is None:
        del campi[campo]  # campo assente
    else:
        campi[campo] = valore  # campo fatto solo di spazi
    testo = "\n".join(f'{k} = "{v}"' for k, v in campi.items())
    with pytest.raises(ValueError, match=campo):
        load_ambito(_toml(tmp_path, testo))


# Verifica che gli esempi debbano essere una lista di testi.
@pytest.mark.parametrize("valore", ['"ciao"', "[1, 2]"])
def test_ambito_esempi_non_lista(tmp_path, valore):
    testo = f'descrizione = "ora"\nrifiuto = "no"\nesempi_in_ambito = {valore}'
    with pytest.raises(ValueError, match="esempi_in_ambito"):
        load_ambito(_toml(tmp_path, testo))


# Verifica che senza MAX_REVISIONI il revisore possa rimandare all'agente 2 volte.
def test_max_revisioni_predefinito(ambiente):
    assert load_settings().max_revisioni == 2


# Verifica che MAX_REVISIONI=0 sia ammesso (il revisore valuta ma non rimanda).
def test_max_revisioni_zero_ammesso(ambiente):
    ambiente.setenv("MAX_REVISIONI", "0")
    assert load_settings().max_revisioni == 0


# Verifica che MAX_REVISIONI non numerico o negativo sia rifiutato.
@pytest.mark.parametrize("valore", ["due", "-1"])
def test_max_revisioni_non_valido(ambiente, valore):
    ambiente.setenv("MAX_REVISIONI", valore)
    with pytest.raises(ValueError, match="MAX_REVISIONI"):
        load_settings()


# Verifica i valori predefiniti del riassunto: soglia 16 messaggi, ultimi 6 conservati.
def test_riassunto_predefiniti(ambiente):
    s = load_settings()
    assert (s.soglia_riassunto, s.messaggi_recenti) == (16, 6)


# Verifica che una soglia non numerica o zero sia rifiutata.
@pytest.mark.parametrize("valore", ["tanti", "0"])
def test_soglia_non_valida(ambiente, valore):
    ambiente.setenv("SOGLIA_RIASSUNTO", valore)
    with pytest.raises(ValueError, match="SOGLIA_RIASSUNTO"):
        load_settings()


# Verifica che i messaggi recenti siano almeno 1 e meno della soglia.
@pytest.mark.parametrize("valore", ["0", "16", "20"])
def test_recenti_non_validi(ambiente, valore):
    ambiente.setenv("MESSAGGI_RECENTI", valore)
    with pytest.raises(ValueError, match="MESSAGGI_RECENTI"):
        load_settings()