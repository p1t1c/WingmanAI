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
async function apiForm(url, formData) {
  const r = await fetch(url, { method: "POST", body: formData });
  if (!r.ok) {
    let msg = `POST ${url} -> ${r.status}`;
    try { const j = await r.json(); if (j.error) msg = j.error; } catch {}
    throw new Error(msg);
  }
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
  $("btn-make-upload").onclick = makeUploadPersona;
  $("btn-delete").onclick = deletePersona;
  $("btn-add-msg").onclick = addMessageTyped;
  $("btn-upload-chat").onclick = uploadChatScreenshot;
  $("btn-suggest").onclick = generateSuggestions;
  $("btn-reset").onclick = resetConversation;
  for (const tab of document.querySelectorAll(".modal-tabs .tab")) {
    tab.onclick = () => {
      for (const t of document.querySelectorAll(".modal-tabs .tab")) {
        t.classList.toggle("active", t === tab);
      }
      for (const p of document.querySelectorAll(".tab-pane")) {
        p.classList.toggle("active", p.id === "tab-" + tab.dataset.tab);
      }
    };
  }
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
      li.innerHTML = `
        <div class="persona-row">
          <div class="persona-text">
            <div class="name">${escapeHtml(p.name)}</div>
            <div class="meta">${escapeHtml(p.source || "")}</div>
          </div>
          <button class="persona-x" type="button" aria-label="Delete">&times;</button>
        </div>`;
      li.onclick = () => selectPersona(p.id);
      const x = li.querySelector(".persona-x");
      x.onclick = (ev) => {
        ev.stopPropagation();
        deletePersonaById(p.id, p.name);
      };
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
    renderChat(persona.messages);
    $("suggest-out").innerHTML = "";
    if (persona.vibe) {
      renderVibe(persona.vibe.score, persona.vibe.note);
    }
    for (const li of document.querySelectorAll("#persona-list li")) {
      li.classList.toggle("active", String(li.dataset.id) === String(id));
    }
  } catch (e) {
    alert("Couldn't load that persona. Try again.");
  } finally {
    hideSpinner();
  }
}

function renderChat(messages) {
  const chat = $("chat");
  chat.innerHTML = "";
  if (!messages || messages.length === 0) {
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.textContent = "No messages yet. Add some so Wingman has something to work with.";
    chat.appendChild(empty);
    return;
  }
  for (const m of messages) {
    const b = document.createElement("div");
    b.className = "bubble " + (m.sender === "me" ? "me" : "them");
    b.textContent = m.content;
    chat.appendChild(b);
  }
  chat.scrollTop = chat.scrollHeight;
}

function renderVibe(score, note) {
  const out = $("suggest-out");
  let vibe = out.querySelector(".vibe");
  if (!vibe) {
    vibe = document.createElement("div");
    vibe.className = "vibe";
    vibe.innerHTML = `
      <div class="score-wrap"><div class="score"></div><div class="score-label">vibe</div></div>
      <div class="note"></div>
    `;
    out.prepend(vibe);
  }
  vibe.querySelector(".score").textContent = score;
  vibe.querySelector(".note").textContent = note;
}

function renderReplies(replies) {
  const out = $("suggest-out");
  for (const r of out.querySelectorAll(".reply")) r.remove();
  for (const r of replies) {
    const div = document.createElement("div");
    const label = (r.label || "safe").toLowerCase();
    div.className = "reply " + label;
    div.innerHTML = `
      <div class="label">${escapeHtml(label)}</div>
      <div class="text">${escapeHtml(r.text || "")}</div>
      <div class="actions">
        <button class="btn btn-ghost btn-copy" type="button">Copy</button>
        <span class="copy-ok hidden">copied ✓</span>
      </div>
    `;
    const btn = div.querySelector(".btn-copy");
    const ok = div.querySelector(".copy-ok");
    btn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(r.text || "");
        ok.classList.remove("hidden");
        setTimeout(() => ok.classList.add("hidden"), 1500);
      } catch {
        alert("Browser blocked the copy. Highlight + Ctrl+C, sorry.");
      }
    };
    out.appendChild(div);
  }
}

async function makeUploadPersona() {
  const name = $("u-name").value.trim();
  const file = $("u-image").files[0];
  if (!name) { alert("Give them a name first."); return; }
  if (!file) { alert("Pick a screenshot first."); return; }
  const fd = new FormData();
  fd.append("name", name);
  fd.append("image", file);
  try {
    showSpinner("Reading their profile...");
    const created = await apiForm("/api/persona/screenshot", fd);
    $("persona-modal").classList.add("hidden");
    $("u-name").value = "";
    $("u-image").value = "";
    await refreshPersonas();
    await selectPersona(created.id);
  } catch (e) {
    alert("Couldn't read that profile. " + (e.message || "Try a clearer pic."));
  } finally {
    hideSpinner();
  }
}

