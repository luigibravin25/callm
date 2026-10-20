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

async function send(text) {
  busy = true;
  sendBtn.disabled = true;
  addBubble(text, "user");
  const bot = addBubble("", "bot");
  thinking(bot);

  // Senza history il modello vede solo l'ultima domanda
  const turns = toggle.checked ? [...history, { role: "user", content: text }]
                               : [{ role: "user", content: text }];
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
    history.push({ role: "user", content: text }, { role: "assistant", content: reply });
  }
  busy = false;
  sendBtn.disabled = false;
  input.focus();
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  input.style.height = "auto";
  send(text);
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
