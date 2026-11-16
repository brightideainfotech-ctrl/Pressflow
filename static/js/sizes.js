// Standard paper sizes (cm), shared by the Rate master screens. Anything else is entered as a custom size.
import { state } from "./api.js";
import { h, input, select, num, money } from "./ui.js";

const FALLBACK_SIZES = [
  ["A0", 84.1, 118.9], ["A1", 59.4, 84.1], ["A2", 42, 59.4], ["A3", 29.7, 42], ["A4", 21, 29.7],
  ["A5", 14.8, 21], ["A6", 10.5, 14.8], ["A7", 7.4, 10.5],
  ["B3", 35.3, 50], ["B4", 25, 35.3], ["B5", 17.6, 25],
  ["Letter", 21.6, 27.9], ["Legal", 21.6, 35.6], ["Tabloid / Ledger", 27.9, 43.2], ["Executive", 18.4, 26.7], ["Foolscap", 21.6, 34.3],
  ["Demy", 45.7, 58.4], ["Demy 1/8", 14, 21.6], ["Double Demy", 58.4, 91.4], ["Crown", 38.1, 50.8], ["Royal", 50.8, 63.5],
];
const TOL = 0.1;

/** The Sheet size master ([name, width, height]); built-in list until the master has loaded. */
export const sizeList = () => (state.masters?.sizes?.length ? state.masters.sizes.map((r) => [r.name, r.width_cm, r.height_cm]) : FALLBACK_SIZES);

export const sizeLabel = ([n, w, hh]) => `${n} (${w} × ${hh} cm)`;

/** Name of the standard size matching w x h (either way round), or "" */
export function sizeNameFor(w, hh) {
  const hit = sizeList().find(([, a, b]) => (Math.abs(a - w) <= TOL && Math.abs(b - hh) <= TOL) || (Math.abs(a - hh) <= TOL && Math.abs(b - w) <= TOL));
  return hit ? hit[0] : "";
}

const presetOptions = (blank) => [["", blank], ...sizeList().map((s) => [s[0], sizeLabel(s)]), ["custom", "Custom size…"]];

/** Sheet size field: a standard size or custom width x height. getValue() -> {width_cm, height_cm} */
export function sheetSizeField(values) {
  const w = input("number", values.width_cm > 0 ? values.width_cm : "", { step: "0.01", min: "0", placeholder: "Width (cm)", "aria-label": "Sheet width" });
  const hh = input("number", values.height_cm > 0 ? values.height_cm : "", { step: "0.01", min: "0", placeholder: "Height (cm)", "aria-label": "Sheet height" });
  const known = values.width_cm > 0 ? sizeNameFor(values.width_cm, values.height_cm) : "";
  const sel = select(presetOptions("No fixed size (reel / kg paper)"), known || (values.width_cm > 0 ? "custom" : ""), { "aria-label": "Sheet size", searchable: true });
  sel.addEventListener("change", () => {
    const p = sizeList().find((s) => s[0] === sel.value);
    if (p) { w.value = p[1]; hh.value = p[2]; } else if (sel.value === "") { w.value = ""; hh.value = ""; }
    w.disabled = hh.disabled = !!p;
  });
  w.disabled = hh.disabled = !!known;
  const el = h("div", { class: "row", style: { gap: ".5rem" } }, sel, w, hh);
  el.getValue = () => ({ width_cm: w.value === "" ? 0 : Number(w.value), height_cm: hh.value === "" ? 0 : Number(hh.value) });
  return el;
}

