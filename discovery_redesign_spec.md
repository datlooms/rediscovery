# discovery_redesign_spec.md

**Phase:** DOT_execution_sequence.md step 17n — gate-first discovery redesign
**Author seat:** Quant Analyst
**Status:** specification for Developer build and Auditor verification
**Date:** 2026-07-23
**Revision 2:** amended 2026-07-23 following external-review assessment and its correction round. Nine verified changes applied (§C.2, §C.3, §D.0, §F.4, §F.5, §F.6, §G.2, §H.1, §J); three provisionally-accepted items refuted by measurement and recorded as withdrawn (§10C).
**Revision 3:** amended 2026-07-23 following Supervisor verification (APPROVE WITH AMENDMENTS). Defects A1–A5 corrected, gaps G1–G8 answered or assigned, three implementability blockers and three fake-step loopholes closed. **§0.1 is new and is the root fix**: depth, population and tolerance are now defined once and every depth-dependent figure is re-derived against them. Two Supervisor findings are disputed with measurement rather than absorbed — see §F.1.
**Revision 9:** amended 2026-07-24 with five corrections, landing before pipeline consolidation. Items 1, 2 and 4 documentation; **items 3 and 5 design**. §C.1 records that `CoFire` is **not consumed by the objective at all** (neither pooled nor per-direction) — no numerical code change, one naming/signature fix specified to close a latent hazard. §I.1 specifies **equal partition** of the post-floor remainder. §I.3's pass criterion is **restated as a ratio to each split's own measured null**, with a derived minimum denominator of **80 qualifying triples (hard floor 40)** — a code change the Developer applies at consolidation. Items 1 and 2 confirmed already applied at Revision 8; the build was correct throughout and the spec now matches it.
**Revision 8:** amended 2026-07-23 with three corrections raised by the Developer and confirmed by the Auditor (documentation only; Build 2 is ratified at `master.py 296d612b7e9f` and Build 3 is authorised — these do not gate it). **§C.2's exclusion-bias direction is corrected to ANTI-CONSERVATIVE** and its root cause traced one level deeper than the notice reached — to the series definition, not only the k<3 degeneracy. **§C.2's independence annotation is corrected** (`lambda_L = 1.0` is perfect tail dependence; independence reads `tau`) and every λ figure re-derived on the corrected series, moving the headline lift from 3.548x to **1.69x**. **§C.1's `CoFire` gains the within-direction treatment `DepthYield` already had**, with cross-direction zero recorded as a property of the D2D alternating-bias design rather than as a market finding. Two provenance items recorded in §10C.
**Revision 7:** amended 2026-07-23, Supervisor amendment C (documentation only, non-blocking; the Developer is building from `2b7f36d407f6` and this does not gate that). §D.0.1's reconciliation block restated against the current doctrine `fae943d40231` (305 lines): the recorded divergence **no longer exists** — the doctrine now states the six-cell robustness range this spec's figures sit inside — and the returned observation on unlabelled parameters is **closed, actioned in the doctrine as M3**. The doctrine's ≥15-trade filter claim is independently verified here and the standing "the filter is part of the finding" construction is adopted document-wide.
**Revision 6:** amended 2026-07-23 following Supervisor CONFIRM. `DOT_signal_discovery_mantra.md` is now **binding doctrine** over this document; §D.0.1 records the reconciliation. §F.3.1 gains the N=5 tolerance table and withdraws the ungeneralised monotonic-decline claim. The MARKET/BOOK labelling construction is extended to five further sections. No figure changed except by addition.
**Revision 5:** amended 2026-07-23 with four measured findings arising from an operator challenge to circular reasoning — market properties had been inferred *through* BOOK-50, which is the output of the funnel being replaced. §D.0.1 establishes a price-only **directional coverage baseline (50/50)** and **retires the upward-drift assumption** previously recorded in §C.3.1a. §D.0.2 separates reach from depth on the short side. §F.3.1 records the cluster arc and rules a normalised-position taper **unimplementable**. §C.3 gains the measured premise for weighting depth over standalone signal quality. Every finding is labelled MARKET (price-only) or BOOK. Three reproduction discrepancies are reported rather than smoothed — see §D.0.2 and §F.3.1.
**Revision 4:** amended 2026-07-23 following Supervisor re-verification (APPROVE WITH AMENDMENTS, BUILD AUTHORISED SCOPED). O1 removes a directional bias in the objective — `DepthYield` is now per-direction and normalised (§C.1) and greedy selection runs per direction and merges (§C.3.1), with **no directional floor, quota or target encoded anywhere** (§C.3.1a). O2 corrects the §C.2 tail operating point to `tau = 0.20 / MIN_SHARED = 10` and recalibrates `T_max` to a per-segment permutation null. O3 keys two stale split-count references to the derived `K`. One O2 sub-finding is disputed with measurement — see §C.2. Structure and section numbering preserved.

---

## 0. PROVENANCE

| item | value |
|---|---|
| repo | `github.com/datlooms/DOT` @ `852c7e0`, 140 files |
| `engine/dots_thresholds.py` | `518862bf19fb` (expected — MATCH) |
| `master.py` | `8ccff8d0df91` (expected — MATCH) |
| dataset | `DOT_stitched172_jan19_jul21_part01..09.csv` → 177,251 × 172, 2026.01.19 15:49 → 2026.07.21 17:09, strictly increasing, 0 dup, 0 NaN |
| S8B output | `cluster_participation_profile.csv`, 2,988 × 69 |
| harness sanity | 3,057 trades / net $98,205 on the full stitched series |
| condition pool | 249 = 180 FEAT hi/lo (90 × 2) + 69 equality |

Every figure in this document was computed in-session through the ratified path. Figures quoted from prior documents are labelled as such and were re-derived before use.

**Governing principle (Step 2, binding):** the redesign is **ADDITIVE**. The measured problem is reach, not excess. No variable, condition, mechanism or family is removed on a single measurement. Where a component looks weak, this spec states what will be measured to decide. Gates are state columns; no bar is ever deleted.

---

## 0.1 CANONICAL DEFINITIONS — DEPTH, POPULATION, TOLERANCE

**Binding for the whole document. Every depth-dependent figure below is stated against these definitions and no other. Any figure quoted without a basis and tolerance label is a defect.**

Prior revisions of this spec used four different depth measures without labelling any of them. That ambiguity produced figures that could not be reproduced. It is closed here.

### 0.1.1 — POPULATION

| population | definition | count | net |
|---|---|---|---|
| **BOOK** | F0 + F1 executed trades. Gap fillers excluded — they fire only when flat and are solo by construction, so they cannot participate in depth. | **2,678** | **$77,239** |
| FULL | BOOK + the 3 gap fillers | 3,057 | $98,205 |

**BOOK is the population for every depth measure, every cluster construction, and the §C.3 objective.** FULL is used only for whole-system survival figures (worst day, daily mDD), where gap-filler P&L genuinely lands on the same day. Each figure states which.

### 0.1.2 — THE TWO DEPTH MEASURES

Both are needed; they answer different questions and must never be conflated.

**(A) BAR-LEVEL QUALIFYING DEPTH — `qd(t)`.** The number of BOOK signals whose mask qualifies at bar `t`, computed from `build_signal_masks` with `entry_ok` applied, **before** the position jar. No tolerance parameter. This is market-state: what the book agreed on, independent of what the jar admitted. Executed depth caps at 6 (`MAX_POSITIONS`); `qd` reaches **14**.

Use: the quality ladder, the §F.3 sizing curve, and any statement about signal agreement.

**(B) TEMPORAL CLUSTER SIZE — `cs_N(i)`.** Maximal run of same-direction BOOK entries where each entry's bar is within `N` bars of the **previous entry** in that direction. Cluster size is the count of entries in the run.

Use: `DepthYield`, coverage, and any statement about a move unfolding over time.

### 0.1.3 — THE TOLERANCE `N` IS FIXED AT **N = 5**

`N` materially changes the objective and a Developer cannot be left to choose it:

| | N=5 | N=10 |
|---|---|---|
| clusters | 991 | 790 |
| size ≥ 5 | 125 | 152 |
| solo (size 1) | 397 | 256 |
| max size | 39 | 53 |
| `DepthYield` (size≥5 per traded day) | **1.033** | 1.256 |

**N = 5 is fixed as primary, for a stated reason: `DepthYield` is MAXIMISED by the objective, so the tolerance must be the stricter of the candidates.** A looser tolerance mechanically manufactures larger clusters and would let the search improve its score by exploiting the definition rather than the market. N=5 also stays closer to the mechanism actually being claimed — near-simultaneous convergence — where N=10 admits entries ten minutes apart as one event.

**N = 10 is reported as mandatory sensitivity on every cluster-derived figure.** If a conclusion holds at N=5 but reverses at N=10 it is not a conclusion.

*Falsification:* if `DepthYield` rankings of candidate books differ materially between N=5 and N=10 (rank correlation < 0.8), the objective is tolerance-sensitive and neither value can be treated as settled; the build reports the rank correlation.

*Fit risk:* N is chosen on six months. It is fixed a priori and never tuned against a selected book, and must be re-stated (not re-fitted) inside each §I split.

---

## 1. CORRECTIONS TO THE RECORD

Three corrections arise from measurements taken while writing this spec. Two are material to decisions already recorded. All are reproducible from the stitched series through the ratified path.

### 1.1 — MATERIAL: the reveal doc §5 "Aligned / Misaligned" table is a REGIME-STATE filter, not a directional-alignment gate

`DOT_new_data_reveal_2026-07-21.md` §5 and `DOT_progress_and_rd_plan.md` decision 2 describe "gating BOOK-50 trades on **directional alignment** with `AT_Regime_ST`". The table's figures do not correspond to a directional-alignment computation. They correspond exactly to a **regime-state filter** — keep trades whose entry bar carries `AT_Regime_ST == 1`, irrespective of trade direction.

All 375 NEW-segment trades, three candidate readings:

| reading | n | WR% | PF | net $ | worst day $ |
|---|---|---|---|---|---|
| A — directional, correct encoding (0=bull), aligned | 171 | 74.9 | **0.97** | **−111** | −682.7 |
| A — directional, correct encoding, misaligned | 204 | 86.3 | 3.98 | 8,518 | −476.0 |
| B — directional, inverted encoding (1=bull), aligned | 204 | 86.3 | 3.98 | 8,518 | −476.0 |
| **C — regime-state only, `AT_Regime_ST == 1`** | **267** | **86.5** | **3.83** | **9,228** | **−116.3** |
| C — regime-state only, `AT_Regime_ST == 0` | 108 | 67.6 | 0.78 | −821 | −534.9 |
| *record as written* | *267 / 108* | *87 / 68* | *3.83 / 0.78* | *9,228 / −821* | *−116 / −535* |

Reading C reproduces the record to every published digit. The arithmetic in the record is correct; **the label is wrong.** What was measured is not what was decided.

**SEGMENT BOUNDARY — stated explicitly (was previously undefined).** The 375-trade NEW population above begins at **bar index 152,814 = 2026.06.25 15:30**. This is the boundary the record used, and it is used here **only** because §1.1 is a forensic reproduction of the record's own figures — reproducing them requires reproducing their population. It is **not** the doctrinally correct boundary and is not used anywhere else in this document.

**The doctrinally correct boundary is bar 152,983 = 2026.06.25 18:19** — the first bar after the sealed baseline's final bar (152,982 = 18:18). Measured at all three candidates:

| boundary | NEW trades | NEW net | OLD trades | OLD net |
|---|---|---|---|---|
| bar 152,814 (record) | 375 | $8,407 | 2,682 | $89,797 |
| **bar 152,983 (sealed endpoint — ADOPTED)** | **359** | **$5,909** | **2,698** | **$92,296** |
| end of day 2026.06.25 | 337 | $5,511 | 2,720 | $92,694 |

**The natural boundary reproduces the canonical committed trade count exactly — 2,698 — at PF 6.40.** (Net $92,296 vs the canonical $92,347; the $51 difference is trades spanning the seam when the full stitched series is scored and then split, rather than the baseline being scored alone.) The record's choice was 169 bars early and cost that agreement.

**ADOPTED: bar 152,983 for every segment-split figure in this document except §1.1's forensic reproduction, which is labelled as such.** §E.3 is restated against it below.

**Consequence:** recorded decision 2 — "`AT_Regime_ST` **directional agreement** joins the gate stack" — cites evidence for a different operation. The directional gate as decided (reading A) is **PF 0.97 and net −$111 on the NEW segment**: it removes the book's profit. This is consistent with my earlier independent measurements on F0 concurrent (ungated PF 9.76 → AT_Regime_ST-aligned 6.85 → sign(AT_Slope_ST)-aligned 6.97).

**This spec does not adopt a directional AT gate.** §E specifies what would be measured to decide the regime-state variant on its merits.

### 1.2 — MATERIAL: the Section D tension is not a contradiction; both figures are correct on different scales

The reveal doc's "77% of profit from the largest-move quartile" and S8B's "9.8–17.9% of deep-cluster bars are thrust bars" measure different quantities.

Reproduced, NEW-segment trades bucketed by |60-bar forward move| (n=370):

| quartile | n | net $ | share of profit | PF | median fwd60 |
|---|---|---|---|---|---|
| Q1 | 93 | 1,154 | 13.3% | 1.78 | 18.9 pt |
| Q2 | 92 | 735 | 8.5% | 1.66 | 53.8 pt |
| Q3 | 92 | 281 | 3.3% | 1.13 | 119.6 pt |
| **Q4** | **93** | **6,481** | **74.9%** | **4.27** | **204.0 pt** |

The record's PF 4.27 and 204 pt median reproduce exactly; profit share is 74.9% against the published 77%.

The reconciliation:

| scale | traded Q4 sits at | interpretation |
|---|---|---|
| **absolute points** | Q4 lower edge 160.8 pt = **percentile 88.9** of all eligible bars | book *does* capture big moves |
| **ATR-normalised** (what thrust uses) | traded Q4 median 5.90 disp/ATR = **percentile 72.6** of all eligible | book's moves are *ordinary multiples* |

All-eligible median disp/ATR is 3.40; the book's traded NEW bars median **2.56** — below the market median once normalised. Only **8.6%** of all traded NEW bars clear the all-eligible p85 disp/ATR threshold, and only 26.9% of traded Q4 bars do.

**Both statements are true.** The book trades during high-ATR conditions where a large absolute move is an unremarkable normalised move. "Big-move capture engine" holds **in absolute points**, which is what pays. The low thrust overlap holds **in ATR multiples**, which is what S8B measures. The record should carry the qualifier; neither figure is wrong.

### 1.3 — the "missed set is too small to trade" hypothesis is REFUTED

The brief instructed measuring absolute point displacement of missed vs traded thrust episodes before specifying anything that chases the missed set. Measured, thrust episodes chained at N=5:

| W, K | episodes | traded | missed | traded median | missed median | missed ≥50 pt |
|---|---|---|---|---|---|---|
| 15, p85 | 3,241 | 151 (4.7%) | 3,090 | 168.0 pt | **58.5 pt** | 61.0% |
| 30, p85 | 2,359 | 128 (5.4%) | 2,231 | 224.0 pt | **77.5 pt** | 80.4% |
| 15, p90 | 2,539 | 112 (4.4%) | 2,427 | 182.8 pt | **64.1 pt** | 67.8% |

The missed set is **not** dominated by untradeable moves: median 58–78 points, with 61–80% of missed episodes exceeding 50 points. On US30 at $1/point/lot these are tradeable.

But the second half of the result matters equally: **traded episodes are 2.5–3× larger than missed ones** (168–224 pt vs 58–78 pt). The book is not blind to thrusts — it is selecting the largest ones. Reaching the missed set means trading a systematically smaller-move population.

**Consequence:** reach is a real opportunity in count (only 4.4–5.4% of thrust episodes are touched) but any signal recruited to reach it must be scored on its own merits, not credited with the traded population's economics. §D specifies this.

### 1.4 — housekeeping: F10 stale flag

`discovery_map.md` §3 line 90 carries `F10 — GAP — flag`, contradicted by the same file's Resolution status line 243: "**F10 — FOLDED INTO F0** (concurrence lens null; F12 profiler is the diagnostic remnant). Not a gap; the family set is complete." Line 90 to be corrected to `FOLDED INTO F0`. Documentation-only; no code impact.

---

## 2. SECTION A — ALL FOURTEEN FAMILIES: OPEN EVALUATION

The committed book draws from F0 (48) and F1 (2). F2–F9, F11, F12, F13 are classified exploratory. **This spec treats that classification as unexamined, not as a diagnosis.** Nobody has evaluated the unused families under a depth/coverage framing; they may contain nothing or a great deal.

### A.1 — The per-family evidence review (mandatory first deliverable of the build)

For each of F0–F13 the build produces one row of an evidence table, grounded in the actual output files under `discovery_results/` and `dots_results/`, not in the map's prose descriptions.

Required columns per family:

| column | definition |
|---|---|
| `family`, `scanner`, `sha` | identity, self-computed |
| `rows_emitted` | actual row count in its results CSV on the sealed run |
| `candidates_passing_S5` | rows meeting `trades>=30 & folds_plus>=4 & agg_pf>=2.0` |
| `distinct_conditions_used` | how much of the 249-vocabulary the family actually touches |
| `depth_participation` | share of its candidates' fires falling inside size≥5 clusters (all three S8B bases) |
| `co_fire_with_F0` | share of its fires sharing an entry bar with an F0 book signal |
| `coverage_of_missed` | share of its fires landing in thrust episodes the current book does NOT touch |
| `regime_conditional_net` | net per §H.3 bucket, not aggregate |
| `verdict` | `SELECTABLE` / `DIAGNOSTIC` / `INSUFFICIENT-EVIDENCE` |

**No family may be assigned `DIAGNOSTIC` on the basis of its historical classification.** The verdict must be justified by the measured columns. `INSUFFICIENT-EVIDENCE` is an acceptable and expected outcome and must be used rather than a guess.

*Falsification:* if a family's candidates show `depth_participation` at or below the base rate and `coverage_of_missed` at or below the base rate across all three bases and all §H.3 buckets, it contributes nothing under this framing. That is a measurement, not an assumption.

*Fit risk:* the sealed-run outputs were produced on Jan–Jun. Family output must be regenerated on the full stitched series before the verdict is taken as evidence, or the review inherits the old window.

### A.2 — F12 (`concurrence_profiler.py`) vs S8B

F12 is classified "MEASURES, never selects" and reads `dots_results/deduped_survivors.csv`. S8B profiles the full 249-condition vocabulary against three cluster bases.

They are **not** the same lens. F12 measures raw variable-depth concurrence among F0 survivors; S8B measures per-condition participation against book-derived (bases 1, 2) and price-derived (basis 3) episodes. F12's population is the F0 survivor set; S8B's is the vocabulary.

