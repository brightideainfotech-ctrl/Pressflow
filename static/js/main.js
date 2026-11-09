import { state, api, get, post, put, loadBootstrap, setToken, getToken, isOffice, isManager, stageLabel } from "./api.js";
import { h, add, clear, badge, field, input, formModal, toast, fail, money0, num, fmtDate, emptyState } from "./ui.js";
import { renderQuoteList, renderQuoteEditor, renderQuoteView } from "./quotes.js";
import { renderJobs, renderJobView, progressBar } from "./jobs.js";
import { renderInventory } from "./inventory.js";
import { renderMonitor } from "./monitor.js";
import { renderCustomers, renderRates, renderUsers, renderSettings } from "./masters.js";

const app = document.getElementById("app");
let main = null;

const OFFICE = ["manager", "desk"];
const NAV = [
  ["WORKSPACE"],
  ["Overview", "#/", "dash", null, "▦"],
  ["Estimates & quotes", "#/quotes", "quotes", OFFICE, "₹"],
  ["Production jobs", "#/jobs", "jobs", null, "▤"],
  ["Production line", "#/line", "line", null, "⇢"],
  ["Team monitor", "#/monitor", "monitor", ["manager"], "◉"],
  ["Inventory", "#/stock", "stock", ["manager", "desk", "superintendent", "operator"], "▥"],
  ["MASTER DATA"],
  ["Customers", "#/customers", "customers", OFFICE, "♙"],
  ["Rate master", "#/rates", "rates", ["manager"], "▧"],
  ["Settings", "#/settings", "settings", ["manager"], "⚙"],
  ["Users", "#/users", "users", ["manager"], "◫"],
];
const ROUTES = [
  { rx: /^\/$/, fn: renderDashboard, nav: "dash" },
  { rx: /^\/quotes$/, fn: renderQuoteList, nav: "quotes", roles: OFFICE },
  { rx: /^\/quotes\/new$/, fn: (v) => renderQuoteEditor(v, null), nav: "quotes", roles: OFFICE },
  { rx: /^\/quotes\/(\d+)\/edit$/, fn: (v, id) => renderQuoteEditor(v, Number(id)), nav: "quotes", roles: OFFICE },
  { rx: /^\/quotes\/(\d+)$/, fn: (v, id) => renderQuoteView(v, Number(id)), nav: "quotes", roles: OFFICE },
  { rx: /^\/jobs$/, fn: (v) => renderJobs(v, "list"), nav: "jobs" },
  { rx: /^\/line$/, fn: (v) => renderJobs(v, "board"), nav: "line" },
  { rx: /^\/jobs\/(\d+)$/, fn: (v, id) => renderJobView(v, Number(id)), nav: "jobs" },
  { rx: /^\/monitor$/, fn: renderMonitor, nav: "monitor", roles: ["manager"] },
  { rx: /^\/stock$/, fn: renderInventory, nav: "stock" },
  { rx: /^\/customers$/, fn: renderCustomers, nav: "customers", roles: OFFICE },
  { rx: /^\/rates$/, fn: renderRates, nav: "rates", roles: ["manager"] },
  { rx: /^\/settings$/, fn: renderSettings, nav: "settings", roles: ["manager"] },
  { rx: /^\/users$/, fn: renderUsers, nav: "users", roles: ["manager"] },
];

// ------------------------------------------------------------------ login / shell

function showLogin(message) {
  clear(app);
  state.user = null;
  const err = h("div", { class: "errbox" + (message ? "" : " hidden"), role: "alert" }, message || "");
  const user = input("text", "", { autocomplete: "username", required: true, autocapitalize: "none" });
  const pass = input("password", "", { autocomplete: "current-password", required: true });
  const btn = h("button", { class: "btn primary", type: "submit", style: { width: "100%" } }, "Sign in");
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true;
      try {
        const r = await post("/api/login", { username: user.value, password: pass.value });
        setToken(r.token);
        await start();
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden"); btn.disabled = false; pass.value = "";
      }
    },
  }, err, field("Username", user), field("Password", pass), btn);
  add(app, h("div", { class: "loginpage" }, h("div", { class: "loginbox" },
    h("div", { class: "brand" }, h("div", { class: "logo" }, "P"), h("div", null, h("b", null, "PrintFlow"), h("small", null, "PRINT PRODUCTION OS"))),
    h("h1", null, "Welcome back"), h("p", { class: "muted", style: { marginTop: 0 } }, "Sign in to manage quotations, jobs and production."), form)));
  user.focus();
}

let content = null;

