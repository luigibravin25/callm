// elementi della pagina usati dallo script
const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const menu = document.getElementById("menu");
const toggle = document.getElementById("history-toggle");
const state = document.getElementById("history-state");
const streamToggle = document.getElementById("stream-toggle");
const streamState = document.getElementById("stream-state");

// cronologia solo in memoria (si perde chiudendo la pagina, mai salvata)
let history = [];
// true mentre il server sta rispondendo
let busy = false;
// true mentre il server aspetta il sì/no per un'eliminazione
let waitingConfirm = false;
// bolla dell'assistente che sta ricevendo il testo
let bot = null;
// testo già arrivato nella bolla corrente
let reply = "";

// apre e chiude il menu delle impostazioni
document.getElementById("menu-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  menu.hidden = !menu.hidden;
});
// un clic fuori dal menu lo chiude
document.addEventListener("click", (e) => {
  if (!menu.contains(e.target)) menu.hidden = true;
});

// interruttore della cronologia: spento svuota la cronologia
toggle.addEventListener("change", () => {
  state.textContent = toggle.checked ? "Attivato" : "Non attivato";
  if (!toggle.checked) history = [];
});
// interruttore dello streaming: aggiorna solo la scritta
streamToggle.addEventListener("change", () => {
  streamState.textContent = streamToggle.checked ? "Attivato" : "Non attivato";
});

// carica dal server l'elenco degli strumenti e lo mostra nel menu
// (ogni voce è {nome, icona}: nome leggibile e icona del gruppo)
fetch("/strumenti").then((r) => r.json()).then((strumenti) => {
  document.getElementById("tools-title").textContent = `Strumenti (${strumenti.length})`;
  document.getElementById("tools-list").replaceChildren(...strumenti.map((s) => {
    const li = document.createElement("li");
    li.textContent = `${s.icona} ${s.nome}`;
    return li;
  }));
}).catch(() => {});

// aggiunge una bolla alla chat e la porta in vista
function addBubble(text, who) {
  document.getElementById("empty")?.remove();
  const el = document.createElement("div");
  el.className = "bubble " + who;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

// bolla dell'assistente: riga degli strumenti usati + testo della risposta
function addBotBubble() {
  const el = addBubble("", "bot");
  const tools = document.createElement("div");
  tools.className = "tools-used";
  tools.hidden = true;
  const text = document.createElement("div");
  text.className = "text";
  el.append(tools, text);
  thinking(el);
  return el;
}

// animazione "Sto pensando..." nella parte di testo della bolla
function thinking(el) {
  el.querySelector(".text").innerHTML =
    'Sto pensando<span class="dots"><span>.</span><span>.</span><span>.</span></span>';
}

// scrive il testo nella bolla dell'assistente
function setBotText(el, text) {
  el.querySelector(".text").textContent = text;
  chat.scrollTop = chat.scrollHeight;
}

// aggiunge uno strumento usato ({nome, icona}) alla riga della bolla
function addTool(el, tool) {
  const tools = el.querySelector(".tools-used");
  tools.hidden = false;
  const tag = document.createElement("span");
  tag.className = "tool-tag";
  tag.textContent = `${tool.icona} ${tool.nome}`;
  tools.appendChild(tag);
  chat.scrollTop = chat.scrollHeight;
}

// mostra un errore nella bolla dell'assistente
function showError(el, message) {
  el.classList.add("error");
  setBotText(el, "Errore: " + message);
}

// ---------- allegati (pulsante "+") ----------
const attachBtn = document.getElementById("attach");
const fileInput = document.getElementById("file-input");
const attachList = document.getElementById("attachments");
const MAX_TEXT = 500 * 1024;       // oltre, il contesto del modello esplode
const MAX_IMAGE = 8 * 1024 * 1024;

// allegati in attesa di invio: { name, kind: "image" | "text", data }
let attachments = [];

// il pulsante "+" apre la scelta dei file
attachBtn.addEventListener("click", () => fileInput.click());
// file scelti: si leggono e si mostrano come chip
fileInput.addEventListener("change", async () => {
  for (const file of fileInput.files) await addAttachment(file);
  fileInput.value = ""; // permette di riselezionare lo stesso file
  renderAttachments();
});

// legge un file come data URL (per le immagini)
function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

// controlla un file e lo aggiunge agli allegati (immagine o testo)
async function addAttachment(file) {
  try {
    if (file.type.startsWith("image/")) {
      if (file.size > MAX_IMAGE) throw new Error("immagine oltre 8 MB");
      attachments.push({ name: file.name, kind: "image", data: await readAsDataURL(file) });
    } else {
      if (file.size > MAX_TEXT) throw new Error("file oltre 500 KB");
      const data = await file.text();
      // un byte nullo indica un file binario (pdf, zip, exe...): non leggibile come testo
      if (data.includes("\0")) throw new Error("formato non testuale");
      attachments.push({ name: file.name, kind: "text", data });
    }
  } catch (err) {
    addBubble(`Impossibile allegare "${file.name}": ${err.message}`, "bot").classList.add("error");
  }
}

// ridisegna le chip degli allegati in attesa
function renderAttachments() {
  attachList.hidden = attachments.length === 0;
  attachList.replaceChildren(...attachments.map((a, i) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    let icon;
    if (a.kind === "image") {
      icon = document.createElement("img");
      icon.src = a.data;
    } else {
      icon = document.createElement("span");
      icon.className = "file-icon";
      icon.textContent = "\u{1F4C4}";
    }
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = a.name;
    // pulsante "×" per togliere l'allegato
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "×";
    del.setAttribute("aria-label", "Rimuovi " + a.name);
    del.addEventListener("click", () => {
      attachments.splice(i, 1);
      renderAttachments();
    });
    chip.append(icon, name, del);
    return chip;
  }));
}

