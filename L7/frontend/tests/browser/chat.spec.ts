// prove nel browser vero (Chrome) con il back-end simulato: elenco, creazione, eliminazione,
// attesa e cambio di chat, agente e back-end spenti, tema scuro
import { expect, test } from "@playwright/test";
import { MSG_INVITO, testoConferma } from "../../src/formato";
import { chatFinta, differita, messaggio, simulaBackend, type Finto } from "./finto";

// due chat: la più recente (Tokyo) con una risposta, poi una vuota
function dueChat(): Finto {
  return {
    chat: [
      chatFinta(1, "Che ore sono a Tokyo?", [
        messaggio(1, "utente", "Che ore sono a Tokyo?"),
        messaggio(2, "assistente", "A Tokyo sono le 17:50.",
          [{ nome: "tooltime", argomenti: { fuso: "Asia/Tokyo" } }]),
      ]),
      chatFinta(2, "Fusi orari in Europa"),
    ],
    risposta: { testo: "A New York sono le 03:50.",
      strumenti: [{ nome: "tooltime", argomenti: { fuso: "America/New_York" } }] },
  };
}

test("apre la chat più recente", async ({ page }) => {
  await simulaBackend(page, dueChat());
  await page.goto("/");
  await expect(page.locator("#elenco-chat .titolo")).toHaveText(["Che ore sono a Tokyo?", "Fusi orari in Europa"]);
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Che ore sono a Tokyo?");
  await expect(page.locator("#messaggi .msg.assistente .testo")).toHaveText("A Tokyo sono le 17:50.");
  await expect(page.locator("#messaggi .strumenti")).toHaveText("🕒 tooltime");
});

test("senza chat mostra l'invito", async ({ page }) => {
  await simulaBackend(page, { chat: [] });
  await page.goto("/");
  await expect(page.locator("#invito")).toHaveText(MSG_INVITO);
});

test("nuova chat", async ({ page }) => {
  await simulaBackend(page, dueChat());
  await page.goto("/");
  await expect(page.locator("#elenco-chat li")).toHaveCount(2);
  await page.click("#nuova-chat");
  await expect(page.locator("#elenco-chat li")).toHaveCount(3);
  await expect(page.locator("#elenco-chat li").first().locator(".titolo")).toHaveText("Nuova chat");
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Nuova chat");
  await expect(page.locator("#campo")).toBeFocused();
});

test("eliminazione annullata e confermata", async ({ page }) => {
  await simulaBackend(page, dueChat());
  await page.goto("/");
  const cestino = page.getByRole("button", { name: "Elimina chat Fusi orari in Europa" });
  let testoDialogo = "";
  page.once("dialog", (d) => { testoDialogo = d.message(); void d.dismiss(); });
  await cestino.click();
  expect(testoDialogo).toBe(testoConferma("Fusi orari in Europa"));
  await expect(page.locator("#elenco-chat li")).toHaveCount(2);
  page.once("dialog", (d) => void d.accept());
  await cestino.click();
  await expect(page.locator("#elenco-chat li")).toHaveCount(1);
});

test("attesa e cambio chat", async ({ page }) => {
  const finto = dueChat();
  const d = differita();
  finto.attesaInvio = d.promessa;
  await simulaBackend(page, finto);
  await page.goto("/");
  await page.fill("#campo", "E a New York?");
  await page.press("#campo", "Enter");
  // domanda subito visibile, «Assistente: …», Invia disattivato
  await expect(page.locator("#messaggi .msg.utente .testo").last()).toHaveText("E a New York?");
  await expect(page.locator("#messaggi .msg.utente .chi").last()).toHaveText("Tu");
  await expect(page.locator(".attesa")).toContainText("Assistente:");
  await expect(page.locator("#invia")).toBeDisabled();
  await expect(page.locator("#campo")).toBeDisabled();
  // un'altra chat resta usabile durante l'attesa
  await page.click("#elenco-chat li[data-id='2'] .apri");
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Fusi orari in Europa");
  await expect(page.locator("#campo")).toBeEnabled();
  await expect(page.locator("#elenco-chat li[data-id='1']")).toHaveClass(/in-attesa/);
  // la risposta arriva mentre si guarda l'altra chat; tornando si vede
  d.risolvi();
  await expect(page.locator("#elenco-chat li[data-id='1']")).not.toHaveClass(/in-attesa/);
  await page.click("#elenco-chat li[data-id='1'] .apri");
  await expect(page.locator("#messaggi .msg.assistente .testo").last()).toHaveText("A New York sono le 03:50.");
  await expect(page.locator("#messaggi .strumenti").last()).toHaveText("🕒 tooltime");
  await expect(page.locator(".attesa")).toHaveCount(0);
});

