// Settings > CRM: LOKI's built-in CRM (engine/crm.py). GET /crm returns the pipeline and the
// lists; POST /crm/<op> adds, updates, deletes. Plain DOM only (CSP: script-src 'self').
"use strict";

const crmState = { data: null };

function crmInput(name, placeholder, type) {
  const input = el("input");
  input.name = name;
  input.placeholder = placeholder;
  input.type = type || "text";
  input.setAttribute("aria-label", placeholder);
  return input;
}

function crmSelect(name, options, labels) {
  const select = el("select");
  select.name = name;
  select.setAttribute("aria-label", name);
  for (const value of options) {
    const opt = el("option", "", (labels && labels[value]) || value);
    opt.value = value;
    select.append(opt);
  }
  return select;
}

function crmMoney(values) {
  const parts = Object.entries(values || {}).map(([cur, v]) => cur + " " + Number(v).toLocaleString());
  return parts.length ? parts.join(", ") : "0";
}

function crmCompanyOptions() {
  const companies = (crmState.data && crmState.data.companies) || [];
  const values = [""].concat(companies.map((c) => String(c.id)));
  const labels = { "": "No company" };
  for (const c of companies) labels[String(c.id)] = c.name;
  return [values, labels];
}

// A one-line form: fields, then an Add button that posts /crm/add {type, fields}.
function crmForm(type, controls, buttonText) {
  const form = el("form", "crm-form");
  for (const c of controls) form.append(c);
  const add = el("button", "", buttonText || "Add");
  add.type = "submit";
  form.append(add);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fields = {};
    for (const c of controls) if (c.name && c.value !== "") fields[c.name] = c.value;
    const result = await api("/crm/add", { type, fields }).catch(() => null);
    if (!result || !result.ok) { addNotice((result && result.error) || "Could not add that.", true); return; }
    loadCrm();
  });
  return form;
}

function crmDelete(type, id, label) {
  const b = el("button", "quiet", "Delete");
  b.type = "button";
  b.setAttribute("aria-label", "Delete " + label);
  b.addEventListener("click", async () => {
    if (!confirm("Delete " + label + " from the CRM?")) return;
    const result = await api("/crm/delete", { type, id }).catch(() => null);
    if (!result || !result.ok) addNotice((result && result.error) || "Could not delete that.", true);
    loadCrm();
  });
  return b;
}

function crmSection(title, count) {
  const section = el("section", "crm-section");
  section.append(el("h4", "", title + (count !== undefined ? " (" + count + ")" : "")));
  return section;
}

