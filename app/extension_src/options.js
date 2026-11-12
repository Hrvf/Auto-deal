// Page de réglages : adresse du serveur + jeton, avec test de connexion.
const status = document.getElementById("status");

function setStatus(msg, kind) {
  status.textContent = msg;
  status.className = kind || "";
}

(async () => {
  const s = await getSettings();
  document.getElementById("server").value = s.server;
  document.getElementById("token").value = s.token;
})();

document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  let server;
  try {
    server = normalizeServer(document.getElementById("server").value);
  } catch (err) {
    return setStatus(err.message || "Adresse invalide.", "err");
  }
  const token = document.getElementById("token").value.trim();
  if (!token.startsWith("adc_")) return setStatus("Le jeton doit commencer par adc_", "err");
  await chrome.storage.local.set({ server, token });
  setStatus("Test de la connexion…");
  try {
    const me = await api("/api/moi");
    setStatus("Connecté à AutoDeal en tant que " + me.nom + ". Vous pouvez fermer cet onglet.", "ok");
  } catch (err) {
    setStatus(err.message, "err");
  }
});
