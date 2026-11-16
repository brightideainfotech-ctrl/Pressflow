// Standard paper sizes (cm), shared by the Rate master screens. Anything else is entered as a custom size.
import { h, input, select } from "./ui.js";

export const PAPER_SIZES = [
  ["A0", 84.1, 118.9], ["A1", 59.4, 84.1], ["A2", 42, 59.4], ["A3", 29.7, 42], ["A4", 21, 29.7],
  ["A5", 14.8, 21], ["A6", 10.5, 14.8], ["A7", 7.4, 10.5],
  ["B3", 35.3, 50], ["B4", 25, 35.3], ["B5", 17.6, 25],
  ["Letter", 21.6, 27.9], ["Legal", 21.6, 35.6], ["Tabloid / Ledger", 27.9, 43.2], ["Executive", 18.4, 26.7], ["Foolscap", 21.6, 34.3],
  ["Demy", 45.7, 58.4], ["Demy 1/8", 14, 21.6], ["Double Demy", 58.4, 91.4], ["Crown", 38.1, 50.8], ["Royal", 50.8, 63.5],
];
const TOL = 0.1;

export const sizeLabel = ([n, w, hh]) => `${n} (${w} × ${hh} cm)`;

/** Name of the standard size matching w x h (either way round), or "" */
export function sizeNameFor(w, hh) {
  const hit = PAPER_SIZES.find(([, a, b]) => (Math.abs(a - w) <= TOL && Math.abs(b - hh) <= TOL) || (Math.abs(a - hh) <= TOL && Math.abs(b - w) <= TOL));
  return hit ? hit[0] : "";
}

const presetOptions = (blank) => [["", blank], ...PAPER_SIZES.map((s) => [s[0], sizeLabel(s)]), ["custom", "Custom size…"]];

/** Sheet size field: a standard size or custom width x height. getValue() -> {width_cm, height_cm} */
export function sheetSizeField(values) {
  const w = input("number", values.width_cm > 0 ? values.width_cm : "", { step: "0.01", min: "0", placeholder: "Width (cm)", "aria-label": "Sheet width" });
  const hh = input("number", values.height_cm > 0 ? values.height_cm : "", { step: "0.01", min: "0", placeholder: "Height (cm)", "aria-label": "Sheet height" });
  const known = values.width_cm > 0 ? sizeNameFor(values.width_cm, values.height_cm) : "";
  const sel = select(presetOptions("No fixed size (reel / kg paper)"), known || (values.width_cm > 0 ? "custom" : ""), { "aria-label": "Sheet size" });
  sel.addEventListener("change", () => {
    const p = PAPER_SIZES.find((s) => s[0] === sel.value);
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
        const sel = select(presetOptions("Choose a size…"), std || (r.width_cm > 0 || r.custom ? "custom" : ""), { "aria-label": "Paper size" });
        const w = input("number", r.width_cm || "", { step: "any", min: "0", placeholder: "Width (cm)", "aria-label": "Width" });
        const hh = input("number", r.height_cm || "", { step: "any", min: "0", placeholder: "Height (cm)", "aria-label": "Height" });
        const kg = input("number", r.kg_per_100 || "", { step: "any", min: "0", placeholder: "kg", "aria-label": "kg per 100 sheets" });
        w.style.width = hh.style.width = "5.5rem"; kg.style.width = "6rem";
        w.disabled = hh.disabled = !!std;
        sel.addEventListener("change", () => {
          const p = PAPER_SIZES.find((s) => s[0] === sel.value);
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