**Specified measurement to decide the relationship:** run both on the stitched series and cross-tabulate F12's depth-outcome relation against S8B's `lift_5` and `cov_missed_share` per condition. Three possible outcomes, and the build reports which obtains:
- **duplicate lens** — F12's depth ranking correlates > 0.8 with S8B `lift_5` on shared conditions → F12 stays diagnostic, superseded.
- **independent lens** — correlation < 0.5 → F12 measures something S8B does not; its diagnostic-only classification should be revisited and the build states what it would take to make it selectable.
- **superseded** — F12's output is reconstructible from S8B columns → retire the lens, keep the file.

**Do not assume the answer.** The classification change, if any, follows the measurement.

### A.3 — F13 (`single_variable_extremes`)

F13 is a documented negative (0 stars, 0 candidates), independently corroborated by S8B basis 3: no single condition separates, maximum ATR-controlled lift 1.35.

**Verdict: the negative stands as settled for F13's stated claim** — that a single variable at an extreme is a standalone tradeable edge. Two independent methods on different framings agree.

**But the negative does not transfer.** F13 tested single conditions as *entry signals*. It did not test single conditions as *cluster participants* or *coverage contributors*, which is what S8B measures and what this redesign selects on. A condition that is worthless alone may still be the third leg of a triple that deepens clusters. The build must not use F13's negative to exclude any condition from the vocabulary or from triple formation.

*Falsification of the settled verdict:* if any single condition shows regime-conditional positive net in all §H.3 buckets with ATR-controlled lift > 2.0 and survives §H.1 correction, F13 warrants a re-look. The build reports whether any does.

### A.4 — CROSS-FAMILY CO-FIRING (new measurement, never performed)

Depth currently arises only from F0 signals firing together. Whether a signal from F2 (state transition) can co-fire with an F0 triple into shared depth has never been examined.

**Specified measurement:** extend the S8B cluster construction to admit entries from any family, tagged by origin. For every cluster, record the family composition vector. Then:

1. **Do mixed-family clusters form at all?** Report the count and size distribution of clusters containing ≥2 distinct families, at N=5 and N=10, all three bases.
2. **Do they behave like same-family clusters on the depth ladder?** Report WR / PF / net / worst-day by cluster-size band, split single-family vs mixed-family. The reference is the measured same-family ladder: size 5-7 → WR 95.5%, PF 11.39; size 13+ → WR 96.0%, PF 11.78, worst day −$12.3 (N=10).
3. **Does mixing add unique-variable count at depth?** Per §F.4 a depth-2 event carrying only 3 unique variables is not genuine corroboration. Cross-family entries are more likely to carry disjoint variables; measure whether they do.

**What a mixed-family cluster would mean:** if mixed clusters match the same-family ladder, depth is a property of *simultaneous independent agreement* rather than of F0's triple architecture, and the book's family monoculture is a reach constraint rather than a quality guarantee. If mixed clusters underperform, F0's architecture is doing work beyond mere co-occurrence. Both outcomes are informative; neither is assumed.

*Fit risk:* admitting 13 families multiplies the co-firing surface. Any mixed-cluster result must clear §H.1 correction at the expanded trial count before it informs selection.

### A.5 — Multiple-testing implications of the family expansion

Scoring all fourteen families rather than one changes the trial count materially. This is handled in §H.1, which must be parameterised on the **actual** post-expansion trial count, not the historical F0-only count. The build reports the count per family and in total.

---

## 3. SECTION B — EVERY MASTER.PY OUTPUT IS A RESEARCH INPUT

Per-stage audit. `feeds selection today` is a factual statement about the current pipeline; `measurement to decide` is what this redesign requires where the answer is no.

| stage | emits | feeds selection today | measurement to decide |
|---|---|---|---|
| **S0 ingest** | `df`, attestation, `input_sha` | no (provenance) | **DIAGNOSTIC — justified.** Provenance and integrity only. Requirement: the attestation must record dataset range and row count in the run report so no downstream figure is read without provenance. |
| **S1 thresholds** | `ad` (mechanism-D), `st` (structural gates) | yes, indirectly | Already the sole threshold source. No change. Sacred. |
| **S2 pool** | 249 conditions, `anchor`, warm-up floor `w` | yes | Feeds everything. §G specifies selection-time handling of duplicates and dead conditions **without modifying the pool** (S.10 sacred). |
| **S3 discovery** | `results_F*.csv` for all families | **F0 and F1 only** | §A.1. All families' output enters the evidence review. This is the largest unused surface in the pipeline. |
| **S4 schema** | `results/discovery_master.csv` (all families collated) | no — collated then filtered | **This file already contains every family's output in one schema.** It is the natural input to §A.1 and is currently consumed only by S5's three-condition filter. Requirement: §A.1's evidence table is built from `discovery_master.csv`, not from per-family files, so nothing is silently dropped. |
| **S5 filter** | `candidates.csv` — `trades>=30 & folds_plus>=4 & agg_pf>=2.0` | yes | **Three hard thresholds with no trial-count adjustment and no regime conditioning.** They are the funnel's only quality bar. §H replaces them: the thresholds stay as a *participation floor* but acceptance moves to the empirical-null bar (§H.1) plus stability (§H.2) plus regime-conditional positivity (§H.3). Measurement: report how many candidates each criterion removes independently, so the filter's actual selectivity is visible rather than assumed. **`folds_plus` is not usable as written — see §B.1.** |
| **S6 regen** | `signal_full_records.csv`, `signal_per_day_pnl.jsonl` | no | Regenerates artifacts documented stale (`746102aae415` / `0910f360a628`). **Measurement to decide:** these carry per-signal per-day P&L, which is exactly the input §C.2 needs for the failure-correlation matrix. Requirement: S6's output becomes the source for §C.2 rather than being regenerated and unused. |
| **S7 contenders** | C0–C5 conviction-variant scores | no — reporting only | Six sizing variants scored on the same book. **DIAGNOSTIC today, but §F.3 requires the depth-size curve to be validated independently of selection.** S7 is the correct home for that: add the depth-conditioned variant as a contender row and report it beside C0–C5. |
| **S8 committed** | committed-book replay + canary | no — verification | **DIAGNOSTIC — justified.** The $92,347 / 2,698-trade canary is an engine-integrity check, not a selection input. Keep as is. |
| **S8B cluster profile** | `cluster_participation_profile.csv`, 2,988 × 69 | **no — built, never consumed** | §D.3 makes its coverage columns a selection input. This is the specification's single largest change to what feeds selection. |
| **S9 report + split** | `master_report.md`, split artifacts | no | **DIAGNOSTIC — justified.** Packaging and reporting. Requirement: the report must surface the §A.1 evidence table and the §H acceptance decisions, not just the committed-book headline. |

### B.1 — `wf.FOLDS` and `OOS_MONTHS` are hardcoded and cannot be used as-is

**`wf.py` is SACRED and byte-locked (`793e6e5f8d9a`). `FOLDS` is hardcoded to the Jan–Jun months. It cannot be edited, so the SELECTION LAYER must handle it explicitly — this is specified, not left to the build.**

Two concrete failures:
1. **On the full stitched series**, 300 July trades (9.8% of the book) are scored against a fold set that does not contain July. A signal trading only in July scores `folds_plus = 0` and is culled for a reason that has nothing to do with its quality.
2. **Inside a §I training segment**, `folds_plus` is undefined — the segment's months and `FOLDS`' months need not intersect at all.

**Specified handling, without touching `wf.py`:**
- `wf.daily_pnl_points` (the daily series builder) **is** used — it is month-agnostic and is the reason `wf.py` is imported at all.
- **`folds_plus` and `min_fold_pf` are NOT used as selection criteria anywhere in the new layer.** They are superseded by §H.3, which buckets by whatever months the active segment contains and is therefore segment-correct by construction. S5's `folds_plus>=4` is retained only as a legacy participation floor on the full-series run and is **disabled inside §I splits**, with the disabling reported.
- `selection.py` computes its own segment-local monthly buckets. It does not import `FOLDS`.

**`OOS_MONTHS = ['2026.05','2026.06']` is hardcoded in `master.py`** (not sacred, but load-bearing): S7's `oos_pf` and `oos_net` are computed against two fixed calendar months. On the stitched series this is neither out-of-sample nor segment-relative — May and June are now interior. Reveal open item #7 (data-relative OOS) remains unresolved.

**Specified:** `master.py`'s S7 `oos_*` columns are **reported as legacy diagnostics with an explicit staleness flag**, and are not selection inputs. The §I walk-forward is the OOS mechanism in the new design; a second fixed-month OOS is redundant and misleading. Making `OOS_MONTHS` data-relative is assigned as a `master.py` change under §11.

*What would falsify this handling:* if §H.3's segment-local bucketing and `folds_plus` agree on the full series (same accept/reject on >95% of candidates), the legacy criterion is harmless and may be retained for continuity. The build reports the agreement rate.

### B.2 — Reveal open items 4 and 8

- **Open item 4 — lead–lag timing structure.** **ASSIGNED IN SCOPE, to §A.1.** F11 (`rolling_leadlag.py`) is one of the fourteen families and its evidence row already requires `depth_participation` and `co_fire_with_F0`. Lead–lag *is* the question of whether one family's fires systematically precede another's, which is measured directly by the §A.4 cross-family co-firing work. No separate mechanism is specified; if §A.4 shows mixed-family clusters forming with consistent ordering, that is the lead–lag result.
- **Open item 8 — per-trade CSV export from `master.py`.** **ASSIGNED IN SCOPE, to §11.** Every measurement in this document was produced from a per-trade table (entry/exit bar, time, price, direction, lots, pnl, exit type, signal index). The pipeline currently reconstructs it ad hoc for each analysis, which is how definitional drift enters. `master.py` S8 must emit `discovery/committed/trades.csv` with those columns, and §11 records it. It is a prerequisite for the Auditor reproducing §F.1 independently.

**Standing requirement:** no stage output may be described as diagnostic-only in the final build without an explicit justification in the run report. Three are justified above (S0, S8, S9). Every other stage either feeds selection or has a named measurement that decides whether it should.

---

## 4. SECTION C — THE DECORRELATION QUESTION

The old objective selected for signals that do not overlap. Overlap **is** depth, and depth is the strongest persistence axis measured. But decorrelation produced a real result — the 448-signal persistent union collapsed to PF 1.82 while the curated 50 held PF 6.40 (record figures). Something in it works.

Two properties were conflated:

- **(i) ENTRY CO-FIRING** — signals firing together, creating depth. **WANTED.**
- **(ii) FAILURE CORRELATION** — signals losing together, concentrating risk. **NOT WANTED.**

These are not in conflict. A book can co-fire heavily while failures stay independent. The old method collapsed them into one axis and optimised the wrong one.

### C.1 — Measuring entry co-firing

For a candidate book *B* and every ordered pair (i, j) in *B*:

```
cofire(i,j) = |bars where i and j both qualify| / |bars where i qualifies|
```

computed on the **pre-jar qualifying masks** (S8B basis 2), not the executed trade list, so the jar's 6-lot cap does not truncate the measurement. Executed max depth is 6; pre-jar qualifying depth reaches **14**. Book-level statistic:

```
CoFire_d(B)   = mean over SAME-DIRECTION pairs within direction d of cofire(i,j)
                -- NEVER pooled across directions in any quantity entering the objective
                   or a constraint. See "cross-direction co-firing" below.

DepthYield_d(B) = ( count of direction-d BOOK clusters of size >= S )
                  / ( traded days ) / ( count of direction-d signals in B )

DepthYield(B)   = the PAIR ( DepthYield_LONG , DepthYield_SHORT ) -- never summed
```

**`CoFire` TAKES THE IDENTICAL WITHIN-DIRECTION TREATMENT, FOR THE SAME REASON.** A previous revision defined `CoFire` as a mean over all pairs. That is wrong, and the defect is in the scoring, not in the market.

**Cross-direction co-firing is structurally zero — this is D2D behaving exactly as designed, and must NOT be written up as an empirical finding.** D2D implements an **alternating bias**: one directional bias at a time, by construction. `portfolio_simulation_engine.build_signal_masks` applies `mask = mask & (d2d_dir == direction)` (L103), so every LONG mask is a subset of `{bars: D2D_Trend_Dir == +1}` and every SHORT mask a subset of `{bars: D2D_Trend_Dir == −1}`. `D2D_Trend_Dir` is scalar per bar, so those sets are **disjoint**. A long signal and a short signal cannot co-fire, ever — not rarely, not in this sample: never, by construction.

Measured (pre-jar qualifying masks with engine `entry_ok`, BOOK): **0 of 481 unordered cross-direction pairs share a single qualifying bar**, and **962 of 2,450 ordered pairs (39.3%) are structurally zero.**

**Why an all-pairs mean is a defect.** It averages over 39.3% of pairs that are zero by design, deflating the statistic for reasons unrelated to signal quality — and, decisively, **it would mechanically reward a single-direction book**, since a book with no shorts carries no structurally-zero pairs dragging its mean down. That is the same failure mode §C.1 guards against for `DepthYield`, arriving by a different route, and it would have partially undone the O1 fix.

**Specified basis, measured (BOOK, pre-jar qualifying, engine `entry_ok`):**

| basis | value | consumed by §C? |
|---|---|---|
| all-pairs | 0.0271 | **NO — deflated by construction** |
| same-direction (pooled) | 0.0447 | reported only |
| **LONG within-direction** | **0.0480** | **YES** |
| **SHORT within-direction** | **0.0162** | **YES** |

**§C consumes the per-direction bases (0.0480 / 0.0162).** The all-pairs figure is emitted for continuity and explicitly marked deflated; the pooled same-direction figure is reported but does not enter the objective, since pooling still lets a large-pool direction dominate the mean.

**BUILD STATUS — NO CODE CHANGE IS REQUIRED, AND THE REASON IS NOT THAT THE BUILD READS THE RIGHT BASIS.** Verified against `selection.py` at the ratified state: `cofire_matrix` and `cofire_book` are **defined but never called from the objective, the greedy search, or any constraint.** Their only call sites are `master.py`'s S5B diagnostic emission, which writes `selection_cofire.csv`. The objective's depth term is `depth_yield_pair`, which is already per-direction by construction (§C.1).

So the answer is neither of the two obvious ones: **the objective does not read `CoFire` at all — pooled or otherwise.** The within-direction requirement above is therefore a **forward constraint on any future wiring**, not a repair of current behaviour.

**One latent hazard, and the low-cost consolidation-time fix.** `cofire_book(M)` takes the unconditional off-diagonal mean — the deflated all-pairs basis — and its name does not say so. If a future revision wires it into the objective, the defect appears silently and would partially undo the O1 directional fix. **Specified for consolidation:** either rename it to `cofire_book_all_pairs_DIAGNOSTIC` or give it a required direction-mask argument, so the pooled basis cannot be consumed by accident. **This is a naming/signature change with no numerical effect and no impact on any emitted figure.**

**`DepthYield` IS EVALUATED WITHIN DIRECTION AND NORMALISED BY THAT DIRECTION'S SIGNAL COUNT. It is never pooled into a single scalar.** A pooled count is scale-dependent: it rewards whichever direction happens to hold more signals, for combinatorial reasons that have nothing to do with signal quality.

**The measured defect it corrects — PROPERTY OF THE BOOK, and specifically of its 37/13 composition; it must be re-derived for any new book and says nothing about directional opportunity in US30 (for that, see §D.0.1).** On the committed book at S=5, N=5, BOOK, 121 traded days:

| | clusters ≥5 | share | per day | signals |
|---|---|---|---|---|
| LONG | 113 | 90.4% | 0.934 | 37 |
| SHORT | 12 | 9.6% | 0.099 | 13 |
| **raw ratio** | | | **9.42 : 1** | 2.85 : 1 |

**A 9.42:1 objective disparity against a 2.85:1 signal-count ratio — and it is combinatorial, not quality.** Verified: median trades per signal is comparable (LONG 51, SHORT 49) and median active days per signal is *higher* for shorts (LONG 31, SHORT 38). Thirteen signals cannot co-fire into clusters the way thirty-seven can. The co-firing opportunity set scales with available pairs: C(37,2) = 666 versus C(13,2) = 78, a ratio of **8.54:1** — which tracks the observed 9.42:1 far more closely than the signal-count ratio does.

**Effect of the normalisation, measured:**

| N | S | raw ratio | normalised ratio | signal-count ratio |
|---|---|---|---|---|
| 5 | 3 | 3.88 : 1 | **1.36 : 1** | 2.85 : 1 |
| **5** | **5** | **9.42 : 1** | **3.31 : 1** | **2.85 : 1** |
| 5 | 7 | 10.50 : 1 | 3.69 : 1 | 2.85 : 1 |
| 10 | 3 | 2.77 : 1 | **0.97 : 1** | 2.85 : 1 |
| 10 | 5 | 5.91 : 1 | 2.08 : 1 | 2.85 : 1 |
| 10 | 7 | 9.75 : 1 | 3.43 : 1 | 2.85 : 1 |

**The disparity largely collapses** — at the default operating point 9.42 → 3.31, against a signal-count ratio of 2.85 — and at S=3 the normalised ratio falls *below* the count ratio (1.36 at N=5; 0.97 at N=10, i.e. shorts marginally ahead).

**A residual remains at S≥5 and it is reported as a finding, not smoothed away.** Normalising by signal count `n` removes a linear factor, but the combinatorial driver is super-linear — co-firing opportunity scales with pair availability (~`n²`), which is why 8.54:1 predicts the raw disparity better than 2.85:1 does. Dividing by `n` therefore leaves roughly the remaining factor. **This is a structural property of counting co-occurrences among unequal pools, not evidence that short signals are worse.** The build reports the normalised ratio at every (N, S) cell so the residual stays visible.

*What would falsify the combinatorial explanation:* if per-signal activity were materially lower for shorts, the disparity would be a quality effect rather than a pool-size effect. Measured, it is not — shorts are active on *more* days per signal. If a future run shows the reverse, the explanation must be revisited.

*Fit risk:* the 37/13 composition is a property of the incumbent book, which is the output of the funnel being replaced. The normalisation is defined in terms of whatever composition the active book has, so it does not encode 37/13 anywhere.

**`S` is NOT hardcoded at 5.** A previous revision fixed `S = 5` while §F.4 declined to fix `U` on the grounds that "setting `U` here would be fitting a threshold to six months without seeing the curve." That argument applies to `S` with identical force, and the inconsistent treatment is removed: **both are deferred to the build, both reported over a grid, both set by the operator on the evidence.**

`DepthYield` is reported over `S ∈ {3, 4, 5, 6, 7}` at N=5 and at N=10. **`S = 5` is the stated default** — not because it is arbitrary but because the measured quality break sits there (bar-level qualifying depth 5-6: PF 87.58, WR 98.6%, worst day positive) — and the default is a starting point the operator may move, not a fixed constant.

Measured reference on the committed book, BOOK population, 121 traded days, S=5:

