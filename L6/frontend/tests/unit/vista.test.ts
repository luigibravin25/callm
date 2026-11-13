// test della vista in jsdom: testo sicuro, invito, attesa, strumenti, tasto Invio, campo conservato
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Messaggio } from "../../src/api/client";
import type { Applicazione } from "../../src/app";
import { MSG_INVITO } from "../../src/formato";
import { datiChat, statoIniziale } from "../../src/stato";
import { intervalloParole, montaVista } from "../../src/vista";

const msg = (id: number, ruolo: "utente" | "assistente", testo: string,
  strumenti: Messaggio["strumenti"] = null): Messaggio =>
  ({ id, ruolo, testo, strumenti, creato_il: "2026-11-13T08:00:00Z" });

// applicazione finta: stato preparato dal test, azioni spiate
function appFinta(): Applicazione {
  return {
    stato: statoIniziale(),
    avvia: vi.fn(async () => {}),
    nuovaChat: vi.fn(async () => {}),
    apri: vi.fn(async () => {}),
    elimina: vi.fn(async () => {}),
    invia: vi.fn(async () => {}),
    aggiornaBozza: vi.fn(),
    chiudiErrore: vi.fn(),
    riprovaElenco: vi.fn(async () => {}),
    impostaStreaming: vi.fn(),
    impostaLog: vi.fn(),
  };
}

let radice: HTMLElement;
let app: Applicazione;

beforeEach(() => {
  document.body.innerHTML = "";
  radice = document.createElement("div");
  document.body.append(radice);
  app = appFinta();
});

// una chat aperta con i messaggi dati
function conChat(messaggi: Messaggio[], titolo = "Chat 1") {
  app.stato.chat = [{ id: 1, titolo, ultimo_messaggio_il: null }];
  app.stato.aperta = 1;
  const d = datiChat(app.stato, 1);
  d.messaggi = messaggi;
  d.caricata = true;
  return d;
}

