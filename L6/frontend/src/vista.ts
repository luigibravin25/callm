// vista: costruisce la pagina una volta e la aggiorna a ogni disegna(); testi sempre con textContent
import type { Messaggio } from "./api/client";
import type { Applicazione } from "./app";
import { formattaData, MSG_INVITO, rigaStrumenti } from "./formato";
import { datiChat, inAttesa } from "./stato";

// crea un elemento con classe e testo (testo sempre come testo, mai come HTML)
function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, classe = "", testo?: string,
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (testo !== undefined) e.textContent = testo;
  return e;
}

// pulsante con testo e azione
function pulsante(classe: string, testo: string, azione: () => void): HTMLButtonElement {
  const b = el("button", classe, testo);
  b.type = "button";
  b.addEventListener("click", azione);
  return b;
}

// un messaggio: fumetto con il testo e, per l'assistente, la riga degli strumenti usati
function fumetto(m: Pick<Messaggio, "ruolo" | "testo" | "strumenti">): HTMLElement {
  const div = el("div", `msg ${m.ruolo}`);
  div.append(el("div", "testo", m.testo));
  const riga = m.ruolo === "assistente" ? rigaStrumenti(m.strumenti) : null;
  if (riga) div.append(el("div", "strumenti", riga));
  return div;
}

