// Small DOM helpers. Everything is built with textContent/createElement, never innerHTML,
// so data from the database can never be interpreted as markup.

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  let value;
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "value") value = v;
      else if (["checked", "disabled", "selected", "readOnly", "required"].includes(k)) el[k] = !!v;
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  if (value !== undefined) el.value = value;  // after children, so <select> options exist
  return el;
}

// Safe append: flattens arrays and skips null/false (the native append() prints "null" and "[object ...]").
export function add(el, ...kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

export function debounce(fn, ms = 350) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
export const money = (n) => inr.format(Number(n) || 0);
export const money0 = (n) => inr0.format(Number(n) || 0);
export const num = (n) => new Intl.NumberFormat("en-IN").format(Number(n) || 0);

export function fmtDate(s) {
  if (!s) return "";
  const [y, m, d] = String(s).slice(0, 10).split("-").map(Number);
  if (!y) return s;
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}
export function fmtDateTime(s) {
  if (!s) return "";
  const [date, time] = String(s).split(" ");
  return fmtDate(date) + (time ? " " + time.slice(0, 5) : "");
}
export function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const badge = (cls, text) => h("span", { class: `badge s-${cls}` }, text);

// ---- toasts
let toastBox;
export function toast(message, isError = false) {
  if (!toastBox) { toastBox = h("div", { class: "toasts", role: "status", "aria-live": "polite" }); document.body.append(toastBox); }
  const t = h("div", { class: "toast" + (isError ? " err" : "") }, message);
  toastBox.append(t);
  setTimeout(() => t.remove(), isError ? 6000 : 3000);
}
export const fail = (e) => toast(e && e.message ? e.message : String(e), true);

// ---- modal
export function modal(title, content, { footer, onClose } = {}) {
  const close = () => { document.removeEventListener("keydown", onKey); overlay.remove(); if (onClose) onClose(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const box = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
    h("h2", null, title), content, footer ? h("div", { class: "foot" }, footer) : null);
  const overlay = h("div", { class: "overlay", onmousedown: (e) => { if (e.target === overlay) close(); } }, box);
  document.addEventListener("keydown", onKey);
  document.body.append(overlay);
  const first = box.querySelector("input:not([type=hidden]), select, textarea");
  if (first) first.focus();
  return { close, box };
}

export function confirmBox(title, message, okText = "Confirm", danger = false) {
  return new Promise((resolve) => {
    let m;
    const done = (v) => { m.close(); resolve(v); };
    m = modal(title, h("p", null, message), {
      footer: [h("button", { class: "btn", onclick: () => done(false) }, "Cancel"),
               h("button", { class: "btn " + (danger ? "danger" : "primary"), onclick: () => done(true) }, okText)],
      onClose: () => resolve(false),
    });
  });
}

// ---- form fields
export function field(label, input, help) {
  return h("label", { class: "f" }, h("span", { class: "lbl" }, label), input, help ? h("div", { class: "help" }, help) : null);
}

export function input(type, value, attrs = {}) {
  return h("input", { type, value: value ?? "", ...attrs });
}

export function select(options, value, attrs = {}) {
  // options: [[value, label], ...]
  return h("select", { value: value ?? "", ...attrs },
    options.map(([v, l]) => h("option", { value: v }, l)));
}

/**
 * Generic form dialog.
 * fields: [{key,label,type:'text'|'number'|'select'|'checkbox'|'textarea'|'password'|'date', options, step, required, help, hint}]
 */
export function formModal({ title, fields, values = {}, submitText = "Save", onSubmit }) {
  const inputs = {};
  const errBox = h("div", { class: "errbox hidden", role: "alert" });
  const rows = fields.map((f) => {
    let el;
    const v = values[f.key];
    if (f.type === "select") el = select(f.options, v, { required: f.required });
    else if (f.type === "checkbox") el = h("input", { type: "checkbox", checked: v === undefined ? !!f.default : !!v });
    else if (f.type === "textarea") el = h("textarea", { value: v ?? "" });
    else if (f.type === "custom") el = f.render(values);
    else el = input(f.type || "text", v, { step: f.step, min: f.min, required: f.required, autocomplete: f.type === "password" ? "new-password" : "off" });
    inputs[f.key] = el;
    if (f.type === "checkbox") return h("label", { class: "check", style: { marginBottom: ".6rem" } }, el, f.label);
    const wrap = field(f.label, el, f.help);
    if (f.full) wrap.style.gridColumn = "1 / -1";
    return wrap;
  });
  const form = h("form", null, errBox, h("div", { class: "row" }, rows));
  let m;
  const save = async (e) => {
    e.preventDefault();
    const out = {};
    for (const f of fields) {
      const el = inputs[f.key];
      if (f.type === "custom") { const val = el.getValue(); if (f.merge) Object.assign(out, val); else out[f.key] = val; }
      else if (f.type === "checkbox") out[f.key] = el.checked;
      else if (f.type === "number") out[f.key] = el.value === "" ? "" : Number(el.value);
      else out[f.key] = el.value;
    }
    saveBtn.disabled = true;
    try { await onSubmit(out); m.close(); }
    catch (err) { errBox.textContent = err.message; errBox.classList.remove("hidden"); saveBtn.disabled = false; }
  };
  const saveBtn = h("button", { class: "btn primary", type: "submit" }, submitText);
  form.addEventListener("submit", save);
  m = modal(title, form, { footer: [h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Cancel"), saveBtn] });
  saveBtn.addEventListener("click", (e) => { e.preventDefault(); form.requestSubmit(); });
  return m;
}

export function emptyState(text) { return h("div", { class: "empty" }, text); }
