# Financing Playbook Assessment Tool — Design

Date: 2026-08-29
Status: approved design, pending implementation plan
Classification: architectural (new project)

## 1. Summary

A single-analyst, web-based tool that reproduces the Financing Playbook assessment
shown in the reference dashboard. The analyst uploads a CSV or Excel questionnaire,
the tool validates it, runs a deterministic scoring engine, and renders the
assessment detail view with a financing scheme recommendation.

The defining requirement is that **the questionnaire structure will change**. The
design meets this by putting every field definition, weight, band and scheme rule in
versioned config files, and keeping Python responsible only for a small closed set
of rule primitives.

## 2. Scope

### In scope for v1

| Screen | Behaviour |
|---|---|
| Upload | CSV or Excel, both layouts (§5), validation report before save |
| Assessments | Local list of saved cases; open, duplicate, delete |
| Assessment Detail | The 11 panels of the reference dashboard |
| Scenario Analysis | Re-run the engine with modified inputs, diff against saved result |
| Data Library | Read-only city CRI and open-data benchmarks used for pre-fill |
| Reports | Export one assessment to standalone HTML and to Excel |

### Out of scope for v1

Authentication and multi-user access; Case Management (stakeholder records, status,
follow-ups); Financing Providers as a managed registry; a UI for editing scoring
rules; respondent-facing data collection; PDF generation.

## 3. Source material and its status

Three workbooks in `resouce/` are the reference for behaviour:

| File | Role |
|---|---|
| `Financing_Playbook_Questionnaire_UPDATED.xlsx` | The engine: 12 sheets, 152 formulas. Chain: Questionnaire → Scoring → TCO → Economic Readiness → Scheme Match → Dashboard → Playbook. Contains the scheme library and the OD1–OD14 open-data list. |
| `Financing_Playbook_Respondent_Questionnaire.xlsx` | The data-entry form: 11 sections, ~70 answerable fields in a single column `D`, data dictionary. |
| `Financing_Playbook_Raw_Data_Dashboard.xlsx` | The reference dashboard's data, long-format (Section / Indicator / Value / Unit / Source), 131 indicators. |

**These are treated as a draft thinking tool, not a specification.** Section 11 lists
every point where the implementation deliberately diverges, with the evidence. The
governing rule: where a formula is documented in the workbooks, adopt it verbatim;
where a value is labelled "Calculated" but no formula exists anywhere, define it
explicitly and record it as a new decision.

## 4. Architecture

Five units. The arrow direction is the dependency direction; nothing on the left
knows about anything on the right.

```
 config/*.yaml ──┐
                 ├─> ingest ──> CaseRecord ──┐
 upload file ────┘   (readers + resolver)     │
                                              ├─> engine ──> AssessmentResult ──┬─> ui (Streamlit)
 data_library (SQLite: CRI, benchmarks) ──────┘        │                        └─> export
                                          pure functions, no I/O
```

**ingest** — Two readers plus the alias resolver (§5). Returns a typed `CaseRecord`
and a list of validation issues. Holds no scoring knowledge.

**engine** — `score(record, config, context) -> AssessmentResult`. Pure functions:
no file access, no database, no `import streamlit` anywhere in the module. This is
what makes the scoring claims testable, and is the property that makes Scenario
Analysis nearly free.

**data_library** — SQLite via the stdlib `sqlite3` driver. Reference tables (city CRI
per year, open-data benchmarks with source and date) and the saved-assessment store.
DuckDB was considered and rejected: no query here needs it, and it is one fewer
dependency.

**ui** — Streamlit. Renders `AssessmentResult`; contains no arithmetic.

**export** — Renders the same `AssessmentResult` to standalone HTML, and to an Excel
workbook in the 131-row long format of `Raw_Data_Master`. HTML rather than PDF
because it renders identically without a headless-browser dependency; browser
print-to-PDF covers the case where a PDF is needed.

Stack: Python 3.11, Streamlit, pandas + openpyxl, SQLite, Plotly, pytest, PyYAML.

## 5. Field specification and ingestion

### 5.1 The problem being solved

The two workbooks number the same concepts differently. `Financing_Playbook_Questionnaire_UPDATED`
uses `FN1`, `RP2a`, `TC6`, `SF3`. `Financing_Playbook_Respondent_Questionnaire` uses
`2.1`, `3.3`, `6.3`, `7.3`. Roughly 70 answerable fields, two vocabularies, neither
stable.