| | N=5 | N=10 |
|---|---|---|
| clusters of size ≥ 5, LONG / SHORT | 113 / 12 | 130 / 22 |
| pooled per day *(superseded — recorded for continuity only)* | 1.033 | 1.256 |
| **`DepthYield_LONG`** (per day per long signal) | **0.02524** | 0.02904 |
| **`DepthYield_SHORT`** (per day per short signal) | **0.00763** | 0.01399 |

`DepthYield` is the objective-relevant quantity — co-firing matters only insofar as it produces depth. **The pooled figure is superseded by the per-direction pair and must not be used in the objective.**

*Fit risk:* `S` and `N` are both six-month choices. `N` is fixed a priori (§0.1.3); `S` is left open and reported over a grid so the sensitivity is visible rather than buried in a constant.

### C.2 — Measuring failure correlation, separately

**Pearson correlation is NOT the measure. It materially understates joint failure on this book, and the understatement was measured, not assumed.**

Build the per-signal daily-loss series from S6's regenerated `signal_per_day_pnl.jsonl` (§B). For each pair, restricted to days where **both** signals traded:

```
tau            = 0.20      -- CORRECTED from 0.10
MIN_SHARED     = 10        -- CORRECTED from 20
series_i       = signal i's RAW DAILY P&L over its active days -- NOT floored at zero
q_i, q_j       = the tau-quantile of each series over the pair's shared active days
coexceed(i,j)  = P( series_i <= q_i  AND  series_j <= q_j )
lambda_L(i,j)  = coexceed(i,j) / tau
                 -- 1.0 == PERFECT LOWER TAIL DEPENDENCE
                 -- independence reads tau (= 0.20), NOT 1.0
lambda_over_independence(i,j) = coexceed(i,j) / (tau * tau)
                 -- the LIFT form; 1.0 == independence. Emitted alongside, for the lift reading.
failcorr(i,j)  = Pearson correlation of the two raw daily P&L series  [REPORTED DIAGNOSTIC ONLY]
```

**ANNOTATION CORRECTED. The formula was right; the annotation was wrong.** A previous revision paired `lambda_L = coexceed / tau` with "1.0 == independence". Both cannot hold: under independence the joint probability is `tau^2`, so dividing by `tau` yields **`tau` = 0.20**, not 1.0. The 1.0-is-independence reading belongs to the `/tau^2` lift form, which is now emitted separately as `lambda_over_independence`. The spec's own step-size claim (`1/(k*tau) = 0.5` at k=10) is consistent with `/tau` and confirms the formula was the correct one. `lambda_L = 1.0` would require `coexceed = tau`, i.e. `P(both in tail) = P(one in tail)` — **perfect** lower tail dependence.

**Verified: nothing downstream is affected.** `T_max` is a ratio to a permutation null computed with the identical estimator (§C.2 acceptance rule 1), so any constant scaling divides out. The Auditor confirmed `kappa` identical to ten decimal places under either scaling; the incumbent reads `lambda_L` 0.339 and `lambda_over_independence` 1.683.

**SERIES DEFINITION CORRECTED — and this is a defect the correction notice did not reach.** "Daily-loss series" was ambiguous and I implemented it as `min(pnl, 0)`, flooring profitable days at zero. **That estimator is degenerate**: with most days profitable the series has heavy mass at exactly 0, the tau-quantile lands on 0, and `series <= q` is then satisfied by *every profitable day*. Measured, **73.4% of pairs returned `coexceed` of exactly 1.0** under that reading. The series is **raw daily P&L**, so that the tau-quantile is a genuine bad-day threshold. Every §C.2 figure below is re-derived on the corrected series.

**THE OPERATING POINT WAS WRONG AND IS CORRECTED. `tau = 0.10 / MIN_SHARED = 20` is superseded.** Measured across the full C(50,2) = 1,225 pair space of the committed book:

**THE PRIMARY FIX — retention — is confirmed and is the reason the change stands:**

| | pairs retained |
|---|---|
| **τ=0.10, k=20** *(superseded)* | **100 / 1,225 = 8.2%** |
| **τ=0.20, k=10 — ADOPTED** | **790 / 1,225 = 64.5%** |

The superseded point calibrated a hard constraint on a twelfth of the structure it claims to bound, and was degenerate at the floor: with `k=20, τ=0.10` co-exceedance moves in steps of `1/(k·τ) = 0.5`, and among near-floor pairs only **8 distinct λ values** occurred across 83 pairs.

**THE SECOND-ORDER CLAIM WAS WRONG AND IS CORRECTED. The exclusion bias at the adopted point is ANTI-CONSERVATIVE, not conservative.** A previous revision claimed the change flips the bias conservative. Re-derived on the corrected raw-P&L series at τ=0.20, k=10 (mean `lambda_L`, independence reads 0.20):

| arm | mean λ | vs retained |
|---|---|---|
| retained, k ≥ 10 (n=790) | **0.3387** | — |
| excluded RAW, 1 ≤ k < 10 (n=435) | **0.4433** | **ANTI-CONSERVATIVE** |
| excluded degeneracy-guarded, 3 ≤ k < 10 (n=414) | **0.3571** | **ANTI-CONSERVATIVE** (narrows, does not flip) |

**Mechanism, measured: degenerate pairs below k=3.** 21 pairs sit at k<3 — **5 at k=1** and **16 at k=2**. At k=1 the single shared day is trivially its own tau-quantile, so `coexceed = 1` and `lambda_L = 1/tau = 5.0` mechanically. Guarding at k≥3 removes them and narrows the gap from 0.4433 to 0.3571, but the excluded arm remains above the retained one. **The bias does not flip.**

*Why my original claim was wrong, stated so the error is not repeated:* it was computed on the `min(pnl, 0)` series described above, under which 73.4% of pairs returned `coexceed = 1.0` and the arms were no longer distinguishable in a meaningful way. The k<3 degeneracy identified downstream is real and secondary; **the series definition is the deeper cause**, and correcting it alone reverses the reported direction.

**MATERIALITY — immaterial in effect, and the reason is structural rather than fortunate.** `T_max` is a **ratio to a per-segment permutation null computed with the identical estimator and the identical `MIN_SHARED` exclusion** (acceptance rule 1). Both numerator and denominator therefore carry the same exclusion bias and it **substantially cancels**. Independently, §C.2's closing rule already subordinates this constraint: where `TailDep` and `FailConc` disagree, `FailConc` and the absolute bound carry the decision. **The direction is corrected because a reader must not later rely on a "conservative" label that is anti-conservative** — not because a design decision turns on it.

**Made visible every run.** The build emits `exclusion_bias_degeneracy_guarded` and `degenerate_excluded_pairs_k_lt3`, so the direction and the degenerate-pair count are observable rather than assumed, in every segment and every §I split.

**Decomposition of what each change does:**
- `MIN_SHARED` 20 → 10 fixes **retention**: 8.2% → 64.5%. Retention depends only on the floor, not on τ. **This is the fix that matters and it reproduces exactly.**
- `tau` 0.10 → 0.20 improves **granularity** (halves the step size at a given k). It does **not** flip the exclusion bias — that was the erroneous claim.

*Residual, not removed by the correction.* The fire-frequency association persists at both operating points — Spearman(retained, fire-frequency) = +0.375 at k=20 versus **+0.584** at k=10. Part is mechanical (an indicator retained 8.2% of the time has less variance to correlate), but the association is real at both points and is **not** eliminated by the fix. It is recorded in the residual limitation below rather than claimed as solved.

**MINIMUM-OVERLAP FLOOR (mandatory).** A 50-signal book yields 1,225 pairs, many sharing only a handful of active days, and Pearson `r` on `n = 2` is noise that must not enter an unweighted mean. **A pair contributes to `TailDep(B)` or `FailCorr(B)` only if it has `>= MIN_SHARED = 10` shared active days.** Pairs below the floor are:
- **excluded** from both means;
- **counted and reported** — the run report states how many pairs qualified, how many were excluded, and the excluded share, so a book whose pairwise structure is mostly unmeasurable is visible rather than silently averaged;
- **flagged as a book-level risk** if more than 50% of pairs fall below the floor, since in that case the pairwise constraint is not meaningfully binding and `FailConc` (which needs no pair overlap) must carry the survival decision alone. **At the corrected operating point the committed book retains 64.5%, so the flag does not fire; at the superseded point it would have.**
- The build must also report the **mean λ of the excluded pairs**, so the direction of the exclusion bias is visible every run rather than assumed benign. That single diagnostic is what exposed the superseded operating point.

Book-level:

```
TailDep(B)   = mean pairwise lambda_L over pairs with >= MIN_SHARED shared active days
FailConc(B)  = the book's worst single-day loss expressed as a multiple of its mean daily loss
CVaR_i       = the mean of signal i's daily P&L over the worst 5% of BOOK days
mCVaR_i      = CVaR_i / (signal i's share of book lots)     -- marginal tail contribution per unit exposure
```

`FailConc` remains the survival-first book-level quantity. `TailDep` replaces `FailCorr` as the pairwise measure. `mCVaR_i` identifies individual tail-risk concentrators — signals whose contribution to the worst days is disproportionate to their exposure — which is the per-signal diagnostic the FTMO daily ceiling actually needs and which no ranking on PF can surface.

**VERIFICATION — RE-DERIVED at the ADOPTED operating point on the CORRECTED raw-P&L series. PROPERTY OF THE BOOK; must be re-derived for any new book. Parameters: τ=0.20, MIN_SHARED=10, BOOK population, 790 qualifying pairs.**

| measure | value |
|---|---|
| mean Pearson correlation of daily P&L | **+0.0992** — reads as near-independent |
| mean `lambda_L` (`coexceed/tau`) | **0.3387**  *(independence reads 0.20)* |
| **as lift over independence** (`lambda_over_independence`) | **1.69x** |
| pairs with Pearson < 0.2 **but** tail lift > 2x independence | **162 of 790 (20.5%)** |
| rank correlation between the two measures | **+0.382** |

**The qualitative finding survives the correction; its magnitude does not.** Pearson reads the book's failures as near-independent (+0.0992) while they co-exceed in the tail at **1.69x** independence, and one pair in five looks benign under Pearson while concentrating risk where the daily ceiling binds. The two measures rank pairs differently (rho +0.382), so neither substitutes for the other.

*Superseded figures, recorded so they are not re-cited:* an earlier revision reported Pearson +0.0604, "3.548x independence", 24.6% and rho +0.246. Those were computed on the degenerate `min(pnl, 0)` series and at the superseded τ=0.10/k=20 point, and the "x independence" label additionally misapplied the `/tau` value as if it were the `/tau^2` lift. **The corrected lift is 1.69x, not 3.5x** — the direction of the finding holds, the strength was overstated by roughly a factor of two. The re-derived 1.69x reconciles with the build's independently-emitted `lambda_over_independence` of 1.6831.

**ACCEPTANCE RULE (implementable and verifiable):**

1. **Hard bound, CALIBRATED TO A PER-SEGMENT PERMUTATION NULL — not to a fixed reference.** `T_max` is expressed as a **ratio to the null**, never as an absolute λ level and never as a fixed full-series figure.

   **Construction, per training segment:** permute each signal's raw daily P&L series independently across its own active days (destroying cross-signal alignment while preserving each signal's own P&L distribution and activity pattern), recompute `TailDep` over the permuted book, repeat `P >= 500` times. This yields `TailDep_null(segment)` — the tail co-exceedance a book of this shape, activity and loss distribution produces **by chance alone** in **this** segment.

   ```
   T_max = kappa * TailDep_null(segment)
   ```

   `kappa` is set from the incumbent book's own ratio `TailDep_incumbent / TailDep_null`, measured **on the active training segment**. A candidate book is rejected if its tail co-exceedance exceeds the incumbent's by more than that multiple of what chance produces in the same segment.

   **Why a null rather than a level.** An absolute λ threshold is not portable: λ depends on `tau`, on `MIN_SHARED`, on book size, on activity density and on segment length, all of which differ across §I splits. A fixed absolute level would be a different bar in every segment while appearing constant. The ratio-to-null is dimensionless and segment-comparable, and it is the same empirical-null logic §H.1 already uses for the selection statistic — applied here to a constraint.

   *Secondary refinement, NOT the primary fix:* partial pooling / empirical-Bayes shrinkage of per-pair λ toward the book mean, weighted by shared-day count, would further stabilise thinly-observed pairs. It is **recorded as a worthwhile refinement to evaluate after the null calibration is in place** — it is not the remedy for the operating-point defect and must not be substituted for it.
2. **Hard bound, RELATIVE:** no single signal may carry `mCVaR_i` worse than `C_max` = the 90th percentile of the incumbent's `mCVaR` distribution, **measured on the ACTIVE TRAINING SEGMENT**.
3. **Hard bound, ABSOLUTE — required, and not satisfied by 1 and 2.** A purely relative bar only guarantees the new book is no worse than the old; it cannot detect a book that is unsafe in absolute terms, and if the incumbent is itself unsafe the bar certifies the fault. The absolute constraint is the survival one and it is stated in units the account uses, not in multiples of the incumbent: **modelled worst day within the FTMO daily ceiling with stated margin, evaluated on the FULL population** (§0.1.1), since gap-filler P&L lands on the same calendar day as book P&L and the ceiling does not distinguish them.
4. **Reported, not gating:** `FailCorr(B)` (Pearson) is retained in the output purely so the divergence between the two measures stays visible to the Auditor.

**The full-series values are REPORTING REFERENCES ONLY** and must never enter a walk-forward constraint: the `lambda_L` 0.3387 / lift 1.69x figures, and the `mCVaR` distribution from which p90 is drawn. Quoting either as a bound inside a §I split is a §I.4.2 violation.

**RESIDUAL LIMITATION — stated plainly, and not to be presented away.** Even at the corrected operating point:
- the pairwise tail structure is measured on **64.5% of the pair space**, a majority but far from all of it;
- retention remains **associated with fire frequency** (Spearman +0.584 at the adopted point on my measurement), so the measured pairs are not a random sample of the pair space — frequently-firing signals are over-represented in the constraint;
- `MIN_SHARED = 10` at `tau = 0.20` still gives co-exceedance steps of `1/(k·tau) = 0.5`, so per-pair λ remains coarse even where it is estimated.

**`TailDep` is therefore a real but imprecise constraint and must not be reported as more precise than the data supports.** Where `TailDep` and `FailConc` disagree, `FailConc` and the absolute survival bound — neither of which needs pair overlap — carry the decision.

*What would falsify this:* if `TailDep` and `FailConc` rank candidate books identically (rank correlation > 0.9), the pairwise tail measure adds nothing over the book-level one and the simpler quantity should govern. The build reports both for every candidate book.

*Fit risk:* `T_max` and `C_max` are anchored to the committed book's six-month measured values. This imports that book's history as the reference point. Stated openly; the alternative — free parameters — is worse. Both must be recomputed inside each §I training split, never carried across a boundary.

### C.3 — The objective

**Maximise `DepthYield_d(B)` WITHIN EACH DIRECTION `d`, subject to `FailConc(B)`, `TailDep(B)` and survival constraints.**

The objective is applied **per direction**, and the constraints below are evaluated on the merged book. Formally, the build implements a lexicographic objective consistent with survival-first doctrine:

1. **Hard constraint:** worst modelled day within the FTMO ceiling with stated margin. Any book violating this is rejected regardless of other properties.
2. **Hard constraint:** `FailConc(B) <= F_max`, with `F_max` set from the incumbent book's value **measured on the ACTIVE TRAINING SEGMENT** — never the full-series figure (§I.4.2).
3. **Hard constraint:** `TailDep(B) <= T_max` and per-signal `mCVaR_i <= C_max` per §C.2.
4. **Maximise:** `DepthYield_d(B)` — the normalised, within-direction measure of §C.1, run independently for each direction per §C.3.1.
5. **Tie-break (§D.1):** higher `Coverage(B)` among books within tolerance of the best `DepthYield_d`. **ITEM 24 CORRECTION — THE TOLERANCE IS RELATIVE, NOT A PERCENTAGE-POINT BAND.** A band stated in points means something different at a 5% coverage scale than at 1.4%: one point is a fifth of the former and three-quarters of the latter, so a fixed band silently tightens as coverage falls and is a different rule at each scale. State it as a fraction of the best `DepthYield_d` in that direction, or re-derive it at the scale it will actually be applied at.
6. **Tie-break:** lower `FailCorr(B)` (Pearson, reported diagnostic).

**This inverts the old objective on axis (i) while preserving it on axis (ii).** Co-firing is now rewarded; correlated failure is still penalised.

**THE MEASURED PREMISE — why participation in depth is weighted over standalone signal quality.** This was previously asserted. It is now evidenced. Spread of win rate **across individual signals**, by cluster depth band (N=10, BOOK, signals with ≥15 trades in the band):

| depth band | signals | sd of WR | range | mean WR |
|---|---|---|---|---|
| shallow (1–2) | 20 | **9.01** | **70–100%** | 86.5% |
| mid (3–7) | 36 | 4.67 | 80–100% | 91.3% |
| deep (8+) | 33 | 5.52 | **81–100%** | **94.5%** |

**At shallow depth, which signal fired matters — the spread is 9 points and the floor is 70%. At depth, the worst signal in the book still wins 81%.** Signal identity dissolves as corroboration accumulates: the dispersion nearly halves and the floor rises 11 points.

This is the core premise of the redesign and the reason the objective maximises a depth quantity rather than ranking signals on standalone PF. **A selection process that ranks individual signals is optimising the variable that stops mattering.** (Property of the BOOK, not the market — it describes how *these* signals behave in company, and must be re-derived for any new book.)

#### C.3.1 — The search procedure

The objective above specifies **what** to optimise. The search over candidate books is **greedy forward selection with CELF (Cost-Effective Lazy Forward) evaluation**, **RUN SEPARATELY PER DIRECTION AND MERGED**: for each direction independently, start from the empty book, iteratively add the signal producing the largest marginal gain in that direction's objective, maintain a priority queue of upper-bound marginal gains and re-evaluate lazily, stop when the marginal gain falls below a stated threshold or a hard constraint binds. Then merge the per-direction books and evaluate the merged book against every constraint in §C.3.

**WHY PER DIRECTION — this is the structural fix, and it is load-bearing.** Under a pooled greedy search, a short signal's marginal `DepthYield` contribution is roughly an order of magnitude below a long signal's **regardless of its quality**, for the combinatorial reasons measured in §C.1 (raw 9.42:1 against a 2.85:1 signal-count ratio, tracking the 8.54:1 pair-availability ratio). Pooled greedy would therefore add longs almost exclusively — and the effect is **self-reinforcing**: each long added raises long co-firing opportunity and depresses the relative marginal value of every remaining short.

**The failure would have been silent.** §H.3.1's directional protections are triggered by *removal*, and a book that never acquires shorts never reaches the "last short signal" trigger. The operator's directive would have been protected at three stages and unguarded at the decisive one. Running the search per direction removes the bias **structurally** — shorts compete only against shorts, so no cross-direction marginal comparison is ever made during selection.

