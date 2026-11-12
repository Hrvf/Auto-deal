// AutoDeal Comparator — interactions légères (aucun script en ligne : compatible CSP stricte)
document.addEventListener("DOMContentLoaded", () => {
  // Barres de progression
  document.querySelectorAll("[data-width]").forEach((el) => {
    const w = Math.max(0, Math.min(100, parseInt(el.dataset.width, 10) || 0));
    requestAnimationFrame(() => { el.style.width = w + "%"; });
  });

  // Lignes de tableau cliquables
  document.querySelectorAll("tr[data-href]").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a, button, form, input, select")) return;
      window.location.href = tr.dataset.href;
    });
  });

  // Bascules (menu mobile, filtres)
  document.querySelectorAll("[data-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.toggle);
      if (target) target.classList.toggle("open");
    });
  });

  // Tri : envoi automatique
  document.querySelectorAll("[data-autosubmit]").forEach((el) => {
    el.addEventListener("change", () => el.form && el.form.submit());
  });

  // Confirmation avant action destructive
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // Nom du fichier choisi
  document.querySelectorAll("input[data-filename]").forEach((input) => {
    input.addEventListener("change", () => {
      const label = input.parentElement.querySelector("[data-filename-label]");
      if (label && input.files.length) label.textContent = input.files[0].name;
    });
  });

  // Copie du jeton
  document.querySelectorAll("[data-copy]").forEach((b) => {
    b.addEventListener("click", async () => {
      const input = document.getElementById(b.dataset.copy);
      input.select();
      try { await navigator.clipboard.writeText(input.value); b.textContent = "Copié ✓"; } catch (e) { document.execCommand("copy"); }
    });
  });

  // Fermeture des messages
  document.querySelectorAll("[data-dismiss]").forEach((b) => {
    b.addEventListener("click", () => b.parentElement.remove());
  });
});
