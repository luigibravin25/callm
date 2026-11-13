// vista: costruisce la pagina una volta e la aggiorna a ogni disegna(); testi sempre con textContent
import type { Messaggio } from "./api/client";
import type { Applicazione } from "./app";
import {
  contaParole, ETICHETTA_BOZZA, formattaData, formattaOra, gruppoData, MSG_AVVISO_REVISORE,
  MSG_INVITO, MSG_PENSA, MSG_REVISORE_CONTROLLA, MSG_STRUMENTO_IN_USO, primeParole, rigaStrumenti,
} from "./formato";
import { datiChat, inAttesa, type StatoChat } from "./stato";

// la bocca si ferma se per tanto tempo non arrivano pezzi di testo (streaming)
export const MS_SILENZIO_BOCCA = 400;

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

// rivelazione delle risposte appena arrivate: 150 ms a parola; le risposte corte rallentano per
// durare almeno 2,5 secondi (il volto «parla» abbastanza da vedersi), le lunghe accelerano per non
// superare 8 secondi in tutto
export const MS_PER_PAROLA = 150;
export const MS_MINIMI = 2500;
export const MS_MASSIMI = 8000;

// millisecondi tra una parola e la successiva per una risposta di «totale» parole
export function intervalloParole(totale: number): number {
  const n = Math.max(totale, 1);
  return Math.min(Math.max(MS_PER_PAROLA, Math.floor(MS_MINIMI / n)), Math.floor(MS_MASSIMI / n));
}

// elemento SVG (occhi e bocca del volto)
function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributi: Record<string, string>) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attributi)) e.setAttribute(k, v);
  return e;
}

// durata di un giro delle animazioni del volto (uguali a quelle di stile.css): bocca aperta e
// chiusa (0,5 s andata + 0,5 s ritorno) e battito degli occhi (4 s)
const GIRO_BOCCA_MS = 1000;
const GIRO_OCCHI_MS = 4000;

// ritardo negativo = punto del giro in cui si trova adesso l'orologio: la vista ricrea il volto a
// ogni parola (ogni 40 ms) e senza questo l'animazione ripartirebbe da capo, con la bocca ferma
function fase(giro: number): string {
  return `-${Date.now() % giro}ms`;
}

// volto dell'assistente: cerchio a sfumatura (CSS), due occhi e la bocca; con parla = true la
// bocca si apre e si chiude (CSS). Decorativo: il nome «Assistente» è nel testo nascosto
function volto(parla: boolean): HTMLElement {
  const a = el("div", parla ? "avatar volto parla" : "avatar volto");
  a.setAttribute("aria-hidden", "true");
  const disegno = svg("svg", { viewBox: "0 0 40 40" });
  const occhi = [
    svg("ellipse", { class: "occhio", cx: "14", cy: "16", rx: "2.4", ry: "3" }),
    svg("ellipse", { class: "occhio", cx: "26", cy: "16", rx: "2.4", ry: "3" }),
  ];
  const bocca = svg("ellipse", { class: "bocca", cx: "20", cy: "26", rx: "6", ry: "4" });
  for (const o of occhi) o.style.animationDelay = fase(GIRO_OCCHI_MS);
  if (parla) bocca.style.animationDelay = fase(GIRO_BOCCA_MS);
  disegno.append(...occhi, bocca);
  a.append(disegno);
  return a;
}

// come mostrare una risposta: tutte le parole oppure solo le prime (rivelazione in corso)
interface Mostra { parole: number | null }

// un messaggio. Domanda: fumetto a sfumatura a destra, senza icona («Tu» solo per i lettori di
// schermo). Risposta: volto + fumetto con testo, strumenti usati e ora
function fumetto(m: Pick<Messaggio, "ruolo" | "testo" | "strumenti"> & { creato_il?: string },
  mostra: Mostra = { parole: null }): HTMLElement {
  const div = el("div", `msg ${m.ruolo}`);
  if (m.ruolo === "utente") {
    div.append(el("div", "chi nascosto", CHI.utente), el("div", "testo", m.testo));
    return div;
  }
  const inCorso = mostra.parole !== null;
  const corpo = el("div", "corpo");
  const testo = inCorso ? primeParole(m.testo, mostra.parole!) : m.testo;
  corpo.append(el("div", "chi nascosto", CHI.assistente), el("div", "testo", testo));
  // strumenti e ora solo a risposta completa
  if (!inCorso) {
    const meta = el("div", "meta");
    const riga = rigaStrumenti(m.strumenti);
    if (riga) meta.append(el("span", "strumenti", riga));
    if (m.creato_il) meta.append(el("span", "ora", formattaOra(m.creato_il)));
    if (meta.childElementCount) corpo.append(meta);
  }
  div.append(volto(inCorso), corpo);
  return div;
}

// tre puntini che compaiono uno alla volta (CSS)
function puntini(): HTMLElement[] {
  return [el("span", "puntino", "●"), el("span", "puntino", "●"), el("span", "puntino", "●")];
}

