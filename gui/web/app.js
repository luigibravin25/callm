const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const menu = document.getElementById("menu");
const toggle = document.getElementById("history-toggle");
const state = document.getElementById("history-state");
const ERR = "\x1eERR:"; // marcatore di errore inviato dal server

// History solo in memoria (si perde chiudendo la pagina, mai salvata)
let history = [];
let busy = false;

document.getElementById("menu-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  menu.hidden = !menu.hidden;
});
document.addEventListener("click", (e) => {
  if (!menu.contains(e.target)) menu.hidden = true;
});

toggle.addEventListener("change", () => {
  state.textContent = toggle.checked ? "Attivato" : "Non attivato";
  if (!toggle.checked) history = [];
});

const streamToggle = document.getElementById("stream-toggle");
const streamState = document.getElementById("stream-state");
streamToggle.addEventListener("change", () => {
  streamState.textContent = streamToggle.checked ? "Attivato" : "Non attivato";
});

function addBubble(text, who) {
  document.getElementById("empty")?.remove();
  const el = document.createElement("div");
  el.className = "bubble " + who;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function thinking(el) {
  el.innerHTML = 'Sto pensando<span class="dots"><span>.</span><span>.</span><span>.</span></span>';
}

// ---------- allegati (pulsante "+") ----------
const attachBtn = document.getElementById("attach");
const fileInput = document.getElementById("file-input");
const attachList = document.getElementById("attachments");
const MAX_TEXT = 500 * 1024;       // oltre, il contesto del modello esplode
const MAX_IMAGE = 8 * 1024 * 1024;

// Allegati in attesa di invio: { name, kind: "image" | "text", data }
let attachments = [];

attachBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", async () => {
  for (const file of fileInput.files) await addAttachment(file);
  fileInput.value = ""; // permette di riselezionare lo stesso file
  renderAttachments();
});

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

async function addAttachment(file) {
  try {
    if (file.type.startsWith("image/")) {
      if (file.size > MAX_IMAGE) throw new Error("immagine oltre 8 MB");
      attachments.push({ name: file.name, kind: "image", data: await readAsDataURL(file) });
    } else {
      if (file.size > MAX_TEXT) throw new Error("file oltre 500 KB");
      const data = await file.text();
      // Un byte nullo indica un file binario (pdf, zip, exe...): non leggibile come testo
      if (data.includes("\0")) throw new Error("formato non testuale");
      attachments.push({ name: file.name, kind: "text", data });
    }
  } catch (err) {
    addBubble(`Impossibile allegare "${file.name}": ${err.message}`, "bot").classList.add("error");
  }
}

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
      icon.textContent = "📄";
    }
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = a.name;
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

// Bolla dell'utente: miniature delle immagini e nomi dei file di testo
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
        tag.textContent = "📄 " + f.name;
        row.appendChild(tag);
      }
    }
    el.appendChild(row);
  }
  if (text) el.append(text);
  return el;
}

// Contenuto del messaggio: stringa semplice, oppure lista di parti se ci sono immagini
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

async function send(text, files) {
  busy = true;
  sendBtn.disabled = true;
  addUserBubble(text, files);
  const bot = addBubble("", "bot");
  thinking(bot);

  const content = buildContent(text, files);
  // Senza history il modello vede solo l'ultima domanda
  const turns = toggle.checked ? [...history, { role: "user", content }]
                               : [{ role: "user", content }];
  let reply = "";
  let failed = false;

  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: turns, stream: streamToggle.checked }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      reply += decoder.decode(value, { stream: true });
      const i = reply.indexOf(ERR);
      if (i !== -1) {
        failed = true;
        bot.classList.add("error");
        bot.textContent = "Errore: " + reply.slice(i + ERR.length);
        break;
      }
      bot.textContent = reply;
      chat.scrollTop = chat.scrollHeight;
    }
  } catch (err) {
    failed = true;
    bot.classList.add("error");
    bot.textContent = "Errore: " + err.message;
  }

  reply = reply.trim();
  if (!failed) bot.textContent = reply;
  if (toggle.checked && !failed && reply) {
    history.push({ role: "user", content }, { role: "assistant", content: reply });
  }
  busy = false;
  sendBtn.disabled = false;
  input.focus();
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
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
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = input.scrollHeight + "px";
});
