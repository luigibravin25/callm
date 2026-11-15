// prova reale dello streaming dal browser (step 10): bozza visibile prima della fine, riga dello
// strumento, risposta salvata dopo il ricaricamento. Servizi accesi (in Compose: E2E_URL=http://127.0.0.1:8080)
import { expect, test } from "@playwright/test";

test.skip(process.env.RUN_E2E !== "1",
  'imposta $env:RUN_E2E = "1" e avvia database, agente, back-end (STREAMING=true) e l\'interfaccia');

test("streaming dal browser con tooltime", async ({ page }, info) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  // menu ⚙: streaming acceso, log acceso per vedere strumento e bozza
  await page.click("#impostazioni");
  await expect(page.locator("#interruttore-streaming")).toBeChecked();
  await page.locator("#interruttore-log").check();
  await page.keyboard.press("Escape");
  const prima = await page.locator("#elenco-chat li").count();
  await page.click("#nuova-chat");
  await expect(page.locator("#elenco-chat li")).toHaveCount(prima + 1);
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Nuova chat");
  const id = await page.locator("#elenco-chat li.aperta").getAttribute("data-id");
  await page.fill("#campo", "Che ore sono a Tokyo?");
  await page.press("#campo", "Enter");
  // durante il turno: riga dello strumento e bozza con l'etichetta (prima della fine)
  await expect(page.locator(".stato-attesa")).toContainText("Sto usando tooltime", { timeout: 300_000 });
  await page.screenshot({ path: info.outputPath("strumento.png") });
  await expect(page.locator(".etichetta-bozza")).toBeVisible({ timeout: 300_000 });
  await page.screenshot({ path: info.outputPath("bozza.png") });
  // fine: risposta salvata con la riga dello strumento, niente più etichetta
  await expect(page.locator(".attesa")).toHaveCount(0, { timeout: 300_000 });
  await expect(page.locator("#messaggi .strumenti").last()).toContainText("tooltime");
  await page.screenshot({ path: info.outputPath("fine.png") });
  await page.reload();
  await page.locator(`#elenco-chat li[data-id='${id}'] .apri`).click();
  await expect(page.locator("#messaggi .strumenti").last()).toContainText("tooltime");
});
