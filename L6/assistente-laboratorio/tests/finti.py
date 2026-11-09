# modelli finti per i test: nessuna richiesta a LM Studio


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
        return self.risposte.pop(0) if len(self.risposte) > 1 else self.risposte[0]


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
