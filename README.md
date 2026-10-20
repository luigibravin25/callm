# Client LLM

Client Python per un server LM Studio locale (API compatibile OpenAI).
`BASE_URL` e `MODEL` si configurano nel file `.env` (vedi `.env.example`).

## Installazione ed esecuzione

```bash
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe client\client.py
```

Per il menù con scelta tra terminale e interfaccia grafica vedi l'Estensione 4.

## Struttura del progetto

```text
app_interface.py      menù di avvio (eseguibile)
client/client.py      il client LLM (invariato nella logica)
gui/web_gui.py        server locale dell'interfaccia web
gui/web/              pagina: index.html, style.css, app.js
```

## Estensione 1: chiamata all'LLM

- `client.py` invia a `BASE_URL` una richiesta `POST` con system prompt e prompt
  (`model`, `messages`, `temperature`, `max_tokens`) usando `requests`.
- Con `STREAM = False` la risposta arriva in un unico JSON e il testo viene stampato a terminale.
- Gli errori di rete o del server (server spento, timeout, 404, 500) sono catturati
  e mostrati come `Errore: ...`.
- Se il modello esaurisce i token ragionando, o la risposta è troncata, il client lo segnala
  (`MAX_TOKENS` è 4096 per lasciare spazio al ragionamento di Gemma).
- `BASE_URL` e `MODEL` sono letti dal file `.env` con `python-dotenv`.

## Estensione 2: risposta in streaming e chat interattiva

- Con `STREAM = True` (valore attuale) il payload include `"stream": true` e la risposta
  arriva a pezzi (eventi `data: {...}`), parola per parola.
- Ogni evento è letto con `iter_lines` e interpretato con il modulo `json`;
  il testo di ogni frammento (`delta.content`) è stampato subito con `flush=True`.
- Il flusso termina con `data: [DONE]`; alla fine il client va a capo e restituisce
  il testo completo.
- I frammenti malformati vengono saltati senza interrompere il programma.
- La codifica è forzata a UTF-8: per `text/event-stream` `requests` assume ISO-8859-1
  e storpierebbe le lettere accentate.
- Con `STREAM = False` il testo compare tutto insieme.
- `client.py` è un ciclo `while`: scrivi una domanda qualsiasi e il modello risponde
  in streaming. Per uscire scrivi `esci` oppure premi `Ctrl+C` (anche durante la risposta).

## Estensione 3: history della conversazione

- Il client tiene una `history` con tutte le domande e le risposte della chat e la invia
  intera, insieme al system prompt, a ogni richiesta: il modello ricorda cosa è stato detto.
- Se una risposta è vuota, la domanda corrispondente viene tolta dalla `history`.
- La `history` esiste solo in memoria: all'uscita dalla chat (`esci`, `Ctrl+C` o errore)
  viene cancellata e il client stampa "Chat terminata, history cancellata.".
  Nulla viene salvato su disco: una nuova chat riparte da zero.

## Estensione 4: interfaccia grafica web e menù di avvio

- `client.py` è stato spostato nella cartella `client/` senza cambiarne il codice.
- `app_interface.py` è un menù: `1` chat da terminale (esegue `client/client.py`),
  `2` chat con interfaccia grafica, `3` esci. Alla fine di una chat si torna al menù.
- L'interfaccia grafica è una pagina web locale (HTML + CSS + JavaScript) servita da
  `gui/web_gui.py` con la sola libreria standard di Python: nessuna dipendenza nuova.
  `web_gui.py` chiama `client.chat()` e inoltra al browser, a pezzi, ciò che stampa.
- Tema scuro in toni di grigio con accento indaco. Tutta la grafica sta in
  `gui/web/style.css`; i colori sono variabili CSS in cima al file.
- Chat a bolle (grigio più chiaro per l'utente, più scuro per il modello), pulsante di
  invio a freccia (Invio invia, Shift+Invio va a capo) e "Sto pensando..." con puntini
  animati finché il modello non produce la risposta.
- Un menù a scomparsa (pulsante ☰) raccoglie le impostazioni della chat, tra cui due
  toggle (history e streaming), entrambi disattivati di default: vedi la sezione
  "Menù Impostazioni" qui sotto.

### Esecuzione

```powershell
venv\Scripts\python.exe app_interface.py
```

Scegli `2` per l'interfaccia: si apre il browser su `http://127.0.0.1:8765`.
`Ctrl+C` nel terminale ferma il server e riporta al menù.
LM Studio deve essere avviato e `.env` configurato come per `client.py`.

`app_interface.py` ha il shebang `#!/usr/bin/env python3` ed è marcato eseguibile, quindi
su Linux/macOS (o Git Bash) si può lanciare anche con `./app_interface.py`.
Se viene avviato con un altro Python, si rilancia da solo con quello della `venv`.

### Menù Impostazioni

Il pulsante ☰ in alto a sinistra apre il menù "Impostazioni"; si chiude con un secondo
clic su ☰ o cliccando fuori dal menù. Contiene due toggle (interruttori). Ognuno mostra
sotto di sé lo stato corrente, "Attivato" o "Non attivato", ed è **non attivato di default**.
Si cambiano con un clic e valgono dal messaggio successivo.

| Toggle | Non attivato (default) | Attivato |
|---|---|---|
| **Conserva history** | Ogni domanda è indipendente: al modello viene inviata solo l'ultima, quindi non ricorda i messaggi precedenti. | Il modello riceve tutta la conversazione (domande e risposte) a ogni richiesta, quindi ricorda cosa è stato detto. |
| **Streaming parole** | La risposta compare tutta insieme a fine generazione. Nel frattempo la bolla mostra "Sto pensando..." con i puntini animati. | La risposta compare parola per parola, man mano che il modello la genera. |

**Conserva history**
- La history vive solo in memoria nella pagina del browser: non viene mai salvata su disco
  e si perde chiudendo o ricaricando la pagina.
- Spegnere il toggle la cancella subito: riaccendendolo si riparte da una conversazione vuota.
- Le bolle già scritte restano visibili in ogni caso; il toggle decide solo cosa viene
  inviato al modello.
- Se una risposta è vuota o dà errore, la domanda non entra nella history.

**Streaming parole**
- Cambia solo come viene mostrata la risposta, non il suo contenuto.
- Tecnicamente `web_gui.py` imposta `client.STREAM` a `True` o `False` a ogni richiesta in
  base al toggle, quindi `client.py` non è stato modificato.
- Il valore `STREAM` scritto in `client.py` vale solo per la chat da terminale (opzione 1
  del menù di avvio).

I due toggle sono indipendenti e si possono combinare liberamente.
