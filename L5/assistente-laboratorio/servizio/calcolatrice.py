"""Calcolatrice sicura: valuta espressioni aritmetiche senza usare l'interprete Python.

Ammessi: numeri con il punto decimale, + - * /, potenza (^ o **), segno unario, parentesi.
Ogni altro input e' rifiutato con ErroreCalcolo e un messaggio che dice il motivo.
"""
# math: controllo dei numeri infiniti o non validi; dataclass: classe dati compatta per i token
import math
from dataclasses import dataclass

# Limiti di sicurezza: impediscono espressioni enormi che bloccherebbero il servizio
MAX_LUNGHEZZA = 200      # caratteri dell'espressione
MAX_ANNIDAMENTO = 50     # livelli tra parentesi e segni unari
MAX_VALORE = 1e100       # valore assoluto massimo di ogni risultato, anche intermedio

# Caratteri che possono comporre un numero (insieme al punto decimale)
_CIFRE = "0123456789"


# Errore della calcolatrice: il servizio lo trasforma in una risposta 400 con il motivo
class ErroreCalcolo(ValueError):
    """Espressione rifiutata: il messaggio spiega il motivo."""


# Un "pezzo" dell'espressione (numero, operatore o parentesi) con la sua posizione.
# frozen=True: il token non si puo' modificare dopo la creazione
@dataclass(frozen=True)
class _Token:
    tipo: str        # "numero", "+", "-", "*", "/", "^", "(", ")"
    testo: str       # testo originale ("**" resta "**" anche se il tipo e' "^")
    posizione: int   # contata da 1


# Primo passo: spezza il testo in una lista di token, rifiutando i caratteri non ammessi
def _tokenizza(espressione: str) -> list[_Token]:
    # token: risultato; i: posizione corrente nel testo; n: lunghezza del testo
    token, i, n = [], 0, len(espressione)
    # Legge il testo un carattere alla volta, da sinistra a destra
    while i < n:
        c = espressione[i]
        # Spazi e tabulazioni si saltano
        if c in " \t":
            i += 1
        # Inizio di un numero: si prendono tutte le cifre e i punti consecutivi
        elif c in _CIFRE or c == ".":
            j = i
            while j < n and (espressione[j] in _CIFRE or espressione[j] == "."):
                j += 1
            testo = espressione[i:j]
            # solo cifre e punti: valido "12" o "12.5", non ".5", "5." o "1.2.3"
            # partition divide al primo punto: parte intera, punto (se c'e'), parte decimale
            intera, punto, decimale = testo.partition(".")
            if not intera or "." in decimale or (punto and not decimale):
                raise ErroreCalcolo(f"numero non valido '{testo}' in posizione {i + 1}: "
                                    "servono cifre prima e dopo il punto decimale")
            token.append(_Token("numero", testo, i + 1))
            # Si riparte dal primo carattere dopo il numero
            i = j
        # "**" e' un altro modo di scrivere la potenza: diventa un token di tipo "^"
        elif espressione.startswith("**", i):
            token.append(_Token("^", "**", i + 1))
            i += 2
        # "//" (divisione intera di Python) si rifiuta con un messaggio chiaro
        elif espressione.startswith("//", i):
            raise ErroreCalcolo(f"operatore non ammesso '//' in posizione {i + 1}: "
                                "la divisione intera non e' consentita")
        # Operatori e parentesi di un solo carattere
        elif c in "+-*/^()":
            token.append(_Token(c, c, i + 1))
            i += 1
        # Qualsiasi altro carattere (lettere, virgola, simboli) non e' ammesso
        else:
            # caratteri non stampabili (a capo, surrogati) come codice: il messaggio resta leggibile
            # e codificabile in UTF-8 nella risposta JSON
            mostrato = f"'{c}'" if c.isprintable() else f"U+{ord(c):04X}"
            messaggio = f"carattere non ammesso {mostrato} in posizione {i + 1}"
            if c == ",":
                messaggio += ": usa il punto decimale (2.5, non 2,5)"
            raise ErroreCalcolo(messaggio)
    # Tutto il testo e' stato letto senza errori
    return token


