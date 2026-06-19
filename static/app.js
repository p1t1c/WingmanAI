// AI Wingman — vanilla JS for the authed pages.

const $ = (id) => document.getElementById(id);
const spinnerEl = $("spinner");
const spinnerMsgEl = $("spinner-msg");

function showSpinner(msg) {
  if (!spinnerEl) return;
  if (msg) spinnerMsgEl.textContent = msg;
  spinnerEl.classList.remove("hidden");
}
function hideSpinner() {
  if (!spinnerEl) return;
  spinnerEl.classList.add("hidden");
}

async function apiGet(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`GET ${url} -> ${r.status}`);
  return r.json();
}
async function apiJson(url, body, method = "POST") {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${method} ${url} -> ${r.status}`);
  return r.json();
}
async function apiDelete(url) {
  const r = await fetch(url, { method: "DELETE" });
  if (!r.ok) throw new Error(`DELETE ${url} -> ${r.status}`);
  return r.json();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

const state = { personaId: null, persona: null };

// --- Main app page bootstrapping ---
if ($("persona-list")) {
  initMainPage();
}

async function initMainPage() {
  await refreshPersonas();
  bindMainEvents();
}

function bindMainEvents() {
  $("btn-new-persona").onclick = () => $("persona-modal").classList.remove("hidden");
  $("btn-close-modal").onclick = () => $("persona-modal").classList.add("hidden");
  $("btn-make-interview").onclick = makeInterviewPersona;
  $("btn-delete").onclick = deletePersona;
}

async function refreshPersonas() {
  try {
    const personas = await apiGet("/api/personas");
    const list = $("persona-list");
    list.innerHTML = "";
    if (personas.length === 0) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "No targets yet.";
      list.appendChild(li);
      return;
    }
    for (const p of personas) {
      const li = document.createElement("li");
      li.dataset.id = p.id;
      li.innerHTML = `<div class="name">${escapeHtml(p.name)}</div>
        <div class="meta">${escapeHtml(p.source || "")}</div>`;
      li.onclick = () => selectPersona(p.id);
      if (state.personaId === p.id) li.classList.add("active");
      list.appendChild(li);
    }
  } catch (e) {
    console.error(e);
  }
}

async function selectPersona(id) {
  try {
    showSpinner("Loading persona...");
    const persona = await apiGet(`/api/persona/${id}`);
    state.personaId = id;
    state.persona = persona;
    $("empty-state").classList.add("hidden");
    $("persona-detail").classList.remove("hidden");
    $("persona-name").textContent = persona.name;
    $("persona-desc").textContent = persona.description || "(no description yet)";
    for (const li of document.querySelectorAll("#persona-list li")) {
      li.classList.toggle("active", String(li.dataset.id) === String(id));
    }
  } catch (e) {
    alert("Couldn't load that persona. Try again.");
  } finally {
    hideSpinner();
  }
}

async function makeInterviewPersona() {
  const body = {
    name: $("i-name").value,
    where: $("i-where").value,
    vibe: $("i-vibe").value,
    stage: $("i-stage").value,
    extra: $("i-extra").value,
  };
  if (!body.name.trim()) {
    alert("Give them a name first.");
    return;
  }
  try {
    showSpinner("Wingman is profiling them...");
    const created = await apiJson("/api/persona/interview", body);
    $("persona-modal").classList.add("hidden");
    for (const el of ["i-name", "i-where", "i-vibe", "i-stage", "i-extra"]) {
      $(el).value = "";
    }
    await refreshPersonas();
    await selectPersona(created.id);
  } catch (e) {
    alert("Persona creation went sideways. Try again.");
  } finally {
    hideSpinner();
  }
}

async function deletePersona() {
  if (!state.personaId) return;
  if (!confirm("Delete this persona and everything with them?")) return;
  try {
    showSpinner("Erasing the evidence...");
    await apiDelete(`/api/persona/${state.personaId}`);
    state.personaId = null;
    state.persona = null;
    $("persona-detail").classList.add("hidden");
    $("empty-state").classList.remove("hidden");
    await refreshPersonas();
  } catch {
    alert("Could not delete.");
  } finally {
    hideSpinner();
  }
}
