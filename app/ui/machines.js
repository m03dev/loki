// Settings > Machines - link this Loki with your other machines (harness/peer_link.py).
// The PC turns on "Let my other machines link"; it shows a link code. Paste that code on
// the Mac. From then on the Mac can see the PC, give it jobs, and send it verified work
// to train on. Uses api(), el() and addNotice() from app.js.
"use strict";

const machines = { timer: 0 };

function machineRow(peer) {
  const r = el("div", "row manifest");
  const top = el("div", "row-top");
  const hello = peer.hello || {};
  const gpu = hello.machine && hello.machine.gpu;
  top.append(el("b", "", peer.name + "  "), el("span", "state" + (peer.ok ? " ready" : ""),
    peer.ok ? "connected (" + peer.ms + " ms)" : "not reachable"));
  r.append(top);
  if (!peer.ok) {
    r.append(el("div", "why", peer.error || ""));
    return r;
  }
  const facts = [];
  if (hello.machine) facts.push(hello.machine.os + " " + (hello.machine.arch || ""));
  if (gpu) facts.push(gpu.name + " - " + gpu.used_mb + "/" + gpu.total_mb + " MB, " + gpu.util + "% busy");
  if (hello.ollama_models && hello.ollama_models.length) facts.push("models: " + hello.ollama_models.slice(0, 6).join(", "));
  const ex = hello.experience || {};
  facts.push("verified examples: " + (ex.trajectories || 0) + " (" + (hello.new_examples || 0) + " new since last training)");
  if (hello.tuned_promoted) facts.push("trained model in use: " + hello.tuned_model);
  for (const f of facts) r.append(el("div", "desc", f));

  const form = el("form", "connect-row");
  const input = el("input");
  input.placeholder = "Give " + peer.name + " a background job...";
  input.setAttribute("aria-label", "Job for " + peer.name);
  const go = el("button", "", "Send");
  go.type = "submit";
  const out = el("div", "note");
  form.append(input, go);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = input.value.trim();
    if (!prompt) return;
    go.disabled = true;
    const result = await api("/peers/jobs", { peer: peer.name, prompt });
    go.disabled = false;
    if (!result.ok) { out.textContent = result.error || "Could not send the job."; return; }
    input.value = "";
    const job = result.job || {};
    out.textContent = "Started on " + peer.name + ": " + (job.title || "") + " (" + (job.status || "queued") + ")";
    watchJob(peer.name, job.id, out);
  });
  r.append(form, out);

  const unlink = el("button", "quiet", "Unlink");
  unlink.type = "button";
  unlink.addEventListener("click", async () => {
    if (!confirm("Unlink " + peer.name + "?")) return;
    await api("/peers/unlink", { name: peer.name });
    loadMachines();
  });
  r.append(unlink);
  return r;
}

async function watchJob(peerName, jobId, out) {
  for (let i = 0; i < 720 && jobId; i += 1) {
    await new Promise((done) => setTimeout(done, 5000));
    if ($("#settings").hidden) return;
    const result = await api("/peers/jobs/status", { peer: peerName, id: jobId }).catch(() => null);
    const job = result && result.job;
    if (!job) continue;
    out.textContent = peerName + ": " + job.title + " - " + job.status +
      (job.output ? "\n" + String(job.output).slice(-600) : "") + (job.error ? "\n" + job.error : "");
    if (["done", "failed", "cancelled"].includes(job.status)) return;
  }
}

async function loadMachines() {
  const box = $("#machines-panel");
  box.replaceChildren(el("p", "note", "Checking your machines..."));
  const data = await api("/peers").catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) {
    box.append(el("p", "why", (data && data.error) || "The engine did not answer."));
    return;
  }
  box.append(el("p", "note", "This machine: " + data.me + (data.trainer ? " - sends verified work to " + data.trainer + " to train on" : "")));

  // The listening side (the PC): show its link code.
  const listen = el("div", "row manifest");
  const label = el("label");
  const toggle = el("input");
  toggle.type = "checkbox";
  toggle.checked = Boolean(data.listening);
  label.append(toggle, document.createTextNode(" Let my other machines link to this one"));
  listen.append(label);
  if (data.listening && data.link_code) {
    listen.append(el("div", "desc", "Link code - paste it into Loki on your other machine (Settings > Machines):"));
    const code = el("textarea", "memory");
    code.rows = 3;
    code.readOnly = true;
    code.value = data.link_code;
    code.addEventListener("focus", () => code.select());
    listen.append(code, el("div", "why", "Keep this private: it lets a machine on your network use this Loki."));
  }
  toggle.addEventListener("change", async () => {
    const result = await api("/peers/listen", { on: toggle.checked });
    if (!result.ok) addNotice(result.error || "Could not change that.", true);
    else if (result.note) addNotice(result.note, false);
    loadMachines();
  });
  box.append(listen);

  // The talking side (the Mac): paste a code.
  const link = el("form", "connect");
  link.append(el("h3", "", "Link another machine"));
  const row2 = el("div", "connect-row");
  const codeIn = el("input");
  codeIn.placeholder = "loki-link:...";
  codeIn.setAttribute("aria-label", "Link code");
  const add = el("button", "", "Link");
  add.type = "submit";
  row2.append(codeIn, add);
  const msg = el("p", "note");
  link.append(row2, msg);
  link.addEventListener("submit", async (event) => {
    event.preventDefault();
    const result = await api("/peers/link", { code: codeIn.value.trim() });
    if (!result.ok) { msg.textContent = result.error || "Could not link."; return; }
    msg.textContent = result.warning ? "Linked " + result.linked + ", but: " + result.warning : "Linked " + result.linked + ".";
    codeIn.value = "";
    loadMachines();
  });
  box.append(link);

  for (const peer of data.peers || []) box.append(machineRow(peer));

  if ((data.peers || []).length) {
    const sync = el("button", "quiet", "Send verified work now");
    sync.type = "button";
    const note = el("p", "note");
    const last = data.last_sync || {};
    if (last.t) note.textContent = "Last sync " + new Date(last.t * 1000).toLocaleTimeString() +
      (last.pushed && last.pushed.sent !== undefined ? " - sent " + last.pushed.sent : "") +
      (last.note ? " - " + last.note : "") + (last.error ? " - " + last.error : "");
    sync.addEventListener("click", async () => {
      sync.disabled = true;
      const result = await api("/peers/sync", {});
      sync.disabled = false;
      const pushed = result.pushed || {};
      note.textContent = result.error ? result.error : "Sent " + (pushed.sent || 0) + " verified example(s)." + (result.note ? " " + result.note : "");
    });
    box.append(sync, note);
  }
}
