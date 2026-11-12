// Fenêtre de l'extension : capture de la page affichée et envoi à AutoDeal.
const $ = (id) => document.getElementById(id);
let currentTab = null;
let detected = null;

function show(id) {
  for (const s of ["setup", "ready", "busy", "error", "result"]) $(s).hidden = s !== id;
}

// Exécutée DANS la page consultée, uniquement après le clic de l'utilisateur (permission activeTab).
function collectPage() {
  const h1 = document.querySelector("h1");
  return {
    url: location.href,
    title: (h1 && h1.innerText.trim()) || document.title,
    html: document.documentElement.outerHTML,
    text: document.body ? document.body.innerText : "",
  };
}

async function init() {
  const { server, token } = await getSettings();
  [currentTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  detected = currentTab && currentTab.url ? detectPlatform(currentTab.url) : null;
  $("where").textContent = detected ? detected.name : "Site non reconnu";
  if (!server || !token) return show("setup");
  if (detected) {
    $("hint").textContent = "Le véhicule affiché sera ajouté à AutoDeal et analysé.";
  } else {
    $("hint").textContent = "Ce site n'est pas reconnu automatiquement : indiquez sa plateforme.";
    $("pick-wrap").hidden = false;
  }
  show("ready");
}

async function capture() {
  const platform = detected ? detected.key : $("pick").value;
  if (!platform) { $("pick").focus(); return; }
  show("busy");
  try {
    const [{ result: page }] = await chrome.scripting.executeScript({ target: { tabId: currentTab.id }, func: collectPage });
    const data = await api("/api/capture", { method: "POST", body: { ...page, platform } });
    renderResult(data);
  } catch (e) {
    $("error-msg").textContent = e.message || String(e);
    show("error");
  }
}

function renderResult(d) {
  const score = $("r-score");
  score.textContent = d.note ?? "–";
  score.className = "score " + (d.note >= 75 ? "excellent" : d.note >= 60 ? "bon" : d.note >= 45 ? "moyen" : "");
  $("r-title").textContent = d.titre;
  const provisional = d.revente === null || d.revente === undefined;
  $("r-verdict").textContent = (provisional ? "Note provisoire : revente inconnue" : (d.verdict || ""))
    + (d.nouveau ? " · ajouté" : " · mis à jour");
  $("r-price").textContent = eur(d.prix);
  $("r-resale").textContent = eur(d.revente);
  const m = $("r-margin");
  m.textContent = d.marge === null ? "non estimable" : eur(d.marge) + (d.marge_pct !== null ? " (" + (d.marge_pct * 100).toFixed(1).replace(".", ",") + " %)" : "");
  m.className = d.marge > 0 ? "pos" : d.marge < 0 ? "neg" : "";
  $("r-bid").textContent = eur(d.enchere_max);
  const ul = $("r-alerts");
  ul.textContent = "";
  for (const a of [...(d.alertes || []), ...(d.avertissements || [])].slice(0, 4)) {
    const li = document.createElement("li");
    li.textContent = a;
    ul.appendChild(li);
  }
  $("r-link").href = d.lien;
  show("result");
}

$("capture").addEventListener("click", capture);
$("retry").addEventListener("click", init);
$("open-options").addEventListener("click", () => chrome.runtime.openOptionsPage());
$("settings-link").addEventListener("click", (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); });
init();