/** Table of "kg per 100 sheets" per size. rows: [{name,width_cm,height_cm,kg_per_100}]. getValue() -> list */
export function weightsEditor(initial) {
  const rows = initial.map((r) => ({ ...r }));
  const box = h("div");
  const draw = () => {
    box.replaceChildren();
    const table = h("table", null,
      h("thead", null, h("tr", null, ["Paper size", "Width (cm)", "Height (cm)", "kg per 100 sheets", ""].map((t) => h("th", null, t)))),
      h("tbody", null, rows.map((r, i) => {
        const std = r.width_cm > 0 ? sizeNameFor(r.width_cm, r.height_cm) : "";
        const sel = select(presetOptions("Choose a size…"), std || (r.width_cm > 0 || r.custom ? "custom" : ""), { "aria-label": "Paper size", searchable: true });
        const w = input("number", r.width_cm || "", { step: "any", min: "0", placeholder: "Width (cm)", "aria-label": "Width" });
        const hh = input("number", r.height_cm || "", { step: "any", min: "0", placeholder: "Height (cm)", "aria-label": "Height" });
        const kg = input("number", r.kg_per_100 || "", { step: "any", min: "0", placeholder: "kg", "aria-label": "kg per 100 sheets" });
        w.style.width = hh.style.width = "5.5rem"; kg.style.width = "6rem";
        w.disabled = hh.disabled = !!std;
        sel.addEventListener("change", () => {
          const p = sizeList().find((s) => s[0] === sel.value);
          if (p) { r.name = p[0]; r.width_cm = p[1]; r.height_cm = p[2]; r.custom = false; }
          else if (sel.value === "custom") { r.name = "Custom"; r.custom = true; }
          else { r.name = ""; r.width_cm = ""; r.height_cm = ""; r.custom = false; }
          draw();
        });
        w.addEventListener("input", () => { r.width_cm = w.value; });
        hh.addEventListener("input", () => { r.height_cm = hh.value; });
        kg.addEventListener("input", () => { r.kg_per_100 = kg.value; });
        return h("tr", null, h("td", null, sel), h("td", null, w), h("td", null, hh), h("td", null, kg),
          h("td", null, h("button", { class: "btn small danger", type: "button", onclick: () => { rows.splice(i, 1); draw(); } }, "Remove")));
      })));
    box.append(h("div", { class: "tablewrap" }, table),
      h("button", { class: "btn small", type: "button", style: { marginTop: ".5rem" }, onclick: () => { rows.push({ name: "", width_cm: "", height_cm: "", kg_per_100: "" }); draw(); } }, "+ Add size"));
  };
  draw();
  const el = h("div", null, box);
  el.getValue = () => rows.filter((r) => r.width_cm || r.height_cm || r.kg_per_100)
    .map((r) => ({ name: r.name || sizeNameFor(Number(r.width_cm), Number(r.height_cm)) || "Custom", width_cm: Number(r.width_cm), height_cm: Number(r.height_cm), kg_per_100: Number(r.kg_per_100) }));
  return el;
}


/**
 * Best-sheet-size table. parts: from /api/suggest-sizes. opts: {money: show paper cost, onApply(part, option)}.
 * The lowest wastage comes first; a size the part already uses is marked.
 */
export function sizeSuggestions(parts, { money: showMoney = false, onApply } = {}) {
  if (!parts.length) return h("p", { class: "muted small" }, "Nothing to suggest yet.");
  return h("div", null, parts.map((p) => {
    const best = p.best, cur = p.current;
    const saving = best && cur && !best.is_current && cur.paper_cost != null && best.paper_cost != null ? cur.paper_cost - best.paper_cost : null;
    const verdict = !best ? "No sheet size in your master fits this page size."
      : best.is_current ? `The sheet already used (${cur.name}) is the best fit: ${best.utilisation_pct}% of it is used.`
      : cur ? `${best.name} wastes ${best.waste_pct}% against ${cur.waste_pct}% on ${cur.name}.` + (saving > 0.5 && showMoney ? ` Paper could cost about ₹${num(Math.round(saving))} less.` : "")
      : `Best fit: ${best.name}, ${best.utilisation_pct}% of the sheet used.`;
    return h("div", { class: "sizesug" }, h("div", { class: "small" }, h("b", null, p.name), ` · ${p.paper}`),
      h("div", { class: "small muted", style: { margin: ".15rem 0 .4rem" } }, verdict),
      p.options.length ? h("div", { class: "tablewrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Sheet", "Ups", "Used", "Waste", "Sheets", showMoney ? "Paper cost" : null, onApply ? "" : null].filter((x) => x !== null).map((t, i) => h("th", { class: i >= 1 && i <= 5 ? "num" : "" }, t)))),
        h("tbody", null, p.options.map((o, i) => h("tr", { class: i === 0 ? "best" : "" },
          h("td", null, h("b", null, o.name), h("div", { class: "small muted" }, `${o.width_cm} × ${o.height_cm} cm`), o.is_current ? h("span", { class: "badge s-plates" }, "in use") : null, i === 0 ? [" ", h("span", { class: "badge s-ready" }, "least waste")] : null),
          h("td", { class: "num" }, o.ups), h("td", { class: "num" }, o.utilisation_pct + "%"), h("td", { class: "num" }, o.waste_pct + "%"),
          h("td", { class: "num" }, o.sheets == null ? "—" : num(o.sheets)),
          showMoney ? h("td", { class: "num" }, o.paper_cost == null ? "—" : money(o.paper_cost)) : null,
          onApply ? h("td", { class: "right" }, o.is_current ? null : h("button", { class: "btn small", type: "button", onclick: () => onApply(p, o) }, "Use this size")) : null))))) : null);
  }));
}