function buildShell() {
  clear(app);
  const role = state.user.role;
  const nav = h("nav", { class: "nav", "aria-label": "Main" });
  let pending = null;
  for (const [label, href, key, roles, ico] of NAV) {
    if (!href) { pending = h("div", { class: "navlabel" }, label); continue; }
    if (roles && !roles.includes(role)) continue;
    if (pending) { add(nav, pending); pending = null; }
    add(nav, h("a", { href, "data-nav": key }, h("span", { class: "ico" }, ico), label));
  }

  const drop = h("div", { class: "drop hidden" },
    h("button", { onclick: () => { drop.classList.add("hidden"); changePassword(); } }, "Change password"),
    h("button", { onclick: logout }, "Sign out"));
  const initials = state.user.name.split(/\s+/).map((x) => x[0]).slice(0, 2).join("").toUpperCase();
  const toggle = h("button", { class: "userbtn", "aria-haspopup": "true", onclick: () => drop.classList.toggle("hidden") },
    h("span", { class: "avatar" }, initials), h("span", { class: "who" }, h("b", null, state.user.name), h("small", null, role)));
  document.addEventListener("click", (e) => { if (!e.target.closest(".usermenu")) drop.classList.add("hidden"); });

  const company = state.settings.company_name || "Press Desk";
  content = h("div", { class: "content" });
  add(app, h("div", { class: "layout" },
    h("aside", { class: "sidebar no-print" },
      h("a", { class: "brand", href: "#/" }, h("div", { class: "logo" }, company[0].toUpperCase()), h("div", null, h("b", null, company), h("small", null, "PRINT PRODUCTION OS"))),
      nav,
      h("div", { class: "sidebarfoot" }, "Quotations, work orders and", h("br"), "production tracking")),
    h("div", { class: "mainwrap" },
      h("header", { class: "topbar no-print" },
        h("div", { class: "crumb" }, "Workspace / ", h("b", { id: "crumbName" }, "Overview")),
        h("div", { class: "usermenu" }, toggle, drop)),
      content)));
}

function changePassword() {
  formModal({
    title: "Change password",
    fields: [
      { key: "current", label: "Current password", type: "password", required: true },
      { key: "new", label: "New password", type: "password", required: true, help: "At least 8 characters" },
    ],
    onSubmit: async (v) => { await post("/api/me/password", v); toast("Password changed"); },
  });
}

async function logout() {
  try { await post("/api/logout"); } catch { /* already signed out */ }
  setToken("");
  showLogin();
}

// ------------------------------------------------------------------ router

function setMain() {
  main = h("main", { id: "view" });
  clear(content);
  add(content, main);
  return main;
}

async function route() {
  if (!state.user) return;
  let path = location.hash.slice(1) || "/";
  if (path === "/" && state.user.role === "operator") path = "/line";
  path = path.split("?")[0].replace(/\/+$/, "") || "/";
  const view = setMain();
  let match = null;
  const r = ROUTES.find((x) => (match = x.rx.exec(path)));
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", !!r && a.dataset.nav === r.nav));
  const crumb = document.getElementById("crumbName");
  const navItem = r && NAV.find((n) => n[2] === r.nav);
  if (crumb && navItem) crumb.textContent = navItem[0];
  if (!r) return add(view, h("div", { class: "card" }, h("h2", null, "Page not found"), h("a", { href: "#/" }, "Go to dashboard")));
  if (r.roles && !r.roles.includes(state.user.role)) {
    return add(view, h("div", { class: "card" }, h("h2", null, "Not available"), h("p", null, "Your role does not have access to this page.")));
  }
  window.scrollTo(0, 0);
  try { await r.fn(view, ...match.slice(1)); }
  catch (e) {
    if (e.status === 401) return;
    add(view, h("div", { class: "card" }, h("div", { class: "errbox" }, e.message), h("a", { href: "#/" }, "Back to dashboard")));
  }
}

async function start() {
  try { await loadBootstrap(); } catch (e) { setToken(""); return showLogin(e.status === 401 ? "" : e.message); }
  buildShell();
  await route();
}

window.addEventListener("hashchange", route);
window.addEventListener("press:signed-out", () => { setToken(""); showLogin("You were signed out. Please sign in again."); });

// ------------------------------------------------------------------ dashboard

function pageHead(title, sub, actions) {
  return h("div", { class: "pagehead" },
    h("div", null, h("div", { class: "eyebrow" }, "Workspace"), h("h1", null, title), sub ? h("div", { class: "sub" }, sub) : null),
    actions ? h("div", { class: "actions" }, actions) : null);
}