**The strongest evidence for this fix is §D.0.2, and it is worth restating here because it separates two things that are easily conflated.** The incumbent book *reaches* both directions at near-equal rates (thrust episodes traded: 4.1% up, 3.0% down; missed set 50.3% down-side) and then builds depth on only one: LONG mean cluster depth **3.38** with 19.3% reaching size ≥5, SHORT mean depth **1.72** with **3.0%** reaching size ≥5 and **56.9% left solo**. The short side is not failing to find opportunity and it is not losing more often — its win rate is 91.0% against the long side's 90.9%. **It is failing to accumulate corroboration, because thirteen signals cannot co-fire the way thirty-seven can.** A pooled search would read that combinatorial shortfall as a quality signal and deepen it.

Note the division of labour between the two O1 fixes: **§C.1's normalisation makes the two directions' numbers comparable for REPORTING**; **this per-direction search is what actually prevents the bias in SELECTION.** The normalisation alone would not have been sufficient, because a residual disparity remains at S≥5 (§C.1) and pooled greedy would still have exploited it.

**NO DIRECTIONAL TARGET IS ENCODED ANYWHERE. This is a prohibition, not a preference.**
- There is **no directional floor, quota, target, minimum short-signal count, or reserved allocation** in the objective, the search, the constraints, or the stopping rule.
- Each direction's search stops on **its own** marginal-gain threshold and **its own** constraint binding — never on a count.
- A direction may legitimately terminate with **zero** signals if nothing in it clears the §H bars. That is a permitted and reportable outcome.
- **An Auditor confirming compliance should verify that no integer signal-count target for either direction appears in `selection.py`, and that neither direction's stopping rule reads the other direction's book.**

A directional floor was proposed and **overruled**, on two grounds recorded here so it is not re-proposed: (i) a floor is a pre-set target imposed before the search runs — it tells the picker what to find, which is the prescriptive failure the additive doctrine forbids; (ii) any floor calibrated on the incumbent's 13 shorts would be calibrated on an **artifact**, since that book is the output of the funnel being replaced, built under a decorrelation objective now believed to have selected against depth. The new search spans fourteen families and ~238 conditions and may surface a materially different composition; calibrating a constraint against the thing being discarded is circular.

**MANDATORY CAVEAT — the approximation guarantee does NOT transfer to the full objective.** `Coverage` is submodular and a greedy selection over coverage alone inherits the standard (1 − 1/e) bound. The failure-correlation and tail-dependence penalties are **not submodular in general** — adding a signal can change pairwise tail structure non-monotonically. The per-direction split does not change this. Therefore:

- The build must **either** verify submodularity for the specific penalty as implemented (and document the proof or the counterexample search),
- **or** use greedy purely as a heuristic and **make no claim of the (1 − 1/e) bound anywhere** in code comments, run reports, or documentation.

Claiming the bound without establishing it is an invalidity condition. The Auditor should check for the claim, not just the algorithm.

**Merge-stage requirement.** The per-direction books are merged before the §C.3 constraints are evaluated, because `FailConc`, `TailDep` and the absolute survival bound are properties of the **combined** book — cross-direction tail co-dependence is real and must not escape measurement by being searched separately. If the merged book violates a constraint, the build reports which direction's marginal additions caused it and backs off **from the direction that caused it**, never by default from the smaller one.

#### C.3.1a — Directional composition is an OUTPUT, not an input

**The resulting long/short split is a measured result about this instrument and this vocabulary. It is reported, never targeted.**

Headline reporting requirements, in the run report and not buried in a CSV:
1. Final **long/short signal split** of the selected book.
2. **`DepthYield_LONG` and `DepthYield_SHORT`** separately, at every (N, S) cell, with the raw and normalised ratios and the signal-count ratio alongside.
3. **Per-direction constraint outcomes** — which direction, if either, was stopped by a constraint rather than by marginal gain, and which constraint.
4. **Per-direction §H outcomes** — empirical-null pass rate, stability retention, and §H.3 bucket results, each within direction.

**Interpretive context — CORRECTED, and the previous assumption is RETIRED.** An earlier revision of this section recorded that "US30 is an equity index with structural upward drift, so a long-dominant book is a plausible and legitimate outcome for this instrument." **That assumption has been measured and it does not hold. It is withdrawn.** See §D.0.1: thrust opportunity computed from price alone is **symmetric and marginally larger to the downside** — 49.8% up / 50.2% down of thrust bars, with a larger median down-move (82.0 vs 77.1 pts) — and it stays close to symmetric in every month including the strongest up-month. Upward drift in the *price level* does not produce upward asymmetry in *directional thrust opportunity*, and the two were conflated.

**What remains true:** directional composition is **regime-dependent** and this span is predominantly bullish in net level, so a composition measured here must not be treated as a permanent property of the system. Whatever emerges — heavily long, balanced, or short-dominant — is a finding.

**What is no longer available as an explanation:** a long-dominant book cannot be justified by appeal to the instrument's drift. If the redesign produces one, that is a property of the selection process and must be reported as such, measured against the symmetric baseline in §D.0.1.

*What would falsify the combinatorial diagnosis:* if, with the per-direction search in place, shorts still enter at a rate far below longs *after* clearing identical within-direction §H bars, the disparity is not purely structural and the residual cause must be measured rather than assumed.

*Fit risk:* the per-direction split is itself a design choice made after observing a directional imbalance on six months. It adds no fitted parameter and encodes no target, which is why it is preferred to a floor — but it must be carried into every §I split unchanged, not re-decided per segment.

*What would falsify greedy as the right search:* on a reduced instance small enough for exhaustive enumeration, if greedy's book is materially worse than the exhaustive optimum, the heuristic is inadequate and the build must escalate to a solver formulation. The build runs this comparison on at least one reduced instance and reports the gap.

#### C.3.2 — Reporting additions (NOT corrections to a measured deficiency)

The following are added because they improve what the operator can see when deciding, **not** because any measurement showed the lexicographic objective to be deficient. They are labelled as such so downstream readers do not infer a defect that was never demonstrated.

- **Model Confidence Set (Hansen).** Report the set of candidate books that cannot be statistically distinguished from the best at 90% confidence, rather than a single point selection. Given measured selection instability, an equivalence class is likely and choosing the most robust member of it is more defensible than chasing the apparent optimum. **Reported diagnostic.**
- **Pareto frontier** over (persistence, worst-day, `DepthYield`, `Coverage`). The lexicographic ordering collapses genuine trade-offs into a fixed precedence; the frontier makes them visible so the human principal can choose. The lexicographic result remains the default selection; the frontier is presented alongside it. **Reported diagnostic.**

*Fit risk for both:* neither adds a fitted parameter, so neither adds overfit surface. The MCS confidence level (90%) is a stated convention, not a tuned value.

*Motivating numbers:* the depth ladder is monotonic on cluster size — bands 1-2 WR ~87%, PF 2.33–2.83; band 5-7 WR 95.5%, PF 11.39; band 13+ WR 96.0%, PF 11.78, worst day **−$12.3** (N=10, trade-level). Pre-jar qualifying depth 5-6 reaches PF 87.58 at WR 98.6%. Solo (depth-1) is PF 3.16 with a −$574 worst day.

*What would falsify the inversion:* if a book selected for high `DepthYield` shows `FailConc` materially worse than the committed book at equal net, co-firing and correlated failure are not separable in practice and the two-axis model is wrong. The build must report both axes for every candidate book so this is visible rather than assumed.

*Fit risk:* `F_max`, `T_max` and `C_max` are all anchored to the incumbent book. Anchoring is preferable to free parameters, but it is **relative** — it certifies only that the new book is no worse than the old, and would certify a fault if the incumbent carried one. That is why §C.2.3's **absolute** survival constraint is mandatory and is evaluated independently of all three. Each is recomputed inside every §I training segment; the full-series values are reporting references only.

---

## 5. SECTION D — THE REACH PROBLEM

**Resolved first, per §1.2 and §1.3:** the book captures large *absolute* moves (traded Q4 at percentile 88.9 of absolute forward move) while sitting at ordinary *ATR-normalised* multiples (percentile 72.6). The missed thrust set is tradeable (median 58–78 pt) but systematically smaller than what the book already takes (168–224 pt). Only 4.4–5.4% of thrust episodes are touched.

Reach is therefore a **real and large opportunity in count**, addressing a **smaller-move population** than the book currently trades. Both halves must govern the design.

#### D.0 — WHY episodes are missed: a coverage gap, not a throughput gap

The reach programme rests on knowing the *mechanism* of the shortfall, not merely its size. Measured on all 3,090 missed thrust episodes (W=15, K=p85, E=p75, N=5):

| reason the episode was missed | count | share | median move |
|---|---|---|---|
| **A — no book signal ever qualified anywhere in the span** | **2,776** | **89.8%** | 55.9 pt |
| B — a signal qualified but no entry resulted | 314 | 10.2% | 87.0 pt |
| of B, span >50% occupied (jar / already-in-trade blocked) | 43 | **1.4% of all missed** | — |

**ITEM 24 CORRECTION — THIS IS A GATE DECOMPOSITION, NOT SIGNAL ABSENCE.** The 89.8% was computed against RAW TERRAIN, which counts episodes the book could never have taken. Two deliberate, measured exclusions sit between raw terrain and anything reachable: the eligibility mask (ADX>=15, ticks>50, post-warmup) and D2D directional agreement. Measured on the corrected frame at this same cell, raw terrain 3,816 UP / 3,674 DOWN reduces to REACHABLE 1,143 UP (29.95%) / 1,155 DOWN (31.44%). So the correct decomposition of a missed episode is:

| gate | what it means | status |
|---|---|---|
| episode not eligible | the bar failed ADX/volume/warm-up | EXCLUDED BY DESIGN, gating PF 16.63 vs 2.25 OOS |
| D2D disagreed with episode direction | the directional gate refused the side | EXCLUDED BY DESIGN, D2D-gated PF 5.14 vs long-ungated 1.53 |
| reachable, no signal fired | the genuine search/vocabulary gap | THE ONLY RESIDUAL THAT MEANS ANYTHING |

**As previously written the line said the vocabulary is the limit, which is the exact framing this rebuild retired.** ~70% of the raw-terrain shortfall is two gates the operator chose and measured, not signal absence. The residual is the reachable unclaimed set — 1,089 UP / 1,127 DOWN against BOOK-50 — and item 6's catalogue emits it per episode with `n_conditions_firing` and `n_valid_triples_touching` so a SEARCH gap (many conditions fire, no valid triple lands) is distinguishable from a GRAMMAR gap (few fire). Occupancy and the 6-lot jar account for 1.4%.


**EXPLICIT LIMIT OF THIS CONCLUSION.** This measurement *locates* the gap. It does **not** establish that the available vocabulary can fill it. Directly against that hope: S8B basis 3 found **no single condition that separates thrust episodes — maximum ATR-controlled lift 1.35.** So the conditions that would populate the missed 89.8% have not been shown to exist in the current 249-condition vocabulary, and it remains entirely possible that they do not. The correct reading is: the gap is real, its mechanism is identified, and whether it is *fillable* is an open question the redesign tests rather than assumes.

*What would falsify the reach programme:* if, after the full funnel, no signal qualifying under §H shows materially higher `cov_missed_share` than the incumbent book, the vocabulary cannot reach the missed set and the programme should be closed in favour of deepening existing coverage. That is a legitimate and reportable outcome.

*Fit risk:* the decomposition is computed at one thrust parameterisation. The build repeats it across the §D.2 grid before the conclusion is treated as stable.

#### D.0.1 — DIRECTIONAL COVERAGE BASELINE (price-only) — the symmetry the redesign is measured against

**PROPERTY OF THE MARKET, not of the book.** Computed from OHLC alone, no signals involved: W=30, K = p85 of |disp|/`ATR_1M`, E = p75 directional efficiency, post-warmup.

**This measurement exists because a market property was previously inferred *through* BOOK-50, which is the output of the funnel being replaced. Reading the instrument through the incumbent book is circular, and it produced the withdrawn drift assumption in §C.3.1a.**

| | thrust bars | share | median move |
|---|---|---|---|
| **UP** | 11,528 | **49.8%** | 77.1 pts |
| **DOWN** | 11,603 | **50.2%** | **82.0 pts** |

Monthly down-share of thrust bars, against monthly net price change:

| month | down-share | net price change |
|---|---|---|
| 2026.01 | 53.2% | −546 |
| 2026.02 | 52.6% | +99 |
| 2026.03 | 54.7% | −2,082 |
| **2026.04** | **45.4%** | **+3,437** |
| 2026.05 | 49.2% | +1,234 |
| 2026.06 | 47.7% | +1,238 |
| 2026.07 | 51.3% | −84 |

**Directional opportunity is symmetric and marginally larger to the downside — in every month, including April, the strongest up-month at +3,437 pts, which still ran 45.4% down-thrusts.**

Against that baseline, BOOK-50's capture (**property of the BOOK**):

| | trades | WR | PF | net | share of net |
|---|---|---|---|---|---|
| LONG | 2,349 | 90.9% | 5.45 | $84,643 | **86.2%** |
| SHORT | 708 | 91.0% | 3.65 | $13,562 | **13.8%** |

**A ~50/50 opportunity set converted into an 86/14 capture. That gap is a property of the SELECTION PROCESS, not of US30.** Note the win rates are effectively identical (90.9 vs 91.0) — the short side is not losing more often, it is capturing less.

**This is the directional coverage baseline the redesign is measured against.** §C.3.1a's reporting requirements are evaluated against 50/50, not against the incumbent's 86/14.

#### D.0.2 — The short-side shortfall is DEPTH, not REACH

**Reach is engaged near-symmetrically. Depth is not.** Thrust episodes (N=5 chaining) versus book participation — **market property on the left, book property on the right**:

| | episodes | traded | missed |
|---|---|---|---|
| UP | 1,534 | 4.1% | 95.9% |
| DOWN | 1,533 | 3.0% | 97.0% |

**The missed set is 50.3% down-side — essentially symmetric.** The book *reaches* both directions at near-equal rates. What differs is what happens after it arrives (**property of the BOOK**, N=5):

| | signals | clusters | mean depth | max | reach ≥5 | solo |
|---|---|---|---|---|---|---|
| **LONG** | 37 | 587 | **3.38** | 39 | **19.3%** | 28.4% |
| **SHORT** | 13 | 404 | **1.72** | 11 | **3.0%** | **56.9%** |

**57% of short clusters are solo — the fragile population that carries the tail (PF ~3) — against 3% reaching depth 5+ where PF runs 11–87.** The book engages both directions and then builds depth on only one.

**This is combinatorial and it is a property of the incumbent book, not the market** — thirteen signals cannot co-fire into depth the way thirty-seven can (§C.1: pair availability 8.54:1). **It is the strongest available justification for the per-direction search adopted in §C.3.1**, and it is recorded there as such.

**It is NOT a justification for a directional floor, quota or target.** That remains prohibited under §C.3.1a. The fix is to stop the *search* from penalising a small pool, not to mandate an outcome.

*Reproduction notes, stated rather than smoothed:* the book-side figures above reproduce **exactly** — 708 shorts / WR 91.0 / PF 3.65 / $13,562 / 13.8%, and every cluster-structure figure at N=5. The price-only thrust bar counts run ~10% above the values supplied to me (11,528/11,603 versus 10,513/10,528) under a post-warmup mask, with medians close (77.1/82.0 versus 76.5/83.5) and shares essentially identical; under an eligible-universe mask the split is 49.1/50.9. **The symmetry conclusion is robust to the masking choice; the absolute counts are not, and the build must state its mask.** Episode counts and traded rates likewise depend on chaining tolerance and on whether "traded" means an entry inside the span — mine use N=5 and entry-bar-inside-span, and differ in level from the supplied figures while agreeing on the near-symmetric ratio.

*Fit risk:* six months, one instrument, two partial months. The symmetry holds in all seven monthly buckets, which is the strongest form of support available on this span, but a second export remains the test.

**DOCTRINE RECONCILIATION — `DOT_signal_discovery_mantra.md`, 305 lines, sha256[:12] `fae943d40231`.** The doctrine is binding and is not superseded by measurement. **Verified against the current revision: the two documents agree, and no divergence stands.**

Reconciled figures: §2's cross-reference to this spec's operating point (3,067 episodes at 4.1% / 3.0% RAW TERRAIN (item 24: the REACHABLE counterparts are the primary figures and must be quoted alongside - BOOK-50 occupies 4.72% UP and 2.42% DOWN of reachable, 1.415%/0.762% of raw)), the 89.8% no-signal-fires figure, §4's depth ladder (N=10, BOOK, with N=5 values noted), §4.1's arc table at `j/(size−1)` (7.74 / 19.43 / 8.32 / 6.79) and its N=5 tolerance caveat, §4.2's win-rate dispersion (sd 9.01 → 4.67 → 5.52), and §5's cluster structure (N=5, BOOK: LONG 3.38 / SHORT 1.72).

**The directional-symmetry figures now agree in form as well as substance.** The doctrine states the split as **~50% up / ~50% down, range 49.7–50.6%, never leaving a ±0.6pp band across six independent parameter cells**, with down-moves larger at every cell. This spec measures **49.8% / 50.2%** at its own stated cell (W=30 / K=p85 / E=p75 / post-warmup), which sits inside that band. **These are the same statement measured at different cells, not a disagreement** — an earlier revision of this block recorded a divergence against the doctrine's superseded point estimates (50.0/50.0, medians 83.5/76.5, April 44.3%); those were replaced by the robustness range and the divergence no longer exists.

**A previously-returned observation is now closed.** This block formerly flagged that the doctrine's §3 quoted bare percentages without W, K, E, mask or N — the same class of omission its own rule 1 forbids. **That was actioned in the doctrine; §3 now carries the six-cell range and its parameters, and every numeric table in the doctrine now states its parameters.** Nothing outstanding.

**One doctrine result independently verified here, because it is the same construction this spec relies on.** The doctrine's §4.2 records that its ≥15-trade-per-band filter is load-bearing rather than cosmetic. Re-derived: without the filter the table reads **sd 13.21 / 5.68 / 14.85 with a 0.0% floor at depth**, and the finding **inverts** — dispersion appears to rise at depth instead of nearly halving. The mechanism is small-`n`: 15 of 48 deep-band signals hold fewer than 15 trades, their win rates are almost all 100%, and the 0.0% floor comes from a single signal holding **one** trade in the band. **This is exactly the argument that sets `MIN_SHARED` in §C.2** — an estimator computed over too few observations is not a weak measurement but a misleading one, and it can reverse a conclusion rather than merely widen it.

**Standing construction, adopted for every finding in this document:** when a finding depends on a filter, threshold or restriction, **the filter is part of the finding.** A reader who cannot reproduce the restriction cannot reproduce the conclusion, and a table quoted without its restriction may support the opposite claim. §C.2's `MIN_SHARED = 10`, §0.1.3's `N = 5`, §F.3.1's tolerance split, §C.1's `S` grid and §H.2's ≥15-day equivalents are all stated on this principle.

