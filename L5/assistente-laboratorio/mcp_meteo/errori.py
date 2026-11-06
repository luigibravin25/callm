"""Categorie di errore del meteo.

Ogni errore ha una categoria fissa che apre il messaggio ("Città non trovata: ...", "Timeout:
..."). Il server MCP la passa al modello cosi' com'e': il modello capisce che tipo di problema
c'e' e non confonde, per esempio, una rete assente con una citta' inesistente.
"""


# Classe base di tutti gli errori del meteo: il server intercetta solo questa.
# Ogni sottoclasse cambia solo CATEGORIA, cioe' la parola iniziale del messaggio
class ErroreMeteo(Exception):
    """Errore del meteo: il messaggio e' "<CATEGORIA>: <dettaglio>"."""

    CATEGORIA = "Errore del servizio meteo"  # le sottoclassi la ridefiniscono

    # Costruttore: riceve solo il dettaglio, la categoria la aggiunge la classe
    def __init__(self, dettaglio: str):
        """Compone il messaggio "<CATEGORIA>: <dettaglio>"."""
        # il testo completo dell'eccezione e' quello che arriva al modello
        super().__init__(f"{self.CATEGORIA}: {dettaglio}")


# Il modello ha passato un argomento sbagliato al tool
class ArgomentoNonValido(ErroreMeteo):
    """city troppo lunga, days fuori intervallo, date non leggibile."""
    CATEGORIA = "Argomento non valido"


# La citta' chiesta non esiste in Italia (o la precisazione non corrisponde)
class CittaNonTrovata(ErroreMeteo):
    """Il geocoding non trova la citta' (o nessuna citta' corrisponde alla precisazione)."""
    CATEGORIA = "Città non trovata"


# Open-Meteo non ha risposto in tempo
class TimeoutMeteo(ErroreMeteo):
    """Il servizio non risponde entro il tempo massimo (errore di trasporto)."""
    CATEGORIA = "Timeout"


# Non si riesce nemmeno a collegarsi al servizio
class ReteNonRaggiungibile(ErroreMeteo):
    """Connessione impossibile: rete assente, DNS, servizio irraggiungibile (trasporto)."""
    CATEGORIA = "Rete non raggiungibile"


# Il servizio e' raggiungibile ma in difficolta': conviene riprovare piu' tardi
class ServizioNonDisponibile(ErroreMeteo):
    """Il servizio risponde con un errore suo (HTTP 5xx) o rifiuta per troppe richieste (429)."""
    CATEGORIA = "Servizio meteo non disponibile"


# Il servizio ha risposto, ma con dati che il programma non sa leggere
class RispostaNonValida(ErroreMeteo):
    """Risposta inattesa: JSON non valido, campi mancanti o di tipo sbagliato, altro HTTP."""
    CATEGORIA = "Risposta non valida"


# Il contatore locale ha bloccato la richiesta (limite di oggi superato)
class LimiteRaggiunto(ErroreMeteo):
    """Limite giornaliero di richieste raggiunto: nessuna richiesta viene inviata."""
    CATEGORIA = "Limite giornaliero raggiunto"


# Il file del contatore non funziona: per prudenza nessuna richiesta parte
class ContatoreNonAccessibile(ErroreMeteo):
    """L'archivio del contatore non si legge o non si scrive: nessuna richiesta viene inviata."""
    CATEGORIA = "Contatore non accessibile"
