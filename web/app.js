/* SubLab UI — preview live + stile + trascrizione */
const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const toHex = (rgb) => "#" + rgb.map((v) => Math.round(clamp(v, 0, 1) * 255).toString(16).padStart(2, "0")).join("");
const fromHex = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const norm = (s) => (s || "").toLowerCase().replace(/[\s_\-.]/g, "");
const fontEntry = (name) => S.fonts.find((f) => (f.key || norm(f.family)) === norm(name));
const faceName = (fam, style) => "sublab_" + (fam.key || norm(fam.family)) + "_" + norm(style || "Regular");

const S = {
  info: null,
  style: null,
  cues: [],
  meta: {},
  fonts: [],
  fontFaces: new Set(),
  selected: new Set(),
  activeCue: 0,
  still: null,
  showSafe: true,
  reveal: true,
  t0: performance.now(),
};

/* ------------------------------------------------------------------ util */
async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}
async function postJSON(url, body) {
  return getJSON(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}
const tc = (frame, fps) => {
  const fpsI = Math.max(1, Math.round(fps || 24));
  const f = Math.max(0, Math.round(frame));
  const s = Math.floor(f / fpsI);
  const ff = f % fpsI;
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}.${String(ff).padStart(2, "0")}`;
};

/* ------------------------------------------------------------------ init */
async function init() {
  // 1) lo stato PRIMA di tutto: buildFontSelect e bindStyleControls usano S.style
  try {
    const st = await getJSON("/api/state");
    S.style = st.style || S.style;
    S.cues = st.cues || [];
    S.meta = st.meta || {};
  } catch (e) {
    fatal("backend non raggiungibile: " + e.message);
  }
  if (!S.style) return;

  if (!S.style.shadow_offset) S.style.shadow_offset = [0.004, -0.004];
  if (!S.style.highlight) S.style.highlight = [0, 0.208, 1];

  try {
    S.fonts = (await getJSON("/api/fonts")).fonts || [];
  } catch (e) {
    $("log").textContent = "font non caricati: " + e.message;
  }
  buildFontSelect();
  bindStyleControls();
  renderCues();
  draw();

  try {
    await refreshInfo();
  } catch (e) {
    fatal("errore leggendo Resolve: " + e.message);
  }
  ensureFont();
}

function fatal(msg) {
  $("ctx").textContent = msg;
  $("ctx").style.color = "var(--err)";
  $("log").textContent = "ERRORE: " + msg;
  console.error(msg);
}

async function refreshInfo() {
  const info = await getJSON("/api/info");
  S.info = info;
  if (info.offline) {
    $("ctx").textContent = "Resolve non connesso — " + (info.error || "");
    $("ctx").style.color = "var(--err)";
    $("pill-range").textContent = "offline";
    return;
  }
  $("ctx").style.color = "";
  $("ctx").textContent = `${info.project} · ${info.timeline} · ${info.width}×${info.height} · ${info.fps}fps`;
  $("btn-apply-all").disabled = false;
  $("btn-apply-sel").disabled = false;
  $("btn-push").disabled = false;
  const fps = info.fps;
  const mode = $("range-mode").value;
  let a = info.start, b = info.end, why = "tutta la timeline";
  if (mode === "io" && (info.mark_in != null || info.mark_out != null)) {
    a = info.mark_in ?? info.start;
    b = info.mark_out ?? info.end;
    why = "In/Out";
  } else if (mode === "selection" && info.selection.length) {
    a = Math.min(...info.selection.map((c) => c.start));
    b = Math.max(...info.selection.map((c) => c.end));
    why = `${info.selection.length} clip selezionate`;
  }
  $("pill-range").textContent = `${tc(a, fps)} → ${tc(b, fps)} · ${((b - a) / fps).toFixed(1)}s`;
  $("pill-range").classList.toggle("on", mode === "io" && info.mark_in != null);
  $("range-hint").textContent = `${why} · ${b - a} frame da ${tc(a, fps)}`;
  $("preview-info").textContent =
    S.meta.stats ? `${S.meta.stats.count} cue · ${S.meta.device || ""} · ${S.meta.language || ""}` : "";
}

/* ------------------------------------------------------------------ font */
function buildFontSelect() {
  const sel = $("font");
  sel.innerHTML = "";
  S.fonts.forEach((f) => {
    const o = document.createElement("option");
    o.value = f.family;
    o.textContent = f.family;
    sel.appendChild(o);
  });
  const cur = fontEntry(S.style.font);
  if (cur && cur.family !== S.style.font) {
    // migrazione: il nome salvato era quello del registro (senza spazi) e Fusion
    // risponde "Font Not Found" -> passo al nome dichiarato nel file
    S.style.font = cur.family;
    saveStyle();
  }
  sel.value = cur ? cur.family : S.style.font;
  if (!cur && S.fonts.length) {
    const o = document.createElement("option");
    o.value = S.style.font;
    o.textContent = S.style.font + " (non trovato)";
    sel.appendChild(o);
    sel.value = S.style.font;
  }
  buildStyleSelect();
}

function buildStyleSelect() {
  const fam = fontEntry($("font").value);
  const sel = $("font-style");
  sel.innerHTML = "";
  const styles = fam ? fam.styles : [S.style.font_style || "Regular"];
  styles.forEach((s) => {
    const o = document.createElement("option");
    o.value = s;
    o.textContent = s;
    sel.appendChild(o);
  });
  const want = S.style.font_style || "Regular";
  if (!styles.includes(want)) {
    const w = norm(want);
    const match = styles.find((s) => norm(s) === w) || styles.find((s) => norm(s).startsWith(w));
    S.style.font_style = match || (styles.includes("Regular") ? "Regular" : styles[0]);
    saveStyle();
  }
  sel.value = S.style.font_style;
}

async function ensureFont() {
  const fam = fontEntry(S.style.font);
  if (!fam) return;
  const style = S.style.font_style || "Regular";
  const file = fam.files[style] || fam.files["Regular"] || Object.values(fam.files)[0];
  if (!file) return;
  const face = faceName(fam, style);
  if (S.fontFaces.has(face)) return;
  try {
    const ff = new FontFace(face, `url(/fonts/${encodeURIComponent(file)})`);
    await ff.load();
    document.fonts.add(ff);
    S.fontFaces.add(face);
  } catch (e) {
    console.warn("font non caricabile", file, e);
  }
  draw();
}

/* ------------------------------------------------------------------ controlli stile */
function bindStyleControls() {
  const st = S.style;
  $("size").value = st.size;
  $("cx").value = st.cx;
  $("cy").value = st.cy;
  $("fill").value = toHex(st.fill);
  $("fill-on").checked = !!st.fill_on;
  $("outline").value = toHex(st.outline);
  $("outline-on").checked = !!st.outline_on;
  $("outline-t").value = st.outline_thickness;
  $("shadow").value = toHex(st.shadow);
  $("shadow-on").checked = !!st.shadow_on;
  $("highlight").value = toHex(st.highlight || [0, 0.208, 1]);
  $("hl-on").checked = !!st.highlight_on;

  const onChange = () => {
    const st2 = S.style;
    st2.size = +$("size").value;
    st2.cx = +$("cx").value;
    st2.cy = +$("cy").value;
    st2.fill = fromHex($("fill").value);
    st2.fill_on = $("fill-on").checked ? 1 : 0;
    st2.outline = fromHex($("outline").value);
    st2.outline_on = $("outline-on").checked ? 1 : 0;
    st2.outline_thickness = +$("outline-t").value;
    st2.shadow = fromHex($("shadow").value);
    st2.shadow_on = $("shadow-on").checked ? 1 : 0;
    st2.highlight = fromHex($("highlight").value);
    st2.highlight_on = $("hl-on").checked ? 1 : 0;
    st2.font = $("font").value;
    st2.font_style = $("font-style").value;
    labels();
    draw();
    saveStyle();
  };
  ["size", "cx", "cy", "fill", "fill-on", "outline", "outline-on", "outline-t",
    "shadow", "shadow-on", "highlight", "hl-on", "font", "font-style"].forEach((id) => {
    $(id).addEventListener("input", onChange);
  });
  $("font").addEventListener("change", () => { buildStyleSelect(); ensureFont(); onChange(); });
  $("font-style").addEventListener("change", () => { ensureFont(); onChange(); });
  labels();
  ensureFont();
}

let saveTimer = null;
function saveStyle() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => postJSON("/api/style", { style: S.style }), 250);
}
function labels() {
  const st = S.style;
  $("v-size").textContent = (st.size * 100).toFixed(1);
  $("v-cx").textContent = st.cx.toFixed(2);
  $("v-cy").textContent = st.cy.toFixed(2);
  $("v-fill").textContent = toHex(st.fill);
  $("v-outline-t").textContent = st.outline_thickness.toFixed(3);
}

/* ------------------------------------------------------------------ preview */
function draw() {
  const cv = $("preview");
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);

  if (S.still) {
    ctx.drawImage(S.still, 0, 0, W, H);
  } else {
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#14171d");
    g.addColorStop(1, "#0a0c10");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  }

  if (S.showSafe) drawSafe(ctx, W, H);

  const cue = S.cues[S.activeCue];
  const text = cue ? cue.text : "Anteprima sottotitoli";
  drawSubs(ctx, W, H, text, cue);
}

function drawSafe(ctx, W, H) {
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,.14)";
  ctx.setLineDash([12, 12]);
  ctx.lineWidth = 3;
  ctx.strokeRect(W * 0.05, H * 0.05, W * 0.9, H * 0.9);
  ctx.strokeStyle = "rgba(255,170,0,.20)";
  ctx.strokeRect(W * 0.1, H * 0.1, W * 0.8, H * 0.8);
  ctx.restore();
}

function layout(ctx, text, W, maxWidth) {
  const words = text.split(/\s+/).filter(Boolean);
  const lines = [];
  let line = [];
  let wsum = 0;
  for (const w of words) {
    const ww = ctx.measureText(w + " ").width;
    if (line.length && wsum + ww > maxWidth) {
      lines.push(line);
      line = [];
      wsum = 0;
    }
    line.push(w);
    wsum += ww;
  }
  if (line.length) lines.push(line);
  return lines;
}

function drawSubs(ctx, W, H, text, cue) {
  const st = S.style;
  const fam = fontEntry(st.font);
  const face = fam ? faceName(fam, st.font_style) : `"${st.font}"`;
  const px = st.size * H;
  ctx.save();
  ctx.font = `${px}px ${face}, "${st.font}", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";

  const lines = layout(ctx, text, W, W * 0.86);
  const lh = px * 1.18;
  const cx = st.cx * W;
  const cyBase = (1 - st.cy) * H;
  const total = lines.length;
  const startY = cyBase - ((total - 1) * lh) / 2;

  // animazione reveal parola-per-parola
  let revealCount = Infinity;
  let currentWord = -1;
  if (S.reveal && cue && cue.words && cue.words.length) {
    const dur = Math.max(0.3, (cue.end - cue.start) / (S.info?.fps || 24));
    const t = ((performance.now() - S.t0) / 1000) % (dur + 0.8);
    const p = clamp(t / dur, 0, 1);
    revealCount = Math.ceil(p * cue.words.length);
    currentWord = Math.min(revealCount - 1, cue.words.length - 1);
  }

  let wordIdx = 0;
  lines.forEach((line, li) => {
    const y = startY + li * lh;
    const widths = line.map((w) => ctx.measureText(w + " ").width);
    const totalW = widths.reduce((a, b) => a + b, 0);
    let x = cx - totalW / 2;
    line.forEach((w, wi) => {
      const cw = widths[wi];
      const wx = x + cw / 2;
      const shown = wordIdx < revealCount;
      const isCurrent = wordIdx === currentWord && st.highlight_on;
      if (shown) {
        const fill = isCurrent ? st.highlight : st.fill;
        if (st.shadow_on) {
          ctx.fillStyle = `rgba(${st.shadow.map((v) => Math.round(v * 255)).join(",")},.85)`;
          const dx = (st.shadow_offset?.[0] || 0.004) * H;
          const dy = -(st.shadow_offset?.[1] || -0.004) * H;
          ctx.fillText(w, wx + dx, y + dy);
        }
        if (st.outline_on) {
          ctx.lineWidth = Math.max(1, st.outline_thickness * H);
          ctx.strokeStyle = `rgb(${st.outline.map((v) => Math.round(v * 255)).join(",")})`;
          ctx.lineJoin = "round";
          ctx.strokeText(w, wx, y);
        }
        if (st.fill_on || isCurrent) {
          ctx.fillStyle = `rgb(${fill.map((v) => Math.round(v * 255)).join(",")})`;
          ctx.fillText(w, wx, y);
        }
      }
      x += cw;
      wordIdx++;
    });
  });
  ctx.restore();
}