async function renderDashboard(view) {
  const d = await get("/api/dashboard");
  const office = isOffice();
  const hr = new Date().getHours();
  const greet = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
  add(view, pageHead("Production overview", `${greet}, ${state.user.name.split(" ")[0]}. Here is what is happening across the press.`,
    office ? h("a", { class: "btn primary", href: "#/quotes/new" }, "+ New quotation") : null));

  if (office && state.settings.rates_confirmed !== "1") {
    const b = h("div", { class: "banner" },
      h("span", null, "The paper, machine and finishing rates are still the built-in SAMPLE values. Quotations will not match your real costs until the rates are replaced."));
    if (isManager()) {
      add(b, h("a", { class: "btn small", href: "#/rates" }, "Review rates"),
        h("button", { class: "btn small", onclick: async () => { await put("/api/settings", { rates_confirmed: true }); state.settings.rates_confirmed = "1"; b.remove(); } }, "I have set my real rates"));
    } else add(b, h("span", null, "Ask the manager to review them."));
    add(view, b);
  }

  const stat = (label, n, sub, alert, href, dot) => {
    const el = h("div", { class: "stat" + (alert ? " alert" : "") },
      h("div", { class: "lbl" }, label, h("i", { style: dot ? { background: dot } : {} })), h("div", { class: "n" }, n), sub ? h("div", { class: "small muted" }, sub) : null);
    return href ? h("a", { href, style: { textDecoration: "none", color: "inherit" } }, el) : el;
  };
  const stats = [
    stat("Active jobs", num(d.open_jobs), "Across all stages", false, "#/jobs", "#8ca5ff"),
    stat("Overdue", num(d.overdue.length), d.overdue.length ? "Needs attention" : "All on time", d.overdue.length > 0, "#/jobs", "#c24141"),
    stat("Ready for delivery", num(d.ready_for_delivery), "Prioritise dispatch", false, "#/line", "#14866d"),
  ];
  if (office) {
    stats.push(
      stat("Quotes awaiting reply", num(d.quotes.awaiting_reply.n), money0(d.quotes.awaiting_reply.value), false, "#/quotes", "#e0a526"),
      stat("Draft quotes", num(d.quotes.draft), "Not yet sent", false, "#/quotes", "#a58bf0"),
      stat("Accepted, no job yet", num(d.quotes.accepted_not_started), "Create the job", d.quotes.accepted_not_started > 0, "#/quotes", "#e0a526"),
      stat("Jobs this month", num(d.month.n), money0(d.month.value) + " incl. GST", false, null, "#8ca5ff"),
      stat("Balance on ready/delivered", money0(d.balance_due), "Collect on delivery", false, null, "#14866d"),
    );
  }
  if (isManager()) stats.push(stat("Not assigned", num(d.unassigned), d.unassigned ? "Give these to someone" : "Everything has an owner", d.unassigned > 0, "#/monitor", "#a58bf0"));
  if (d.low_stock) stats.push(stat("Low stock", num(d.low_stock.length), d.low_stock.length ? d.low_stock.slice(0, 2).map((x) => x.name).join(", ") : "All above warning level", d.low_stock.length > 0, "#/stock", "#c24141"));
  add(view, h("div", { class: "stats" }, stats));
  if (d.my_jobs.length) add(view, h("div", { class: "card" }, h("h2", null, `My jobs (${d.my_jobs.length})`),
    h("div", { class: "tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Order", "Job", "Customer", "Stage", "Progress", "Due"].map((t) => h("th", null, t)))),
      h("tbody", null, d.my_jobs.map((j) => h("tr", { class: "clickable", onclick: () => (location.hash = `#/jobs/${j.id}`) },
        h("td", { class: "nowrap" }, h("b", { style: { color: "var(--accent)" } }, j.order_no)), h("td", null, j.title), h("td", null, j.customer_name),
        h("td", null, badge(j.stage, stageLabel(j.stage))), h("td", { style: { minWidth: "110px" } }, progressBar(j.progress_pct)),
        h("td", { class: "nowrap" }, fmtDate(j.delivery_date)))))))));

  const stages = state.stages.filter((s) => s.key !== "cancelled");
  const peak = Math.max(1, ...stages.map((s) => d.by_stage[s.key] || 0));
  const byStage = h("div", { class: "card" }, h("h2", null, "Work by stage"),
    h("div", { class: "bars" }, stages.map((s) => {
      const n = d.by_stage[s.key] || 0;
      return h("a", { class: "wbar", href: "#/line", style: { textDecoration: "none", color: "inherit" } },
        h("span", null, s.label), h("span", { class: "track" }, h("span", { class: "fill", style: { display: "block", width: (n / peak * 100) + "%" } })), h("b", null, String(n)));
    })));

  const list = (title, items) => h("div", { class: "card" }, h("h2", null, title),
    items.length ? h("div", { class: "tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Order", "Job", "Customer", "Stage", "Due"].map((t) => h("th", null, t)))),
      h("tbody", null, items.map((j) => h("tr", { class: "clickable", onclick: () => (location.hash = `#/jobs/${j.id}`) },
        h("td", { class: "nowrap" }, h("b", { style: { color: "var(--accent)" } }, j.order_no)), h("td", null, j.title), h("td", null, j.customer_name),
        h("td", null, badge(j.stage, stageLabel(j.stage))), h("td", { class: "nowrap" }, fmtDate(j.delivery_date))))))) : emptyState("Nothing here"));
  add(view, h("div", { class: "cols two" }, h("div", null, list("Overdue", d.overdue), list("Due in the next 3 days", d.due_soon)), byStage));
}

if (getToken()) start(); else showLogin();
