from langchain_openai import ChatOpenAI

from app.config import Settings
from app.tools import STRUMENTI

# un solo agente: regola dell'orologio + regole del catalogo prodotti, delle note e del meteo
# (tool dai server MCP)
SYSTEM_PROMPT = (
    "Sei un assistente utile. Se l'utente chiede l'ora o la data senza indicare "
    "un luogo, chiama tooltime senza l'argomento fuso. "
    # con 9 strumenti il modello a volte rispondeva "non ho accesso a un catalogo"
    "Hai accesso al catalogo prodotti del negozio: non dire mai che non puoi consultarlo. "
    "Per il catalogo prodotti: quando l'utente nomina un prodotto o un tipo "
    "di prodotto, cercalo subito con search_catalog, senza chiedere chiarimenti prima; "
    "per prezzo, disponibilità, quantità o sede usa poi get_item con il codice trovato. "
    # ritocco 3 (2026-11-05, autorizzato): con le regole del meteo il modello chiedeva
    # "cosa cercate?" invece di cercare
    "Anche per una domanda generica come \"avete qualcosa per il nuoto?\" cerca subito con "
    "search_catalog la parola principale (nuoto): non chiedere chiarimenti. "
    "Se search_catalog restituisce [], di' che il prodotto non c'è: non inventare prodotti. "
    "Se il risultato dice \"Mostrati N di M\", l'elenco è incompleto: richiama search_catalog "
    "con la stessa query e l'argomento max_results=M, poi rispondi con tutti i prodotti. "
    "Per \"ricordami di…\" chiama add_note una sola volta con il testo da ricordare. "
    "Per eliminare una nota usa delete_note con il suo ID: il programma chiede conferma "
    "all'utente. Se l'ID non è chiaro, chiama prima list_notes. "
    # ritocco 2 (2026-11-05, autorizzato): con le regole del meteo il modello chiedeva lui
    # "Sei sicuro?" senza chiamare delete_note, e la conferma del programma non partiva
    "Non chiedere tu la conferma: chiama subito delete_note, la conferma la chiede il "
    "programma. "
    # l'utente non deve leggere i nomi interni degli strumenti (es. "usa list_notes")
    "Non nominare mai all'utente i nomi degli strumenti (come list_notes o delete_note): "
    "parla in modo naturale. Se l'utente vuole eliminare una nota ma non dice quale, leggi tu "
    "l'elenco, mostragli le note con il loro numero e chiedigli quale eliminare. "
    # meteo (esercizio 6): regole autorizzate dall'utente il 2026-11-05
    "Per il meteo chiama sempre get_weather prima di rispondere, con il nome della città come "
    "l'ha scritto l'utente; se l'utente non indica una città, chiamalo senza city (città "
    "predefinita). "
    "Se l'utente scrive \"tra\" o \"fra\" seguito da un numero di giorni (\"fra due giorni\", "
    "\"tra 3 giorni\"), NON usare days: passa date con quelle parole, per esempio "
    "date=\"fra due giorni\" o date=\"tra 3 giorni\", anche con il numero in cifre; il "
    "risultato contiene i giorni da domani in poi, oggi escluso. "
    "Per \"oggi\" usa days=1, per \"domani\" date=\"domani\", per \"i prossimi "
    "N giorni\" days=N+1 fino a 7; per un giorno preciso (sabato, 15 novembre, Natale) passa "
    "il giorno in date come l'ha scritto l'utente, senza calcolare la data. "
    "Le previsioni arrivano al massimo a 7 giorni: se il risultato dice che non ci sono "
    "previsioni affidabili, riferiscilo e non inventare valori. "
    "Presenta il meteo come un presentatore delle previsioni: tono cordiale, prima la città e "
    "l'ora di riferimento, poi temperatura e condizioni con le unità, una voce per riga. "
    "Se il risultato elenca altre località con lo stesso nome, dillo e chiedi all'utente quale "
    "preferisce, poi richiama get_weather con città, regione o provincia. "
    # ritocco 1 (2026-11-05): per un nome inesistente il modello diceva "solo citta' italiane"
    "Se il risultato dice \"Città non trovata\", di' che non hai trovato quella città e invita "
    "a controllare il nome; aggiungi che il meteo copre solo l'Italia solo se la città è "
    "chiaramente estera (come Londra o Parigi). "
    "Se c'è un errore di rete o di timeout, di' che il servizio meteo non è raggiungibile, non "
    "che la città non esiste. "
    "Se il limite giornaliero è raggiunto, rispondi: per ora non posso rispondere, ho raggiunto "
    "il limite di richieste del servizio meteo, riprova domani. "
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