/* sfondo della preview: trascina un'immagine sul canvas */
function setBackgroundFromFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  const reader = new FileReader();
  reader.onload = () => {
    const img = new Image();
    img.onload = () => { S.still = img; draw(); };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
}
["dragover", "drop"].forEach((ev) =>
  $("preview").addEventListener(ev, (e) => {
    e.preventDefault();
    if (ev === "drop") setBackgroundFromFile(e.dataTransfer.files[0]);
  }));

/* loop per l'anteprima animata */
function tick() {
  if (S.reveal) draw();
  requestAnimationFrame(tick);
}

/* ------------------------------------------------------------------ cue list */
function renderCues() {
  const box = $("cues");
  box.innerHTML = "";
  $("cue-count").textContent = S.cues.length;
  const fps = S.info?.fps || 24;
  S.cues.forEach((c, i) => {
    const row = document.createElement("div");
    row.className = "cue" + (i === S.activeCue ? " active" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = S.selected.has(i);
    cb.onchange = () => {
      cb.checked ? S.selected.add(i) : S.selected.delete(i);
      $("sel-info").textContent = `${S.selected.size} selezionati`;
    };
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = tc(c.start, fps);
    const ta = document.createElement("textarea");
    ta.className = "txt";
    ta.value = c.text;
    ta.rows = 1;
    ta.onfocus = () => { S.activeCue = i; S.t0 = performance.now(); draw(); markActive(); };
    ta.oninput = () => {
      c.text = ta.value;
      const toks = ta.value.trim().split(/\s+/).filter(Boolean);
      if (toks.length && Array.isArray(c.words) && c.words.length === toks.length) {
        c.words = c.words.map((w, idx) => ({ ...w, w: toks[idx] }));
      } else if (toks.length) {
        const span = Math.max(1, (c.end || 1) - (c.start || 0));
        c.words = toks.map((w, idx) => ({
          w,
          s: Math.round((c.start || 0) + (span * idx) / toks.length),
          e: Math.round((c.start || 0) + (span * (idx + 1)) / toks.length),
        }));
      } else {
        c.words = [];
      }
      draw();
      scheduleCuesSave();
    };
    row.append(cb, t, ta);
    row.onclick = (e) => {
      if (e.target === cb) return;
      S.activeCue = i; S.t0 = performance.now(); draw(); markActive();
    };
    box.appendChild(row);
  });
  $("sel-info").textContent = `${S.selected.size} selezionati`;
}
function markActive() {
  [...document.querySelectorAll(".cue")].forEach((el, i) => el.classList.toggle("active", i === S.activeCue));
}
let cuesTimer = null;
function scheduleCuesSave() {
  clearTimeout(cuesTimer);
  cuesTimer = setTimeout(() => postJSON("/api/cues", { cues: S.cues }), 400);
}

/* ------------------------------------------------------------------ azioni */
async function transcribe() {
  const body = {
    mode: $("range-mode").value,
    model: $("model").value,
    language: $("language").value || null,
    max_chars: +$("max-chars").value,
    max_dur: +$("max-dur").value,
  };
  $("btn-transcribe").disabled = true;
  const r = await postJSON("/api/transcribe", body);
  if (!r.ok) {
    $("log").textContent = "ERRORE: " + (r.error || "avvio fallito");
    $("btn-transcribe").disabled = false;
    return;
  }
  pollJob();
}

async function pollJob() {
  const j = await getJSON("/api/job");
  $("bar").style.width = (j.progress * 100).toFixed(1) + "%";
  $("log").textContent = (j.log || []).slice(-8).join("\n");
  if (j.state === "running") {
    setTimeout(pollJob, 700);
  } else {
    $("btn-transcribe").disabled = false;
    const st = await getJSON("/api/state");
    S.cues = st.cues || [];
    S.meta = st.meta || {};
    S.selected.clear();
    S.activeCue = 0;
    renderCues();
    draw();
    await refreshInfo();
  }
}
function pollJobOnce() { if (S.meta && S.cues.length) renderCues(); }

async function applyStyle(target) {
  const btn = target === "all" ? $("btn-apply-all") : $("btn-apply-sel");
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "applico…";
  const frames = target === "selected"
    ? [...S.selected].map((idx) => S.cues[idx]?.start).filter((v) => v != null)
    : undefined;
  const r = await postJSON("/api/apply", { target, style: S.style, frames });
  btn.textContent = label;
  btn.disabled = false;
  if (r.ok) {
    $("log").textContent = `stile applicato a ${r.updated} clip` + (r.errors?.length ? `\n${r.errors.join("\n")}` : "");
  } else {
    $("log").textContent = "ERRORE: " + r.error;
  }
}

async function pushToResolve() {
  if (!S.cues.length) { $("log").textContent = "prima trascrivi qualcosa"; return; }
  const btn = $("btn-push");
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "push…";
  try {
    const dry = await postJSON("/api/push", { dry_run: true });
    if (!dry.ok) throw new Error(dry.error || "errore");
    const trackMsg = dry.create_track
      ? `su una nuova traccia (V${dry.track})`
      : `sulla traccia esistente (V${dry.track})`;
    const copyMsg = $("push-copy").checked ? "\nVerra' creata una copia della timeline." : "";
    const ok = confirm(
      `Inserire ${dry.cues} sottotitoli ${trackMsg}?\n` +
      `Frame ${dry.first} → ${dry.last} (${dry.frames} frame totali).${copyMsg}\n\n` +
      `I clip SubLab già presenti sulla traccia verranno sostituiti.`);
    if (!ok) { $("log").textContent = "push annullato"; return; }
    const r = await postJSON("/api/push", { dry_run: false, on_copy: $("push-copy").checked });
    if (!r.ok) throw new Error(r.error || "errore");
    $("log").textContent = `push: ${r.created}/${r.cues} clip creati, ${r.styled} stilizzati` +
      (r.copied ? `\nTimeline di lavoro: ${r.copied}` : "") +
      (r.backup ? `\nBackup: ${r.backup}` : "") +
      (r.errors?.length ? `\n${r.errors.join("\n")}` : "") +
      `\nRicordati Ctrl+S in Resolve per salvare il progetto.`;
    await refreshInfo();
  } catch (e) {
    $("log").textContent = "ERRORE push: " + e.message;
  } finally {
    btn.textContent = label;
    btn.disabled = false;
  }
}

async function loadStill() {
  const cue = S.cues[S.activeCue];
  const frame = cue ? cue.start : null;
  const r = await getJSON("/api/still" + (frame != null ? `?frame=${frame}` : ""));
  if (!r.ok) {
    $("log").textContent = "Resolve 21.1 non espone i thumbnail via API — " +
      "trascina un'immagine sulla preview per usarla come sfondo.";
    return;
  }
  const img = new Image();
  img.onload = () => { S.still = img; draw(); };
  img.src = "data:image/png;base64," + r.data;
}

/* ------------------------------------------------------------------ wire */
$("btn-transcribe").onclick = transcribe;
$("btn-apply-all").onclick = () => applyStyle("all");
$("btn-apply-sel").onclick = () => applyStyle("selected");
$("btn-push").onclick = pushToResolve;
$("btn-still").onclick = loadStill;
$("btn-safe").onclick = () => { S.showSafe = !S.showSafe; draw(); };
$("reveal-anim").onchange = (e) => { S.reveal = e.target.checked; draw(); };
$("range-mode").onchange = refreshInfo;
$("sel-all").onclick = () => { S.cues.forEach((_, i) => S.selected.add(i)); renderCues(); };
$("sel-none").onclick = () => { S.selected.clear(); renderCues(); };

init().then(() => { tick(); });
