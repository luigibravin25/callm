"""Calcolatrice sicura: valuta espressioni aritmetiche senza usare l'interprete Python.

Ammessi: numeri con il punto decimale, + - * /, potenza (^ o **), segno unario, parentesi.
Ogni altro input e' rifiutato con ErroreCalcolo e un messaggio che dice il motivo.
"""
import math
from dataclasses import dataclass

MAX_LUNGHEZZA = 200      # caratteri dell'espressione
MAX_ANNIDAMENTO = 50     # livelli tra parentesi e segni unari
MAX_VALORE = 1e100       # valore assoluto massimo di ogni risultato, anche intermedio

_CIFRE = "0123456789"


class ErroreCalcolo(ValueError):
    """Espressione rifiutata: il messaggio spiega il motivo."""


@dataclass(frozen=True)
class _Token:
    tipo: str        # "numero", "+", "-", "*", "/", "^", "(", ")"
    testo: str       # testo originale ("**" resta "**" anche se il tipo e' "^")
    posizione: int   # contata da 1


def _tokenizza(espressione: str) -> list[_Token]:
    token, i, n = [], 0, len(espressione)
    while i < n:
        c = espressione[i]
        if c in " \t":
            i += 1
        elif c in _CIFRE or c == ".":
            j = i
            while j < n and (espressione[j] in _CIFRE or espressione[j] == "."):
                j += 1
            testo = espressione[i:j]
            # solo cifre e punti: valido "12" o "12.5", non ".5", "5." o "1.2.3"
            intera, punto, decimale = testo.partition(".")
            if not intera or "." in decimale or (punto and not decimale):
                raise ErroreCalcolo(f"numero non valido '{testo}' in posizione {i + 1}: "
                                    "servono cifre prima e dopo il punto decimale")
            token.append(_Token("numero", testo, i + 1))
            i = j
        elif espressione.startswith("**", i):
            token.append(_Token("^", "**", i + 1))
            i += 2
        elif espressione.startswith("//", i):
            raise ErroreCalcolo(f"operatore non ammesso '//' in posizione {i + 1}: "
                                "la divisione intera non e' consentita")
        elif c in "+-*/^()":
            token.append(_Token(c, c, i + 1))
            i += 1
        else:
            # caratteri non stampabili (a capo, surrogati) come codice: il messaggio resta leggibile
            # e codificabile in UTF-8 nella risposta JSON
            mostrato = f"'{c}'" if c.isprintable() else f"U+{ord(c):04X}"
            messaggio = f"carattere non ammesso {mostrato} in posizione {i + 1}"
            if c == ",":
                messaggio += ": usa il punto decimale (2.5, non 2,5)"
            raise ErroreCalcolo(messaggio)
    return token


def _controlla(valore: float) -> float:
    if not math.isfinite(valore) or abs(valore) > MAX_VALORE:
        raise ErroreCalcolo("risultato troppo grande (oltre 1e100 in valore assoluto)")
    return valore


def _potenza(base: float, esponente: float) -> float:
    if base < 0 and not esponente.is_integer():
        raise ErroreCalcolo("potenza non definita nei reali: base negativa con esponente "
                            "non intero")
    try:
        return _controlla(base ** esponente)
    except ZeroDivisionError:
        raise ErroreCalcolo("divisione per zero (zero elevato a esponente negativo)") from None
    except OverflowError:
        raise ErroreCalcolo("risultato troppo grande (oltre 1e100 in valore assoluto)") from None


class _Parser:
    """Discesa ricorsiva; calcola durante l'analisi.

    somma    := prodotto (('+'|'-') prodotto)*
    prodotto := unario (('*'|'/') unario)*
    unario   := ('+'|'-') unario | potenza
    potenza  := primario ('^' unario)?        (associativa a destra)
    primario := numero | '(' somma ')'
    """

    def __init__(self, token: list[_Token]):
        self.token = token
        self.i = 0
        self.profondita = 0

    def _attuale(self) -> _Token | None:
        return self.token[self.i] if self.i < len(self.token) else None

    def _tipo(self) -> str | None:
        attuale = self._attuale()
        return attuale.tipo if attuale else None

    def _errore_sintassi(self) -> ErroreCalcolo:
        attuale = self._attuale()
        if attuale is None:
            return ErroreCalcolo("sintassi non valida: l'espressione finisce in modo inatteso")
        return ErroreCalcolo(f"sintassi non valida in posizione {attuale.posizione}: "
                             f"'{attuale.testo}' inatteso")

    def _entra(self) -> None:
        self.profondita += 1
        if self.profondita > MAX_ANNIDAMENTO:
            raise ErroreCalcolo(f"annidamento eccessivo: piu' di {MAX_ANNIDAMENTO} livelli "
                                "tra parentesi e segni")

    def analizza(self) -> float:
        valore = self._somma()
        if self._attuale() is not None:
            raise self._errore_sintassi()
        return valore

    def _somma(self) -> float:
        valore = self._prodotto()
        while self._tipo() in ("+", "-"):
            operatore = self._tipo()
            self.i += 1
            destra = self._prodotto()
            valore = _controlla(valore + destra if operatore == "+" else valore - destra)
        return valore

    def _prodotto(self) -> float:
        valore = self._unario()
        while self._tipo() in ("*", "/"):
            operatore = self._tipo()
            self.i += 1
            destra = self._unario()
            if operatore == "*":
                valore = _controlla(valore * destra)
            elif destra == 0:
                raise ErroreCalcolo("divisione per zero")
            else:
                valore = _controlla(valore / destra)
        return valore

    def _unario(self) -> float:
        if self._tipo() in ("+", "-"):
            segno = self._tipo()
            self._entra()
            self.i += 1
            valore = self._unario()
            self.profondita -= 1
            return -valore if segno == "-" else valore
        return self._potenza()

    def _potenza(self) -> float:
        base = self._primario()
        if self._tipo() == "^":
            self.i += 1
            return _potenza(base, self._unario())
        return base

    def _primario(self) -> float:
        attuale = self._attuale()
        if attuale is not None and attuale.tipo == "numero":
            self.i += 1
            return _controlla(float(attuale.testo))
        if attuale is not None and attuale.tipo == "(":
            self._entra()
            self.i += 1
            if self._tipo() == ")":
                raise ErroreCalcolo(f"sintassi non valida in posizione {attuale.posizione}: "
                                    "parentesi vuote")
            valore = self._somma()
            if self._tipo() != ")":
                if self._attuale() is None:
                    raise ErroreCalcolo("sintassi non valida: manca ')' per la parentesi "
                                        f"aperta in posizione {attuale.posizione}")
                raise self._errore_sintassi()
            self.i += 1
            self.profondita -= 1
            return valore
        raise self._errore_sintassi()


def calcola(espressione: str) -> float:
    """Valuta un'espressione aritmetica ammessa; solleva ErroreCalcolo con il motivo."""
    if not espressione.strip():
        raise ErroreCalcolo("espressione vuota")
    if len(espressione) > MAX_LUNGHEZZA:
        raise ErroreCalcolo(f"espressione troppo lunga: {len(espressione)} caratteri "
                            f"(massimo {MAX_LUNGHEZZA})")
    return _Parser(_tokenizza(espressione)).analizza()
