"""Comandi della CLI per i prompt MCP (step 5): /prompts e /prompt nome chiave=valore.

Solo funzioni pure: leggono la riga e la confrontano con l'elenco di prompts/list, senza chiamare
il server ne' il modello. Il server controlla poi i valori (livello, stile).
"""
# librerie standard: divisione della riga come una shell (virgolette doppie), classi di dati
import shlex
from dataclasses import dataclass

# tipo dei prompt pubblicati dal server (prompts/list)
from app.info_prompt import InfoPrompt

# messaggi fissi della CLI (i test li confrontano parola per parola)
MSG_SCONOSCIUTO = "Comando sconosciuto: {comando}. Comandi: /prompts, /prompt nome chiave=valore."
MSG_USO = ('Uso: /prompt nome chiave=valore ... (esempio: /prompt spiega '
           'argomento="Model Context Protocol" livello=base)')
MSG_PROMPT_SCONOSCIUTO = "Prompt sconosciuto: {nome}. Scrivi /prompts per l'elenco."
MSG_MANCANTE = "Manca l'argomento obbligatorio '{argomento}' del prompt {nome}."
MSG_ARG_SCONOSCIUTO = "Argomento sconosciuto '{argomento}'. Argomenti di {nome}: {ammessi}."
MSG_NON_LEGGIBILI = ("Argomenti non leggibili ({dettaglio}): usa chiave=valore, con le virgolette "
                     "doppie se il valore ha spazi.")
MSG_NESSUN_PROMPT = "Nessun prompt disponibile: server MCP non avviato."
MSG_USO_PROMPTS = "Uso: /prompts (senza argomenti)."
MSG_ERRORE_PROMPT = "Il server non ha restituito il prompt: {motivo}."  # usato dalla CLI


# richiesta valida: prompt da chiedere al server con i suoi argomenti
@dataclass(frozen=True)
class RichiestaPrompt:
    nome: str
    argomenti: dict[str, str]


# testo di /prompts: nome, descrizione e argomenti di ogni prompt
def elenco_prompt(prompts: list[InfoPrompt]) -> str:
    righe = ["Prompt disponibili:"]
    for p in prompts:
        righe.append(f"- {p.nome}: {p.descrizione}")
        # ogni argomento con "obbligatorio" o "facoltativo"
        argomenti = ", ".join(f"{a.nome} ({'obbligatorio' if a.obbligatorio else 'facoltativo'})"
                              for a in p.argomenti)
        righe.append(f"  argomenti: {argomenti or 'nessuno'}")
    return "\n".join(righe)


# divide gli argomenti come una shell, ma solo le virgolette doppie tengono insieme un valore:
# l'apostrofo resta un carattere normale (con shlex.split "dell'MCP livello=l'avanzato" diventava
# un solo valore senza errori)
def _dividi(testo: str) -> list[str]:
    lettore = shlex.shlex(testo, posix=True)
    lettore.whitespace_split = True  # pezzi divisi solo dagli spazi, come shlex.split
    lettore.quotes = '"'  # solo virgolette doppie
    lettore.commenters = ""  # "#" e' un carattere normale
    return list(lettore)


# trasforma i pezzi "chiave=valore" in un dizionario; un errore diventa il suo messaggio
def leggi_argomenti(pezzi: list[str]) -> dict[str, str] | str:
    argomenti = {}
    for pezzo in pezzi:
        # divisione al primo "=": il valore puo' contenere altri "="
        chiave, uguale, valore = pezzo.partition("=")
        if not uguale or not chiave:
            return MSG_NON_LEGGIBILI.format(dettaglio=f"'{pezzo}' senza =")
        if chiave in argomenti:
            return MSG_NON_LEGGIBILI.format(dettaglio=f"chiave '{chiave}' ripetuta")
        if not valore.strip():
            return MSG_NON_LEGGIBILI.format(dettaglio=f"valore vuoto per '{chiave}'")
        argomenti[chiave] = valore
    return argomenti


# confronta gli argomenti con quelli pubblicati: prima gli sconosciuti, poi gli obbligatori
def controlla_argomenti(info: InfoPrompt, argomenti: dict[str, str]) -> str | None:
    nomi = [a.nome for a in info.argomenti]
    for chiave in argomenti:
        if chiave not in nomi:
            return MSG_ARG_SCONOSCIUTO.format(argomento=chiave, nome=info.nome,
                                              ammessi=", ".join(nomi))
    for a in info.argomenti:
        if a.obbligatorio and a.nome not in argomenti:
            return MSG_MANCANTE.format(argomento=a.nome, nome=info.nome)
    return None


# interpreta una riga che inizia con "/": testo da stampare (elenco o errore) o richiesta valida
def interpreta(riga: str, prompts: list[InfoPrompt]) -> str | RichiestaPrompt:
    # primo pezzo = comando (maiuscole indifferenti), il resto = nome e argomenti; split() divide
    # su qualsiasi spazio bianco (anche il tab)
    comando, resto = (riga.strip().split(maxsplit=1) + ["", ""])[:2]
    if comando.lower() not in ("/prompts", "/prompt"):
        return MSG_SCONOSCIUTO.format(comando=comando)
    # server non avviato: nessun elenco con cui controllare
    if not prompts:
        return MSG_NESSUN_PROMPT
    if comando.lower() == "/prompts":
        # /prompts non accetta argomenti: il testo in piu' non si ignora in silenzio
        return MSG_USO_PROMPTS if resto.strip() else elenco_prompt(prompts)
    # nome del prompt: maiuscole distinte, come in MCP
    nome, testo_argomenti = (resto.strip().split(maxsplit=1) + ["", ""])[:2]
    if not nome:
        return MSG_USO
    info = next((p for p in prompts if p.nome == nome), None)
    if info is None:
        return MSG_PROMPT_SCONOSCIUTO.format(nome=nome)
    try:
        pezzi = _dividi(testo_argomenti)
    except ValueError:
        return MSG_NON_LEGGIBILI.format(dettaglio="virgolette non chiuse")
    argomenti = leggi_argomenti(pezzi)
    if isinstance(argomenti, str):
        return argomenti
    errore = controlla_argomenti(info, argomenti)
    return errore if errore else RichiestaPrompt(nome, argomenti)
