# CLAUDE.md

## Progetto
`client.py`: client Python per un server LM Studio locale (API compatibile OpenAI,
`http://127.0.0.1:1234/v1/chat/completions`, modello `google/gemma-4-e2b`).

## Cosa è stato fatto
- Creato `client.py`: invia system prompt + prompt, supporta streaming (`STREAM`)
  e mostra un indicatore di attesa ("Elaborazione in corso") mentre il modello lavora.
- Corretto l'output "risposta vuota dal modello": Gemma ragiona prima di rispondere
  e il server restituisce `content` vuoto con il testo in `reasoning_content`.
  Con `MAX_TOKENS = 180` i token finivano nel ragionamento (`finish_reason: length`).
  Ora `MAX_TOKENS = 1024`, e se la risposta è comunque vuota il client distingue
  "token esauriti nel ragionamento" da "risposta vuota"; segnala anche la troncatura.
- Compilato `requirements.txt` (`requests`; le altre librerie sono standard library).

## Note
- Eseguire con l'ambiente virtuale: `venv\Scripts\python.exe client.py`.
- `requirements.txt` è elencato in `.gitignore`: rimuoverlo da lì se deve essere versionato.