The respondent form is also not self-enforcing: of ~86 answerable cells, only 9 carry
a data validation. The rest accept free text. So the platform must own the field
vocabulary rather than inherit it from whoever typed into Excel.

### 5.2 Canonical slugs and aliases

The spec defines a canonical slug once. Every file layout becomes a set of aliases
pointing at it.

```yaml
# config/questionnaire.yaml   spec_version: 2026-01
sections:
  - id: financing_need
    title: "2. Financing Need"
    fields:
      - slug: fn_external_need
        label: "External Financing Need"
        type: likert_5              # integer, 1..5
        required: true
        scoring_role: financing_need
        weight: 0.25
        aliases:
          form_column_d: "2.1"      # respondent-workbook layout
          master_id: FN1            # engine-workbook layout
          csv: external_financing_need
      - slug: rp_ownership
        type: likert_5
        aliases: { form_column_d: "3.1", master_id: RP1, csv: ownership_preference }
```

Field types: `likert_5`, `numeric` (with unit and plausible range), `choice` (with
the allowed option list — the authoritative vocabulary), `date`, `text`.
`routing` conditions such as `applies_when: scope in [cold_chain, both]` mark fields
that are legitimately absent.

### 5.3 Readers

Both readers are dumb and emit the same `{alias: value}` object:

- **form reader** — locates the section number in column `B` of the respondent
  workbook, reads column `D`. One case per file.
- **flat reader** — maps CSV/XLSX headers. Many cases per file.

One resolver translates aliases to slugs, validates against type and options, applies
routing, and returns a `CaseRecord`: typed, complete, carrying its validation issues
and its `spec_version`. Everything downstream sees slugs only.

When the questionnaire changes, a slug that still means the same thing keeps its
name, and the engine does not move.

### 5.4 Validation

Detected before scoring, reported on the upload screen with row and field references:
out-of-range (`4.5` in a 1–5 field), unknown vocabulary (`"hight"` where the spec
allows `Low/Medium/High`), wrong type, missing required field, implausible value
(negative CAPEX, 5,000 operating days per year).

**A case is not saved until issues are resolved or explicitly overridden.** An
override is a recorded, stamped decision. Nothing is silently defaulted: a blank
`fn_external_need` quietly becoming `3` would produce a confident wrong
recommendation, which is the failure mode this tool most needs to avoid.

## 6. Scoring engine

### 6.1 Adopted verbatim from the workbooks

```
index            = (score - 1) / 4 * 100
band             = LOW 0-33 | MEDIUM 34-66 | HIGH 67-100
financing_need   = mean(FN1, FN2, FN3, FN4)          # 25% each
risk_profile     = 0.5 * RP1 + 0.5 * mean(RP2a..RP2e)
economic_readiness = 0.50*TCO_comp + 0.25*inv_burden + 0.25*market_access
scheme_fit       = 0.20*need + 0.20*risk + 0.20*tco + 0.15*ops + 0.10*payment + 0.15*support
```

All arithmetic is at full precision; rounding happens only at display.

### 6.2 Risk Profile definition

The two candidate rules disagree. The documented `50% ownership + 50% mean(RP2a–RP2e)`
appears with live formulas in two independent places in the workbooks. A simple
average of all six items appears nowhere.

**Decision: use the documented 50/50 rule.** It is also conceptually correct —
averaging six items gives five-sixths of the weight to risk tolerance and
contradicts the framework's stated intent that ownership preference is half the
profile. On divergent answers the gap is material: `RP1=5`, all tolerances `=1` gives
index 50 under the documented rule and 17 under the simple average.

### 6.3 Financing Market Access — new definition

Panel 5 of the reference dashboard shows 72, labelled "Calculated", but no formula
exists in any of the three workbooks. It is 25% of Economic Readiness, so it cannot
be left undefined.

**Definition:** mean of the panel-7 availability fields, mapped through
`None=0, Low=33, Medium=66, High=100`.

The field set is the five questionnaire availability fields (8.1 bank/green loan,
8.2 lease/rent, 8.3 BaaS, 8.4 project finance, 8.5 blended finance/VGF), excluding
8.6–8.10 which are tenor, affordability, collateral and credit-constraint items
rather than instrument availability. On the reference dashboard's own panel-7 labels
this yields 73.0 against the displayed 72 — the closest fit of any candidate scale,
and within the rounding of a hand-placed placeholder.

