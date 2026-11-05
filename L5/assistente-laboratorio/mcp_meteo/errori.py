"""Categorie di errore del meteo.

Ogni errore ha una categoria fissa che apre il messaggio ("Città non trovata: ...", "Timeout:
..."). Il server MCP la passa al modello cosi' com'e': il modello capisce che tipo di problema
c'e' e non confonde, per esempio, una rete assente con una citta' inesistente.
"""


class ErroreMeteo(Exception):
    """Errore del meteo: il messaggio e' "<CATEGORIA>: <dettaglio>"."""

    CATEGORIA = "Errore del servizio meteo"  # le sottoclassi la ridefiniscono

    def __init__(self, dettaglio: str):
        """Compone il messaggio "<CATEGORIA>: <dettaglio>"."""
        # il testo completo dell'eccezione e' quello che arriva al modello
        super().__init__(f"{self.CATEGORIA}: {dettaglio}")


class ArgomentoNonValido(ErroreMeteo):
    """city troppo lunga, days fuori intervallo, date non leggibile."""
    CATEGORIA = "Argomento non valido"


class CittaNonTrovata(ErroreMeteo):
    """Il geocoding non trova la citta' (o nessuna citta' corrisponde alla precisazione)."""
    CATEGORIA = "Città non trovata"


class TimeoutMeteo(ErroreMeteo):
    """Il servizio non risponde entro il tempo massimo (errore di trasporto)."""
    CATEGORIA = "Timeout"


class ReteNonRaggiungibile(ErroreMeteo):
    """Connessione impossibile: rete assente, DNS, servizio irraggiungibile (trasporto)."""
    CATEGORIA = "Rete non raggiungibile"


class ServizioNonDisponibile(ErroreMeteo):
    """Il servizio risponde con un errore suo (HTTP 5xx) o rifiuta per troppe richieste (429)."""
    CATEGORIA = "Servizio meteo non disponibile"


class RispostaNonValida(ErroreMeteo):
    """Risposta inattesa: JSON non valido, campi mancanti o di tipo sbagliato, altro HTTP."""
    CATEGORIA = "Risposta non valida"


class LimiteRaggiunto(ErroreMeteo):
    """Limite giornaliero di richieste raggiunto: nessuna richiesta viene inviata."""
    CATEGORIA = "Limite giornaliero raggiunto"


class ContatoreNonAccessibile(ErroreMeteo):
    """L'archivio del contatore non si legge o non si scrive: nessuna richiesta viene inviata."""
    CATEGORIA = "Contatore non accessibile"
