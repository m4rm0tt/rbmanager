// Crate — frontend, no build step (plain fetch against the FastAPI JSON API).
// Chat NEVER writes to the library directly: it only edits the plan preview,
// which requires an explicit "Apply Changes" click — see PROJECT_CONTEXT.md §14.

const state = {
  libraryId: null,
  lastPlan: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ---------- Navigation ----------
$$(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".nav-item").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${btn.dataset.view}`).classList.remove("hidden");
    if (btn.dataset.view === "playlists") loadPlaylists();
    if (btn.dataset.view === "artists") loadArtists();
    if (btn.dataset.view === "activity") loadActivity();
    if (btn.dataset.view === "settings") loadSettings();
  });
});

// ---------- Library upload ----------
const dropzone = $("#dropzone");
const fileInput = $("#file-input");
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.style.borderColor = "var(--accent)"; });
dropzone.addEventListener("dragleave", () => { dropzone.style.borderColor = ""; });
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.style.borderColor = "";
  if (e.dataTransfer.files.length) uploadLibrary(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) uploadLibrary(fileInput.files[0]);
});

async function uploadLibrary(file) {
  const statusEl = $("#upload-status");
  statusEl.textContent = "Uploading...";
  statusEl.className = "status-line";
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/library/upload", { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json()).detail || "Upload failed");
    const body = await res.json();
    state.libraryId = body.library_id;
    statusEl.textContent = `Loaded ${body.nb_tracks} tracks.`;
    statusEl.className = "status-line ok";
    $("#stat-tracks").textContent = body.nb_tracks;
    $("#stat-playlists").textContent = body.nb_playlists;
    $("#stat-libid").textContent = body.library_id.slice(0, 8);
    $("#library-stats").hidden = false;
    $("#download-panel").hidden = false;
    $("#lib-indicator .dot").className = "dot dot-on";
    $("#lib-indicator span:last-child").textContent = `${body.nb_tracks} tracks loaded`;
  } catch (err) {
    statusEl.textContent = String(err.message || err);
    statusEl.className = "status-line err";
  }
}

$("#btn-download").addEventListener("click", () => {
  if (!state.libraryId) return;
  window.location.href = `/api/library/${state.libraryId}/download`;
});

// ---------- Organizer ----------
$("#btn-analyze").addEventListener("click", () => runAnalyze());

async function runAnalyze() {
  if (!requireLibrary("#analyze-status")) return;
  const statusEl = $("#analyze-status");
  statusEl.textContent = "Analyzing...";
  statusEl.className = "status-line";
  try {
    const res = await fetch(`/api/library/${state.libraryId}/analyze`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail || "Analyze failed");
    const plan = await res.json();
    renderPlan(plan);
    statusEl.textContent = "";
  } catch (err) {
    statusEl.textContent = String(err.message || err);
    statusEl.className = "status-line err";
  }
}

function renderPlan(plan) {
  state.lastPlan = plan;
  $("#analysis-result").hidden = false;
  $("#an-tracks").textContent = plan.summary.nb_tracks;
  $("#an-artists").textContent = plan.summary.nb_artists;
  $("#an-known").textContent = plan.summary.nb_known_from_db;
  $("#an-researched").textContent = plan.summary.nb_researched;

  const tbody = $("#plan-table tbody");
  tbody.innerHTML = "";
  for (const change of plan.changes) {
    const tr = document.createElement("tr");
    const badge = change.action === "reuse_playlist"
      ? `<span class="badge badge-existing">existing</span>`
      : `<span class="badge badge-new">new playlist</span>`;
    tr.innerHTML = `<td>${escapeHtml(change.name)}</td><td class="num">${change.nb_tracks}</td><td>${badge}</td>`;
    tbody.appendChild(tr);
  }
}

$("#btn-apply").addEventListener("click", async () => {
  if (!requireLibrary("#apply-status")) return;
  const statusEl = $("#apply-status");
  statusEl.textContent = "Applying...";
  statusEl.className = "status-line";
  try {
    const res = await fetch(`/api/library/${state.libraryId}/apply`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail || "Apply failed");
    const body = await res.json();
    statusEl.textContent = `${body.nb_tracks_moved} tracks organized into ${body.playlists_created.length + body.playlists_reused.length} playlists.`;
    statusEl.className = "status-line ok";
  } catch (err) {
    statusEl.textContent = String(err.message || err);
    statusEl.className = "status-line err";
  }
});

// ---------- Chat ----------
$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!requireLibrary("#analyze-status")) return;
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  addChatMessage(message, "user");
  input.value = "";
  try {
    const res = await fetch(`/api/library/${state.libraryId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const body = await res.json();
    addChatMessage(body.explanation, "ai");
    if (body.understood) renderPlan(body.plan);
  } catch (err) {
    addChatMessage(String(err.message || err), "ai");
  }
});