This is a new decision, not a recovered formula, and is listed as such in §11.

### 6.4 Overall Financing Fit Score — new definition

The reference dashboard shows 78 as the headline. It cannot be a weighted blend of
the five KPI cards beside it, since the highest of those is 63.

**Definition:**

```
overall_financing_fit =
    0.40 * primary_scheme_fit
  + 0.25 * economic_readiness
  + 0.20 * financing_need_index
  + 0.15 * mean(consumer_readiness, city_cri)
```

Weights live in config and are retunable. On the workbook illustrative case this
yields 80.1.

### 6.5 TCO engine

The workbook's cost/km, payback and break-even chain is adopted verbatim; it
reproduces the reference dashboard's TCO panel exactly (5,333 vs 5,334 and 5,517 vs
5,518 Rp/km; break-even 331,200 vs 331,273 km). Three changes are required.

**Symmetric diesel formula.** The workbook's EV total includes subsidy, dedicated
infrastructure CAPEX and a battery-replacement line; its diesel total omits all
three. Harmless in the illustrative case where they are zero, but the respondent
questionnaire explicitly asks for them (fields 5.2, 5.6, 5.7). An analyst entering a
diesel subsidy or refuelling investment gets it ignored, biasing the comparison
toward EV. Fix: one formula applied to both powertrains. Verified to reproduce both
existing sheet totals (1,272.4 and 1,426.0) unchanged — a bug fix with no cost to the
reference case.

**Divide-by-zero guard on Investment Burden.**
`100 - ((EV_net / diesel_net) - 1) * 100` is undefined when diesel net CAPEX is zero,
which is the normal case for a lease, a conversion of an existing asset, or a
government availability-payment scheme. Rules: no incremental premium → 100 (no
burden); diesel net zero with non-zero EV net → 0. The reason is recorded, not hidden.

**Explicit payback verdict.** The reference case shows payback 9.2 years against an
8-year lifetime. The workbook prints 9.2 and lets the reader notice. The engine
returns `recovered_within_horizon: false`, which feeds the key-conditions panel and
prevents a scheme being recommended on economics that do not close inside the
assessment period.

**Cold-chain add-on.** Configurable via `cold_chain.apply_to`, defaulting to
`[ev, diesel]` — a refrigeration box and its energy exist whether the truck is diesel
or EV, so charging both is the analytically honest default. The choice moves TCO
Competitiveness between 94 and 61 on the reference inputs, a 33-point swing that
propagates into Economic Readiness, scheme ranking and the headline score, so it is
surfaced on the dashboard rather than left implicit.

Insurance and tax default from the open-data library when left blank, with source and
date recorded — the workbook's own "public benchmarks first, respondent override"
rule made enforceable.

### 6.6 Scheme matching

The workbook's 63 formulas collapse into five primitives plus a weighted sum. All
eight rule-bearing schemes reproduce to the cent, and the rank order matches exactly.

```yaml
# config/schemes.yaml   spec_version: 2026-01
weights: {need: 0.20, risk: 0.20, tco: 0.20, operational: 0.15, payment: 0.10, support: 0.15}
bands:   {low: [0,33], medium: [34,66], high: [67,100]}

schemes:
  - id: "5"
    name: "Blended Finance / VGF"
    library_priority: 6
    status: active
    closes_financing_gap: true
    green_eligible: false
    fit:
      need:        {target_band: {source: financing_need_index, target: HIGH, match: 100, mismatch: 70}}
      risk:        {target_band: {source: risk_profile_index,   target: HIGH, match: 100, mismatch: 70}}
      tco:         {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 95}
      payment:     {constant: 90}
      support:     {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70},
                                  green_eligible: 80, default: 70}}
      total:       {weighted_sum: [need, risk, tco, operational, payment, support]}
```

Primitives: `target_band`, `parity_or_gap`, `constant`, `support_fit`,
`weighted_sum`. Adding a scheme is a YAML block; the engine and its tests do not
move. Every fit value is stored with the primitive that produced it and its inputs,
so panel 8 can explain *why* a scheme ranked where it did — necessary because the
workbook marks these rules "Proposed" with calibration "Proposed", meaning they will
be argued with.

### 6.7 Stated financing-structure preference

