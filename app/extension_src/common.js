// Fonctions partagées par la fenêtre et la page d'options de l'extension.
const PLATFORMS = {
  "alcopa-auction.fr": { key: "alcopa", name: "Alcopa Auction" },
  "leboncoin.fr": { key: "leboncoin", name: "Leboncoin" },
  "vpauto.fr": { key: "vpauto", name: "VPauto" },
  "encheres-domaine.gouv.fr": { key: "domaine", name: "Enchères Domaine" },
  "bca.fr": { key: "bca", name: "BCA" },
  "lacentrale.fr": { key: "lacentrale", name: "La Centrale" },
};

function detectPlatform(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    for (const [domain, p] of Object.entries(PLATFORMS)) {
      if (host === domain || host.endsWith("." + domain)) return p;
    }
  } catch (e) { /* URL invalide */ }
  return null;
}

async function getSettings() {
  const s = await chrome.storage.local.get(["server", "token"]);
  return { server: s.server || "", token: s.token || "" };
}

function normalizeServer(url) {
  const u = new URL(url.trim());
  if (!["https:", "http:"].includes(u.protocol)) throw new Error("L'adresse doit commencer par https://");
  if (u.protocol === "http:" && !["localhost", "127.0.0.1"].includes(u.hostname)) {
    throw new Error("Utilisez https:// (http:// n'est accepté qu'en local).");
  }
  return u.origin;
}

async function api(path, { method = "GET", body } = {}) {
  const { server, token } = await getSettings();
  if (!server || !token) throw new Error("Extension non configurée.");
  let resp;
  try {
    resp = await fetch(server + path, {
      method,
      headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      credentials: "omit",
    });
  } catch (e) {
    throw new Error("Serveur AutoDeal injoignable (" + server + ").");
  }
  let data = null;
  try { data = await resp.json(); } catch (e) { /* réponse non JSON */ }
  if (!resp.ok) {
    if (resp.status === 401) throw new Error("Jeton refusé : recréez-en un dans AutoDeal > Paramètres.");
    throw new Error((data && data.detail) || ("Erreur " + resp.status));
  }
  return data;
}

function eur(v) {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(v) + " €";
}