function renderCrm() {
  const box = $("#crm-panel");
  if (!box) return;
  box.replaceChildren();
  const data = crmState.data;
  if (!data) { box.append(el("p", "note", "The CRM is not available right now.")); return; }
  const p = data.pipeline;
  const companyName = {};
  for (const c of data.companies || []) companyName[c.id] = c.name;

  const summary = el("div", "crm-summary");
  summary.append(el("b", "", p.open_deals + " open deal" + (p.open_deals === 1 ? "" : "s")),
    el("span", "", " worth " + crmMoney(p.open_value) + " · won " + crmMoney(p.won_value)
      + " · win rate " + (p.win_rate === null ? "n/a" : Math.round(p.win_rate * 100) + "%")
      + " · " + p.open_tasks + " open task" + (p.open_tasks === 1 ? "" : "s")
      + (p.overdue_tasks.length ? " (" + p.overdue_tasks.length + " overdue)" : "")));
  const stages = el("div", "crm-stages");
  for (const stage of data.stages) {
    const info = p.stages[stage] || { count: 0, value: {} };
    stages.append(el("span", "pill", stage + " " + info.count));
  }
  box.append(summary, stages);

  // Deals
  const deals = crmSection("Deals", (data.deals || []).length);
  const dealRows = el("div", "rows");
  for (const d of data.deals || []) {
    const r = el("div", "row crm-row");
    const left = el("span", "", d.title + (d.company_id && companyName[d.company_id] ? " · " + companyName[d.company_id] : ""));
    const right = el("span", "crm-row-actions");
    const stage = crmSelect("stage", data.stages);
    stage.value = d.stage;
    stage.setAttribute("aria-label", "Stage of " + d.title);
    stage.addEventListener("change", async () => {
      const result = await api("/crm/update", { type: "deals", id: d.id, fields: { stage: stage.value } }).catch(() => null);
      if (!result || !result.ok) addNotice((result && result.error) || "Could not move that deal.", true);
      loadCrm();
    });
    right.append(el("span", "state", d.currency + " " + Number(d.value || 0).toLocaleString()), stage,
      crmDelete("deals", d.id, d.title));
    r.append(left, right);
    dealRows.append(r);
  }
  const [companyValues, companyLabels] = crmCompanyOptions();
  const value = crmInput("value", "Value", "number");
  value.min = "0";
  value.step = "any";
  deals.append(dealRows, crmForm("deals", [crmInput("title", "Deal title"), crmSelect("company_id", companyValues, companyLabels),
    crmSelect("stage", data.stages), value, crmInput("currency", "Currency (USD)")], "Add deal"));

  // Contacts
  const contacts = crmSection("Contacts", (data.contacts || []).length);
  const contactRows = el("div", "rows");
  for (const c of data.contacts || []) {
    const r = el("div", "row crm-row");
    const bits = [c.email, c.phone, c.company_id && companyName[c.company_id]].filter(Boolean).join(" · ");
    r.append(el("span", "", c.name + (c.title ? " (" + c.title + ")" : "")),
      el("span", "crm-row-actions"));
    r.lastChild.append(el("span", "state", bits), crmDelete("contacts", c.id, c.name));
    contactRows.append(r);
  }
  contacts.append(contactRows, crmForm("contacts", [crmInput("name", "Name"), crmInput("email", "Email", "email"),
    crmInput("phone", "Phone"), crmSelect("company_id", companyValues, companyLabels)], "Add contact"));

  // Companies
  const companies = crmSection("Companies", (data.companies || []).length);
  const companyRows = el("div", "rows");
  for (const c of data.companies || []) {
    const r = el("div", "row crm-row");
    r.append(el("span", "", c.name), el("span", "crm-row-actions"));
    r.lastChild.append(el("span", "state", c.website || c.industry || ""), crmDelete("companies", c.id, c.name));
    companyRows.append(r);
  }
  companies.append(companyRows, crmForm("companies", [crmInput("name", "Company name"), crmInput("website", "Website"),
    crmInput("industry", "Industry")], "Add company"));

  // Tasks
  const tasks = crmSection("Tasks", (data.tasks || []).length);
  const taskRows = el("div", "rows");
  for (const t of data.tasks || []) {
    const r = el("div", "row crm-row" + (t.done ? " done" : ""));
    const label = el("label");
    const box2 = el("input");
    box2.type = "checkbox";
    box2.checked = Boolean(t.done);
    box2.addEventListener("change", async () => {
      await api("/crm/update", { type: "tasks", id: t.id, fields: { done: box2.checked } }).catch(() => null);
      loadCrm();
    });
    label.append(box2, document.createTextNode(" " + t.title));
    r.append(label, el("span", "crm-row-actions"));
    r.lastChild.append(el("span", "state", t.due ? "due " + t.due : ""), crmDelete("tasks", t.id, t.title));
    taskRows.append(r);
  }
  tasks.append(taskRows, crmForm("tasks", [crmInput("title", "Task"), crmInput("due", "Due", "date")], "Add task"));

  box.append(deals, contacts, companies, tasks);
}

async function loadCrm() {
  const data = await api("/crm").catch(() => null);
  crmState.data = data && data.ok ? data : null;
  renderCrm();
}
