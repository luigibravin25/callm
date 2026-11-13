// test delle funzioni pure di formato: date, strumenti usati, messaggi fissi
import { describe, expect, test } from "vitest";
import {
  formattaData,
  formattaOra,
  gruppoData,
  MSG_BACKEND_GIU,
  MSG_CHAT_SPARITA,
  MSG_INVITO,
  MSG_NESSUN_MESSAGGIO,
  MSG_RETE,
  rigaStrumenti,
  testoConferma,
} from "../../src/formato";

describe("formattaData", () => {
  // data costruita in ora locale: il test vale con qualsiasi fuso del computer
  test("giorno/mese ore:minuti nell'ora locale", () => {
    expect(formattaData(new Date(2026, 10, 13, 8, 5).toISOString())).toBe("13/11 08:05");
  });

  test("null o assente: nessun messaggio", () => {
    expect(formattaData(null)).toBe("nessun messaggio");
    expect(formattaData(undefined)).toBe(MSG_NESSUN_MESSAGGIO);
  });
});

describe("formattaOra", () => {
  test("ore:minuti nell'ora locale", () => {
    expect(formattaOra(new Date(2026, 10, 13, 9, 7).toISOString())).toBe("09:07");
  });
});

describe("gruppoData", () => {
  // «adesso» fisso: 13/11/2026 alle 10:00 in ora locale
  const adesso = new Date(2026, 10, 13, 10, 0);
  const iso = (g: number, h = 9) => new Date(2026, 10, g, h, 0).toISOString();

  test("oggi, ieri, ultimi 7 giorni, più vecchie", () => {
    expect(gruppoData(iso(13, 0), adesso)).toBe("Oggi");
    expect(gruppoData(iso(12, 23), adesso)).toBe("Ieri");
    expect(gruppoData(iso(7), adesso)).toBe("Ultimi 7 giorni");
    expect(gruppoData(iso(5), adesso)).toBe("Più vecchie");
  });

  test("chat senza messaggi (appena creata) tra quelle di oggi", () => {
    expect(gruppoData(null, adesso)).toBe("Oggi");
  });
});

describe("rigaStrumenti", () => {
  test("null o lista vuota: nessuna riga", () => {
    expect(rigaStrumenti(null)).toBeNull();
    expect(rigaStrumenti([])).toBeNull();
  });

  test("uno strumento con un argomento", () => {
    expect(rigaStrumenti([{ nome: "tooltime", argomenti: { fuso: "Asia/Tokyo" } }]))
      .toBe("🔧 tooltime (fuso: Asia/Tokyo)");
  });

  test("due strumenti separati da ·", () => {
    expect(rigaStrumenti([
      { nome: "tooltime", argomenti: { fuso: "Asia/Tokyo" } },
      { nome: "tooltime", argomenti: { fuso: "America/New_York" } },
    ])).toBe("🔧 tooltime (fuso: Asia/Tokyo) · tooltime (fuso: America/New_York)");
  });

  test("senza argomenti solo il nome", () => {
    expect(rigaStrumenti([{ nome: "tooltime", argomenti: {} }])).toBe("🔧 tooltime");
    expect(rigaStrumenti([{ nome: "tooltime" }])).toBe("🔧 tooltime");
  });

  test("argomenti non stringa in JSON, più argomenti separati da virgola", () => {
    expect(rigaStrumenti([{ nome: "conta", argomenti: { n: 2, unita: "ore" } }]))
      .toBe("🔧 conta (n: 2, unita: ore)");
  });

  test("voci malformate ignorate", () => {
    expect(rigaStrumenti([{}, "x", { nome: 3 }, { nome: "tooltime" }])).toBe("🔧 tooltime");
    expect(rigaStrumenti([{}, "x", { nome: 3 }])).toBeNull();
    expect(rigaStrumenti("non una lista")).toBeNull();
  });
});

describe("messaggi fissi", () => {
  test("testi esatti della spec", () => {
    expect(testoConferma("Tokyo"))
      .toBe("Eliminare la chat «Tokyo»? L'operazione non si può annullare.");
    expect(MSG_BACKEND_GIU(502))
      .toBe("Il back-end non risponde (HTTP 502): controlla che sia avviato.");
    expect(MSG_RETE).toBe(
      "Impossibile contattare il server dell'interfaccia: controlla la connessione e ricarica la pagina.");
    expect(MSG_CHAT_SPARITA).toBe("La chat non esiste più.");
    expect(MSG_INVITO).toBe("Nessuna chat: crea la prima con + Nuova chat");
  });
});