describe("vista", () => {
  test("testo con <script> mostrato come testo", () => {
    conChat([msg(1, "assistente", "<script>alert(1)</script>")], "<b>x</b>");
    montaVista(radice, app).disegna();
    expect(radice.querySelector("#messaggi .msg.assistente")!.textContent)
      .toContain("<script>alert(1)</script>");
    expect(radice.querySelector("#messaggi script")).toBeNull();
    expect(radice.querySelector("#elenco-chat .titolo")!.textContent).toBe("<b>x</b>");
    expect(radice.querySelector("#elenco-chat b")).toBeNull();
  });

  test("senza chat mostra l'invito", () => {
    montaVista(radice, app).disegna();
    const invito = radice.querySelector<HTMLElement>("#invito")!;
    expect(invito.hidden).toBe(false);
    expect(invito.textContent).toBe(MSG_INVITO);
  });

  test("attesa mostra Assistente: … e disattiva invio e campo", () => {
    const d = conChat([]);
    d.provvisoria = "Che ore sono a Tokyo?";
    montaVista(radice, app).disegna();
    expect(radice.querySelector("#messaggi .msg.utente .testo")!.textContent).toBe("Che ore sono a Tokyo?");
    expect(radice.querySelector(".attesa")!.textContent).toContain("Assistente:");
    // tre puntini separati: compaiono uno alla volta (ritardo dell'animazione per ciascuno)
    const puntini = [...radice.querySelectorAll(".attesa .puntino")].map((p) => p.textContent);
    // pallini pieni come nella bozza del design B (non punti tipografici)
    expect(puntini).toEqual(["●", "●", "●"]);
    expect(radice.querySelector<HTMLButtonElement>("#invia")!.disabled).toBe(true);
    expect(radice.querySelector<HTMLTextAreaElement>("#campo")!.disabled).toBe(true);
    expect(radice.querySelector<HTMLButtonElement>("#elenco-chat button.elimina")!.disabled).toBe(true);
  });

  test("segnaposto breve nel campo", () => {
    conChat([]);
    montaVista(radice, app).disegna();
    expect(radice.querySelector<HTMLTextAreaElement>("#campo")!.placeholder).toBe("Scrivi una domanda...");
  });

  test("ogni fumetto dice chi parla", () => {
    conChat([msg(1, "utente", "Che ore sono?"), msg(2, "assistente", "Le 9.")]);
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".msg.utente .chi")!.textContent).toBe("Tu");
    expect(radice.querySelector(".msg.assistente .chi")!.textContent).toBe("Assistente");
    // il testo del messaggio resta separato dall'etichetta
    expect(radice.querySelector(".msg.utente .testo")!.textContent).toBe("Che ore sono?");
  });

  test("elenco raggruppato per data con intestazioni", () => {
    const oggi = new Date().toISOString();
    app.stato.chat = [
      { id: 1, titolo: "Nuova", ultimo_messaggio_il: oggi },
      { id: 2, titolo: "Vecchia", ultimo_messaggio_il: "2020-01-01T08:00:00Z" },
    ];
    montaVista(radice, app).disegna();
    expect([...radice.querySelectorAll("#elenco-chat .gruppo")].map((g) => g.textContent))
      .toEqual(["Oggi", "Più vecchie"]);
    // le intestazioni non sono voci dell'elenco: le chat restano 2
    expect(radice.querySelectorAll("#elenco-chat li")).toHaveLength(2);
  });

  test("risposta con il volto, domanda senza icona", () => {
    conChat([msg(1, "utente", "Che ore sono?"), msg(2, "assistente", "Le 9.")]);
    montaVista(radice, app).disegna();
    // volto disegnato con la bocca, ferma sulle risposte già lette
    expect(radice.querySelector(".msg.assistente .avatar.volto svg .bocca")).not.toBeNull();
    expect(radice.querySelector(".msg.assistente .volto.parla")).toBeNull();
    expect(radice.querySelector(".msg.utente .avatar")).toBeNull();
    // ora del messaggio accanto agli strumenti
    expect(radice.querySelector(".msg.assistente .ora")!.textContent)
      .toMatch(/^\d{2}:\d{2}$/);
    // Invia è un pulsante con icona e nome accessibile
    expect(radice.querySelector("#invia")!.getAttribute("aria-label")).toBe("Invia");
  });

  test("risposta appena arrivata: parola per parola con la bocca che si muove", () => {
    vi.useFakeTimers();
    try {
      const d = conChat([msg(1, "utente", "Che ore sono?"),
        msg(2, "assistente", "A Tokyo sono le 17:37.", [{ nome: "tooltime", argomenti: { fuso: "Asia/Tokyo" } }])]);
      d.daRivelare = 2;
      montaVista(radice, app).disegna();
      const testo = () => radice.querySelector(".msg.assistente .testo")!.textContent;
      // all'inizio la prima parola, bocca in movimento, strumenti non ancora mostrati
      expect(testo()).toBe("A");
      expect(radice.querySelector(".msg.assistente .volto.parla")).not.toBeNull();
      expect(radice.querySelector(".msg.assistente .strumenti")).toBeNull();
      vi.advanceTimersByTime(500 * 2);
      expect(testo()).toBe("A Tokyo sono");
      vi.advanceTimersByTime(500 * 10);
      // finita: testo intero, bocca ferma, riga degli strumenti
      expect(testo()).toBe("A Tokyo sono le 17:37.");
      expect(radice.querySelector(".msg.assistente .volto.parla")).toBeNull();
      expect(radice.querySelector(".msg.assistente .strumenti")!.textContent)
        .toBe("🕒 tooltime");
    } finally {
      vi.useRealTimers();
    }
  });

  test("animazioni del volto agganciate all'orologio: non ripartono quando la vista ridisegna", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(10_500);
      const d = conChat([msg(2, "assistente", "una due tre")]);
      d.daRivelare = 2;
      montaVista(radice, app).disegna();
      // fase = istante attuale nel giro (bocca 1 s andata e ritorno, battito 4 s)
      const bocca = radice.querySelector<SVGElement>(".volto.parla .bocca")!;
      expect(bocca.style.animationDelay).toBe(`-${10_500 % 1000}ms`);
      const occhio = radice.querySelector<SVGElement>(".volto .occhio")!;
      expect(occhio.style.animationDelay).toBe(`-${10_500 % 4000}ms`);
    } finally {
      vi.useRealTimers();
    }
  });

  test("almeno 2,5 secondi di parlato, 150 ms a parola, al massimo 8 secondi in tutto", () => {
    expect(intervalloParole(2)).toBe(1250);
    expect(intervalloParole(10)).toBe(250);
    expect(intervalloParole(20)).toBe(150);
    expect(intervalloParole(53)).toBe(150);
    expect(intervalloParole(200)).toBe(40);
  });

  test("una risposta già rivelata non riparte a un nuovo disegno", () => {
    vi.useFakeTimers();
    try {
      const d = conChat([msg(2, "assistente", "uno due")]);
      d.daRivelare = 2;
      const vista = montaVista(radice, app);
      vista.disegna();
      vi.advanceTimersByTime(8000);
      vista.disegna();
      expect(radice.querySelector(".msg.assistente .testo")!.textContent).toBe("uno due");
      expect(radice.querySelector(".volto.parla")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  test("a capo e spazi della risposta conservati durante la rivelazione", () => {
    vi.useFakeTimers();
    try {
      const d = conChat([msg(2, "assistente", "riga uno\n\nriga  due")]);
      d.daRivelare = 2;
      montaVista(radice, app).disegna();
      vi.advanceTimersByTime(8000);
      expect(radice.querySelector(".msg.assistente .testo")!.textContent).toBe("riga uno\n\nriga  due");
    } finally {
      vi.useRealTimers();
    }
  });

  test("riga strumenti sotto la risposta", () => {
    conChat([msg(1, "assistente", "Sono le 17:50.",
      [{ nome: "tooltime", argomenti: { fuso: "Asia/Tokyo" } }])]);
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".msg.assistente .strumenti")!.textContent)
      .toBe("🕒 tooltime");
  });

  test("Enter invia, Shift+Enter no", () => {
    const d = conChat([]);
    d.bozza = "ciao";
    montaVista(radice, app).disegna();
    const campo = radice.querySelector<HTMLTextAreaElement>("#campo")!;
    campo.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }));
    campo.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(app.invia).toHaveBeenCalledTimes(1);
    expect(app.invia).toHaveBeenCalledWith(1);
  });

  test("il campo conserva il valore tra due disegna()", () => {
    conChat([]);
    const vista = montaVista(radice, app);
    vista.disegna();
    const campo = radice.querySelector<HTMLTextAreaElement>("#campo")!;
    campo.value = "sto scrivendo";
    vista.disegna();
    expect(radice.querySelector("#campo")).toBe(campo);
    expect(campo.value).toBe("sto scrivendo");
  });

  test("errore della chat con ✕ e domanda rimessa nel campo", () => {
    const d = conChat([]);
    const vista = montaVista(radice, app);
    vista.disegna();
    d.errore = "Agente non raggiungibile";
    d.bozza = "Che ore sono a Tokyo?";
    vista.disegna();
    const errore = radice.querySelector<HTMLElement>("#errore-chat")!;
    expect(errore.hidden).toBe(false);
    expect(errore.textContent).toContain("Agente non raggiungibile");
    expect(radice.querySelector<HTMLTextAreaElement>("#campo")!.value).toBe("Che ore sono a Tokyo?");
    errore.querySelector<HTMLButtonElement>("button.chiudi")!.click();
    expect(app.chiudiErrore).toHaveBeenCalledWith(1);
  });

  test("il fuoco torna nel campo quando arriva la risposta", () => {
    const d = conChat([]);
    const vista = montaVista(radice, app);
    vista.disegna();
    const campo = radice.querySelector<HTMLTextAreaElement>("#campo")!;
    // il browser toglie il fuoco a un campo disattivato (jsdom no: blur() prima di disattivarlo)
    campo.blur();
    d.provvisoria = "Che ore sono?";
    vista.disegna();
    d.provvisoria = null;
    d.messaggi = [msg(1, "utente", "Che ore sono?"), msg(2, "assistente", "Le 9.")];
    vista.disegna();
    expect(document.activeElement).toBe(campo);
  });

  test("lo scorrimento in fondo solo quando cambiano i messaggi", () => {
    conChat([msg(1, "utente", "a")]);
    const vista = montaVista(radice, app);
    const messaggi = radice.querySelector<HTMLElement>("#messaggi")!;
    let scorrimenti = 0;
    Object.defineProperty(messaggi, "scrollTop", { set: () => { scorrimenti++; }, get: () => 0 });
    vista.disegna();
    // nuovo disegno senza messaggi nuovi (per esempio rilettura dell'elenco): niente salto in fondo
    vista.disegna();
    expect(scorrimenti).toBe(1);
    datiChat(app.stato, 1).messaggi.push(msg(2, "assistente", "b"));
    vista.disegna();
    expect(scorrimenti).toBe(2);
  });

  test("errore su un'altra chat non tocca il campo della chat aperta", () => {
    app.stato.chat = [{ id: 1, titolo: "A", ultimo_messaggio_il: null },
      { id: 2, titolo: "B", ultimo_messaggio_il: null }];
    app.stato.aperta = 2;
    const vista = montaVista(radice, app);
    vista.disegna();
    const campo = radice.querySelector<HTMLTextAreaElement>("#campo")!;
    campo.value = "sto scrivendo in B";
    const a = datiChat(app.stato, 1);
    a.errore = "Agente non raggiungibile";
    a.bozza = "domanda di A";
    vista.disegna();
    expect(campo.value).toBe("sto scrivendo in B");
    expect(radice.querySelector<HTMLElement>("#errore-chat")!.hidden).toBe(true);
  });

  test("errore della barra con Riprova solo per l'elenco", () => {
    app.stato.erroreBarra = { messaggio: "Il back-end non risponde (HTTP 502)", riprova: true };
    montaVista(radice, app).disegna();
    const barra = radice.querySelector<HTMLElement>("#errore-barra")!;
    expect(barra.textContent).toContain("HTTP 502");
    barra.querySelector<HTMLButtonElement>("button.riprova")!.click();
    expect(app.riprovaElenco).toHaveBeenCalled();
  });
});

