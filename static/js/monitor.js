import { get, stageLabel } from "./api.js";
import { h, add, badge, fail, fmtDate, fmtDateTime, emptyState } from "./ui.js";
import { progressBar } from "./jobs.js";

const ago = (stamp) => {
  if (!stamp) return "";
  const t = new Date(stamp.replace(" ", "T")).getTime();
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 48) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} days ago`;
};
const daysSince = (stamp) => (stamp ? (Date.now() - new Date(stamp.replace(" ", "T")).getTime()) / 86400000 : 0);

export async function renderMonitor(view) {
  let d;
  try { d = await get("/api/monitor"); } catch (e) { return fail(e); }

  const jobRow = (j) => h("tr", { class: "clickable", onclick: () => (location.hash = `#/jobs/${j.id}`) },
    h("td", { class: "nowrap" }, h("b", { style: { color: "var(--accent)" } }, j.order_no), j.priority === "urgent" ? h("span", { class: "flag" }, " !") : null),
    h("td", null, j.title, h("div", { class: "small muted" }, j.customer_name)),
    h("td", null, badge(j.stage, stageLabel(j.stage)), h("div", { class: "small " + (daysSince(j.stage_changed_at) > 3 ? "flag" : "muted") }, "in stage " + ago(j.stage_changed_at).replace(" ago", ""))),
    h("td", { style: { minWidth: "120px" } }, progressBar(j.progress_pct), h("span", { class: "small muted" }, `${j.progress_pct || 0}%`)),
    h("td", { class: "nowrap" }, h("span", { class: j.overdue ? "flag" : "" }, fmtDate(j.delivery_date) || "—")),
    h("td", { class: "small muted" }, ago(j.last_activity)));
  const head = h("thead", null, h("tr", null, ["Order", "Job", "Stage", "Progress", "Due", "Last update"].map((t) => h("th", null, t))));

  const busy = d.people.filter((p) => p.jobs.length);
  const idle = d.people.filter((p) => !p.jobs.length);
  add(view,
    h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Workspace"), h("h1", null, "Team monitor"),
      h("div", { class: "sub" }, `${d.open_jobs} open jobs. Who holds each one, how far along it is, and what happened last.`))),
    d.unassigned.length ? h("div", { class: "card" }, h("h2", null, `Not assigned to anyone (${d.unassigned.length})`),
      h("div", { class: "tablewrap" }, h("table", null, head, h("tbody", null, d.unassigned.map(jobRow))))) : null,
    busy.map((p) => h("div", { class: "card" }, h("h2", null, p.name, h("span", { class: "muted", style: { fontWeight: 400 } }, ` · ${p.department || p.role} · ${p.jobs.length} job${p.jobs.length > 1 ? "s" : ""}`)),
      h("div", { class: "tablewrap" }, h("table", null, head, h("tbody", null, p.jobs.map(jobRow)))))),
    idle.length ? h("div", { class: "card" }, h("h2", null, "No jobs right now"),
      h("p", null, idle.map((p) => `${p.name}${p.department ? " (" + p.department + ")" : ""}`).join(" · "))) : null,
    h("div", { class: "card" }, h("h2", null, "Recent activity"),
      d.activity.length ? h("ul", { class: "timeline" }, d.activity.map((e) => h("li", null,
        h("div", null, h("a", { href: `#/jobs/${e.job_id}` }, h("strong", null, e.order_no)), " — ", e.kind === "stage" ? `moved to ${stageLabel(e.stage)}` : e.note || e.kind, e.kind === "stage" && e.note ? ": " + e.note : ""),
        h("div", { class: "at" }, `${e.user_name || "System"} · ${fmtDateTime(e.at)}`)))) : emptyState("No activity yet")));
}
