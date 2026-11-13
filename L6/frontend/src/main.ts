// avvio dell'interfaccia: client dell'API (/api tramite proxy), stato, vista
import "./stile.css";
import { creaApi } from "./api/client";
import { creaApplicazione } from "./app";
import { montaVista } from "./vista";

const radice = document.getElementById("app")!;
// la vista si crea dopo l'applicazione: ridisegna la richiama solo quando esiste
let vista: { disegna(): void } | null = null;
const app = creaApplicazione(creaApi(), (testo) => window.confirm(testo), () => vista?.disegna());
vista = montaVista(radice, app);
vista.disegna();
// elenco delle chat e apertura della più recente
void app.avvia();