Respondent field 2.5 (`Preferred Financing Structure`) has no role in the documented
six-dimension fit formula. **v1: display it alongside the recommendation as context
only.** It does not influence ranking. If the displayed preference differs from the
recommended scheme, the UI notes the divergence without acting on it.

## 7. Scheme library

The two sources disagree about which schemes exist. The workbook library has 8
entries; the reference dashboard has 7; they share only 5 members.

| Workbook `Scheme Library` | Reference dashboard | In union |
|---|---|---|
| 1 Conventional Ownership | Ownership (Conventional Loan) | yes |
| 2 Conversion / Recycle | — | workbook only |
| 3 Lease / Rent | Lease / Rent (Operating Lease) | yes |
| 4 Lease + Charging | — | workbook only |
| 4a/4b BaaS | BaaS | yes |
| 5 Blended Finance / VGF | Blended Finance (w/ VGF) | yes |
| 6 Performance-based / FaaS | Fee / Performance-based Service | yes |
| 7 Total Outsourcing | — | workbook only |
| — | Green Loan (w/ Partial Guarantee) | dashboard only |
| — | Project Finance | dashboard only |

**Decision: ship the union, tagged.** 10 entries — the 8 from the workbook library,
which is the only source with actual scoring rules, marked `status: active`, plus
Green Loan (w/ Partial Guarantee) and Project Finance from the dashboard, marked
`status: draft` with placeholder fits.

`status: draft` schemes are excluded from primary-recommendation eligibility but
remain visible in the comparison table, so the library's gaps are explicit rather
than silently absent. Fit dimensions are calibrated per scheme, so a rule cannot be
ported from one list onto a scheme in the other — which is why the two dashboard-only
schemes must be placeholders rather than scored.

## 8. Storage and versioning

Every saved assessment stores **both** the input `CaseRecord` and the frozen
`AssessmentResult`, together with `spec_version` and `config_version`.

Rationale: in a decision-support tool, outputs get quoted in meetings. A number
changing underneath someone because a weight was retuned is worse than a stale number
that is visibly stamped with its version. The detail view therefore shows the stored
result, and "re-run with current config" is an explicit action that presents a diff
against the stored version.

## 9. Error handling

### 9.1 Ties

The workbook logic is `rank = RANK(total, desc)` then
`status = IF(rank=1,"PRIMARY", IF(rank=2,"ALTERNATIVE",""))`. `RANK` assigns ties the
same rank, so two schemes at 84 produces **two primary recommendations and no
alternative**, with the second slot silently empty. This is reachable in practice:
fit scores are sums of six values drawn mostly from `{40, 70, 80, 100}` times fixed
weights, so ties land on round numbers.

Fix: a deterministic tie-break on `library_priority` ascending — the scheme list's
existing order, which runs roughly ascending in risk transfer, so the less
provider-dependent scheme wins. The tie remains visible as a badge with its reason
rather than being resolved invisibly.

### 9.2 Partial data

A respondent who skips the TCO section does not get a smaller answer, they get a
structurally missing one. Non-computable: TCO competitiveness, investment burden,
economic readiness, the `tco_fit` dimension of every scheme, and therefore the
Overall Financing Fit Score. Still valid: Financing Need, Risk Profile, readiness
context.

The engine returns three distinct states per metric — `computed`, `not_applicable`
(excluded by routing), and `insufficient_inputs` naming the missing fields. The UI
renders "cannot recommend a scheme yet: questionnaire sections 5–6 are empty" instead
of a dashboard of blanks. Degradation is per panel, not all-or-nothing.

## 10. Testing

1. **Reference reproduction.** Two golden-value cases encoded as tests: the workbook
   illustrative case and the reference dashboard case FPB-2025-001. Already computed
   and confirmed — Financing Need 4.75/93.75, Risk Profile 4.80/95.0, TCO totals
   1,272.4/1,426.0, cost/km 3,181/3,565, competitiveness 75.9, investment burden 50.0,
   payback 6.13, and all 8 scheme fit scores to the cent with matching rank order.
   Any future change that breaks these is a deliberate, reviewable decision.
2. **Unit tests per primitive**, with hand-computed expectations: band edges at
   exactly 33/34/66/67, the divide-by-zero guards, tie-break ordering, cold-chain
   `apply_to` in both settings.