# Controlla ogni risultato, anche intermedio: rifiuta infinito, NaN e valori oltre MAX_VALORE
def _controlla(valore: float) -> float:
    if not math.isfinite(valore) or abs(valore) > MAX_VALORE:
        raise ErroreCalcolo("risultato troppo grande (oltre 1e100 in valore assoluto)")
    return valore


# Calcola base^esponente trasformando i casi impossibili in ErroreCalcolo
def _potenza(base: float, esponente: float) -> float:
    # Es. (-8)^0.5: nei numeri reali non esiste (Python darebbe un numero complesso)
    if base < 0 and not esponente.is_integer():
        raise ErroreCalcolo("potenza non definita nei reali: base negativa con esponente "
                            "non intero")
    try:
        return _controlla(base ** esponente)
    # 0 elevato a un esponente negativo e' una divisione per zero
    except ZeroDivisionError:
        raise ErroreCalcolo("divisione per zero (zero elevato a esponente negativo)") from None
    # Risultato troppo grande per un float (es. 10^1000)
    except OverflowError:
        raise ErroreCalcolo("risultato troppo grande (oltre 1e100 in valore assoluto)") from None


# Secondo passo: legge i token secondo una grammatica e calcola il risultato.
# Discesa ricorsiva: ogni regola della grammatica e' un metodo, e le regole con priorita'
# piu' alta (potenza, segno, parentesi) stanno "piu' in basso" e vengono chiamate per prime.
# Cosi' 2+3*4 fa prima 3*4, perche' _somma chiede a _prodotto i suoi operandi.
# Le parentesi rimandano di nuovo a _somma: e' qui che la discesa diventa ricorsiva.
class _Parser:
    """Discesa ricorsiva; calcola durante l'analisi.

    somma    := prodotto (('+'|'-') prodotto)*
    prodotto := unario (('*'|'/') unario)*
    unario   := ('+'|'-') unario | potenza
    potenza  := primario ('^' unario)?        (associativa a destra)
    primario := numero | '(' somma ')'
    """

    # Prepara il parser: lista dei token, indice del token corrente, livello di annidamento
    def __init__(self, token: list[_Token]):
        self.token = token
        self.i = 0
        self.profondita = 0

    # Restituisce il token corrente, o None se i token sono finiti
    def _attuale(self) -> _Token | None:
        return self.token[self.i] if self.i < len(self.token) else None

    # Restituisce solo il tipo del token corrente (comodo nei confronti)
    def _tipo(self) -> str | None:
        attuale = self._attuale()
        return attuale.tipo if attuale else None

    # Crea l'errore di sintassi giusto: fine inattesa o token fuori posto (con la posizione)
    def _errore_sintassi(self) -> ErroreCalcolo:
        attuale = self._attuale()
        if attuale is None:
            return ErroreCalcolo("sintassi non valida: l'espressione finisce in modo inatteso")
        return ErroreCalcolo(f"sintassi non valida in posizione {attuale.posizione}: "
                             f"'{attuale.testo}' inatteso")

    # Si chiama entrando in una parentesi o in un segno unario: conta i livelli e
    # blocca l'annidamento eccessivo, che esaurirebbe lo stack della ricorsione
    def _entra(self) -> None:
        self.profondita += 1
        if self.profondita > MAX_ANNIDAMENTO:
            raise ErroreCalcolo(f"annidamento eccessivo: piu' di {MAX_ANNIDAMENTO} livelli "
                                "tra parentesi e segni")

    # Punto di partenza: legge un'intera somma e controlla che non avanzino token
    def analizza(self) -> float:
        valore = self._somma()
        # Es. "2 3": dopo il 2 resta un token non usato, quindi la sintassi e' sbagliata
        if self._attuale() is not None:
            raise self._errore_sintassi()
        return valore

    # Regola "somma": un prodotto seguito da zero o piu' "+ prodotto" / "- prodotto"
    def _somma(self) -> float:
        valore = self._prodotto()
        # Il ciclo applica gli operatori da sinistra a destra: 5-2-1 vale (5-2)-1
        while self._tipo() in ("+", "-"):
            operatore = self._tipo()
            self.i += 1
            destra = self._prodotto()
            valore = _controlla(valore + destra if operatore == "+" else valore - destra)
        return valore

    # Regola "prodotto": come la somma, ma con * e / tra operandi unari
    def _prodotto(self) -> float:
        valore = self._unario()
        while self._tipo() in ("*", "/"):
            operatore = self._tipo()
            self.i += 1
            destra = self._unario()
            if operatore == "*":
                valore = _controlla(valore * destra)
            # La divisione per zero si rifiuta prima di calcolarla
            elif destra == 0:
                raise ErroreCalcolo("divisione per zero")
            else:
                valore = _controlla(valore / destra)
        return valore

    # Regola "unario": segni + o - davanti a un valore, anche ripetuti (es. --3)
    def _unario(self) -> float:
        if self._tipo() in ("+", "-"):
            segno = self._tipo()
            self._entra()
            self.i += 1
            # Chiamata ricorsiva: il segno si applica a tutto cio' che segue (anche altri segni)
            valore = self._unario()
            # Uscita dal livello aperto con _entra
            self.profondita -= 1
            return -valore if segno == "-" else valore
        # Nessun segno: si passa alla regola con priorita' piu' alta
        return self._potenza()

    # Regola "potenza": l'esponente si legge con _unario, quindi 2^3^2 vale 2^(3^2)
    # (associativa a destra) e 2^-1 e' ammesso
    def _potenza(self) -> float:
        base = self._primario()
        if self._tipo() == "^":
            self.i += 1
            return _potenza(base, self._unario())
        return base

    # Regola "primario": un numero oppure una sottoespressione tra parentesi
    def _primario(self) -> float:
        attuale = self._attuale()
        # Caso numero: il testo del token diventa un float
        if attuale is not None and attuale.tipo == "numero":
            self.i += 1
            return _controlla(float(attuale.testo))
        # Caso parentesi: dentro si riparte dalla regola piu' bassa, la somma
        if attuale is not None and attuale.tipo == "(":
            self._entra()
            self.i += 1
            # "()" senza niente dentro non e' un'espressione
            if self._tipo() == ")":
                raise ErroreCalcolo(f"sintassi non valida in posizione {attuale.posizione}: "
                                    "parentesi vuote")
            valore = self._somma()
            # Dopo la sottoespressione deve esserci la parentesi di chiusura
            if self._tipo() != ")":
                # Testo finito: la parentesi non e' mai stata chiusa
                if self._attuale() is None:
                    raise ErroreCalcolo("sintassi non valida: manca ')' per la parentesi "
                                        f"aperta in posizione {attuale.posizione}")
                raise self._errore_sintassi()
            # Salta la ")" ed esce dal livello di annidamento
            self.i += 1
            self.profondita -= 1
            return valore
        # Ne' numero ne' parentesi (es. un operatore di troppo): errore di sintassi
        raise self._errore_sintassi()


# Funzione pubblica usata dall'endpoint /calcola: controlli iniziali, poi token e parser
def calcola(espressione: str) -> float:
    """Valuta un'espressione aritmetica ammessa; solleva ErroreCalcolo con il motivo."""
    # Testo vuoto o fatto solo di spazi
    if not espressione.strip():
        raise ErroreCalcolo("espressione vuota")
    # Limite di lunghezza, controllato prima di qualsiasi altro lavoro
    if len(espressione) > MAX_LUNGHEZZA:
        raise ErroreCalcolo(f"espressione troppo lunga: {len(espressione)} caratteri "
                            f"(massimo {MAX_LUNGHEZZA})")
    # Spezza il testo in token e li fa analizzare (e calcolare) dal parser
    return _Parser(_tokenizza(espressione)).analizza()
