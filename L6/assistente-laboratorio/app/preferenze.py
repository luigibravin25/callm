"""Preferenze dell'utente lette dalla resource MCP utente://preferenze (step 4).

L'host le valida campo per campo e le mette in cima al prompt di sistema dell'agente.
"""
# librerie standard: JSON, log, classi di dati, fusi orari IANA
import json
import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# logger delle preferenze: nel terminale compare come [preferenze]
log = logging.getLogger("preferenze")

LINGUA_PREDEFINITA = "italiano"
STILE_PREDEFINITO = "sintetico"
STILI = ("sintetico", "dettagliato")  # unici stili ammessi

# frasi del blocco in cima al prompt di sistema dell'agente
INTESTAZIONE = "Preferenze dell'utente (valgono per tutta la conversazione):"
FRASE_LINGUA = ("- Rispondi sempre in {lingua}, anche se i risultati degli strumenti sono in "
                "un'altra lingua: traducili.")
FRASE_FUSO = ("- Fuso orario predefinito: {fuso} ({luogo}). Ora e data senza un luogo si "
              "riferiscono a questo fuso.")
FRASE_STILE = {
    "sintetico": "- Stile sintetico: rispondi in una o due frasi, solo con ciò che è stato chiesto.",
    "dettagliato": "- Stile dettagliato: rispondi in modo completo, con qualche spiegazione in più.",
}


# preferenze in uso nella sessione: frozen=True le rende immutabili
@dataclass(frozen=True)
class Preferenze:
    lingua: str  # lingua delle risposte, testo libero ("italiano", "inglese", ...)
    fuso: str  # fuso IANA usato quando l'utente non indica un luogo
    stile: str  # "sintetico" o "dettagliato"


# preferenze predefinite: il fuso arriva dall'host (FUSO_PREDEFINITO o Europe/Rome)
def predefinite(fuso_riserva: str) -> Preferenze:
    return Preferenze(LINGUA_PREDEFINITA, fuso_riserva, STILE_PREDEFINITO)


# controlli dei singoli campi: restituiscono il valore pulito oppure None se non valido
def _lingua(valore) -> str | None:
    return valore.strip() if isinstance(valore, str) and valore.strip() else None


def _fuso(valore) -> str | None:
    if not isinstance(valore, str) or not valore.strip():
        return None
    # il fuso e' valido solo se ZoneInfo lo riconosce
    try:
        ZoneInfo(valore.strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return valore.strip()


def _stile(valore) -> str | None:
    # maiuscole e spazi non contano: " Sintetico " vale "sintetico"
    pulito = valore.strip().lower() if isinstance(valore, str) else None
    return pulito if pulito in STILI else None


CAMPI = ("lingua", "fuso", "stile")  # campi del file delle preferenze


# valida il testo della resource campo per campo; None = resource non disponibile
def valida(testo: str | None, fuso_riserva: str) -> Preferenze:
    """Ogni campo mancante o non valido prende il suo predefinito con un WARNING che lo nomina;
    JSON illeggibile, non oggetto o resource assente: tutti i predefiniti con WARNING."""
    base = predefinite(fuso_riserva)
    dati = None
    dal_file = False  # almeno un campo valido letto dal file?
    if testo is None:
        log.warning("resource non disponibile: preferenze predefinite")
    else:
        try:
            dati = json.loads(testo)
        except json.JSONDecodeError as errore:
            log.warning("JSON delle preferenze non leggibile (%s): preferenze predefinite", errore)
        else:
            if not isinstance(dati, dict):
                log.warning("le preferenze devono essere un oggetto JSON: preferenze predefinite")
                dati = None
    if dati is None:
        p = base
    else:
        valori = {}
        # per ogni campo: valore del file se valido, altrimenti il predefinito con un avviso
        for campo, controllo in zip(CAMPI, (_lingua, _fuso, _stile)):
            predefinito = getattr(base, campo)
            if campo not in dati:
                log.warning("preferenze: campo '%s' mancante: uso %r", campo, predefinito)
                valori[campo] = predefinito
                continue
            pulito = controllo(dati[campo])
            if pulito is None:
                log.warning("preferenze: campo '%s' non valido (%r): uso %r",
                            campo, dati[campo], predefinito)
                valori[campo] = predefinito
            else:
                valori[campo] = pulito
                dal_file = True
        p = Preferenze(**valori)
    # evidenza: preferenze in uso in questa sessione e da dove vengono (almeno un campo dal file
    # = "da file")
    fonte = "da file" if dal_file else "predefinite"
    _registra(p, fonte)
    return p


# server MCP non partito: preferenze predefinite senza l'avviso sulla resource (basta quello sul
# server, scritto da chi avvia l'agente)
def usa_predefinite(fuso_riserva: str) -> Preferenze:
    p = predefinite(fuso_riserva)
    _registra(p, "predefinite")
    return p


# scrive nel log le preferenze in uso e la loro fonte
def _registra(p: Preferenze, fonte: str) -> None:
    log.info("in uso: lingua=%s fuso=%s stile=%s (%s)", p.lingua, p.fuso, p.stile, fonte)


# blocco di testo messo in cima al prompt di sistema dell'agente
def blocco_preferenze(p: Preferenze) -> str:
    # nome leggibile del luogo: "America/New_York" diventa "New York"
    luogo = p.fuso.rsplit("/", 1)[-1].replace("_", " ")
    return "\n".join([INTESTAZIONE, FRASE_LINGUA.format(lingua=p.lingua),
                      FRASE_FUSO.format(fuso=p.fuso, luogo=luogo), FRASE_STILE[p.stile]])