test("agente spento", async ({ page }) => {
  const finto = dueChat();
  finto.erroreInvio = { status: 503,
    corpo: { errore: "agente_non_raggiungibile", messaggio: "L'agente non è raggiungibile." } };
  await simulaBackend(page, finto);
  await page.goto("/");
  await page.fill("#campo", "E a New York?");
  await page.click("#invia");
  await expect(page.locator("#errore-chat")).toContainText("L'agente non è raggiungibile.");
  await expect(page.locator("#campo")).toHaveValue("E a New York?");
  await expect(page.locator("#campo")).toBeEnabled();
  await expect(page.locator(".attesa")).toHaveCount(0);
  // l'interfaccia resta usabile
  await page.click("#nuova-chat");
  await expect(page.locator("#elenco-chat li")).toHaveCount(3);
  await page.click("#elenco-chat li[data-id='1'] .apri");
  await expect(page.locator("#errore-chat")).toContainText("L'agente non è raggiungibile.");
  await expect(page.locator("#campo")).toHaveValue("E a New York?");
});

test("back-end spento", async ({ page }) => {
  const finto = dueChat();
  finto.erroreElenco = { status: 502, corpo: "" };
  await simulaBackend(page, finto);
  await page.goto("/");
  await expect(page.locator("#errore-barra")).toContainText("Il back-end non risponde (HTTP 502)");
  delete finto.erroreElenco;
  await page.click("#errore-barra .riprova");
  await expect(page.locator("#elenco-chat li")).toHaveCount(2);
  await expect(page.locator("#errore-barra")).toBeHidden();
});

// nessuna simulazione: il proxy vero di Vite punta a una porta chiusa (BACKEND_URL della configurazione)
test("proxy di Vite con back-end spento", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#errore-barra")).toContainText(/Il back-end non risponde \(HTTP \d+\)/);
  await expect(page.locator("#nuova-chat")).toBeEnabled();
});

test.describe("tema", () => {
  test.use({ colorScheme: "light" });

  test("tema scuro anche con sistema chiaro", async ({ page }) => {
    await simulaBackend(page, { chat: [] });
    await page.goto("/");
    const sfondo = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(sfondo).toBe("rgb(15, 17, 21)");
  });
});

// ---------- step 10: streaming (stream simulato in un solo corpo SSE) ----------
test.describe("streaming", () => {
  test("stream con strumento: risposta e riga dello strumento", async ({ page }) => {
    const finto = dueChat();
    finto.streaming = true;
    finto.eventi = [["fase", { fase: "pensa" }], ["bozza", {}],
      ["strumento", { nome: "tooltime", argomenti: { fuso: "America/New_York" } }], ["bozza", {}],
      ["testo", { testo: "A New York " }], ["testo", { testo: "sono le 03:50." }],
      ["fase", { fase: "revisore" }]];
    await simulaBackend(page, finto);
    await page.goto("/");
    // interruttori nel menu ⚙: Streaming acceso di base, Log acceso per vedere i dettagli
    await expect(page.locator("#menu-impostazioni")).toBeHidden();
    await page.click("#impostazioni");
    await expect(page.locator("#interruttore-streaming")).toBeChecked();
    await expect(page.locator("#interruttore-log")).toBeChecked();
    await page.fill("#campo", "E a New York?");
    await page.press("#campo", "Enter");
    await expect(page.locator("#messaggi .msg.assistente .testo").last()).toHaveText("A New York sono le 03:50.");
    await expect(page.locator("#messaggi .strumenti").last()).toHaveText("🕒 tooltime");
    await expect(page.locator(".etichetta-bozza")).toHaveCount(0);
  });

  test("stream con revisione: avviso sparito a fine", async ({ page }) => {
    const finto = dueChat();
    finto.streaming = true;
    finto.eventi = [["bozza", {}], ["testo", { testo: "Bozza." }], ["fase", { fase: "revisore" }],
      ["revisione", { motivo: "manca l'ora" }], ["bozza", {}], ["testo", { testo: "Completa." }]];
    const d = differita();
    finto.attesaInvio = d.promessa;
    await simulaBackend(page, finto);
    await page.goto("/");
    await page.click("#impostazioni");
    await page.locator("#interruttore-log").check();
    await page.keyboard.press("Escape");
    await page.fill("#campo", "E a New York?");
    await page.press("#campo", "Enter");
    await expect(page.locator(".stato-attesa")).toContainText("Sto pensando");
    d.risolvi();
    await expect(page.locator("#messaggi .msg.assistente .testo").last()).toHaveText("A New York sono le 03:50.");
    await expect(page.locator(".avviso-revisore")).toHaveCount(0);
  });

  test("errore a metà: riquadro e domanda nel campo", async ({ page }) => {
    const finto = dueChat();
    finto.streaming = true;
    finto.eventi = [["bozza", {}], ["testo", { testo: "A met" }]];
    finto.erroreFlusso = { errore: "modello_non_raggiungibile", messaggio: "LM Studio non risponde." };
    await simulaBackend(page, finto);
    await page.goto("/");
    await page.fill("#campo", "E a New York?");
    await page.press("#campo", "Enter");
    await expect(page.locator("#errore-chat")).toContainText("LM Studio non risponde.");
    await expect(page.locator("#campo")).toHaveValue("E a New York?");
    await expect(page.locator(".attesa")).toHaveCount(0);
  });

  test("interruttore spento usa l'invio di oggi", async ({ page }) => {
    const finto = dueChat();
    finto.streaming = true;
    await simulaBackend(page, finto);
    let stream = 0;
    page.on("request", (r) => { if (r.url().endsWith("/messaggi/stream")) stream++; });
    await page.goto("/");
    await page.click("#impostazioni");
    await page.locator("#interruttore-streaming").uncheck();
    await page.fill("#campo", "E a New York?");
    await page.press("#campo", "Enter");
    await expect(page.locator("#messaggi .msg.assistente .testo").last()).toHaveText("A New York sono le 03:50.");
    expect(stream).toBe(0);
  });

  test("interruttore assente senza streaming", async ({ page }) => {
    await simulaBackend(page, dueChat());
    await page.goto("/");
    await expect(page.locator("#messaggi .msg.assistente")).toHaveCount(1);
    await expect(page.locator("#interruttore-streaming")).toBeHidden();
  });
});