### D.1 — Reach must not relax quality

The acceptance bar for a signal recruited for coverage is **identical** to the bar for any other signal: §H.1 empirical-null, §H.2 stability, §H.3 regime-conditional positivity, and the §C.3 survival constraints. Coverage is a **tie-breaker among qualifying signals**, never a substitute for qualification.

Concretely, coverage enters as **step 5** of the §C.3 lexicographic objective, after the three hard constraints and the `DepthYield` maximisation:

4. maximise `DepthYield(B)`
5. **among books within a stated RELATIVE tolerance (a fraction of the best `DepthYield_d`, never a percentage-point band — item 24) of the best `DepthYield`, prefer the book with higher `Coverage(B)`, measured against the REACHABLE denominator with the raw-terrain figure reported alongside**
6. tie-break on `FailCorr(B)` (Pearson, reported diagnostic only)

### D.2 — Defining Coverage

**ITEM 24 CORRECTION — SIZE STRATA MUST BE COMPUTED WITHIN REACHABLE.** Strata computed over raw terrain do not sum to the reachable population, so a per-stratum coverage table built on raw terrain has a denominator no row of it shares. Compute every stratum inside the reachable set (episodes holding >=1 eligible bar where D2D agrees with the episode direction, per grid cell), and report the raw-terrain counterpart alongside rather than instead — the pair is what shows the room remaining.

```
Coverage(B) = fraction of thrust episodes (basis 3) that book B touches with >= 1 entry
```

reported per (W, K, E) grid cell, never at a single parameter setting. Reference value: the committed book's measured 4.4–5.4%.

Because missed episodes are smaller, `Coverage` is additionally reported **stratified by episode absolute size** (<50 pt, 50–100 pt, 100–200 pt, >200 pt) so that coverage gains in the small-move stratum are never presented as equivalent to gains in the large.

### D.3 — S8B coverage columns as a selection input

`cov_book_traded`, `cov_book_missed`, `cov_missed_share` become inputs to candidate ranking, subject to three constraints established in the S8B review:

1. **Lift, not raw rate.** Raw participation is confounded by fire frequency; cluster-span coverage of the eligible universe is 1.18–2.28% at size≥5, while conditions fire at a median 20.0% of eligible bars. Rank on `lift`, with the absolute participating-fire count reported alongside.
2. **ATR-controlled.** The volatility-proxy check must be applied. Its necessity is measured — **all figures below are basis 1, N=5, post-remediation causal mechanism-D strata**, and every lift quoted anywhere in this document carries its basis and N for the same reason:

| condition (basis 1, N=5) | raw `lift_5` | ATR-controlled |
|---|---|---|
| `ATR_1M:hi` | 4.118 | **1.000** |
| `Bar_Range:hi` | 3.937 | **1.107** |
| `Volume:hi` | 4.524 | **2.050** |
| `Slope_Accel_LT:hi` | 3.907 | **6.401** |
| `OR_Low_Side:==-1` | 4.434 | **4.025** |

Pure volatility proxies collapse to the independence line: `ATR_1M:hi` from 4.118 to **exactly 1.000**. `Slope_Accel_LT:hi` **rises** under control, 3.907 → 6.401 — it is the informative exemplar, and it is the same 6.40 quoted in §E.4, now consistent.

**`OR_Low_Side:==-1` is NOT a rise exemplar and was previously misused as one.** At N=5 — the tolerance its raw 4.434 comes from — it **falls** (4.434 → 4.025). It rises only at N=10 (3.888 → 4.386). Quoting the N=5 raw against the N=10 direction is exactly the unlabelled-tolerance error §0.1.3 exists to prevent.

*Superseded values, recorded so they are not re-introduced:* an earlier revision quoted 1.302 / 1.244 / 2.243 / 5.814 / 4.979 for these five. Those were the Developer's **pre-fix full-sample** ATR strata, which carried look-ahead into a ranking column. They were superseded by the causal-strata remediation and must not be cited.
3. **Single conditions are not signals.** The vocabulary is single conditions; the book's signals are triples. No book may be selected from the S8B CSV. It ranks *ingredients*, and the triple built from them is scored on its own merits through the full funnel.

*What would falsify the reach programme:* if signals recruited for coverage qualify under §H but their clusters show materially worse depth-ladder behaviour than the incumbent population at equal size band, the missed set is structurally lower-quality and reach should be abandoned in favour of deepening existing coverage. **The measurement that decides this is the depth ladder computed separately for reach-recruited and incumbent clusters.** The build must produce it.

*Fit risk:* the thrust definition's W, K, E are chosen on six months. The grid requirement (never a single cell) is the mitigation. Basis 3 is forward-looking by construction and is **selection-side only** — it may never become a live gate or entry condition.

---

## 6. SECTION E — GATES

### E.1 — Unchanged

