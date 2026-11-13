// vista: costruisce la pagina una volta e la aggiorna a ogni disegna(); testi sempre con textContent
import type { Messaggio } from "./api/client";
import type { Applicazione } from "./app";
import { formattaData, gruppoData, MSG_INVITO, rigaStrumenti } from "./formato";
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

// etichetta in cima a ogni fumetto: chi parla
const CHI = { utente: "Tu", assistente: "Assistente" } as const;

// avatar rotondo dell'assistente (decorativo: il nome è già scritto accanto)
function avatar(): HTMLElement {
  const a = el("div", "avatar", "A");
  a.setAttribute("aria-hidden", "true");
  return a;
}

// un messaggio. Domanda: «pillola» a destra (l'etichetta «Tu» resta per i lettori di schermo).
// Risposta: avatar + nome + testo libero + etichetta degli strumenti usati
function fumetto(m: Pick<Messaggio, "ruolo" | "testo" | "strumenti">): HTMLElement {
  const div = el("div", `msg ${m.ruolo}`);
  if (m.ruolo === "utente") {
    div.append(el("div", "chi nascosto", CHI.utente), el("div", "testo", m.testo));
    return div;
  }
  const corpo = el("div", "corpo");
  corpo.append(el("div", "chi", CHI.assistente), el("div", "testo", m.testo));
  const riga = rigaStrumenti(m.strumenti);
  if (riga) corpo.append(el("div", "strumenti", riga));
  div.append(avatar(), corpo);
  return div;
}

// «Assistente: ...» con i tre puntini, nella stessa forma di una risposta
function attesa(): HTMLElement {
  const div = el("div", "msg assistente attesa");
  const corpo = el("div", "corpo", "Assistente: ");
  // tre puntini separati: lo stile li fa comparire uno alla volta
  corpo.append(el("span", "puntino", "."), el("span", "puntino", "."), el("span", "puntino", "."));
  div.append(avatar(), corpo);
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
  // elenco: un'intestazione (Oggi, Ieri, ...) e una lista per ogni gruppo
  const elenco = el("nav");
  elenco.id = "elenco-chat";
  elenco.setAttribute("aria-label", "Chat");
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
  campo.placeholder = "Scrivi una domanda...";
  campo.setAttribute("aria-label", "Domanda");
  // pulsante rotondo con la freccia dentro il campo; il nome «Invia» per i lettori di schermo
  const invia = el("button", "", "↑");
  invia.id = "invia";
  invia.type = "submit";
  invia.setAttribute("aria-label", "Invia");
  invia.title = "Invia (Invio)";
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
    // elenco delle chat: titolo, data, 🗑; nell'ordine del back-end, diviso per gruppi di data
    const voci = s.chat.map((c) => {
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
      return { voce, gruppo: gruppoData(c.ultimo_messaggio_il) };
    });
    // un'intestazione e una lista ogni volta che il gruppo cambia (l'elenco è già ordinato per data)
    const parti: HTMLElement[] = [];
    let lista: HTMLUListElement | null = null;
    let gruppo = "";
    for (const v of voci) {
      if (!lista || v.gruppo !== gruppo) {
        gruppo = v.gruppo;
        lista = el("ul");
        parti.push(el("div", "gruppo", gruppo), lista);
      }
      lista.append(v.voce);
    }
    elenco.replaceChildren(...parti);
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
      elementi.push(fumetto({ ruolo: "utente", testo: dati.provvisoria, strumenti: null }), attesa());
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
