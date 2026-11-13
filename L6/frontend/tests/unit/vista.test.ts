// test della vista in jsdom: testo sicuro, invito, attesa, strumenti, tasto Invio, campo conservato
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Messaggio } from "../../src/api/client";
import type { Applicazione } from "../../src/app";
import { MSG_INVITO } from "../../src/formato";
import { datiChat, statoIniziale } from "../../src/stato";
import { montaVista } from "../../src/vista";

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
    expect(radice.querySelector("#messaggi .msg.utente")!.textContent).toBe("Che ore sono a Tokyo?");
    expect(radice.querySelector(".attesa")!.textContent).toContain("Assistente:");
    // tre puntini separati: compaiono uno alla volta (ritardo dell'animazione per ciascuno)
    expect(radice.querySelectorAll(".attesa .puntino")).toHaveLength(3);
    expect(radice.querySelector<HTMLButtonElement>("#invia")!.disabled).toBe(true);
    expect(radice.querySelector<HTMLTextAreaElement>("#campo")!.disabled).toBe(true);
    expect(radice.querySelector<HTMLButtonElement>("#elenco-chat button.elimina")!.disabled).toBe(true);
  });

  test("riga strumenti sotto la risposta", () => {
    conChat([msg(1, "assistente", "Sono le 17:50.",
      [{ nome: "tooltime", argomenti: { fuso: "Asia/Tokyo" } }])]);
    montaVista(radice, app).disegna();
    expect(radice.querySelector(".msg.assistente .strumenti")!.textContent)
      .toBe("🔧 tooltime (fuso: Asia/Tokyo)");
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