async function uploadChatScreenshot() {
  if (!state.personaId) return;
  const file = $("chat-screenshot").files[0];
  if (!file) { alert("Pick a screenshot first."); return; }
  const fd = new FormData();
  fd.append("image", file);
  try {
    showSpinner("Extracting messages...");
    const data = await apiForm(
      `/api/persona/${state.personaId}/screenshot`, fd
    );
    $("chat-screenshot").value = "";
    if (data.saved === 0) {
      alert("Wingman couldn't read any messages in that. Try a clearer screenshot.");
    }
    await selectPersona(state.personaId);
  } catch (e) {
    alert("Vision couldn't parse that. " + (e.message || ""));
  } finally {
    hideSpinner();
  }
}

async function addMessageTyped() {
  if (!state.personaId) return;
  const sender = $("msg-sender").value;
  const content = $("msg-content").value.trim();
  if (!content) {
    alert("Type something first.");
    return;
  }
  try {
    showSpinner("Saving...");
    await apiJson(`/api/persona/${state.personaId}/messages`, {
      messages: [{ sender, content }],
    });
    $("msg-content").value = "";
    await selectPersona(state.personaId);
  } catch {
    alert("Could not save that message.");
  } finally {
    hideSpinner();
  }
}

async function generateSuggestions() {
  if (!state.personaId) return;
  const personality = $("personality").value;
  try {
    showSpinner("Wingman is thinking too hard...");
    const data = await apiJson(`/api/persona/${state.personaId}/suggest`, {
      personality,
    });
    renderVibe(data.vibe_score, data.vibe_note);
    renderReplies(data.replies);
  } catch {
    alert("Suggestions failed. Wingman is taking a smoke break.");
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
  await deletePersonaById(state.personaId, state.persona && state.persona.name);
}

async function deletePersonaById(id, name) {
  const label = name ? `"${name}"` : "this persona";
  if (!confirm(`Delete ${label} and everything with them? This cannot be undone.`)) return;
  try {
    showSpinner("Erasing the evidence...");
    await apiDelete(`/api/persona/${id}`);
    if (state.personaId === id) {
      state.personaId = null;
      state.persona = null;
      $("persona-detail").classList.add("hidden");
      $("empty-state").classList.remove("hidden");
    }
    await refreshPersonas();
  } catch {
    alert("Could not delete.");
  } finally {
    hideSpinner();
  }
}

async function resetConversation() {
  if (!state.personaId) return;
  if (!confirm(
    "Archive the current chat and start fresh? The old messages stay in DB and appear under Archives."
  )) return;
  try {
    showSpinner("Stashing this in the vault...");
    const r = await apiJson(`/api/persona/${state.personaId}/reset`, {});
    if (r.archived_id == null) {
      alert("Nothing to archive — chat was already empty.");
    }
    await selectPersona(state.personaId);
  } catch {
    alert("Could not reset.");
  } finally {
    hideSpinner();
  }
}

// --- Coaching page ---
if ($("stats-grid")) {
  initCoaching();
}

async function initCoaching() {
  try {
    showSpinner("Diagnosing your texting...");
    const data = await apiGet("/api/coaching");
    renderStats(data.stats);
    $("roast").textContent = data.roast;
  } catch {
    $("roast").textContent = "Diagnosis machine is offline. Reload?";
  } finally {
    hideSpinner();
  }
  const btn = $("btn-analyze");
  if (btn) btn.onclick = analyzeOldChat;
}

async function analyzeOldChat() {
  const text = $("old-chat").value.trim();
  if (text.length < 20) {
    alert("Paste a bit more — at least 20 characters.");
    return;
  }
  try {
    showSpinner("Wingman is reading the wreckage...");
    const data = await apiJson("/api/analyze", { text });
    $("analyze-out").textContent = data.analysis;
  } catch {
    alert("Could not analyze. Try again.");
  } finally {
    hideSpinner();
  }
}

// --- Archives page ---
if ($("archive-list")) {
  initArchives();
}

async function initArchives() {
  try {
    showSpinner("Loading the vault...");
    const archives = await apiGet("/api/archives");
    renderArchives(archives);
  } catch {
    $("archive-list").innerHTML =
      '<li class="muted">Vault is offline. Reload?</li>';
  } finally {
    hideSpinner();
  }
}

function renderArchives(items) {
  const list = $("archive-list");
  list.innerHTML = "";
  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No archived chats yet. Hit Reset chat on a persona to stash one here.";
    list.appendChild(li);
    return;
  }
  for (const a of items) {
    const li = document.createElement("li");
    li.className = "archive-item";
    li.dataset.id = a.id;
    const ended = (a.ended_at || "").replace("T", " ").slice(0, 16);
    const vibeBadge = a.last_vibe != null
      ? `<span class="vibe-badge">${a.last_vibe}</span>` : "";
    li.innerHTML = `
      <div class="archive-head">
        <div>
          <div class="archive-title">
            ${escapeHtml(a.persona_name)} ${vibeBadge}
          </div>
          <div class="meta">
            Closed ${escapeHtml(ended)} · ${a.msg_count} msgs
            ${a.last_vibe_note ? "· " + escapeHtml(a.last_vibe_note) : ""}
          </div>
        </div>
        <div class="archive-actions">
          <button class="btn btn-ghost btn-sm" data-act="toggle" type="button">View</button>
          <button class="btn btn-primary btn-sm" data-act="analyze" type="button">Analyze</button>
          <button class="btn btn-ghost btn-sm" data-act="del" type="button">Delete</button>
        </div>
      </div>
      <div class="archive-body hidden">
        <div class="chat archive-chat"></div>
        <div class="analyze-out"></div>
      </div>
    `;
    li.querySelector('[data-act="toggle"]').onclick = () => toggleArchive(li, a.id);
    li.querySelector('[data-act="analyze"]').onclick = () => analyzeArchive(li, a.id);
    li.querySelector('[data-act="del"]').onclick = () => deleteArchive(li, a.id);
    list.appendChild(li);
  }
}