// bolla dell'utente: miniature delle immagini e nomi dei file di testo
function addUserBubble(text, files) {
  const el = addBubble("", "user");
  if (files.length) {
    const row = document.createElement("div");
    row.className = "sent-files";
    for (const f of files) {
      if (f.kind === "image") {
        const img = document.createElement("img");
        img.src = f.data;
        row.appendChild(img);
      } else {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "\u{1F4C4} " + f.name;
        row.appendChild(tag);
      }
    }
    el.appendChild(row);
  }
  if (text) el.append(text);
  return el;
}

// contenuto del messaggio: stringa semplice, oppure lista di parti se ci sono immagini
function buildContent(text, files) {
  if (!files.length) return text;
  const texts = files.filter((f) => f.kind === "text")
    .map((f) => `[File: ${f.name}]\n${f.data}\n[Fine file]`);
  const body = [...texts, text].filter(Boolean).join("\n\n");
  const images = files.filter((f) => f.kind === "image");
  if (!images.length) return body;
  return [
    { type: "text", text: body || "Descrivi l'immagine." },
    ...images.map((f) => ({ type: "image_url", image_url: { url: f.data } })),
  ];
}

// gestisce un evento del server ({"t": tipo, "v": valore}); restituisce il testo finale
// se l'evento è "done", altrimenti null
function handleEvent(ev) {
  if (ev.t === "token") {
    // pezzo di risposta in streaming
    reply += ev.v;
    setBotText(bot, reply);
  } else if (ev.t === "tool") {
    // il modello usa uno strumento: il nome compare sopra il testo
    addTool(bot, ev.v);
  } else if (ev.t === "confirm") {
    // eliminazione da confermare: la domanda la dice l'assistente in una bolla sua
    if (reply.trim()) setBotText(bot, reply.trim());
    else if (bot.querySelector(".tools-used").hidden) bot.remove();
    else bot.querySelector(".text").textContent = "";
    addBubble(ev.v, "bot").classList.add("question");
    // la prossima riga scritta dall'utente va a /confirm, non a /chat
    waitingConfirm = true;
    sendBtn.disabled = false;
    input.placeholder = "Rispondi sì o no...";
    input.focus();
  } else if (ev.t === "error") {
    showError(bot, ev.v);
  } else if (ev.t === "done") {
    return ev.v;
  }
  return null;
}

// manda la domanda a /chat e legge gli eventi fino alla fine della risposta
async function send(text, files) {
  busy = true;
  sendBtn.disabled = true;
  addUserBubble(text, files);
  bot = addBotBubble();
  reply = "";

  const content = buildContent(text, files);
  // senza history il modello vede solo l'ultima domanda
  const turns = toggle.checked ? [...history, { role: "user", content }]
                               : [{ role: "user", content }];
  let finale = null;

  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: turns, stream: streamToggle.checked }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ""; // righe JSON non ancora complete
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // ogni riga completa è un evento; l'ultima (forse incompleta) resta nel buffer
      const righe = buffer.split("\n");
      buffer = righe.pop();
      for (const riga of righe) {
        if (!riga.trim()) continue;
        const risultato = handleEvent(JSON.parse(riga));
        if (risultato !== null) finale = risultato;
      }
    }
  } catch (err) {
    showError(bot, err.message);
  }

  // risposta completa: testo finale ripulito dal server
  if (finale !== null) {
    setBotText(bot, finale.trim());
    if (toggle.checked && finale.trim()) {
      history.push({ role: "user", content }, { role: "assistant", content: finale.trim() });
    }
  } else if (!bot.classList.contains("error")) {
    showError(bot, "risposta interrotta");
  }
  waitingConfirm = false;
  input.placeholder = "Scrivi un messaggio...";
  busy = false;
  sendBtn.disabled = false;
  input.focus();
}

// risposta dell'utente alla domanda di conferma: va a /confirm, poi si aspetta il seguito
async function sendConfirm(text) {
  waitingConfirm = false;
  sendBtn.disabled = true;
  input.placeholder = "Scrivi un messaggio...";
  addUserBubble(text, []);
  // dopo la risposta il modello parla di nuovo, in una bolla nuova
  bot = addBotBubble();
  reply = "";
  try {
    await fetch("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: text }),
    });
  } catch (err) {
    showError(bot, err.message);
  }
}

// invio del modulo: domanda nuova oppure risposta alla conferma
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (waitingConfirm) {
    if (!text) return;
    input.value = "";
    input.style.height = "auto";
    sendConfirm(text);
    return;
  }
  if ((!text && !attachments.length) || busy) return;
  const files = attachments;
  attachments = [];
  renderAttachments();
  input.value = "";
  input.style.height = "auto";
  send(text, files);
});

// Invio = manda, Shift+Invio = a capo
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
// la casella cresce con il testo
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = input.scrollHeight + "px";
});
