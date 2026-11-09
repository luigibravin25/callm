# modelli finti per i test: nessuna richiesta a LM Studio
from langchain_core.messages import AIMessage


# finto modello dell'agente: restituisce le risposte preparate, una per chiamata
class ModelloFinto:
    def __init__(self, risposte: list):
        self.risposte = list(risposte)  # AIMessage da restituire in ordine
        self.chiamate = []  # messaggi ricevuti a ogni chiamata

    # il grafo associa gli strumenti al modello: qui non serve, si restituisce lo stesso oggetto
    def bind_tools(self, strumenti):
        return self

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        # finite le risposte preparate si ripete l'ultima (utile per i test del limite)
        risposta = self.risposte.pop(0) if len(self.risposte) > 1 else self.risposte[0]
        # copia nuova a ogni chiamata: add_messages assegna un id al messaggio e, se lo stesso
        # oggetto tornasse due volte, lo sostituirebbe invece di aggiungerlo (come un modello vero)
        return risposta.model_copy(deep=True)


# finto router: ogni elemento e' una DecisioneRouter, None oppure un'eccezione da sollevare
class RouterFinto:
    def __init__(self, decisioni: list):
        self.decisioni = list(decisioni)
        self.chiamate = []  # messaggi ricevuti a ogni chiamata

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        # finite le decisioni preparate si ripete l'ultima
        decisione = self.decisioni.pop(0) if len(self.decisioni) > 1 else self.decisioni[0]
        if isinstance(decisione, Exception):
            raise decisione
        return decisione


# finto revisore: stesso comportamento del finto router (decisioni, None o eccezioni)
RevisoreFinto = RouterFinto


# finto modello del riassunto: restituisce i testi preparati come AIMessage (o solleva)
class RiassuntoFinto:
    def __init__(self, testi: list):
        self.testi = list(testi)
        self.chiamate = []  # messaggi ricevuti a ogni chiamata

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        # finiti i testi preparati si ripete l'ultimo
        testo = self.testi.pop(0) if len(self.testi) > 1 else self.testi[0]
        if isinstance(testo, Exception):
            raise testo
        return AIMessage(testo)
