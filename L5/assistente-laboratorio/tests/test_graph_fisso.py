# Test del grafo senza modello: build_graph() senza argomenti risponde sempre RISPOSTA_FISSA.
# messaggio dell'utente nel formato di LangChain
from langchain_core.messages import HumanMessage

# parti dell'app da provare: il ciclo da terminale e il grafo
from app.cli import ETICHETTA_ASSISTENTE, main
from app.graph import RISPOSTA_FISSA, build_graph


# Verifica che il grafo senza modello risponda con il testo fisso: il flusso base funziona.
def test_risposta_fissa():
    # azione: un solo messaggio "ciao", contatore dei passi a zero
    out = build_graph().invoke({"messages": [HumanMessage("ciao")], "steps": 0})
    # controllo: l'ultimo messaggio e' la risposta fissa
    assert out["messages"][-1].content == RISPOSTA_FISSA


# Verifica che la cronologia si conservi tra due turni (requisito: memoria della sessione).
def test_cronologia_cresce():
    grafo = build_graph()
    cronologia = []
    # due turni: ogni volta si aggiunge la domanda e si riprende la cronologia restituita
    for testo in ("uno", "due"):
        cronologia.append(HumanMessage(testo))
        out = grafo.invoke({"messages": cronologia, "steps": 0})
        cronologia = out["messages"]
    # controllo: 2 domande + 2 risposte
    assert len(cronologia) == 4


# Supporto: esegue la CLI con righe di input preparate e restituisce tutto cio' che stampa.
def _esegui(righe):
    it = iter(righe)

    # input finto: da' una riga alla volta; finite le righe simula Ctrl+Z/Ctrl+D (EOFError)
    def input_fn(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    # le uscite finiscono in una lista invece che sullo schermo; nessuno streaming
    uscite = []
    main(input_fn=input_fn, output_fn=uscite.append, stream=False)
    return uscite


# Verifica che righe vuote o di soli spazi non arrivino al grafo (nessuna risposta inutile).
def test_input_vuoto_ignorato():
    uscite = _esegui(["", "   ", "exit"])
    # controllo: l'assistente non ha mai risposto
    assert ETICHETTA_ASSISTENTE + RISPOSTA_FISSA not in uscite


# Verifica che la CLI esca senza errori con "exit" e con la fine dell'input (EOF).
def test_uscita_pulita():
    _esegui(["exit"])
    _esegui([])  # EOF subito
    # controllo: una domanda prima di "exit" riceve esattamente una risposta
    assert _esegui(["ciao", "exit"]).count(ETICHETTA_ASSISTENTE + RISPOSTA_FISSA) == 1