// fumetto dell'assistente in attesa. Senza streaming: «Assistente: ...» con i puntini. Con lo
// streaming (step 10): avviso del revisore, bozza in arrivo con l'etichetta, riga di stato
// (Sto pensando / Sto usando <strumento>… / Il revisore sta controllando…); parla = bocca in moto
function attesa(dati: StatoChat, parla: boolean): HTMLElement {
  const div = el("div", "msg assistente attesa");
  const corpo = el("div", "corpo");
  // «Assistente: » per i lettori di schermo
  corpo.append(el("span", "nascosto", "Assistente: "));
  if (dati.avvisoRevisore) corpo.append(el("div", "avviso-revisore", MSG_AVVISO_REVISORE(dati.avvisoRevisore)));
  if (dati.testoInArrivo) {
    corpo.append(el("div", "etichetta-bozza", ETICHETTA_BOZZA), el("div", "testo", dati.testoInArrivo));
  }
  // riga di stato: sempre durante il revisore; altrimenti solo finché non arriva testo
  if (dati.fase === "revisore") {
    corpo.append(el("div", "stato-attesa", MSG_REVISORE_CONTROLLA));
  } else if (dati.fase === "strumento" && dati.strumentoInUso) {
    // anche se il modello ha scritto testo insieme alla chiamata («Controllo l'ora…»)
    corpo.append(el("div", "stato-attesa", MSG_STRUMENTO_IN_USO(dati.strumentoInUso)));
  } else if (!dati.testoInArrivo && dati.fase === "pensa") {
    const riga = el("div", "stato-attesa", MSG_PENSA + " ");
    riga.append(...puntini());
    corpo.append(riga);
  } else if (!dati.testoInArrivo) {
    // senza streaming: solo i puntini (comportamento dello step 8)
    corpo.append(...puntini());
  }
  div.append(volto(parla), corpo);
  return div;
}

// movimento ridotto chiesto dal sistema: risposte subito intere, niente animazione
function movimentoRidotto(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
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
  // pulsante rotondo con la freccia ➤ dentro il campo; il nome «Invia» per i lettori di schermo
  const invia = el("button", "", "➤");
  invia.id = "invia";
  invia.type = "submit";
  invia.setAttribute("aria-label", "Invia");
  invia.title = "Invia (Invio)";
  modulo.append(campo, invia);
  // interruttore «Streaming» sotto il campo, visibile solo se il back-end lo rende disponibile
  const opzioni = el("label", "opzioni");
  const casella = el("input");
  casella.type = "checkbox";
  casella.id = "interruttore-streaming";
  casella.addEventListener("change", () => app.impostaStreaming(casella.checked));
  opzioni.append(casella, document.createTextNode(" Streaming"));
  opzioni.title = "Risposta mostrata mentre il modello la scrive";
  area.append(erroreChat, invito, messaggi, modulo, opzioni);
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
    provvisoria: null as string | null, elementi: -1, arrivo: 0 };

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

  // un solo ridisegno in sospeso (per fermare la bocca dopo il silenzio)
  let ridisegnoInSospeso: ReturnType<typeof setTimeout> | null = null;
  function programmaRidisegno(ms: number): void {
    if (ridisegnoInSospeso !== null) clearTimeout(ridisegnoInSospeso);
    ridisegnoInSospeso = setTimeout(() => { ridisegnoInSospeso = null; disegna(); }, ms);
  }

  function disegnaChat(): void {
    const s = app.stato;
    opzioni.hidden = !s.streamingDisponibile || s.aperta === null;
    casella.checked = s.streamingScelto;
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
    const daRivelare = dati?.daRivelare ?? null;
    const elementi = (dati?.messaggi ?? []).map((m) => fumetto(m, mostra(m, daRivelare)));
    if (dati?.provvisoria != null) {
      // bocca in moto finché arrivano pezzi; un ridisegno la ferma dopo il silenzio
      const silenzio = Date.now() - dati.ultimoPezzo;
      const parla = dati.ultimoPezzo > 0 && silenzio < MS_SILENZIO_BOCCA;
      if (parla) programmaRidisegno(MS_SILENZIO_BOCCA - silenzio + 10);
      elementi.push(fumetto({ ruolo: "utente", testo: dati.provvisoria, strumenti: null }),
        attesa(dati, parla));
    }
    messaggi.replaceChildren(...elementi);
    // regione occupata durante l'attesa: i lettori di schermo annunciano la risposta finita, non
    // ogni pezzo del testo in arrivo
    messaggi.setAttribute("aria-busy", dati?.provvisoria != null ? "true" : "false");
    // in fondo solo se cambiano chat o messaggi, o mentre la risposta compare: chi sta leggendo più
    // in alto non viene spostato da un disegno dovuto ad altro (rilettura dell'elenco)
    const staRivelando = daRivelare !== null && inCorso.has(daRivelare);
    // streaming: il fumetto in attesa cresce senza cambiare il numero di elementi
    const arrivo = dati?.testoInArrivo.length ?? 0;
    if (id !== ultimo.aperta || elementi.length !== ultimo.elementi || staRivelando ||
        arrivo !== ultimo.arrivo) {
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
      elementi: elementi.length, arrivo };
  }

  // rivelazione parola per parola delle risposte appena arrivate (anche se si cambia chat:
  // il timer continua e tornando si vede il punto a cui è arrivata)
  const inCorso = new Map<number, number>(); // id della risposta → parole già mostrate
  const rivelate = new Set<number>();        // risposte già mostrate per intero

  // parole da mostrare per un messaggio: null = tutte
  function mostra(m: Messaggio, daRivelare: number | null): Mostra {
    if (m.ruolo !== "assistente" || m.id !== daRivelare || rivelate.has(m.id)) return { parole: null };
    if (!inCorso.has(m.id)) {
      const totale = contaParole(m.testo);
      // una parola sola o movimento ridotto: subito intera
      if (totale <= 1 || movimentoRidotto()) {
        rivelate.add(m.id);
        return { parole: null };
      }
      inCorso.set(m.id, 1);
      const timer = setInterval(() => {
        const n = inCorso.get(m.id)! + 1;
        if (n >= totale) {
          clearInterval(timer);
          inCorso.delete(m.id);
          rivelate.add(m.id);
        } else {
          inCorso.set(m.id, n);
        }
        disegna();
      }, intervalloParole(totale));
    }
    return { parole: inCorso.get(m.id)! };
  }

  function disegna(): void {
    disegnaBarra();
    disegnaChat();
  }

  return { disegna };
}
