// The few app.js helpers lab.js uses (api, el, row, addNotice), for the preview page only.
"use strict";
const state = { token: "preview" };
async function api(path, body) {
  const init = { headers: { Authorization: "Bearer " + state.token } };
  if (body !== undefined) { init.method = "POST"; init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
  const r = await fetch(path, init);
  return r.json();
}
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function row(label, status, ready) {
  const r = el("div", "row");
  r.append(el("span", "", label), el("span", "state" + (ready ? " ready" : ""), status));
  return r;
}
window.notices = [];
function addNotice(text, bad) { window.notices.push((bad ? "ERR " : "") + text); }
