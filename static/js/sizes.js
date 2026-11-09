// Standard paper sizes (inches), shared by the Rate master screens. Anything else is entered as a custom size.
import { h, input, select } from "./ui.js";

export const PAPER_SIZES = [
  ["A0", 33.11, 46.81], ["A1", 23.39, 33.11], ["A2", 16.54, 23.39], ["A3", 11.69, 16.54], ["A4", 8.27, 11.69],
  ["A5", 5.83, 8.27], ["A6", 4.13, 5.83], ["A7", 2.91, 4.13],
  ["B3", 13.9, 19.69], ["B4", 9.84, 13.9], ["B5", 6.93, 9.84],
  ["Letter", 8.5, 11], ["Legal", 8.5, 14], ["Tabloid / Ledger", 11, 17], ["Executive", 7.25, 10.5], ["Foolscap", 8.5, 13.5],
  ["Demy", 18, 23], ["Demy 1/8", 5.5, 8.5], ["Double Demy", 23, 36], ["Crown", 15, 20], ["Royal", 20, 25],
];
const TOL = 0.02;

export const sizeLabel = ([n, w, hh]) => `${n} (${w} × ${hh} in)`;

/** Name of the standard size matching w x h (either way round), or "" */
export function sizeNameFor(w, hh) {
  const hit = PAPER_SIZES.find(([, a, b]) => (Math.abs(a - w) <= TOL && Math.abs(b - hh) <= TOL) || (Math.abs(a - hh) <= TOL && Math.abs(b - w) <= TOL));
  return hit ? hit[0] : "";
}

const presetOptions = (blank) => [["", blank], ...PAPER_SIZES.map((s) => [s[0], sizeLabel(s)]), ["custom", "Custom size…"]];

/** Sheet size field: a standard size or custom width x height. getValue() -> {width_in, height_in} */
export function sheetSizeField(values) {
  const w = input("number", values.width_in > 0 ? values.width_in : "", { step: "0.01", min: "0", placeholder: "Width (in)", "aria-label": "Sheet width" });
  const hh = input("number", values.height_in > 0 ? values.height_in : "", { step: "0.01", min: "0", placeholder: "Height (in)", "aria-label": "Sheet height" });
  const known = values.width_in > 0 ? sizeNameFor(values.width_in, values.height_in) : "";
  const sel = select(presetOptions("No fixed size (reel / kg paper)"), known || (values.width_in > 0 ? "custom" : ""), { "aria-label": "Sheet size" });
  sel.addEventListener("change", () => {
    const p = PAPER_SIZES.find((s) => s[0] === sel.value);
    if (p) { w.value = p[1]; hh.value = p[2]; } else if (sel.value === "") { w.value = ""; hh.value = ""; }
    w.disabled = hh.disabled = !!p;
  });
  w.disabled = hh.disabled = !!known;
  const el = h("div", { class: "row", style: { gap: ".5rem" } }, sel, w, hh);
  el.getValue = () => ({ width_in: w.value === "" ? 0 : Number(w.value), height_in: hh.value === "" ? 0 : Number(hh.value) });
  return el;
}

/** Table of "kg per 100 sheets" per size. rows: [{name,width_in,height_in,kg_per_100}]. getValue() -> list */
export function weightsEditor(initial) {
  const rows = initial.map((r) => ({ ...r }));
  const box = h("div");
  const draw = () => {
    box.replaceChildren();
    const table = h("table", null,
      h("thead", null, h("tr", null, ["Paper size", "Width (in)", "Height (in)", "kg per 100 sheets", ""].map((t) => h("th", null, t)))),
      h("tbody", null, rows.map((r, i) => {
        const std = r.width_in > 0 ? sizeNameFor(r.width_in, r.height_in) : "";
        const sel = select(presetOptions("Choose a size…"), std || (r.width_in > 0 || r.custom ? "custom" : ""), { "aria-label": "Paper size" });
        const w = input("number", r.width_in || "", { step: "any", min: "0", placeholder: "Width", "aria-label": "Width" });
        const hh = input("number", r.height_in || "", { step: "any", min: "0", placeholder: "Height", "aria-label": "Height" });
        const kg = input("number", r.kg_per_100 || "", { step: "any", min: "0", placeholder: "kg", "aria-label": "kg per 100 sheets" });
        w.style.width = hh.style.width = "5.5rem"; kg.style.width = "6rem";
        w.disabled = hh.disabled = !!std;
        sel.addEventListener("change", () => {
          const p = PAPER_SIZES.find((s) => s[0] === sel.value);
          if (p) { r.name = p[0]; r.width_in = p[1]; r.height_in = p[2]; r.custom = false; }
          else if (sel.value === "custom") { r.name = "Custom"; r.custom = true; }
          else { r.name = ""; r.width_in = ""; r.height_in = ""; r.custom = false; }
          draw();
        });
        w.addEventListener("input", () => { r.width_in = w.value; });
        hh.addEventListener("input", () => { r.height_in = hh.value; });
        kg.addEventListener("input", () => { r.kg_per_100 = kg.value; });
        return h("tr", null, h("td", null, sel), h("td", null, w), h("td", null, hh), h("td", null, kg),
          h("td", null, h("button", { class: "btn small danger", type: "button", onclick: () => { rows.splice(i, 1); draw(); } }, "Remove")));
      })));
    box.append(h("div", { class: "tablewrap" }, table),
      h("button", { class: "btn small", type: "button", style: { marginTop: ".5rem" }, onclick: () => { rows.push({ name: "", width_in: "", height_in: "", kg_per_100: "" }); draw(); } }, "+ Add size"));
  };
  draw();
  const el = h("div", null, box);
  el.getValue = () => rows.filter((r) => r.width_in || r.height_in || r.kg_per_100)
    .map((r) => ({ name: r.name || sizeNameFor(Number(r.width_in), Number(r.height_in)) || "Custom", width_in: Number(r.width_in), height_in: Number(r.height_in), kg_per_100: Number(r.kg_per_100) }));
  return el;
}