`ADX >= 15` and `Volume > 50` (**strictly greater** — `portfolio_simulation_engine.py` L146, `dots_thresholds.py` L87; the record's "ticks >= 50" is imprecise) stay as minimal-participation filters removing dead bars. The reveal doc §5 measured ADX≥15 as redundant in practice — every trade already clears it. They are a floor, not an edge, and are not to be presented as one.

**D2D directional agreement stays in the stack — and is UNMEASURED. That is a defect in the evidence, not in the gate.**

A previous revision stated "D2D directional agreement is existing and unchanged" and left it there. That is structurally the same position the AT episode just produced: a gate carried in the stack whose only supporting measurement is known to be invalid. The reveal withdrew the sole measurement of D2D's contribution as confounded and made re-measuring it open item #3; that item is still open. The document that exists to fix unmeasured gates cannot exempt one.

**This is not a claim that D2D is weak. It is a claim that nobody knows, and the redesign must not inherit an unknown as a settled component.**

**SPECIFIED MEASUREMENT (§E.5 protocol, applied to D2D):**
1. Score the committed book with the D2D directional agreement condition **removed from `build_signal_masks`**, all else identical, on the full stitched series. Report the delta in trades, net, PF, worst day, and `DepthYield`.
2. Report the same **per §H.3 bucket**, never aggregate — this is what disqualified the §E.3 regime-state filter and is the standing requirement for any gate.
3. Report separately for **BOOK, F0-solo and F0-concurrent** populations, since §1.1 established that whole-book and concurrent-only populations respond oppositely to a directional gate.
4. Report against **both D2D polarities** and with the gate inverted, so an encoding error cannot pass silently — the same failure mode that produced the AT_Regime_ST inversion.

**The gate is NOT removed pending this measurement.** Removing a component on an absent measurement is the subtractive error the governing principle prohibits; the measurement decides.

*What would falsify keeping it:* if removing D2D agreement leaves net, PF and worst day statistically indistinguishable across all §H.3 buckets, the gate is inert and its retention is a complexity cost with no benefit — a finding, and an actionable one.

*Fit risk:* the measurement runs on the same six months as everything else, and must be repeated inside the §I splits before the verdict is treated as settled.

### E.2 — The AT gate: not adopted, on evidence

Per §1.1, the directional AT gate as recorded in decision 2 is **not supported**:

| population | ungated PF | AT_Regime_ST directional-aligned PF | sign(AT_Slope_ST)-aligned PF |
|---|---|---|---|
| F0 concurrent, full series | 9.76 | 6.85 | 6.97 |
| whole book, NEW segment | 2.19 | **0.97** (net −$111) | — |

The directional gate removes profitable trades. `sign(AT_Slope_ST)` is the panel-true variable (DOT.cs L10800; the panel's "Direction" row reads `sign(detectedSlope_ST)`, and `detectedSlope_ST = hist_detectedSlope_ST[i]` at L3154, which exports as `AT_Slope_ST`) — the right variable was tested and gave the same non-result.

**Encoding, for the record:** `AT_Regime_ST == 0` is BULLISH (DOT.cs L3102 `curr_AnchorType_ST = (st_Slope > 0.0) ? 0 : 1`, corroborated L3113). It is a **latched anchor**, updated only when a slope sign change coincides with a qualifying flip (L3110); 96.98% agreement with `sign(AT_Slope_ST)` on nonzero-slope bars, and 100% of the 5,302 disagreements fall within 3 bars of a flip. Additionally `UseTrendAnchor=false` (L1584), so the exported `AT_Slope_ST` is the **raw per-bar** regression slope, not a latched value — it changes on 88.5% of bars.

### E.3 — The regime-state variant: measured, and it does not persist

The operation the record actually measured (`AT_Regime_ST == 1`, irrespective of direction) is genuinely interesting on the NEW segment. It does not survive regime-conditional examination.

**PROPERTY OF THE BOOK — this measures how the incumbent's trades sort by a regime state, not whether that regime state carries information in the market. A gate that fails on this book has not been shown to fail on any other.**

**Restated at the adopted boundary, bar 152,983 (§1.1). The record's boundary is shown alongside so the conclusion can be seen to be boundary-independent:**

| boundary | segment | ungated | reg==1 | reg==0 |
|---|---|---|---|---|
| **152,983 (adopted)** | OLD | PF 6.40, $92,296 | PF 6.57, $55,146 | PF 6.16, $37,149 |
| **152,983 (adopted)** | NEW | PF 1.84, $5,909 | **PF 3.10, $6,832** | PF 0.76, **−$923** |
| 152,814 (record) | OLD | PF 6.25, $89,797 | PF 6.33, $52,750 | PF 6.14, $37,047 |
| 152,814 (record) | NEW | PF 2.19, $8,407 | PF 3.83, $9,228 | PF 0.78, −$821 |

The shape is identical at both boundaries: near-neutral on OLD (6.57 vs 6.40 adopted; 6.33 vs 6.25 record), large on NEW, with `reg==0` negative. **The conclusion below is unchanged by the boundary correction.**

Monthly (whole book, net $):

| month | reg==1 | reg==0 |
|---|---|---|
| 2026.01 | PF 13.51, 3,095 | PF 5.33, 1,920 |
| 2026.02 | PF 5.78, 11,721 | **PF 6.48, 7,698** |
| 2026.03 | PF 6.69, 15,276 | PF 5.24, 10,185 |
| 2026.04 | PF 6.70, 5,984 | PF 5.79, 7,278 |
| 2026.05 | PF 10.81, 9,803 | **PF 11.03, 4,040** |
| 2026.06 | PF 3.88, 9,744 | **PF 4.47, 6,015** |
| 2026.07 | PF 3.72, 6,355 | PF 0.71, **−910** |

`reg==0` outperforms on PF in **three of seven months**. On the OLD segment the filter is essentially neutral (6.33 vs 6.25). **The entire effect is one month — July.** This is precisely the pattern §H.3 exists to catch, and it fails that test.

**Specified decision: the regime-state filter is NOT adopted as a gate.** It is retained as a **measured conditioner** entering §H.3's regime bucketing as a candidate bucket definition, where its behaviour can be observed without it filtering anything.

*What would establish it:* positive differential in ≥6 of 7 monthly buckets and in both volatility terciles, surviving §H.1 at the expanded trial count. The build reports this; the answer today is no.

### E.4 — The long-term adaptive family: an open question, explicitly not decided

S8B causal-strata ranking places the **long-term** adaptive family at the top of basis-1 ATR-controlled lift:

| condition | controlled lift | PF in clusters touched | PF in clusters not touched |
|---|---|---|---|
| `Slope_Accel_LT:hi` | 6.40 | 17.26 | 9.08 |
| `AT_Score_LT:lo` | 5.06 | — | — |
| `Slope_EMA_LT:lo` | 3.59 | — | — |
| `AT_Slope_LT:lo` | 3.46 | — | — |

**Every AT gate tested to date has been short-term.** The LT family has never been tested as a gate.

**Specified measurement, not a decision:**
1. Score the committed book gated on each LT directional state, both encodings tested explicitly (the ST encoding is inverted; the LT encoding must be verified against DOT.cs, not assumed to match).
2. Report per §H.3 buckets, never aggregate — this is what would have caught §E.3.
3. Report on F0 concurrent separately from whole book, since §1.1 shows the two populations respond oppositely.
4. Report against all three S8B bases, since basis 1 is book-derived and high lift there partly means "resembles the incumbents."

**Two caveats stated in the spec so they cannot be lost:** these are single conditions, not triples; and basis-1 lift is confounded with incumbency. High basis-1 lift is necessary but not sufficient evidence.

*Fit risk:* the LT family surfaced from a ranking computed on these six months. Testing it as a gate on the same six months is circular. It must be evaluated inside the §I walk-forward, selected on A and tested on B.

---

## 7. SECTION F — DEPTH AND SOLO ENTRIES

### F.1 — The measured facts

**All figures re-derived against §0.1. Every one states its population, basis and tolerance. The previous revision quoted four different depth measures in a single bullet list without labelling any; that is the defect this section corrects.**

**PROPERTY OF THE BOOK throughout this section — solo economics, the cost of waiting and the non-separability of first entries all describe how *these 50 signals* behave, and must be re-derived for any new book. None of it is a claim about US30.** In particular, "solo entries are fragile" is a statement about the incumbent's solo population, not evidence that isolated opportunity in the market is fragile.

**Solo economics** — F0 depth-1, FULL population (these are the tail figures and the tail lands on the account, so gap-filler days are included):
- 1,135 trades, WR 88.5%, PF 3.16, **+$26,710**.
- Structurally fragile: avg loss 2–3× avg win, breakeven-WR 64–75% versus 39–52% concurrent. They carry the tail — the −$574 worst day and the July bleed (2026.07 solo: WR 70.1%, PF 0.64, **−$1,208**).

**Cost of waiting for depth** — BOOK population, take-all baseline **$77,239** (2,678 trades). Measured under **all three** depth definitions, because the answer is definition-sensitive and the previous revision quoted one without saying which:

| commit rule | trades | WR% | PF | net | cost vs take-all |
|---|---|---|---|---|---|
| take-all | 2,678 | — | — | **$77,239** | — |
| bar-level `qd >= 3` (§0.1.2A) | 670 | 97.0 | 30.66 | $33,105 | **57%** |
| bar-level `qd >= 5` | 253 | 99.2 | 119.18 | $17,869 | **77%** |
| cluster position ≥ 3, **N=5** | 1,093 | 94.6 | 9.08 | $40,429 | **48%** |
| cluster position ≥ 5, **N=5** | 624 | 96.3 | 11.98 | $23,102 | **70%** |
| cluster position ≥ 3, N=10 | 1,354 | 93.6 | 7.65 | $45,430 | 41% |
| cluster position ≥ 5, N=10 | 846 | 94.8 | 8.97 | $28,004 | 64% |

**At the fixed tolerance N=5 the cost of a depth filter is 48% and 70% of book net.** The previously-quoted $45,430 / $28,004 (41% / 64%) are the **N=10** running-position figures — they reproduce exactly under that definition, but N=10 is not the fixed tolerance and quoting them unlabelled was the defect.

*Note on a Supervisor finding.* The Supervisor reported these two figures as matching no definition in the ratified toolchain, within a measured range of $33,105–$55,283 at ≥3 and $17,869–$43,631 at ≥5. My re-derivation reproduces them **exactly** at N=10 cluster position on the BOOK population, and reproduces the Supervisor's lower bounds exactly at bar-level `qd`. The disagreement is therefore about which definitions were enumerated, not about arithmetic. **The Supervisor's substantive point stands in full and is the reason this table exists: the figures were unlabelled, and unlabelled figures are not reproducible.** The direction is also confirmed — **no definition makes depth-as-filter cheap**, the cost spanning 41–57% at ≥3 and 64–77% at ≥5.

**Non-separability of the first entry** — BOOK population, early entries = cluster position ≤ 2, cohorts by eventual cluster size:

| cohort (position ≤ 2) | **N=5** | N=10 |
|---|---|---|
| cluster stayed 1–2 | n=1,009, WR 87.0, PF 2.78, avg **$17.6** | n=728, WR 86.4, PF 2.62, avg **$17.3** |
| cluster → 3–4 | n=326, WR 91.1, PF 5.20, avg $24.9 | n=292, WR 89.0, PF 4.20, avg $23.0 |
| cluster → 5–7 | n=148, WR 95.3, PF 9.54, avg $45.7 | n=176, WR 96.6, PF 10.79, avg $39.5 |
| cluster → 8+ | n=102, WR 92.2, PF 5.31, avg **$41.4** | n=128, WR 92.2, PF 5.31, avg **$43.7** |

*Second Supervisor disagreement, reported rather than absorbed.* The Supervisor measured the → 8+ cohort at WR 85.3 / PF 2.50 / avg $28.7 (N=10) and WR 85.2 / PF 2.18 / avg $21.5 (N=5). My re-derivation gives WR 92.2 / PF 5.31 / avg $43.7 at N=10 — reproducing the original figures exactly — while agreeing with the Supervisor to the cent on the paired "stayed 1–2" cohort ($17.3). Identical agreement on one cohort and material disagreement on the other points to a **cluster-construction difference**, most plausibly whether gap-filler trades participate in cluster formation: including them enlarges clusters and dilutes the → 8+ cohort. §0.1.1 now fixes this — **gap fillers are excluded from all cluster construction** — and the build must report which value obtains under that definition.

**The conclusion is unaffected either way, and this is the point that matters:** whichever cohort statistics obtain, they are *ex-post* properties of clusters that had already formed. Non-separability is a claim about what is knowable **at fire time**, and no predictor available at the first entry was found under either measurement. If the Supervisor's figures obtain, the case is stronger still — the "became big" cohort would then be indistinguishable in win rate and *worse* in profit factor than the cohort that stayed shallow, leaving nothing to separate on at all.

*Fit risk:* every figure here is six months, one instrument. The definitional sensitivity now visible in the tables is itself the argument for §I re-deriving all of them inside each split.

### F.2 — Depth enters SIZING, not selection-time filtering

**Specified: depth is a sizing input applied live as the cluster develops, not a pre-trade filter.** A depth filter costs **48–70% of book net at the fixed tolerance N=5**, and 41–77% across every definition measured (§F.1), to buy a WR improvement — and it discards the front of every large move.

The base position opens on the existing trigger with no depth pre-condition; size scales as running depth crosses stated thresholds. Motivating ladder (pre-jar qualifying depth, executed trades bucketed by their entry bar's qualifying depth):

**PROPERTY OF THE BOOK — the ladder describes what happens when *these* signals agree, and must be re-derived for any new book.**

| qualifying depth | trades | WR% | PF | worst day $ |
|---|---|---|---|---|
| 1-2 | 2,008 | 89.3 | 3.52 | −639.1 |
| 3-4 | 417 | 95.7 | 16.79 | −138.9 |
| 5-6 | 141 | 98.6 | 87.58 | **+8.4** |
| 7-9 | 67 | 100.0 | — | +28.8 |
| 10+ | 45 | 100.0 | — | +83.4 |

**Recorded decision 1 ("solo convergence is excluded from the forward book") is a selection-side statement and is preserved as such:** the forward book need not *contain* signals whose only mode is solo firing. But an *executed* first entry of a developing cluster is not a solo and must not be blocked at fire time — it cannot be distinguished from one, and blocking it costs the front of every large move. The distinction is between **which signals enter the book** (selection) and **which entries are taken and at what size** (runtime). This spec keeps them separate per §F.3.

### F.3 — The coupling constraint (binding)

Selecting a signal *because* it fires at shallow depth in episodes that deepen, and then *sizing* by depth, fits the book to its own sizing mechanism. The measured pull is not small ($41.4 vs $17.6 on the same trigger at N=5; $43.7 vs $17.3 at N=10).

**Mandatory mitigations, all three:**
1. The depth→size curve is **fixed a priori** and never tuned against the selected book. It is scored as an S7 contender row (§B) against C0–C5, independently of selection.
2. Selection-side depth metrics use **basis 3** (price-anchored) wherever available, since basis 3 is defined without reference to the book or the jar.
3. Selection and sizing are validated on **different splits** of the §I walk-forward.

*Falsification:* if the depth-sized book's advantage over flat sizing disappears when the curve is fixed a priori rather than fitted, the ladder's economic value was an artifact of the fitting.

#### F.3.1 — THE CLUSTER ARC: the sizing curve is not monotonic, and the obvious taper is UNIMPLEMENTABLE

**PROPERTY OF THE BOOK — it describes how *these* signals behave in company inside a cluster, and must be re-derived for any new book. It is not a property of the terrain.** Outcome by normalised position within large clusters (size ≥ 8, BOOK, gaps excluded, normalised position `j / (size − 1)` so the first entry sits at 0 and the last at 1):

**N = 10 (940 trades):**

| quartile of cluster | n | WR | PF | avg trade |
|---|---|---|---|---|
| first 25% | 256 | 93.4% | 7.74 | **$46.58** |
| second 25% | 227 | **96.9%** | **19.43** | $41.91 |
| third 25% | 218 | 95.4% | 8.32 | $32.14 |
| last 25% | 239 | 93.3% | 6.79 | **$27.09** |

**N = 5 (696 trades):**

| quartile of cluster | n | WR | PF | avg trade |
|---|---|---|---|---|
| first 25% | 194 | 93.8% | 7.94 | $44.01 |
| second 25% | 165 | 95.2% | **14.06** | **$48.80** |
| third 25% | 160 | **97.5%** | 12.74 | $35.12 |
| last 25% | 177 | 95.5% | 9.01 | **$33.40** |

**What holds at BOTH tolerances — the load-bearing part:**
- **Profit factor ARCS**, peaking in the second quarter (19.43 at N=10, 14.06 at N=5) and decaying thereafter.
- **The last quarter is worth materially less than the first** on both metrics — Q4 < Q1 on average trade at both tolerances ($27.09 vs $46.58 at N=10; $33.40 vs $44.01 at N=5).

**What is TOLERANCE-SPECIFIC and must not be generalised:** the monotonic decline of average trade. **At N=10 average trade falls from the first quarter onward; at N=5 it RISES from Q1 to Q2 ($44.01 → $48.80) before falling.** The fixed tolerance is N=5 (§0.1.3), so the monotonic-decline description is the **N=10** behaviour and is stated as such. A previous revision asserted monotonic decline without the tolerance qualifier; that generality is withdrawn.

§F.2 specifies size scaling *up* as depth builds; within a large cluster the later entries are worth materially less than the earlier ones at either tolerance. Both can be true — the depth ladder compares *clusters*, this compares *positions inside one* — but **the sizing curve must not be assumed monotonic on the strength of the ladder alone.**

*Reproduction note.* The arc shape reproduces at both tolerances. The quartile counts I measure at N=10 (256/227/218/239) are close to the reverse of figures supplied earlier (218/239/227/256), which is the signature of the superseded `(j+1)/size` convention; `j/(size−1)` is adopted here and in the doctrine, and both conventions reproduce exactly under their own definition. The build must state its position convention.

**WHY A NORMALISED-POSITION TAPER CANNOT BE BUILT.** Normalised position is `j / (size − 1)`, and **`size` is the cluster's final size, which is not knowable until the cluster has ended.** At fire time the EA knows how many entries have occurred; it cannot know how many more will follow, and therefore cannot know whether the current entry sits at 20% or 80% of the arc. **This is the first-entry problem (§F.1, §J) in mirror image — the same class of unknowable, at the other end of the cluster.**

**Specified: NO taper on normalised position is adopted, because it is not implementable causally.** Specifying one would put an unbuildable rule in a build document.

**What IS specified — measure whether a causal proxy recovers the arc.** Two quantities *are* knowable at fire time: **bars elapsed since the cluster's first entry**, and **running depth so far**. The build measures the same quartile table against each, and reports:
1. whether either proxy reproduces the PF arc and the average-trade decline;
2. the rank correlation between each causal proxy and true normalised position;
3. whether a taper keyed to the proxy improves net or worst-day over flat sizing beyond the §H.2 stability noise band.

**If neither proxy recovers the arc, that is the answer and it is recorded as a documented negative** — sizing stays monotonic in running depth per §F.2, and the arc remains a measured property with no implementable consequence. **Do not specify a taper on a quantity the EA cannot compute.**

*Fit risk:* the arc is measured on 940 trades in size≥8 clusters over six months, and the quartile bins are a presentation choice. Any proxy-based taper adds free parameters to a curve §F.3 already requires to be fixed a priori, and inherits the same coupling constraint.

### F.4 — Minimum unique-variable count at depth — A FORWARD GUARD, NOT A REPAIR

**The motivating population does not exist. This rule guards against a future failure mode; it does not fix a present one, and must not be described as fixing one.**

Recorded decision 6 was motivated by observing depth-2 events carrying only 3 unique variables. Re-measured on the stitched series with the committed book: **0 of 623 depth≥2 events carry ≤3 unique variables.** Distinct underlying variables rise monotonically with depth:

| depth | events | median unique vars | median condition slots | unique/slot |
|---|---|---|---|---|
| 1 | 1,199 | 3 | 3 | 1.00 |
| 2 | 487 | 5 | 6 | 0.83 |
| 3 | 83 | 7 | 9 | 0.78 |
| 4 | 24 | 9 | 12 | 0.75 |
| 5 | 14 | 11 | 15 | 0.73 |
| 6 | 15 | 12 | 18 | 0.67 |

**The original observation was a measurement artifact** (independently confirmed): the variable lookup was populated for F0 rows only — 48 of the 50 book signals — so F1 and gap-filler entries contributed empty variable lists and appeared to carry no variables. 4 of 59 depth-2 bars were affected. Corrected, the population is empty.

This also **refutes** the related concern that concurrence measures duplicated information rather than independent evidence: depth adds genuine variable diversity (3 → 12), though with mild repetition at the top (unique/slot falls 1.00 → 0.67).

**The rule is retained unchanged as a forward guard.** A future book assembled from a different vocabulary could produce degenerate depth, and the constraint costs nothing when the population is empty.

**Specified:** define `unique_vars(cluster)` = count of distinct underlying variables across all conditions of all entries in the cluster, computed after §G.1 duplicate-collapsing and across **all** entry families (F0, F1 and any admitted under §A.4) — the lookup must be complete or the metric silently under-counts, which is precisely how the original artifact arose. A cluster counts toward `DepthYield` (§C.3) only if `unique_vars >= U`.

`U` is **not chosen in this spec.** The build reports the depth ladder recomputed at `U ∈ {3, 4, 5, 6}` and the operator sets it on the evidence. Setting `U` here would be fitting a threshold to six months without seeing the curve.

*Verification requirement:* the build must assert lookup completeness (every admitted signal index resolves to a non-empty variable set) and abort otherwise. The artifact above is the reason.

### F.5 — Depth-dependent position cap — SPECIFIED OPTION, SACRED-TOUCHING

**AUTHORISATION REQUIRED BEFORE BUILD.** `MAX_POSITIONS` lives in `portfolio_simulation_engine.py`, which is **byte-locked** (`bb498eb13ce3`). Any behaviour-changing edit without documented human authorisation is INVALID regardless of merit. This section specifies the option; it does not authorise it.

§F.2 framed the choice as filter-or-size and measured that filtering costs **48–70% of book net at N=5** ($77,239 → $40,429 at position≥3 → $23,102 at position≥5; §F.1). A depth-conditional **cap** is a third mechanism: take every first entry, but limit how much shallow risk can accumulate concurrently.

**Specified form:** `cap = 2` while running same-direction depth is 1; `cap = 6` once depth ≥ 3. Intermediate value at depth 2 to be reported, not assumed.

*What would falsify it:* if the depth-conditional cap produces worse worst-day than flat cap-6 at equal or lower net, the mechanism is not buying survival and should be dropped. The build scores it as an S7 contender row (§B) against C0–C5 and flat-cap, never as a silent default.

*Fit risk:* the cap schedule is a free parameter set on six months. It must be fixed a priori and validated inside §I, exactly as the depth→size curve is under §F.3 — and the §F.3 coupling constraint applies to it identically, since a depth-conditional cap is another depth-keyed runtime mechanism.

### F.6 — Depth × volatility interaction

Depth and volatility **interact**; the sizing curve should not be assumed one-dimensional. **PROPERTY OF THE BOOK — measured on F0 trades of the incumbent book, and to be re-derived for any new one; it is not a claim that market volatility amplifies depth in general.** ATR terciles computed within the traded population:

| ATR tercile | depth-5+ average trade |
|---|---|
| LO | **$23.3** |
| MID | **$28.0** |
| HI | **$115.5** |

The same depth band is worth ~5x more in the top volatility tercile than the bottom. The depth ladder itself survives the volatility control — monotonic in WR and PF in all three terciles, partial Spearman rho(depth, pnl) controlling ATR and hour = **+0.2793, p = 4.6e-47** — so this is an interaction on top of a real main effect, not a confound explaining it away.

**Specified:** the build reports the depth→size curve in two-way form (depth × ATR tercile) alongside the one-way form, and the S7 contender comparison includes both.

*What would falsify a two-way curve:* if the two-way curve's advantage over one-way is inside the noise band established by §H.2 stability draws, the extra dimension is not earning its parameters and one-way governs.

*Fit risk:* a two-way curve has materially more free parameters than one-way and a correspondingly larger overfit surface. This is the strongest argument for fixing it a priori and for §F.3's requirement that sizing be validated on different splits from selection.

---

## 8. SECTION G — VOCABULARY HYGIENE

**THE IDENTITY TEST DOMAIN IS THE ELIGIBLE UNIVERSE.** This was previously unstated and it changes the answer. Equivalence is tested on the bars where triples are actually formed and evaluated — `(ADX_Value >= 15) & (Volume > 50) & post-warmup`, 103,214 bars — not over all 177,251:

| identity tested over | dead | exact duplicate pairs | effective vocabulary |
|---|---|---|---|
| **ELIGIBLE 103,214 bars — CORRECT** | **7** | **4** | **238** |
| all 177,251 bars | 6 | 1 | 242 |

**Verified exact duplicate pairs (4), by bitwise mask identity on the eligible universe:**
`OBVf_Signal:==1` ≡ `OBVf_Trend_Dir:==1`; `OBVf_Signal:==-1` ≡ `OBVf_Trend_Dir:==-1`; `Trend_Concordance:==0` ≡ `Trend_Conflict:==1`; `Trend_Concordance:==1` ≡ `Trend_Conflict:==0`.

**`PrevDay_Close_Side:==0` ≡ `DailyOpen_Side:==0` IS NOT A DUPLICATE PAIR and was previously listed in error.** Measured: 30 eligible fires each with **intersection 0**; 285 and 48 fires respectively over all 177,251 bars, again with **intersection 0**. The two conditions are **disjoint** — they never fire on the same bar. The matching eligible fire count is coincidence, and inferring duplication from matching aggregate statistics rather than from mask identity is the weaker test that produced the false pair.

**Verified zero-firing conditions on the eligible universe (7):** `D2D_Dn_Count:lo`, `D2D_Dynamic_Sensitivity:hi`, `D2D_Up_Count:lo`, `AT_Lookback_LT:lo`, `AT_Lookback_ST:lo`, `OR_High_Dist_ATR:lo`, `OR_Low_Dist_ATR:lo`. (`D2D_Dynamic_Sensitivity:hi` fires only outside the eligible universe, which is why the all-bars count is 6.)

**Effective live vocabulary = 238**, not 237 and not 249. **238 is the number entering §H.1's trial count.** **0 of the 50 committed triples are affected.**

**NOTE ON THE MECHANISM.** §G.1.1 specifies bitwise mask identity, re-derived each run, never hardcoded — and a build implementing that mechanism produces 4 and never inherits this error. The defect was in the stated fact, not in the mechanism. It is corrected here because an Auditor checking a compliant build against the previous text would have flagged correct output as non-compliant.

### G.1 — Handling, at SELECTION time only

`build_condition_pool` is S.10 sacred and is **not modified**. All handling occurs downstream, in the selection layer, against the pool the oracle produces.

**ORDER IS BINDING: dead conditions are excluded BEFORE equivalence classes are formed.** The 7 zero-firing masks are all-zero and therefore all identical to each other; forming equivalence classes first would collapse them into a spurious 7-member class and corrupt both the duplicate count and the trial count. Exclude, then classify.

**SCOPE IS BINDING: both the equivalence map and the dead-condition list are derived PER TRAINING SEGMENT, not once per `master.py` invocation.** A single full-series derivation would compute the trial count entering §H.1 on every split with sight of the test segments — a §I.4.2 violation hidden inside a hygiene step. "Re-derived each run" was ambiguous and is replaced by this.

1. **Duplicate collapsing.** Maintain a canonical-equivalence map, built by measuring bitwise mask identity **on the eligible bars of the active training segment** — never hardcoded, since equality-arm membership is data-dependent. For ranking and for triple formation, the members of an equivalence class count as **one** condition. A triple containing both members of a pair is a two-condition signal and must be **rejected at formation**, not discovered and then explained.
2. **Dead conditions.** Zero-firing conditions are **excluded from RANKING and from triple formation**, and are **NOT deleted from the vocabulary.** They are reported with their fire count of 0. If a segment or a future dataset makes one live, it re-enters automatically — the exclusion is a computed property of the segment, never a hardcoded list.
3. **Trial-count impact.** The effective vocabulary — **238 on the full series**, recomputed per segment — is the number entering §H.1's trial count. Duplicates manufacture false corroboration in ranking; collapsing them is also what makes the multiple-testing correction honest.

*Fit risk:* none material — this removes an artifact rather than adding a choice. The one judgment is treating exact mask identity as equivalence; near-duplicates are handled separately in §G.2.

### G.2 — Near-duplication: domain bridging and community detection

**RIGHT-SIZED ON MEASUREMENT. This is modest hygiene, NOT a structural reach mechanism, and must not be presented downstream as one.**

The near-duplicate structure of the live vocabulary was measured across all 29,161 pairs of the 242 live conditions:

| pairwise \|r\| | pairs | share |
|---|---|---|
| ≥ 0.95 | 33 | 0.11% |
| ≥ 0.90 | 39 | 0.13% |
| ≥ 0.80 | 62 | 0.21% |
| **≥ 0.70** | **100** | **0.34%** |

Median \|r\| = **0.033**; p90 = 0.209; p99 = 0.496. Effective dimensionality: **126 components carry 90% of variance**, 154 carry 95%, participation ratio 46.2.

**So near-duplication is real but sparse** — about 100 pairs out of 29,161, on top of the 5 exact pairs §G.1 already collapses. The broader redundancy shown by the effective-dimension figures is mild and diffuse rather than concentrated in clusters of near-clones. Two mechanisms, both cheap:

1. **Domain bridging.** Group the live conditions into functional domains (microstructure/order-flow, adaptive volatility, temporal/session, structural trend, volume profile, D2D/OBV family) by measured mask correlation and by variable provenance. **A candidate triple must draw from at least 2 distinct domains.** This mechanically prevents a "triple" that is three views of the same underlying read.
2. **Community detection** (Louvain or Leiden on the |r| graph, resolution reported) as the data-driven counterpart, so domain membership is measured rather than assigned by name. Where the semantic grouping and the detected communities disagree, the run report shows both and the measured communities govern.

**What this does and does not buy.** It removes false corroboration in ranking and prevents degenerate triples. It does **not** address the §D reach gap — 89.8% of missed thrusts have no qualifying signal at all, which is a vocabulary-content problem that no amount of hygiene on the existing 249 conditions can solve.

*What would falsify it:* if fewer than ~20 candidate triples are rejected by the 2-domain rule across a full run, the constraint is not binding and can be dropped as noise. The build reports the rejection count.

*Fit risk:* the domain boundaries are a choice. Requiring the measured communities to govern where they disagree with the semantic grouping is the mitigation; the resolution parameter is reported and its sensitivity shown at three values.

---

## 9. SECTION H — QUANT-DESK RIGOUR

The historical funnel ran 1.7M → 89K → 51K → 1,788 → 50 with **no trial-count adjustment**, and that was one family. §A expands to fourteen.

### H.1 — Multiple-testing correction

**Primary method: empirical null via matched random signals.** Parametric corrections (Bonferroni, and to a lesser degree BH) assume a tractable dependence structure; the candidate triples here are massively correlated (shared conditions, shared bars), so a parametric bar is either wildly conservative or wrong. The project already has the right machinery: the 400-random-triple baseline that established the 27% random-persistence rate.

Specified:
1. Generate `M >= 10,000` random signals from the **same** post-§G vocabulary, **matched on fire-rate distribution** to the real candidate pool (unmatched random signals are a weaker null — a rare random signal is not comparable to a rare real one).
2. Score every one through the **identical funnel**, including the §H.2 and §H.3 stages.
3. The acceptance bar is the **q-quantile of the null distribution** of the selection statistic, with `q` set so the expected false-acceptance count across the whole expanded funnel is `<= 1`. The build reports `q`, `M`, the realised null distribution, and the implied bar.

**Secondary cross-check: Benjamini–Yekutieli FDR at q = 0.10** — **NOT Benjamini–Hochberg** — applied with the family as strata (14 strata), reported alongside. Where the two disagree, the empirical null governs and the discrepancy is reported.

**Why BY and not BH — measured, not assumed.** BH controls FDR only under positive regression dependency (PRDS). The signed dependence structure of the live vocabulary was measured across all 29,161 pairs of the 242 live conditions:

| | |
|---|---|
| positive pairwise correlations | **14,469 (49.6%)** |
| negative pairwise correlations | **14,692 (50.4%)** |

The dependence is essentially symmetric in sign, so **PRDS fails and BH is not valid on this vocabulary.** Benjamini–Yekutieli (2001) controls FDR under arbitrary dependence and is the correct choice. It is less powerful, which is the price of validity; the empirical null remains primary precisely so that power is not lost overall.

**Additional machinery — REPORTING ADDITIONS AND GATES, distinguished explicitly.** None of the following corrects a measured deficiency in the empirical null; they capture failure modes the null does not, and are labelled so downstream readers do not infer a defect that was never demonstrated.

| technique | role | what it captures that the matched null does not |
|---|---|---|
| **White's Reality Check (2000)** | **GATE** | Bootstraps the *search*, not the signals. Estimates how good the best-of-N rule should look under pure chance given the adaptive search itself. The matched null asks "what does a random signal look like"; White asks "what does the winner of N searches look like". Different failure modes; both required. |
| **Hansen's SPA** | **GATE** | Improves the power of White's by removing obviously poor candidates before computing significance. Given a candidate universe dominated by weak rules, SPA is the more usable of the two. Run alongside; report both. |
| **Romano–Wolf stepdown** | reported diagnostic | FWER control accounting for dependence between tests. Reported as a stricter cross-check on the accepted set. |
| **PBO via CSCV** (Bailey et al.) | reported diagnostic | Probability of Backtest Overfitting — the estimated fraction of apparent winners expected to fail forward. Reported per §I split. **PBO < 0.10 is the stated reference bar; it is reported, not enforced, on the first run** so that the realised value informs whether it becomes a gate. |

*What would falsify the additions:* if White's/SPA accept exactly the set the empirical null accepts across all §I splits, they are redundant here and can be demoted to diagnostics. The build reports the set differences.

**Effective number of independent tests.** The naive trial count is not the effective one. The build computes and reports:
- naive trial count per family and in total;
- effective count after §G.1 duplicate collapsing and §G.2 domain handling;
- an eigenvalue-based effective-dimension estimate on the condition-mask correlation matrix, so the correlation-induced reduction is measured rather than guessed.

**Measured reference for that estimate** (242 masks live over all bars; 238 effective on the eligible universe per §G): **126 components carry 90% of variance, 154 carry 95%, participation ratio 46.2.** The effective dimensionality is materially below the nominal count but far above the 4 exact-duplicate pairs — the reduction is broad and mild, not concentrated.

*Fit risk:* the null is generated on the same six months. It shares the period's structure, which is the point — it is a null for *this* market, not a universal one. Stated openly.

### H.2 — Stability selection

Specified per Meinshausen–Bühlmann, adapted to time-series structure.

- **Resampling scheme: day-level block bootstrap.** Draw whole **trading days** with replacement. Naive iid bar resampling is forbidden — it destroys intraday autocorrelation, session structure, and cluster formation (clusters span up to 80 bars; sessions span ~1,400). Day-level blocks preserve all three.
- **Resampling pool: all 127 post-warmup trading days in the series — NOT the 123 days the incumbent book happened to trade.** Drawing only from traded days conditions the bootstrap on the current book's activity, which is the incumbency bias §A.4 and §D.3.3 warn against elsewhere; a candidate book that trades on days the incumbent sat out could never be sampled fairly. The pool is the market, not the incumbent's footprint.
- **Subsample size:** 80% of the 127 available post-warmup trading days per draw.
- **Count:** `B = 200` draws. Reported with a convergence check (selection frequencies stable between B=100 and B=200); if not converged, increase B rather than accept.
- **What is re-run:** the **entire** selection funnel on each draw — not a re-score of a fixed book. This is the point of the exercise.
- **Retention threshold:** a signal is retained only if selected in `>= 70%` of draws. Sensitivity at 60% and 80% reported so the threshold's influence is visible.

*Falsification:* if fewer than a workable number of signals clear 70%, the selection process is unstable and the book is not ready — that is a valid and reportable outcome, not a reason to lower the threshold.

*Fit risk:* 127 trading days is a small pool for 200 draws; draws overlap heavily. The convergence check and the sensitivity band are the mitigations; the limitation is real and stated. Inside a §I training segment the pool is smaller still — see §I.1's minimum-segment floor, which exists because §H.2 becomes unexecutable below it.

### H.3 — Regime-conditional persistence

Aggregate positivity hides regime failure. This is what would have caught the short-side collapse, and it is what disqualifies the §E.3 regime-state filter.

**BUCKETING IS A RULE, NOT A FIXED COUNT.** A previous revision fixed 7 calendar-month buckets with a ≥6-of-7 bar. That is unexecutable inside a §I training segment — the first anchored segment contains roughly 1–1.5 months, so there are not 7 buckets in it, and a build faced with that has only two options, both prohibited: break, or apply the full-series rule and consume test-segment months. **That is the precise mechanism by which §I Step 6 would pass while being fake — not by anyone deciding to skip it, but by a Developer hitting an impossible constraint on day one.**

**Primary bucketing rule: calendar month, whatever count the active segment contains.**

**Proportional bar:**
- **positive net in all but at most one bucket**, and
- **a minimum of 3 buckets must exist** for the criterion to be evaluated at all.

If a segment contains fewer than 3 monthly buckets the criterion **cannot be evaluated**, and that is a property of the split, not of the signal: the segment is too short and §I.1's floor exists to prevent it arising. A build must **fail loudly** in that case, never silently pass the signal and never silently borrow months from the test segment.

On the full series (7 buckets) the rule yields ≥6-of-7 — identical to the previous fixed bar, so nothing is loosened; it is generalised so that it executes.

**Secondary bucketing: causal volatility tercile**, derived from the oracle's mechanism-D `ATR_1M` thresholds (never a local full-sample quantile — that is a mechanism-A surface, and the S8B remediation established this precedent). Terciles are balanced by construction, so the bar here is strict: **positive in all three**.

**Tertiary bucketing (reported, not gating): `AT_Regime_ST` state**, per §E.3.

#### H.3.1 — DIRECTIONAL ASYMMETRY: the short side is not to be culled as a side effect

**OPERATOR DIRECTIVE, BINDING.** The market has been primarily bullish across this span. The committed book is 37 long / 13 short, and the reveal records the short side degrading from PF 5.38 to 0.74 while longs went 6.97 to 3.20. Applied naively, per-bucket positivity will cull the short side wholesale — not because a decision was taken, but because a statistical rule met an asymmetric sample.

**If the short side is to be treated differently that must be a DECIDED outcome with a stated measurement, never an emergent one.**

**Specified handling:**
1. **§H.3 is evaluated WITHIN direction, not pooled.** Long candidates are bucketed and barred against the long population; short candidates against the short population. A short signal is not required to clear a bar calibrated on a bullish sample.
2. **The minimum-bucket rule applies per direction.** If the short population in a segment does not populate 3 buckets, the short-side criterion is **unevaluable** — reported as such, and the signal is **neither passed nor culled** on that basis. It carries forward to the operator as an explicit open decision.
3. **Directional composition is a reported book property.** Every candidate book reports its long/short split alongside net and worst day, so a book that has become directionally monolithic is visible before commitment rather than after.
4. **No rule in this document may remove the last short signal from a book without that removal appearing as a named line in the run report.**

*What would falsify this handling:* if short-side signals clearing a short-calibrated bar go on to fail in §I test segments at a materially higher rate than long-side signals clearing a long-calibrated bar, the asymmetric calibration is too permissive and the bar must be raised — by decision, with the measurement recorded.

*Fit risk:* calibrating a bar per direction on a directionally-imbalanced six months risks fitting the short bar to a very small sample (13 signals). The unevaluable-and-report path exists precisely so that a thin sample produces an open question rather than a false pass.

**Requirement:** a signal must be **positive in each bucket**, not in aggregate — net > 0 in **all but at most one** monthly bucket of however many the segment contains (minimum 3), **and** net > 0 in **all three** volatility terciles, evaluated within direction per §H.3.1. The one-bucket allowance acknowledges partial months; the volatility requirement is strict because terciles are balanced by construction.

*Motivating number:* the §E.3 filter is positive in aggregate on every segment and still fails, because `reg==0` beats `reg==1` in 3 of 7 months and the whole effect is July. Aggregate would have passed it.

---

## 10. SECTION I — WALK-FORWARD ON THE SELECTION PROCESS (MANDATORY)

All prior validation — blind audit, OOS May–Jun, 6/6 folds, decorrelation, null/shuffle — sat **inside** Jan–Jun, downstream of a funnel already run across that whole window. **The book was validated; the method never was.**

### I.1 — Construction

**THE SPLIT COUNT IS DERIVED FROM AN EXECUTABILITY FLOOR, NOT FIXED IN ADVANCE.** A previous revision fixed 4 splits. With 127 post-warmup trading days that gives a first training segment of roughly 25–30 days, in which §H.3 cannot form 3 monthly buckets and §H.2 cannot draw 200 bootstrap samples at 80% of ~25 days with any independence. Fixing the count first and discovering the impossibility later is how a Developer is forced into a fake step.

- **MINIMUM TRAINING-SEGMENT LENGTH — the binding floor.** A training segment is valid only if it satisfies **all** of:
  - **≥ 3 calendar-month buckets** with trades, so §H.3 is evaluable;
  - **≥ 60 post-warmup trading days**, so §H.2's 80% draws retain enough distinct days for selection frequencies to converge;
  - **≥ 3 monthly buckets in EACH direction** where a direction is to be evaluated, per §H.3.1 — otherwise that direction is reported unevaluable rather than culled.
- **Splits: derived.** With 127 post-warmup days and a 60-day floor on the *first* anchored training segment, the series supports **3 splits**. **The build computes the count from the floor and reports it; it does not assume 4.** If the floor admits fewer than 3 splits the walk-forward is under-powered and that must be reported as a limitation of the data, not absorbed by shortening segments.

- **PARTITION RULE — EQUAL PARTITION OF THE POST-FLOOR REMAINDER. This was previously unstated and the two readings return different split counts from identical inputs.**

  Once the first training prefix meeting the floor is fixed at 60 days, **67 post-warmup trading days remain. They are partitioned into contiguous, as-equal-as-possible test segments**, remainder distributed to the earliest segments. On this series that yields **3 splits with test segments of 21 / 20 / 20 days**, which reproduces the spec's own stated "roughly 20–30 trading days".

  **The rejected alternative, recorded so it is not re-derived:** a downward scan for the largest test segment admitting ≥3 splits leaves a 1-day final stub that the 1,440-bar embargo annihilates, returning **2 splits**. That is what a first implementation produced. **The spec's stated arithmetic reproduces only under equal partition**, so equal partition is the rule.

  *Falsification:* if equal partition on a future dataset produces a final segment below the minimum test length needed for §H.3 to evaluate, the partition must reduce the split count rather than ship an unevaluable final split — the floor governs, not the partition.
- **Scheme: anchored walk-forward.** Split *k* selects on all data up to boundary *k* and tests on the untouched segment between boundary *k* and *k+1*. Anchored rather than rolling because the warm-up floor (6,900 bars) consumes a fixed prefix and a rolling window would repeatedly pay it. Anchoring also means later training segments strictly contain earlier ones, so the floor binds only on the first.
- **Embargo: one full trading day, `>= 1,440 bars`.** Stated as a bar count, not a session count: the measured median session is 1,365 bars, so 1,440 is conservative in the right direction, and "one trading day" must not be read as "one session" by a build that then embargoes fewer bars. Required, not optional: the §D thrust labels use forward windows up to W=60 bars, trades hold for a bounded but nonzero duration, and cluster spans reach 80 bars. Without an embargo the training window's forward labels peek into the test segment.
- **Test segments are touched exactly once**, at the end, to produce the reported number. **That single touch includes the §I.3 null re-run** — see §I.3.

### I.2 — What is re-run on each split

**The ENTIRE selection funnel across ALL families** — S3 discovery through §H.1 correction, §H.2 stability, §H.3 regime conditioning, and final book assembly. Every parameter that the process would set is set *inside* the training segment: thresholds, `U` (§F.4), `F_max` (§C.3), the null bar (§H.1), the retention threshold sensitivity, and the thrust grid (§D).

**Nothing may be carried across the boundary except the code itself.**

### I.3 — Pass criterion

Signal-level persistence into the held-out segment, measured as the record measures it (net > 0, PF >= 2, WR >= 75 in both train and test):

**THE CRITERION IS A RATIO TO THE SPLIT'S OWN MEASURED NULL, NOT AN ABSOLUTE THRESHOLD. The previous absolute form is withdrawn as incoherent.**

The previous criterion was `mean >= 0.65, no split < 0.50`, inherited from a recorded **full-window** random-triple baseline of 27%. That is incoherent on two counts:

1. **The quantities are not comparable.** The 27% is a full-window figure. The per-split nulls are 20–21-day test segments under a train-and-test qualification. Different objects, and no absolute threshold can be inherited from one to the other.
2. **It contradicts the mechanism that replaced it.** §I.4 item 7 now *enforces* a null regenerated per split. Expressing the bar as an absolute inherited from the fixed baseline reintroduces exactly the dependency that rejection item was written to remove.

**Measured per-split nulls (BOOK-independent; null triples, `triples_per_split=120`, seeded):** 6/16, 7/16, 5/16 = **37.5% / 43.75% / 31.25%**.

**These are NOT evidence of a higher bar.** The three counts are consecutive integers — the entire spread is ±1 triple — and the exact binomial 95% intervals **[0.152, 0.646], [0.198, 0.701], [0.110, 0.587] all contain 0.27**. Pooled, 18/48 = 37.5% with CI [0.240, 0.526], which also contains 0.27. **At n=16 one cannot distinguish 27% from 44%.** An earlier reading of these as "a higher bar than assumed" is withdrawn.

**SPECIFIED CRITERION:**

```
ratio_s      = book_persistence(s) / null_persistence(s)      for each derived split s
PASS         = mean_s(ratio_s) >= 2.40  AND  min_s(ratio_s) >= 1.85
               AND the 95% lower bound on mean_s(ratio_s) exceeds 1.0
```

The two ratio thresholds **preserve the previous intent exactly** at the recorded baseline: 0.65 / 0.27 = **2.41** and 0.50 / 0.27 = **1.85**. The additional lower-bound requirement is what stops a point estimate clearing on noise.

**MINIMUM NULL DENOMINATOR — `n_null` is the count of TRAIN-QUALIFYING null triples, not the count generated.**

| | value |
|---|---|
| **Target `n_null`** | **80 qualifiers per split** |
| **Hard floor `n_null`** | **40 qualifiers per split — below this the criterion is UNEVALUABLE, not evaluated** |

Two independent derivations converge on this range:

- **The null arm must not dominate the comparison.** The book arm carries `n_book ≈ 50` at `p ≈ 0.50`, contributing variance 0.00500. For the null's variance contribution (`p(1−p)/n` at `p=0.27`) to be **no larger** than the book's requires `n_null ≥ 40`; for it to be **at most half** the book's requires `n_null ≥ 79`.
- **Power to detect the criterion's own floor ratio.** Detecting ratio 1.85 (0.27 → 0.50) at α=0.05 one-sided needs **n ≥ 55 per arm at 80% power** and **n ≥ 76 at 90%**. Detecting ratio 2.00 needs n ≥ 40 at 80%.

At `n_null = 80` the null's 95% CI half-width is ±0.098 versus **±0.218 at n=16** — the current estimate is more than twice as wide as the effect the criterion must resolve.

**WHAT THE DEVELOPER MUST APPLY — target the QUALIFIER count, not the generated count.**

The measured train-qualification rate is **16/120 = 13.3%**, but that rate is itself uncertain: exact 95% CI **[0.078, 0.208]**, so the generated count needed for 80 qualifiers spans **386 to 1,024**. **A fixed `NULL_TRIPLES_PER_SPLIT` is therefore fragile and must not be the control.**

```
generate null triples in seeded batches until train_qualifiers >= 80
hard cap NULL_TRIPLES_CAP = 1500 per split
if the cap is reached with train_qualifiers < 40 -> that split's criterion is UNEVALUABLE
if 40 <= train_qualifiers < 80 -> EVALUABLE, with the reduced denominator reported
```

At the measured 13.3% rate the expected generation is **~600 triples per split** (5.0× the current 120), and 1,800 across three splits against the current 360. That is the honest compute cost.

**DO NOT LOOSEN THE TRAIN BAR TO RAISE THE QUALIFICATION RATE.** It would raise `n_null` cheaply and **invalidate the comparison**: the null exists to answer "what fraction of things that cleared *the same bar as the book's signals* persist by chance?" Null triples admitted under a looser bar are not a null for qualified signals, and the ratio would compare two different populations. **The cost of loosening is the meaning of the measurement; the cost of raising the count is compute. Raise the count.**

*What a FAIL looks like:* `mean ratio < 2.40`, or any split below 1.85, or a mean-ratio lower bound not exceeding 1.0. **A fail is a legitimate result and is reported as one. No bar is lowered to obtain a pass, and an UNEVALUABLE split is reported as unevaluable rather than imputed.**

*Fit risk:* the 2.40 / 1.85 thresholds inherit the incumbent's 50%-vs-27% relationship, which is itself a six-month figure. They are fixed a priori and never tuned against a walk-forward result; the ratio form at least makes the denominator segment-local, which the absolute form did not.

**THE NULL RE-RUN IS PART OF THE SINGLE TEST TOUCH — loophole closed.** Regenerating the random-triple null per split requires scoring random signals on the test segment, which is a second read of held-out data. §I.1 permits touching a test segment exactly once and the previous text never said whether null scoring counted. It does. **The real book and the null are scored in the SAME single pass over the test segment**, from one loading of that segment, and the pass is recorded once in the §I.4 attestation. A build that scores the book, inspects the result, and then scores the null has touched held-out data twice and the split is void — even though no stated rule previously forbade it.

**Additionally:** the held-out books must satisfy the §C.3 survival constraint on their test segments. A book that persists but breaches the daily ceiling fails.

### I.4 — What constitutes a FAKE step (rejection list)

Any of the following invalidates the walk-forward and must be rejected by the Auditor:

1. **Re-scoring a fixed book on held-out data.** That is book validation. It is what has already been done and is not this test.
2. **Any parameter chosen with sight of a test segment** — including thresholds, `U`, `F_max`, the thrust grid, bucket boundaries, or the retention threshold.
3. **Running discovery across the full series and splitting afterwards.** The funnel must run inside each training segment.
4. **Omitting the embargo**, or setting it shorter than the longest forward-looking label in use.
5. **Reporting the best split, or the mean without the per-split values.** Every derived split is reported.
6. **Re-running a failed split after adjustment.** If a split fails, the iteration happens and the *whole* walk-forward re-runs from clean code — the failed configuration is reported, not buried. **ENFORCED BY §I.4.1 ATTESTATION, not by convention.**
7. **Carrying the 27% null from the record** instead of regenerating it per split.
8. **Deleting rows anywhere** to construct a segment. Segments are index ranges over the intact series; the oracle's rolling-2500 ring must see the unbroken data.
9. **Touching a test segment more than once**, including scoring the book and the null in separate passes (§I.3).
10. **Shortening a training segment below the §I.1 floor** to fit a desired split count.

#### I.4.1 — ENFORCEMENT: the walk-forward attestation

Item 6 was previously a convention with no mechanism. The sacred five have `verify_sacred()` aborting on drift; §I had no equivalent, so "the failed configuration is reported, not buried" rested entirely on trust.

**Specified mechanism — an append-only run attestation.** Before any test segment is touched, `wf_selection.py` appends one record to `discovery/.wf_attest.jsonl`:

```
{ run_id, utc_timestamp, code_sha256 (wf_selection.py + selection.py),
  split_definition_sha256 (boundaries, embargo, floor parameters),
  input_sha (dataset), split_index, segment_bar_range }
```

- The file is **append-only**; the build never rewrites or truncates it, and a missing prior record is not inferred.
- **A second record with the same `(code_sha, split_definition_sha, input_sha, split_index)` is a REPEAT and is reported as such in the run report** — it is not blocked, because legitimate re-runs exist, but it can never be silent.
- The §I.3 headline may only be reported alongside the full attestation trail. **A pass figure presented without its trail is not a result.**
- The Auditor verifies the trail count against the number of reported splits. A trail longer than the report is the signature this mechanism exists to expose.

*Fit risk, stated plainly:* the split count is **derived from the §I.1 floor, not fixed** — on 127 post-warmup trading days with a 60-day floor on the first anchored training segment, the series supports **3 splits**, with a first training segment of ~60 days and test segments of roughly 20–30 trading days. These are short, and the floor exists because anything shorter makes §H.2 and §H.3 unexecutable rather than merely weak. A pass is meaningful evidence that the method generalises; it is not proof that it generalises across market regimes not present in 2026 H1. The honest resolution is a second out-of-sample export, which remains the project's highest-value un-run validation.

---

## 10B. SECTION J — RESEARCH ITEM: HAWKES / HAZARD TEST ON CLUSTER FORMATION

**This is specified as RESEARCH with a defined pass/fail, not as an adopted component. Nothing depends on it. If it fails, the spec is unchanged.**

### J.1 — The problem it attacks

§F.2 records the one measured dead end in this design: **the first entry of a large cluster is indistinguishable from a solo at fire time.** Early entries (position 1–2, BOOK, N=5) in clusters that reached size ≥8 averaged **$41.4**; the same positions in clusters that stayed shallow averaged **$17.6** — a real difference, but not separable *before the second entry arrives*. That is why depth went to sizing rather than filtering, and why waiting for confirmation costs **48–70% of book net at N=5** (§F.1).

If cluster formation were predictable at the first arrival, §F changes substantially: the front of every large move could be entered at size rather than probed.

### J.2 — The test

Model same-direction signal arrivals as a self-exciting point process with conditional intensity

```
lambda(t) = mu_0 + sum over arrivals t_k < t of  alpha * exp(-beta * (t - t_k))
```

fitted **causally** — `mu_0`, `alpha`, `beta` estimated on a training segment only, never on the segment being scored, and evaluated with information available at bar t only.

**The discriminating question:** does `lambda(t)` evaluated immediately after the **first** arrival of an episode separate episodes that go on to reach size ≥5 from those that do not?

Primary statistic: **AUC of `lambda(t_1)` as a classifier of "cluster reaches size ≥5"**, computed out-of-sample on the §I splits, against the base rate of size-≥5 formation.

### J.3 — Pass / fail

| outcome | interpretation | consequence |
|---|---|---|
| **AUC ≥ 0.65** out-of-sample on **at least `ceil(0.75 * K)` of the `K` derived §I splits** (K per §I.1; K=3 → 3, K=4 → 3, K=5 → 4) | first-arrival intensity carries real predictive information | escalate: §F is revisited, depth may become partly a pre-trade input |
| **AUC 0.55–0.65** | weak signal, not actionable alone | report; may enter as one input to a §F.3 sizing curve, never as a filter |
| **AUC < 0.55** | the §F.2 finding stands and is now confirmed by a second method | close the line; record as a documented negative |

### J.4 — Constraints

- **Selection-side / research only.** A live `lambda(t)` gate would require causal computation in MQL4 and would have to clear export=live parity. Nothing in this section authorises a live component.
- The fit must respect §I boundaries: parameters estimated inside a training segment, evaluated on the untouched test segment, embargo applied.
- **No row deletion.** Arrival times are indices into the intact series.

*Fit risk:* three free parameters (`mu_0`, `alpha`, `beta`) fitted on short segments. A positive result on a single split is not a result; the `ceil(0.75 * K)`-of-`K` requirement is the guard. **The bar is keyed to the derived split count, not to a literal**, so it cannot silently become unanimity if `K` changes — at the currently derived `K = 3` it is 3-of-3, which IS unanimity, and that is a known consequence of a short series rather than an intended strictness. If `K = 3` obtains, the build reports the AUC margin on every split so a narrow 3-of-3 pass is distinguishable from a decisive one. Reporting AUC without the per-split values is a §I.4-class fake step.

---

## 10C. WITHDRAWN — DO NOT RE-RAISE

### 10C.1 — Figures withdrawn by their originating seat

| figure | status |
|---|---|
| **`CoFire = 0.1757`** | **WITHDRAWN BY THE AUDITOR.** Computed on the first 12 raw conditions of the 249-condition vocabulary as a runnability smoke-test — **not** on the 50 book signals' qualifying masks — and reported without its basis. The Auditor's own characterisation: a breach of the standing construction it is charged with enforcing. The Developer was correct to flag it as unreproducible rather than ship a number it could not stand behind. **Do not carry 0.1757 forward anywhere.** The verified bases are in §C.1 (0.0271 all-pairs / 0.0447 same-direction / 0.0480 LONG / 0.0162 SHORT). |
| **`min(pnl, 0)` tail figures** | **WITHDRAWN BY THIS SEAT.** Every §C.2 λ figure computed on the zero-floored series is superseded — see §C.2. The floored series returns `coexceed = 1.0` on 73.4% of pairs and is not a tail estimator. |

### 10C.2 — The LONG greedy-optimality figure is a LOWER BOUND, not a tight result

**The fixture's `exhaustive_optimum` is a lower bound, and the LONG headline of 88.41% should not be read as tight.** Enumeration runs to `max_k_enumerated` plus the all-signals set; for LONG `max_k_enumerated = 2`, so **the entire interior of the LONG search space is unenumerated.** A simple forward hill-climb reaches **0.027664 at size 24** against the reported optimum of **0.025033**, which puts the honest LONG figure at **≤ 80%**, not 88.41%.

**SHORT's 100.00% IS exact**, because the SHORT optimum sits at k=2 and is therefore inside the enumerated region.

The artifact header discloses the lower-bound restriction correctly; the point recorded here is that **the headline percentage must not be quoted as a tight optimality gap for LONG.** Per the standing construction, the enumeration limit is part of the finding.

### 10C.3 — Items refuted by measurement

Three items were proposed during external review, provisionally accepted, and then **refuted by measurement**. They are recorded here with their disproof so they are not re-introduced later as fresh insights.

| withdrawn item | why it is wrong |
|---|---|
| **"Execution costs are not modelled"** | `SPREAD = 3.0` is defined at `portfolio_simulation_engine.py` **L16** and applied at **L208** and **L331** to every trade in both the concurrent and gap-filler paths. **$10,717.50 of execution cost is already deducted** from every figure in this project (3,572.5 lots × $3.00); gross before cost is $108,922.3. FTMO indices CFDs are **commission-free**. 3.0 points is **above** the account's typical US30 spread, so the assumption is conservative — at a realistic 1.0–1.5 pt the reported net would be **higher** by $7,145 / $5,359. Residual checks: raising spread by +7 pt across the entire 09:00–13:00 concentration window costs 14% of net (break-even needs +50 pt); +10 pt of adverse slippage on every SL fill costs 3.0% of net (break-even needs +331 pt); under joint stress (+7 spread, +5 SL slip) worst day moves −$565.3 → −$678.3. And **deep clusters are the LEAST cost-sensitive population** — cost at 3.0 is 5.0% of the average depth-5+ trade versus 10.8% for solo. |
| **"Missed episodes may be inaccessible because of execution cost"** | Cost is **1.8% of a traded episode's median move and 5.1% of a missed one's** — and is already deducted at the conservative rate above. Cost is not the barrier to reach. The real mechanism is §D.0: 89.8% of missed episodes had no qualifying signal at all. |
| **"Concurrence may measure duplicated information rather than independent evidence"** | Refuted in §F.4: distinct underlying variables rise **monotonically 3 → 5 → 7 → 9 → 11 → 12** across depth 1 → 6, and **0 of 623 depth≥2 events** carry ≤3 unique variables. Depth adds genuine diversity. |

**Standing note on how these arose.** All three were asserted by external reviewers without access to the codebase, accepted without verification against source, and only then checked. The lesson is recorded in the non-negotiables (Section A) and applies to this document as much as to any other: **an assertion about the code is not evidence about the code.** Verify, then classify.

---

## 11. SCRIPTS THAT CHANGE

Sacred five stay **byte-locked**: `dots_thresholds.py` `518862bf19fb`, `wf.py` `793e6e5f8d9a`, `core.py` `6530e2508b17`, `portfolio_simulation_engine.py` `bb498eb13ce3`, `conviction.py` `27af7acee824`. `verify_sacred()` must still abort on drift. `build_condition_pool` (S.10) is not modified (§G.1).

| script | change |
|---|---|
| `master.py` | new stages: **S3B** family evidence review (§A.1–A.5), **S5B** selection layer (§C, §D, §G, §H). S7 gains the depth-sized contender rows (§F.3, §F.5 if authorised, §F.6 two-way). S9 report surfaces the §A.1 table and §H decisions. New sha; fresh Auditor pass required. |
| `engine/cluster_profiler.py` | extend to admit cross-family entries with origin tags (§A.4); emit family-composition vectors per cluster; stratify coverage by episode absolute size (§D.2); emit the §D.0 missed-episode decomposition across the thrust grid. |
| `scanners/concurrence_profiler.py` (F12) | unchanged pending the §A.2 measurement; classification may change on the result. |
| **new** `engine/selection.py` | implements §C.3 objective and §C.3.1 greedy/CELF search, §C.2 tail-dependence and mCVaR, §D.2 coverage, §G.1 collapsing, §G.2 domain bridging and community detection, §H.1–H.3. The single place selection logic lives, so the Auditor has one file to verify. **Must not claim the (1 − 1/e) bound unless §C.3.1 submodularity is established.** |
| **new** `engine/wf_selection.py` | implements §I including the §I.4.1 append-only attestation. Must not import from `selection.py` in a way that lets a test segment influence a fitted parameter; the split boundary is enforced structurally, not by convention. Derives the split count from the §I.1 floor; does not assume 4. |
| `master.py` (additional) | S8 emits `discovery/committed/trades.csv` (per-trade table, reveal open item 8, §B.2). `OOS_MONTHS` made data-relative or its outputs flagged stale (§B.1, reveal open item 7). |
| **new** `engine/hawkes_research.py` | implements §J. Research only — no live path, no import from the committed scoring chain. |
| `portfolio_simulation_engine.py` | **SACRED / byte-locked. Unchanged.** §F.5's depth-dependent cap touches `MAX_POSITIONS` and is **specified but NOT authorised**; it requires documented human authorisation before any edit. |
| `discovery_map.md` | §3 line 90 F10 flag correction (§1.4). |
| `DOT_new_data_reveal_2026-07-21.md`, `DOT_progress_and_rd_plan.md` | §1.1, §1.2 corrections. Decision 2 to be restated. |

Everything runs under `master.py`. No standalone scripts.

---

## 12. GROUNDED vs PROPOSED

**Grounded in measurement taken this session, reproducible through the ratified path:**

- §1.1 the record's §5 table is a regime-state filter — reading C reproduces every published digit; the directional gate gives PF 0.97 / −$111 on NEW.
- §1.2 the 77% / thrust-overlap reconciliation — Q4 at percentile 88.9 absolute vs 72.6 ATR-normalised; traded median 2.56 disp/ATR vs all-eligible 3.40.
- §1.3 missed episodes are tradeable (median 58–78 pt) but 2.5–3× smaller than traded (168–224 pt); 4.4–5.4% of episodes touched.
- §E.3 the regime-state filter's effect is one month; `reg==0` wins on PF in 3 of 7 months; OLD-segment differential is 6.33 vs 6.25.
- §F.1 solo economics, the non-separability of first entries, and the cost of waiting for depth across all three depth definitions ($77,239 take-all → $40,429 / $23,102 at N=5 cluster position; $33,105 / $17,869 at bar-level qualifying depth).
- §F.2 the pre-jar depth ladder (§0.1.2A bar-level qualifying depth).
- §0.1 the canonical definitions, and the N=5 vs N=10 divergence that made them necessary (clusters 991 vs 790, size≥5 125 vs 152, DepthYield 1.033 vs 1.256/day).
- §1.1 the segment-boundary arithmetic at all three candidates; the natural boundary reproduces the canonical 2,698 trades at PF 6.40.
- §B.1 that `wf.FOLDS` excludes July and is unusable inside a split.
- §G the **4** duplicate pairs and 7 dead conditions on the eligible universe, effective vocabulary **238** — and the finding that the identity-test domain changes the answer (all-bars gives 1 pair / 6 dead / 242).
- The depth ladders and cluster statistics quoted throughout, on all three bases.
- **§C.2 the inadequacy of Pearson (BOOK)** — τ=0.20, k=10, raw daily P&L, 790 pairs: mean Pearson +0.0992 against a tail lift of **1.69x** independence, 20.5% of pairs misread, rank correlation +0.382.
- **§I.3 the per-split nulls cannot distinguish 27% from 44% at n=16** — 6/16, 7/16, 5/16 with exact 95% intervals [0.152,0.646], [0.198,0.701], [0.110,0.587], all containing 0.27; pooled 18/48 CI [0.240,0.526].
- **§I.3 the required null denominator** — two independent derivations converge on 55–79; target 80, hard floor 40; train-qualification 16/120 = 13.3% with CI [0.078,0.208].
- **§C.2 the exclusion bias is ANTI-CONSERVATIVE (BOOK)** — retained 0.3387 vs excluded 0.4433 raw / 0.3571 degeneracy-guarded; 21 degenerate pairs at k<3 (5 at k=1, 16 at k=2).
- **§C.1 cross-direction co-firing is structurally zero (DESIGN, not market)** — 0 of 481 unordered cross pairs share a qualifying bar; 962 of 2,450 ordered pairs (39.3%) are zero by construction.
- **§C.2 the operating-point defect** — τ=0.10/k=20 retains 8.2% of the pair space and its exclusion is anti-conservative (excluded λ 4.34 vs retained 3.96); τ=0.20/k=10 retains 64.5% and flips the bias conservative.
- **§D.0.1 directional opportunity is symmetric (PRICE-ONLY)** — 49.8% up / 50.2% down of thrust bars, median down-move larger (82.0 vs 77.1 pts), near-symmetric in all 7 monthly buckets including April (+3,437 pts, still 45.4% down-thrusts). BOOK-50 converts that into 86.2% / 13.8% of net at effectively equal win rates (90.9 vs 91.0).
- **§D.0.2 the short-side shortfall is depth, not reach (BOOK)** — thrust episodes traded 4.1% up vs 3.0% down, missed set 50.3% down-side; but LONG mean cluster depth 3.38 / 19.3% reach ≥5 versus SHORT 1.72 / 3.0% reach ≥5 / 56.9% solo.
- **§F.3.1 the cluster arc (BOOK)** — within size≥8 clusters, PF 7.74 → 19.43 → 8.32 → 6.79 and average trade declining monotonically $46.58 → $27.09.
- **§C.3 signal identity dissolves at depth (BOOK)** — WR spread across signals falls from sd 9.01 (floor 70%) at depth 1–2 to sd 5.52 (floor 81%) at depth 8+.
- **§C.1 the directional disparity is combinatorial** — raw 9.42:1 at S=5/N=5 against a 2.85:1 signal-count ratio and an 8.54:1 pair-availability ratio, with short signals active on *more* days per signal (38 vs 31) and comparable trades (49 vs 51). Normalisation collapses it to 3.31:1.
- **§D.0 the missed-episode decomposition** — 89.8% no qualifying signal, 10.2% qualified without entry, 1.4% occupancy-blocked.
- **§F.4 that the decision-6 population is empty** — 0 of 623 depth≥2 events at ≤3 unique variables; unique variables rise 3 → 12 with depth; the original observation was a lookup artifact covering 48 of 50 signals.
- **§F.6 the depth × volatility interaction** ($23.3 / $28.0 / $115.5) and the survival of the depth ladder under volatility and session control (partial rho +0.2793, p = 4.6e-47).
- **§G.2 the near-duplicate structure** — 100 pairs at |r| ≥ 0.70 of 29,161, median |r| 0.033, 126 components for 90% variance.
- **§H.1 that PRDS fails** — 49.6% positive / 50.4% negative signed dependence, so BH is invalid and BY is required.
- **§10C all three withdrawn items**, each disproved against source or data.

**Reasoned proposals awaiting a first run — no result is claimed for any of these:**

- §A.1 the family evidence table and every verdict in it. Nobody has looked; the outcome is unknown.
- §A.2 whether F12 is duplicate, independent or superseded.
- §A.4 whether mixed-family clusters form at all, and whether they behave like same-family clusters. This is a genuinely open question with no prior measurement.
- §C.3 that `DepthYield` and `FailConc` are separable in practice. The two-axis model is motivated but unproven.
- §D.3 that reach-recruited signals qualify under §H and that their clusters behave. §1.3 gives grounds for caution — the missed population is smaller.
- §E.4 whether the LT adaptive family carries gate value. The S8B lift is real; its meaning as a gate is untested.
- §F.4 the value of `U`. Deliberately not chosen.
- §H.1–H.3 that a book survives the corrected funnel at all. It is entirely possible that few or no signals clear the empirical-null bar plus 70% stability plus 6-of-7 regime positivity. **That outcome must be reported as a result, not treated as a failure requiring the bar to be lowered.**
- §I that the method passes at ≥65%. Unknown. The current 50% against a 27% null is the honest starting point.
- **§C.3.1 whether the full objective is submodular.** Unresolved. Coverage alone is; the tail penalty in general is not. The build must establish it or drop the bound claim.
- **§D.0's limit — whether the vocabulary can fill the located gap.** The gap's mechanism is measured; its fillability is not. S8B basis 3 found no single condition separating (max controlled lift 1.35), which is evidence against.
- **§F.5 whether the depth-dependent cap improves survival.** Untested, and unauthorised — it touches a byte-locked file.
- **§F.6 whether a two-way size curve beats one-way** by more than the §H.2 noise band.
- **§G.2 whether the 2-domain rule binds** on enough triples to matter.
- **§J whether first-arrival Hawkes intensity predicts cluster formation.** The named attack on the one measured dead end. Defined pass/fail; outcome unknown.
- **§H.1 whether White's/SPA accept a different set** than the empirical null, or are redundant here.

**One standing limitation applies to everything above:** six months, one instrument, two partial months, one dominant crash month. The direction of the depth findings survives three independent measurement methods and both cluster tolerances; the magnitudes do not have out-of-sample support. A second export remains the highest-value un-run validation in the project.