// ---------- step 10: streaming nella vista ----------
describe("streaming", () => {
  // chat 1 aperta e in attesa, con lo stato dello streaming dato
  function inAttesa(campi: Partial<ReturnType<typeof datiChat>>) {
    const d = conChat([]);
    Object.assign(d, { provvisoria: "Che ore sono?" }, campi);
    app.stato.logVisibile = true;
    return d;
  }

  test("riga Sto pensando", () => {
    inAttesa({ fase: "pensa" });
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".stato-attesa")!.textContent).toContain("Sto pensando");
  });

  test("riga dello strumento con la sua icona", () => {
    inAttesa({ fase: "strumento", strumentoInUso: "tooltime" });
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".stato-attesa")!.textContent).toBe("🕒 Sto usando tooltime…");
  });

  test("bozza con l'etichetta e avviso del revisore", () => {
    inAttesa({ fase: "pensa", testoInArrivo: "A Tokyo sono", avvisoRevisore: "manca l'ora di Roma" });
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".attesa .testo")!.textContent).toBe("A Tokyo sono");
    expect(radice.querySelector(".etichetta-bozza")!.textContent).toBe("bozza, in revisione");
    expect(radice.querySelector(".avviso-revisore")!.textContent)
      .toBe("Il revisore ha chiesto una correzione: manca l'ora di Roma");
    // con il testo in arrivo niente «Sto pensando»
    expect(radice.querySelector(".stato-attesa")).toBeNull();
  });

  test("Il revisore sta controllando", () => {
    inAttesa({ fase: "revisore", testoInArrivo: "A Tokyo sono le 20." });
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".stato-attesa")!.textContent).toBe("Il revisore sta controllando…");
    expect(radice.querySelector(".etichetta-bozza")).not.toBeNull();
  });

  test("bocca che parla mentre arriva il testo, ferma dopo 400 ms", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(10_000);
      inAttesa({ fase: "pensa", testoInArrivo: "Sono", ultimoPezzo: 10_000 });
      montaVista(radice, app).disegna();
      expect(radice.querySelector(".attesa .volto.parla")).not.toBeNull();
      // nessun pezzo nuovo: la vista si ridisegna da sola e la bocca si ferma
      vi.advanceTimersByTime(450);
      expect(radice.querySelector(".attesa .volto.parla")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  test("interruttore assente se lo streaming non è disponibile", () => {
    conChat([]);
    app.stato.streamingDisponibile = false;
    montaVista(radice, app).disegna();
    expect(radice.querySelector<HTMLElement>("#interruttore-streaming")?.closest("label")?.hidden ?? true).toBe(true);
  });

  test("interruttore presente e collegato", () => {
    conChat([]);
    app.stato.streamingDisponibile = true;
    app.stato.streamingScelto = true;
    montaVista(radice, app).disegna();
    const casella = radice.querySelector<HTMLInputElement>("#interruttore-streaming")!;
    expect(casella.closest("label")!.hidden).toBe(false);
    expect(casella.closest("label")!.textContent).toContain("Streaming");
    expect(casella.getAttribute("role")).toBe("switch");
    expect(casella.checked).toBe(true);
    casella.click();
    expect(app.impostaStreaming).toHaveBeenCalledWith(false);
  });
});

