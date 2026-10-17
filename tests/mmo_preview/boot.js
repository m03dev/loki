// The preview's stand-ins for app.js: state, api() and el(). api() asks the preview server
// (tests/mmo_preview/serve.py), which answers with fake LOKI data.
"use strict";
const state = { token: "preview" };
async function api(path, body) {
  const init = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, init);
  return r.json();
}
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