export function montaVista(radice: HTMLElement, app: Applicazione): { disegna(): void } {
  // struttura fissa: barra laterale e area della chat
  const barra = el("aside", "barra");
  const nuova = pulsante("", "+ Nuova chat", () => void app.nuovaChat());
  nuova.id = "nuova-chat";
  const erroreBarra = el("div", "errore");
  erroreBarra.id = "errore-barra";
  erroreBarra.setAttribute("role", "alert");
  const elenco = el("ul");
  elenco.id = "elenco-chat";
  barra.append(nuova, erroreBarra, elenco);

  const area = el("main", "area");
  const erroreChat = el("div", "errore");
  erroreChat.id = "errore-chat";
  erroreChat.setAttribute("role", "alert");
  const invito = el("p", "invito", MSG_INVITO);
  invito.id = "invito";
  const messaggi = el("div", "messaggi");
  messaggi.id = "messaggi";
  messaggi.setAttribute("aria-live", "polite");
  const modulo = el("form", "modulo");
  // il campo non si ricrea mai: fuoco e cursore restano tra un disegno e l'altro
  const campo = el("textarea");
  campo.id = "campo";
  campo.rows = 2;
  campo.placeholder = "Scrivi una domanda… (Invio per inviare, Maiusc+Invio per andare a capo)";
  campo.setAttribute("aria-label", "Domanda");
  const invia = el("button", "", "Invia");
  invia.id = "invia";
  invia.type = "submit";
  modulo.append(campo, invia);
  area.append(erroreChat, invito, messaggi, modulo);
  radice.replaceChildren(barra, area);

  // invio della bozza della chat aperta
  const inviaAperta = () => {
    if (app.stato.aperta !== null) void app.invia(app.stato.aperta);
  };
  modulo.addEventListener("submit", (e) => { e.preventDefault(); inviaAperta(); });
  // Invio invia, Maiusc+Invio va a capo
  campo.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      inviaAperta();
    }
  });
  // ogni tasto aggiorna la bozza della chat aperta e lo stato del pulsante Invia
  campo.addEventListener("input", () => {
    if (app.stato.aperta === null) return;
    app.aggiornaBozza(app.stato.aperta, campo.value);
    invia.disabled = campo.disabled || !campo.value.trim();
  });

  // ultimo stato visto: il campo prende la bozza solo quando cambiano chat, errore o attesa;
  // elementi = numero di fumetti mostrati (per lo scorrimento in fondo)
  let ultimo = { aperta: null as number | null, errore: null as string | null,
    provvisoria: null as string | null, elementi: -1 };

  function disegnaBarra(): void {
    const s = app.stato;
    // errore della barra, con «Riprova» solo per il caricamento dell'elenco
    erroreBarra.replaceChildren();
    erroreBarra.hidden = !s.erroreBarra;
    if (s.erroreBarra) {
      erroreBarra.append(el("span", "", s.erroreBarra.messaggio));
      if (s.erroreBarra.riprova) erroreBarra.append(pulsante("riprova", "Riprova", () => void app.riprovaElenco()));
    }
    // elenco delle chat: titolo, data, 🗑
    elenco.replaceChildren(...s.chat.map((c) => {
      const voce = el("li", c.id === s.aperta ? "aperta" : "");
      voce.dataset.id = String(c.id);
      const attesa = inAttesa(s, c.id);
      if (attesa) voce.classList.add("in-attesa");
      const apri = pulsante("apri", "", () => void app.apri(c.id));
      apri.append(el("span", "titolo", c.titolo), el("span", "data", formattaData(c.ultimo_messaggio_il)));
      if (c.id === s.aperta) apri.setAttribute("aria-current", "true");
      const cestino = pulsante("elimina", "🗑", () => void app.elimina(c.id));
      cestino.setAttribute("aria-label", `Elimina chat ${c.titolo}`);
      cestino.title = attesa ? "In attesa della risposta" : "Elimina chat";
      cestino.disabled = attesa;
      voce.append(apri, cestino);
      return voce;
    }));
  }

  function disegnaChat(): void {
    const s = app.stato;
    const id = s.aperta;
    const dati = id === null ? null : datiChat(s, id);
    invito.hidden = s.chat.length > 0 || id !== null;
    modulo.hidden = id === null;

    // errore della chat (✕) oppure errore di apertura (Riprova)
    erroreChat.replaceChildren();
    if (dati?.errore) {
      erroreChat.append(el("span", "", dati.errore),
        pulsante("chiudi", "✕", () => app.chiudiErrore(id!)));
    } else if (s.erroreApertura && id !== null) {
      erroreChat.append(el("span", "", s.erroreApertura),
        pulsante("riprova", "Riprova", () => void app.apri(id)));
    }
    erroreChat.hidden = !erroreChat.childElementCount;
    erroreChat.querySelector(".chiudi")?.setAttribute("aria-label", "Chiudi errore");

    // messaggi confermati, poi domanda in attesa e «Assistente: …»
    const elementi = (dati?.messaggi ?? []).map(fumetto);
    if (dati?.provvisoria != null) {
      elementi.push(fumetto({ ruolo: "utente", testo: dati.provvisoria, strumenti: null }));
      const attesa = el("div", "msg assistente attesa", "Assistente: ");
      attesa.append(el("span", "puntini", "…"));
      elementi.push(attesa);
    }
    messaggi.replaceChildren(...elementi);
    // in fondo solo se cambiano chat o messaggi: chi sta leggendo più in alto non viene spostato
    // da un disegno dovuto ad altro (rilettura dell'elenco, risposta di un'altra chat)
    if (id !== ultimo.aperta || elementi.length !== ultimo.elementi) {
      messaggi.scrollTop = messaggi.scrollHeight;
    }

    // campo e Invia: disattivati durante l'attesa; valore dalla bozza solo se qualcosa è cambiato
    const occupato = dati?.provvisoria != null;
    const cambiata = id !== ultimo.aperta;
    if (dati && (cambiata || dati.errore !== ultimo.errore || dati.provvisoria !== ultimo.provvisoria)) {
      campo.value = dati.bozza;
    }
    campo.disabled = occupato;
    invia.disabled = occupato || !campo.value.trim();
    // fuoco nel campo quando si cambia chat e quando finisce l'attesa della chat aperta
    // (il browser lo toglie al campo disattivato): la domanda successiva si scrive subito
    const finitaAttesa = !cambiata && ultimo.provvisoria !== null && !occupato;
    if ((cambiata || finitaAttesa) && id !== null && !occupato) campo.focus();
    ultimo = { aperta: id, errore: dati?.errore ?? null, provvisoria: dati?.provvisoria ?? null,
      elementi: elementi.length };
  }

  return { disegna: () => { disegnaBarra(); disegnaChat(); } };
}