describe("streaming: correzioni della revisione", () => {
  test("la vista segue il testo in arrivo", () => {
    const d = conChat([]);
    d.provvisoria = "x";
    d.fase = "pensa";
    const vista = montaVista(radice, app);
    const messaggi = radice.querySelector<HTMLElement>("#messaggi")!;
    let scorrimenti = 0;
    Object.defineProperty(messaggi, "scrollTop", { set: () => { scorrimenti++; }, get: () => 0 });
    vista.disegna();
    const dopoIlPrimo = scorrimenti;
    d.testoInArrivo = "A Tokyo";
    vista.disegna();
    d.testoInArrivo = "A Tokyo sono le 20.";
    vista.disegna();
    expect(scorrimenti).toBe(dopoIlPrimo + 2);
  });

  test("riga dello strumento anche con testo scritto insieme alla chiamata", () => {
    const d = conChat([]);
    Object.assign(d, { provvisoria: "x", fase: "strumento", strumentoInUso: "tooltime",
      testoInArrivo: "Controllo l'ora…" });
    app.stato.logVisibile = true;
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".stato-attesa")!.textContent).toBe("🕒 Sto usando tooltime…");
  });
});


test("area dei messaggi occupata durante l'attesa (lettori di schermo)", () => {
  const d = conChat([]);
  const vista = montaVista(radice, app);
  vista.disegna();
  const messaggi = radice.querySelector("#messaggi")!;
  expect(messaggi.getAttribute("aria-busy")).toBe("false");
  d.provvisoria = "x";
  vista.disegna();
  expect(messaggi.getAttribute("aria-busy")).toBe("true");
});