function addChatMessage(text, who) {
  const log = $("#chat-log");
  const div = document.createElement("div");
  div.className = `chat-msg ${who}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// ---------- Playlists ----------
async function loadPlaylists() {
  if (!state.libraryId) { $("#playlist-tree").innerHTML = "<li class='dim'>No library loaded yet.</li>"; return; }
  const res = await fetch(`/api/library/${state.libraryId}/playlists`);
  const body = await res.json();
  $("#playlist-tree").innerHTML = renderPlaylistNodes(body.playlists);
}

function renderPlaylistNodes(nodes) {
  return nodes.map((n) => {
    const label = n.is_folder
      ? `<span class="p-folder">${escapeHtml(n.name)}/</span>`
      : `<span class="p-name">${escapeHtml(n.name)}</span><span class="p-count">${n.nb_tracks} tracks</span>`;
    const children = n.children && n.children.length ? `<ul>${renderPlaylistNodes(n.children)}</ul>` : "";
    return `<li>${label}${children}</li>`;
  }).join("");
}

// ---------- Artists ----------
async function loadArtists() {
  const search = $("#artist-search").value.trim();
  const genre = $("#artist-genre-filter").value;
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (genre) params.set("genre", genre);
  const res = await fetch(`/api/artists?${params.toString()}`);
  const body = await res.json();
  const tbody = $("#artists-table tbody");
  tbody.innerHTML = "";

  const genreFilter = $("#artist-genre-filter");
  const knownGenres = new Set(Array.from(genreFilter.options).map((o) => o.value));

  for (const a of body.artists) {
    if (!knownGenres.has(a.primary_genre)) {
      const opt = document.createElement("option");
      opt.value = a.primary_genre;
      opt.textContent = a.primary_genre;
      genreFilter.appendChild(opt);
      knownGenres.add(a.primary_genre);
    }
    const tr = document.createElement("tr");
    const confidencePct = Math.round(a.confidence * 100);
    tr.innerHTML = `
      <td>${escapeHtml(a.artist_name)}</td>
      <td>${escapeHtml(a.primary_genre)}</td>
      <td class="num">${confidencePct}%</td>
      <td><span class="badge ${a.source === "manual" ? "badge-manual" : "badge-existing"}">${escapeHtml(a.source)}</span></td>
      <td><button class="edit-link" data-artist="${escapeHtml(a.normalized_artist_name)}" data-genre="${escapeHtml(a.primary_genre)}">Edit</button></td>`;
    tbody.appendChild(tr);
  }

  $$(".edit-link").forEach((btn) => btn.addEventListener("click", () => editArtist(btn.dataset.artist, btn.dataset.genre)));
}

async function editArtist(normalizedName, currentGenre) {
  const newGenre = prompt("New genre:", currentGenre);
  if (!newGenre || newGenre === currentGenre) return;
  await fetch(`/api/artists/${encodeURIComponent(normalizedName)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ primary_genre: newGenre, confidence: 1.0 }),
  });
  loadArtists();
}

$("#artist-search").addEventListener("input", debounce(loadArtists, 250));
$("#artist-genre-filter").addEventListener("change", loadArtists);

// ---------- Activity ----------
async function loadActivity() {
  if (!state.libraryId) { $("#activity-table tbody").innerHTML = "<tr><td colspan='4' class='dim'>No library loaded yet.</td></tr>"; return; }
  const res = await fetch(`/api/library/${state.libraryId}/history`);
  const body = await res.json();
  const tbody = $("#activity-table tbody");
  tbody.innerHTML = "";
  for (const run of body.runs) {
    const tr = document.createElement("tr");
    const date = new Date(run.created_at).toLocaleString();
    const undoBtn = run.undone
      ? `<span class="dim">undone</span>`
      : `<button class="edit-link" data-run="${run.id}">Undo</button>`;
    tr.innerHTML = `<td class="mono">${date}</td><td class="num">${run.nb_tracks}</td><td>${run.playlists_created.join(", ") || "—"}</td><td>${undoBtn}</td>`;
    tbody.appendChild(tr);
  }
  $$('button[data-run]').forEach((btn) => btn.addEventListener("click", () => undoRun(btn.dataset.run)));
}

async function undoRun(runId) {
  if (!confirm("Undo this organization run? This restores the backup taken right before it.")) return;
  await fetch(`/api/library/${state.libraryId}/history/${runId}/undo`, { method: "POST" });
  loadActivity();
}

// ---------- Settings ----------
async function loadSettings() {
  if (!state.libraryId) { $("#genre-chips").innerHTML = "<span class='dim'>No library loaded yet.</span>"; return; }
  const res = await fetch(`/api/library/${state.libraryId}/config`);
  const body = await res.json();
  $("#genre-chips").innerHTML = body.genres.map((g) => `<span class="chip">${escapeHtml(g)}</span>`).join("");
}

$("#add-genre-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#new-genre-input");
  const name = input.value.trim();
  if (!name || !state.libraryId) return;
  await fetch(`/api/library/${state.libraryId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: `Crée une catégorie ${name}.` }),
  });
  input.value = "";
  loadSettings();
});

// ---------- Helpers ----------
function requireLibrary(statusSelector) {
  if (state.libraryId) return true;
  const el = $(statusSelector);
  el.textContent = "Upload a library first (see the Library tab).";
  el.className = "status-line err";
  return false;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
