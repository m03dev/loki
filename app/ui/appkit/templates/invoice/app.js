// Invoices - line items, tax, totals; saved as a file; track paid and unpaid.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const S = { me: {}, invoices: [], open: null };

async function load() {
  S.me = await loki.store.get("business", { name: "", address: "", email: "", currency: "USD", tax: 0, terms: "Due within 14 days" });
  S.invoices = await loki.store.get("invoices", []);
  render();
}
const save = () => Promise.all([loki.store.set("business", S.me), loki.store.set("invoices", S.invoices)]);
const money = (n, inv) => kit.money(n, (inv && inv.currency) || S.me.currency || "USD");
const totals = (inv) => {
  const sub = kit.sum(inv.items, (i) => (Number(i.qty) || 0) * (Number(i.price) || 0));
  const tax = sub * (Number(inv.tax) || 0) / 100;
  return { sub, tax, total: sub + tax };
};

function nextNumber() {
  const n = S.invoices.reduce((m, i) => Math.max(m, parseInt(String(i.number).replace(/\D/g, ""), 10) || 0), 0) + 1;
  return "INV-" + String(n).padStart(4, "0");
}

async function newInvoice() {
  const inv = { id: kit.uid(), number: nextNumber(), date: kit.today(), client: "", clientAddress: "", items: [{ id: kit.uid(), text: "", qty: 1, price: 0 }],
    tax: S.me.tax || 0, currency: S.me.currency || "USD", notes: S.me.terms || "", paid: false };
  S.invoices.unshift(inv);
  S.open = inv.id;
  await save();
  render();
}

async function businessDetails() {
  const v = await kit.form("Your business", [
    { name: "name", label: "Business name", value: S.me.name, required: true },
    { name: "address", label: "Address", type: "textarea", value: S.me.address },
    { name: "email", label: "Email", value: S.me.email },
    { name: "currency", label: "Currency (USD, EUR, GBP...)", value: S.me.currency },
    { name: "tax", label: "Default tax %", type: "number", value: S.me.tax },
    { name: "terms", label: "Default payment terms", value: S.me.terms },
  ], "Save");
  if (!v) return;
  Object.assign(S.me, v, { currency: String(v.currency || "USD").toUpperCase().slice(0, 3), tax: Number(v.tax) || 0 });
  await save();
  render();
}

function invoiceText(inv) {
  const t = totals(inv);
  const lines = [S.me.name || "Your business", S.me.address || "", S.me.email || "", "", "INVOICE " + inv.number, "Date: " + inv.date, "", "Bill to:", inv.client, inv.clientAddress || "", ""];
  for (const i of inv.items) if (i.text) lines.push(i.text + "  " + i.qty + " x " + money(i.price, inv) + " = " + money(i.qty * i.price, inv));
  lines.push("", "Subtotal: " + money(t.sub, inv), "Tax (" + (inv.tax || 0) + "%): " + money(t.tax, inv), "TOTAL: " + money(t.total, inv), "", inv.notes || "");
  return lines.join("\n");
}

function invoiceHtml(inv) {
  const t = totals(inv);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const rows = inv.items.filter((i) => i.text).map((i) => "<tr><td>" + esc(i.text) + "</td><td style='text-align:right'>" + esc(i.qty) + "</td><td style='text-align:right'>" + esc(money(i.price, inv)) + "</td><td style='text-align:right'>" + esc(money(i.qty * i.price, inv)) + "</td></tr>").join("");
  return "<!doctype html><meta charset='utf-8'><title>" + esc(inv.number) + "</title><body style='font:14px/1.5 system-ui;max-width:720px;margin:40px auto;color:#111'>"
    + "<div style='display:flex;justify-content:space-between'><div><b style='font-size:18px'>" + esc(S.me.name) + "</b><br>" + esc(S.me.address).replace(/\n/g, "<br>") + "<br>" + esc(S.me.email) + "</div>"
    + "<div style='text-align:right'><b style='font-size:22px'>INVOICE</b><br>" + esc(inv.number) + "<br>" + esc(inv.date) + "</div></div><p><b>Bill to</b><br>" + esc(inv.client) + "<br>" + esc(inv.clientAddress).replace(/\n/g, "<br>") + "</p>"
    + "<table style='width:100%;border-collapse:collapse'><tr style='border-bottom:1px solid #ccc'><th align=left>Item</th><th align=right>Qty</th><th align=right>Price</th><th align=right>Amount</th></tr>" + rows + "</table>"
    + "<p style='text-align:right'>Subtotal " + esc(money(t.sub, inv)) + "<br>Tax (" + esc(inv.tax || 0) + "%) " + esc(money(t.tax, inv)) + "<br><b style='font-size:18px'>Total " + esc(money(t.total, inv)) + "</b></p><p>" + esc(inv.notes) + "</p></body>";
}

async function saveFile(inv) {
  const saved = await loki.files.save(inv.number + ".html", invoiceHtml(inv), { type: "text/html" });
  if (saved) kit.toast("Saved " + saved.name + " - open it and print to PDF", "ok");
}

