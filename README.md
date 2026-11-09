# PrintFlow for the press: quotation and job tracking

Replaces the paper work order (St. Joseph's Orphanage Press form, 2026-27) with:

1. **Quotation / estimate calculator**: paper, plates, machine time, binding and finishing are priced from an editable rate master, with mark-up, discount and GST. Printable customer quotation and a separate internal cost breakdown.
2. **Job tracking**: an approved quotation becomes a job (work order) that moves through the agreed flow:
   Quotation → Approved → Design / Proof → Plates → Printing → Binding / Finishing → Ready → Delivered → Billed.
   Every move is logged with who and when. Board view, overdue and due-soon flags, notes for the team.
3. **Assignment and monitoring**: every job is held by one named person (for example the designer), who hands it to the next person or department with an instruction. The holder reports percent-done and notes; the manager's **Team monitor** shows who has what, how far along it is, how long it has sat in a stage, and recent activity.
4. **Inventory**: paper reels (kg), sheets, plates, ink and other stock, with receipts, issues to jobs, recounts, history and low-stock warnings. Jobs show the paper they need against what has been issued.
5. **Printable work order** laid out like the paper form (customer, paper, plates, machine and binding tick boxes, advance, receipt and bill numbers, signatures).

The interface follows the PrintFlow demo: navy sidebar (Overview, Estimates & quotes, Production jobs, Production line, Team monitor, Items & stock, the Accounts group (Parties, Sales, Purchases, Payments, Reports), then Customers, Rate master, Settings, Users), stat tiles, a stage-by-stage Production line board, and a login page in the same style. Operators land on the Production line.

No installs needed: Python 3.11+ standard library only, SQLite database, plain JavaScript front end.

## Run it

```
cd press-app
python3 -m press.server                 # http://127.0.0.1:8000
python3 -m press.server --demo          # same, with sample customers, quotes and jobs
python3 -m press.server --host 0.0.0.0  # let other computers on the press network connect
```

On the first run a manager account (`admin`) is created and its password is printed once.
Set `PRESS_ADMIN_PASSWORD` to choose it yourself. Demo users (`desk`, `super`, `operator`) all use
`demo-pass-1`; use `--demo` on a test machine only.

Data lives in `data/press.db`. Back that one file up daily.

Tests: `python3 -m pytest tests`

## Roles

| Role | Can do |
|---|---|
| manager | everything: rates, settings, users, quotations, all stages, Team monitor, stock |
| desk | customers, quotations, create jobs, assign jobs, edit job details, billing and delivery stages, receive/recount stock |
| superintendent | edit job details and move jobs through approval and production stages, assign jobs (no prices) |
| operator | see jobs and the work order (no prices); report progress on, and hand over, the jobs they hold; move jobs through design/proof, plates, printing, finishing and ready; take stock for a job |

## IMPORTANT: replace the sample rates

The paper, machine and finishing rates are **placeholders** so the app works on day one. A banner
stays on the dashboard until the manager opens **Rates**, enters the press's real figures and clicks
"I have set my real rates". Until then, quotations do not reflect real costs.

## How an estimate is calculated

Per printed part (text, cover, end paper):

- pages per sheet side ("ups") from page size and parent sheet size, or typed in by hand
- sheets per copy = pages / (2 × ups); plate sets = ceil of that
- sheets issued = copies × sheets per copy + wastage % + make-ready sheets
- paper cost = sheets × rate per ream / 500, **or** for reel / kg-priced paper: weight × rate per kg,
  where weight of a sheet (kg) = width × height (in) × 0.00064516 × GSM / 1000. With no sheet size, the page
  area is used instead. Or the press can enter its **own kg per 100 sheets for each size** (Rate master >
  Paper > My weights per size) and the estimate uses that figure for the matching size.
- plates = sets × sides × colours (offset machines only) × plate rate
- printing = max(minimum charge, impressions × rate per 1000 + set-up per plate)

Then binding/finishing lines (per copy, per 1000, per sq ft, per unit, flat, **per 1000 printed sheets** or **per 1000 leaves**; sheet and leaf items can be set to one part such as an insert, and have a *times* multiplier for several folds), design charge and
other charges are added to give **cost**; **mark-up %**, discount and **GST** follow; the total is
rounded to the rupee. "Compare other quantities" prices the same job at other copy counts.

Because the press's own method is not yet known, every number above is a setting in Rates or Settings.
If their method differs (for example, a fixed rate per form), the formulas are in
`press/estimator.py`, which is pure functions with its own tests, and easy to change.

## Layout

```
press/estimator.py   pricing maths (no database, no HTTP)
press/db.py          schema, sample rates, running numbers (Q-202627-0001, J-202627-0001)
press/auth.py        scrypt password hashes, sessions
press/api.py         JSON API and role checks (jobs, assignment, monitor, inventory)
press/server.py      HTTP server + static files
press/demo.py        demo data
static/              single-page front end (no build step)
tests/               estimator and API tests
```

## Before going live

- Put it behind HTTPS if it is reachable outside the press office network.
- Change the admin password and create a login for each person.
- Set company address, phone and GSTIN in **Settings** (printed on quotations).


## Basic accounting

Parties (customers and suppliers, with opening balances and state), items with HSN/GST/prices (the same list as the stock page),
sales invoices, purchase bills, payments, and reports. Sales invoices take stock out and purchase bills add it. A job can be
turned into an invoice from its page ("Create invoice"). GST is CGST+SGST when the party's state equals the press's state
(Settings), otherwise IGST. Invoices cannot be edited: cancel (stock is put back) and create again. A bill with payments must have
the payments deleted first.

Reports: sales and purchase registers, customers owe you / you owe suppliers (with ageing), stock summary and value, GST summary
with HSN, profit and loss (an estimate: stock is valued at each item's latest buying price), daybook, and party statements.
Set your logo in Settings; it is printed on quotations, work orders, invoices, statements and reports.

Limits: no double-entry ledger, bank reconciliation, credit/debit notes, TDS or e-invoicing. Have your accountant check the GST
figures before filing.