3. **Property tests** on invariants that hold for any input: indices within 0–100,
   weights summing to 1, exactly one primary recommendation, ranking a strict total
   order, and monotonicity (raising a scheme's fit dimension cannot lower its total).
4. **Round-trip per reader**: spec → generate template → fill → ingest → assert the
   `CaseRecord` matches what was written. This is what keeps "structure may change"
   from silently breaking ingestion.

## 11. Divergences from the source workbooks

Every deliberate departure, with evidence.

| # | Item | Workbook / dashboard | This design | Why |
|---|---|---|---|---|
| 1 | Risk Profile rule | 50/50 documented (index 27.5 on the dashboard case); dashboard shows 30 | documented 50/50 | The 30 is a double-rounding artifact: 2.2 is the rounded display of 2.1667, and `(2.2−1)/4×100 = 30` while exact arithmetic gives 29.2. A simple average of six items reproduces neither cleanly. |
| 2 | TCO Competitiveness | dashboard shows 42 | documented formula, giving 93.1 on those inputs | 42 would require EV cost/km to be 29% above diesel; the same panel reports 3.4%. No cold-chain treatment reproduces 42 either (range 61–94). Treated as a placeholder. |
| 3 | Financing Market Access | 72, "Calculated", no formula | new definition, §6.3 | Cannot remain undefined; it carries 25% of Economic Readiness. |
| 4 | Overall Financing Fit | 78, "Calculated", no formula | new definition, §6.4 | Headline number; cannot be a blend of the five KPI cards since the highest is 63. |
| 5 | Economic Readiness | sheet 64.18 | 68.7 on the same case | The sheet's 64.18 comes from a hardcoded `Financing Market Accessibility = 55` marked "Illustrative": `0.5×75.86 + 0.25×50 + 0.25×55 = 64.178`. With market access computed from actual availability fields instead of the placeholder, readiness rises to 68.7. All other inputs match exactly. |
| 6 | Diesel TCO total | omits subsidy, infrastructure, battery | symmetric formula | Respondent form collects all three for diesel; omitting them biases toward EV. Verified not to change existing reference totals. |
| 7 | Scheme library | 8 workbook entries vs 7 dashboard entries, 5 shared | union of 10, 8 active + 2 draft | Neither list is complete; see §7. |
| 8 | Band labels | dashboard labels index 27.5/30 as "Moderate–High" | `LOW` per documented bands | 34–66 is MEDIUM, 0–33 is LOW. The dashboard's label contradicts its own band definition. |
| 9 | Tie handling | `RANK()` yields two PRIMARY and no ALTERNATIVE | deterministic `library_priority` tie-break, tie surfaced | §9.1. |
| 10 | Preferred Financing Structure (2.5) | collected, unused | displayed as context only | No documented role in the fit formula; §6.7. |
| 11 | Investment Burden | dashboard shows 34 | documented formula, giving 50.0 on those inputs | 34 would require EV net CAPEX to be 1.66× diesel net; the same panel's payback (9.2 yrs × 36,000 km) implies an incremental CAPEX of ~1,156 Rp million against a diesel net of ~500 — an EV/diesel ratio of 2.3, which the formula maps to 0. The two dashboard numbers are mutually inconsistent; the formula value is kept. |

## 12. Configuration surface

| File | Contents |
|---|---|
| `config/questionnaire.yaml` | sections, slugs, types, options, units, required-ness, routing, aliases, `spec_version` |
| `config/scoring.yaml` | index conversion, band edges, component weights, Overall Fit weights, cold-chain `apply_to`, market-access scale |
| `config/schemes.yaml` | scheme library with fit rules, `library_priority`, `status` |
| `config/reference_data/` | city CRI rows, open-data benchmarks with source and date (OD1–OD14) |

Settings are edited in these files, not in the UI. Each carries a version, and every
assessment records the versions that produced it. This is deliberate: a UI for
retuning weights invites untracked changes, which is precisely the failure mode §11
documents in the source workbooks.

## 13. Known limitations

- Scheme fit rules are marked "Proposed" in the source and are unvalidated against
  pilot or provider data. The tool surfaces the provenance of each fit value so a
  reviewer can challenge it, but v1 cannot validate the calibration.
- The two dashboard-only schemes are placeholders and cannot become recommendations
  until calibrated.
- Provider supply data (SUP4–SUP6) is ingested and displayed but has no managed
  provider registry behind it in v1.
- The reference dashboard's own numbers are not reproducible from its displayed
  inputs (§11 rows 2–5), so the tool will disagree with the mock-up on several
  panels. This is expected and is the point of §11.