function editor(inv) {
  const t = totals(inv);
  const bind = (obj, key, num) => ({ input: kit.debounce(async (e) => { obj[key] = num ? Number(e.target.value) || 0 : e.target.value; await save(); updateTotals(); }, 300) });
  const totalBox = h("div", { class: "lk-col lk-right", style: { gap: "2px" } });
  function updateTotals() {
    const x = totals(inv);
    kit.mount(totalBox, h("span", { class: "lk-muted" }, "Subtotal " + money(x.sub, inv)), h("span", { class: "lk-muted" }, "Tax " + money(x.tax, inv)), h("b", { style: { fontSize: "20px" } }, "Total " + money(x.total, inv)));
  }
  updateTotals();
  const items = h("tbody", {}, inv.items.map((i) => h("tr", {},
    h("td", {}, kit.input({ value: i.text, placeholder: "Design work", on: bind(i, "text") })),
    h("td", { style: { width: "80px" } }, kit.input({ type: "number", value: i.qty, on: bind(i, "qty", true) })),
    h("td", { style: { width: "120px" } }, kit.input({ type: "number", value: i.price, step: "0.01", on: bind(i, "price", true) })),
    h("td", {}, kit.button("✕", async () => { inv.items = inv.items.filter((x) => x.id !== i.id); await save(); render(); }, "ghost sm")))));
  return [kit.header("🧾", inv.number, (inv.client || "No client yet") + " · " + money(t.total, inv),
    kit.button("‹ All invoices", () => { S.open = null; render(); }, "ghost"), kit.button("Save as file", () => saveFile(inv)),
    kit.button(inv.paid ? "Mark unpaid" : "Mark paid", async () => { inv.paid = !inv.paid; await save(); render(); }, inv.paid ? "" : "primary")),
  h("div", { class: "lk-grid two" },
    kit.card("Bill to", kit.field("Client", kit.input({ value: inv.client, on: bind(inv, "client") })), kit.field("Client address", h("textarea", { class: "lk-textarea", on: bind(inv, "clientAddress") }, inv.clientAddress || ""))),
    kit.card("Details", kit.field("Date", kit.input({ type: "date", value: inv.date, on: bind(inv, "date") })), kit.field("Tax %", kit.input({ type: "number", value: inv.tax, on: bind(inv, "tax", true) })),
      kit.field("Notes / payment terms", kit.input({ value: inv.notes, on: bind(inv, "notes") })))),
  kit.card("Items", h("table", { class: "lk-table" }, h("thead", {}, h("tr", {}, h("th", {}, "Item"), h("th", {}, "Qty"), h("th", {}, "Price"), h("th", {}))), items),
    h("div", { class: "lk-row" }, kit.button("+ Line", async () => { inv.items.push({ id: kit.uid(), text: "", qty: 1, price: 0 }); await save(); render(); }, "sm"), h("span", { class: "lk-spacer" }), totalBox)),
  h("div", { class: "lk-row" }, kit.button("Delete invoice", async () => { if (await kit.confirm("Delete " + inv.number + "?", { ok: "Delete", danger: true })) { S.invoices = S.invoices.filter((x) => x.id !== inv.id); S.open = null; await save(); render(); } }, "ghost danger sm"),
    kit.button("Copy as text (ask LOKI to email it)", () => kit.askLoki("Write a short, polite email to send this invoice to the client.", { invoice: invoiceText(inv) }), "ghost sm"))];
}

function render() {
  const open = S.invoices.find((i) => i.id === S.open);
  if (open) return mount(root, editor(open));
  const unpaid = S.invoices.filter((i) => !i.paid);
  mount(root,
    kit.header("🧾", "Invoices", S.me.name || "Set your business details first", kit.button("Business details", businessDetails), kit.button("+ Invoice", newInvoice, "primary")),
    h("div", { class: "lk-grid stats" }, kit.stat("Unpaid", kit.money(kit.sum(unpaid, (i) => totals(i).total), S.me.currency), unpaid.length + " invoices", unpaid.length ? "bad" : ""),
      kit.stat("Paid", kit.money(kit.sum(S.invoices.filter((i) => i.paid), (i) => totals(i).total), S.me.currency), "", "good")),
    kit.card(null, S.invoices.length ? h("table", { class: "lk-table" }, h("thead", {}, h("tr", {}, h("th", {}, "Number"), h("th", {}, "Client"), h("th", {}, "Date"), h("th", { class: "lk-num" }, "Total"), h("th", {}))),
      h("tbody", {}, S.invoices.map((i) => h("tr", { style: { cursor: "pointer" }, on: { click: () => { S.open = i.id; render(); } } },
        h("td", {}, h("b", {}, i.number)), h("td", {}, i.client || "—"), h("td", { class: "lk-muted" }, kit.date(i.date)),
        h("td", { class: "lk-num" }, money(totals(i).total, i)), h("td", { class: "lk-right" }, h("span", { class: "lk-tag " + (i.paid ? "ok" : "warn") }, i.paid ? "paid" : "unpaid"))))))
      : kit.empty("🧾", "No invoices yet.", "Make an invoice", newInvoice)));
}

loki.ready(load);
