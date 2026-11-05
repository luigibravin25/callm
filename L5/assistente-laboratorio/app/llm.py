from langchain_openai import ChatOpenAI

from app.config import Settings
from app.tools import STRUMENTI

# un solo agente: regola dell'orologio + regole del catalogo prodotti e delle note (tool dai
# server MCP)
SYSTEM_PROMPT = (
    "Sei un assistente utile. Se l'utente chiede l'ora o la data senza indicare "
    "un luogo, chiama tooltime senza l'argomento fuso. "
    "Per il catalogo prodotti: quando l'utente nomina un prodotto o un tipo "
    "di prodotto, cercalo subito con search_catalog, senza chiedere chiarimenti prima; "
    "per prezzo, disponibilità, quantità o sede usa poi get_item con il codice trovato. "
    "Se search_catalog restituisce [], di' che il prodotto non c'è: non inventare prodotti. "
    "Se il risultato dice \"Mostrati N di M\", l'elenco è incompleto: richiama search_catalog "
    "con la stessa query e l'argomento max_results=M, poi rispondi con tutti i prodotti. "
    "Per \"ricordami di…\" chiama add_note una sola volta con il testo da ricordare. "
    "Per eliminare una nota usa delete_note con il suo ID: il programma chiede conferma "
    "all'utente. Se l'ID non è chiaro, chiama prima list_notes. "
    # l'utente non deve leggere i nomi interni degli strumenti (es. "usa list_notes")
    "Non nominare mai all'utente i nomi degli strumenti (come list_notes o delete_note): "
    "parla in modo naturale. Se l'utente vuole eliminare una nota ma non dice quale, leggi tu "
    "l'elenco, mostragli le note con il loro numero e chiedigli quale eliminare. "
    # il terminale non interpreta il Markdown: gli asterischi resterebbero visibili
    "Rispondi in testo semplice, senza asterischi e senza grassetto: per gli elenchi scrivi "
    "una voce per riga che inizia con un trattino.")
STREAM = True  # True = token per token, False = risposta in blocco
HISTORY = True  # True = il modello ricorda i messaggi precedenti, False = ogni domanda parte da zero
LOG_HTTP = True  # True = mostra nel terminale le richieste HTTP verso LM Studio
LOG_GRAFO = True  # True = mostra nel terminale i log del grafo (chiamate agli strumenti, limite)


def build_llm(settings: Settings, strumenti=STRUMENTI, max_tokens: int = 8192):
    modello = ChatOpenAI(
        base_url=settings.base_url,
        model=settings.model,
        api_key="lm-studio",  # LM Studio ignora la chiave: valore fittizio, non un segreto
        temperature=0.2,
        timeout=300,
        max_tokens=max_tokens,  # il modello ragiona prima di rispondere: servono token a sufficienza
    )
    return modello.bind_tools(strumenti)