test("log spento: solo i tre puntini durante l'attesa", async ({ page }) => {
  const finto = dueChat();
  finto.streaming = true;
  finto.eventi = [["fase", { fase: "pensa" }], ["strumento", { nome: "tooltime", argomenti: {} }]];
  const d = differita();
  finto.attesaInvio = d.promessa;
  await simulaBackend(page, finto);
  await page.goto("/");
  // il Log è acceso di base: lo si spegne dal menu
  await page.click("#impostazioni");
  await page.locator("#interruttore-log").uncheck();
  await page.keyboard.press("Escape");
  await page.fill("#campo", "E a New York?");
  await page.press("#campo", "Enter");
  await expect(page.locator(".attesa .puntino")).toHaveCount(3);
  await expect(page.locator(".stato-attesa")).toHaveCount(0);
  d.risolvi();
  await expect(page.locator("#messaggi .strumenti").last()).toHaveText("🕒 tooltime");
});


test.describe("impaginazione", () => {
  // molti messaggi: scorre solo l'area dei messaggi, la pagina resta ferma
  function chatLunga(): Finto {
    const messaggi = [];
    for (let i = 0; i < 30; i++) {
      messaggi.push(messaggio(100 + 2 * i, "utente", `Domanda ${i}`),
        messaggio(101 + 2 * i, "assistente", `Risposta ${i}\nseconda riga\nterza riga`));
    }
    return { chat: [chatFinta(1, "Chat lunga", messaggi), chatFinta(2, "Altra")] };
  }

  test("la pagina non scorre, scorre solo l'area dei messaggi", async ({ page }) => {
    await simulaBackend(page, chatLunga());
    await page.goto("/");
    await expect(page.locator("#messaggi .msg")).toHaveCount(60);
    const pagina = await page.evaluate(() => ({
      alta: document.documentElement.scrollHeight, finestra: window.innerHeight }));
    expect(pagina.alta).toBeLessThanOrEqual(pagina.finestra);
    const area = await page.locator("#messaggi").evaluate((e) => e.scrollHeight > e.clientHeight);
    expect(area).toBe(true);
  });

  test("barra laterale sempre a sinistra quando la finestra si stringe", async ({ page }) => {
    await simulaBackend(page, chatLunga());
    for (const larghezza of [1280, 900, 600]) {
      await page.setViewportSize({ width: larghezza, height: 700 });
      await page.goto("/");
      const barra = (await page.locator(".barra").boundingBox())!;
      const area = (await page.locator(".area").boundingBox())!;
      // barra a sinistra, alta quanto la finestra, area a destra
      expect(barra.x).toBe(0);
      expect(barra.height).toBe(700);
      expect(area.x).toBeGreaterThanOrEqual(barra.width - 1);
      expect(area.y).toBe(0);
    }
  });
});


test("log acceso di base: riga dello strumento senza aprire il menu", async ({ page }) => {
  const finto = dueChat();
  finto.streaming = true;
  finto.eventi = [["fase", { fase: "pensa" }], ["strumento", { nome: "tooltime", argomenti: {} }]];
  const d = differita();
  finto.attesaInvio = d.promessa;
  await simulaBackend(page, finto);
  await page.goto("/");
  await page.fill("#campo", "E a New York?");
  await page.press("#campo", "Enter");
  await expect(page.locator(".stato-attesa")).toContainText("Sto pensando");
  d.risolvi();
  await expect(page.locator("#messaggi .strumenti").last()).toHaveText("🕒 tooltime");
});