async function toggleArchive(li, convId) {
  const body = li.querySelector(".archive-body");
  const chat = li.querySelector(".archive-chat");
  if (!body.classList.contains("hidden")) {
    body.classList.add("hidden");
    return;
  }
  if (!chat.dataset.loaded) {
    try {
      showSpinner("Pulling the messages...");
      const conv = await apiGet(`/api/archives/${convId}`);
      chat.innerHTML = "";
      if (!conv.messages.length) {
        chat.innerHTML = '<div class="chat-empty">No messages in this archive.</div>';
      } else {
        for (const m of conv.messages) {
          const b = document.createElement("div");
          b.className = "bubble " + (m.sender === "me" ? "me" : "them");
          b.textContent = m.content;
          chat.appendChild(b);
        }
      }
      chat.dataset.loaded = "1";
    } catch {
      chat.innerHTML = '<div class="chat-empty">Could not load messages.</div>';
    } finally {
      hideSpinner();
    }
  }
  body.classList.remove("hidden");
}

async function analyzeArchive(li, convId) {
  const body = li.querySelector(".archive-body");
  const out = li.querySelector(".analyze-out");
  body.classList.remove("hidden");
  try {
    showSpinner("Wingman is dissecting the corpse...");
    const r = await apiJson(`/api/archives/${convId}/analyze`, {});
    out.textContent = r.analysis;
  } catch {
    out.textContent = "Analysis failed. Try again.";
  } finally {
    hideSpinner();
  }
}

async function deleteArchive(li, convId) {
  if (!confirm("Permanently delete this archived chat? Cannot be undone.")) return;
  try {
    showSpinner("Shredding...");
    await apiDelete(`/api/archives/${convId}`);
    li.remove();
    if (!$("archive-list").children.length) {
      $("archive-list").innerHTML =
        '<li class="muted">No archived chats yet.</li>';
    }
  } catch {
    alert("Could not delete that archive.");
  } finally {
    hideSpinner();
  }
}

function renderStats(stats) {
  const grid = $("stats-grid");
  grid.innerHTML = "";
  const tiles = [
    ["Total messages", stats.total_messages],
    ["Sent by you", stats.my_messages],
    ["Double-text rate", (stats.double_text_rate_pct ?? 0) + "%"],
    ["Avg your length", stats.avg_my_message_chars + " ch"],
  ];
  for (const [k, v] of tiles) {
    const div = document.createElement("div");
    div.className = "stat";
    div.innerHTML = `<div class="k">${escapeHtml(k)}</div>
      <div class="v">${escapeHtml(String(v))}</div>`;
    grid.appendChild(div);
  }
  const ul = $("persona-stats");
  ul.innerHTML = "";
  if (!stats.personas || stats.personas.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No personas yet. Make one over on Suggestions.";
    ul.appendChild(li);
    return;
  }
  for (const p of stats.personas) {
    const li = document.createElement("li");
    const trendClass = p.trend > 0 ? "trend-up" : p.trend < 0 ? "trend-down" : "trend-flat";
    const arrow = p.trend > 0 ? "↑" : p.trend < 0 ? "↓" : "→";
    const trendVal = p.trend ? Math.abs(p.trend) : "";
    const latest = p.latest_vibe != null ? p.latest_vibe : "—";
    li.innerHTML = `
      <span class="ps-name">${escapeHtml(p.name)}
        <span class="meta">(${p.messages_count} msgs)</span></span>
      <span class="ps-vibe">${latest}
        <span class="${trendClass}">${arrow}${trendVal}</span></span>
    `;
    ul.appendChild(li);
  }
}