describe("menu delle impostazioni e log", () => {
  test("con il log spento solo i tre puntini, poi il testo senza etichetta", () => {
    const d = conChat([]);
    Object.assign(d, { provvisoria: "x", fase: "strumento", strumentoInUso: "tooltime",
      avvisoRevisore: "manca", testoInArrivo: "" });
    app.stato.logVisibile = false;
    const vista = montaVista(radice, app);
    vista.disegna();
    expect(radice.querySelectorAll(".attesa .puntino")).toHaveLength(3);
    expect(radice.querySelector(".stato-attesa")).toBeNull();
    expect(radice.querySelector(".avviso-revisore")).toBeNull();
    d.testoInArrivo = "A Tokyo";
    vista.disegna();
    expect(radice.querySelector(".attesa .testo")!.textContent).toBe("A Tokyo");
    expect(radice.querySelector(".etichetta-bozza")).toBeNull();
    expect(radice.querySelector(".stato-attesa")).toBeNull();
  });

  test("menu nascosto, si apre con il pulsante ⚙ e si chiude con Esc", () => {
    conChat([]);
    montaVista(radice, app).disegna();
    const pulsante = radice.querySelector<HTMLButtonElement>("#impostazioni")!;
    const menu = radice.querySelector<HTMLElement>("#menu-impostazioni")!;
    expect(pulsante.getAttribute("aria-label")).toBe("Impostazioni");
    expect(menu.hidden).toBe(true);
    pulsante.click();
    expect(menu.hidden).toBe(false);
    expect(pulsante.getAttribute("aria-expanded")).toBe("true");
    menu.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(menu.hidden).toBe(true);
  });

  test("interruttore Log nel menu collegato", () => {
    conChat([]);
    app.stato.logVisibile = false;
    montaVista(radice, app).disegna();
    const log = radice.querySelector<HTMLInputElement>("#menu-impostazioni #interruttore-log")!;
    expect(log.getAttribute("role")).toBe("switch");
    expect(log.closest("label")!.textContent).toContain("Log");
    expect(log.checked).toBe(false);
    log.click();
    expect(app.impostaLog).toHaveBeenCalledWith(true);
  });
});

test("menu: Esc anche dal pulsante ⚙ e clic fuori lo chiudono", () => {
  conChat([]);
  montaVista(radice, app).disegna();
  const pulsante = radice.querySelector<HTMLButtonElement>("#impostazioni")!;
  const menu = radice.querySelector<HTMLElement>("#menu-impostazioni")!;
  pulsante.click();
  pulsante.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  expect(menu.hidden).toBe(true);
  pulsante.click();
  expect(menu.hidden).toBe(false);
  // clic dentro il menu: resta aperto; clic fuori: si chiude
  menu.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  expect(menu.hidden).toBe(false);
  radice.querySelector<HTMLElement>("#messaggi")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  expect(menu.hidden).toBe(true);
});
