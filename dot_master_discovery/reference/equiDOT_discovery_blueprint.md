# equiDOT — Stage 8 Signal Discovery Blueprint

*Created 2026-07-02. The organizational plan for the definitive discovery run (execution-sequence step 14). Defines every script, the order they run, the common result schema, and how findings are collected and collated into one comparable table. Source of truth for status: `equiDOT_progress_and_rd_plan.md`. Pattern definitions: `equiDOT_discovery_pattern_map.md` (v6). This blueprint is the HOW; the map is the WHAT.*

---

## 1. Fixed infrastructure — the shared spine (ratified; never run standalone as a scanner)

Every family scanner rides on these three ratified modules + the sealed baseline. They are imported, never reconstructed.

- **`dots_thresholds.py` — the oracle (SACRED).** `compute_adaptive_thresholds(df)` and `compute_structural_gates(df)` produce the per-bar hi/lo levels and structural gates ONCE on the full series. Every condition mask in every family comes from these. Zero independent threshold computation anywhere.
- **`portfolio_simulation_engine.py` — the sim engine (ratified).** `load_sealed_baseline()` loads the 152,983×171 baseline (+ derived VWAP_Sigma_ATR); `warmup_floor(df)` = 6900 (covers the deepest-warmup variable); `condition_mask(df, feat, thresh, adaptive, structural)` is the oracle-routed mask builder; `run_portfolio(...)` is the SOLE trade path (locked S.7 TM + the D2D gate). The `Trade` class and exit loop are here — no scanner reconstructs them.
- **`wf.py` — walk-forward scoring (ratified, locked step 12).** `FOLDS` = 6 monthly (Jan19-31/Feb/Mar/Apr/May/Jun1-25); `fold_metrics`, `daily_pnl_points`, `points_to_usd`, `pf_from_pnls`, `spread_stress`, `run_walkforward`; `DAILY_LOSS_CEILING_USD` = 2500. Every family scores through these — so all families are directly comparable on the SAME survival-first metric.
- **Sealed baseline** `equiDOT_recon171_step7_part1..8.csv` — FINAL for Stages 8–10. No EA changes during the run (sealed-data directive).

Data flow, once per run: `load_sealed_baseline` → `compute_adaptive_thresholds` + `compute_structural_gates` (oracle, once) → each scanner builds its candidate masks from `condition_mask` → each candidate scored via `run_portfolio` + `wf` primitives → survival-first result row.

---

## 2. The 11 scanners

| Family | Script | Entry (full scope) | Searches | D2D | Prod tier |
|---|---|---|---|---|---|
| F0 | `triple_convergence_and_d2ddir.py` | `run_search` + `run_density` | 3-var same-bar convergence over 117/249; **density** mode sweeps co-fire count>=k over the selected set | confirm | no-burden |
| F1 | `sequential_temporal.py` | `run_search` | ordered A→B→C over lag windows | confirm | new-input |
| F2 | `state_transition.py` | `run_search` | state value[t]≠value[t-1] (typed + generic) | confirm | new-input |
| F3 | `conditional_interaction.py` | `run_search` | base FEAT_ AND state-gate (sub-population) | confirm | no-burden |
| F4 | `divergence_nonconfirm.py` | `run_search` | price-extreme AND opposite-flow | invert/exempt | no-burden |
| F5 | `persistence_autocorr.py` | `run_search` | state-hold; fwd-return = discovery-only target | confirm | no-burden |
| F6 | `threshold_crossing.py` | `run_search` | first-breach of oracle level + optional ROC | confirm | new-input |
| F7 | `mean_reversion.py` | `run_search` | single stretched condition, faded | invert/exempt | no-burden |
| F8 | `cross_variable_structure.py` | `run_search` | structural A>B / A<B / A≠B | confirm | new-input |
| F9 | `session_temporal.py` | `run_search` | base FEAT_ × named session anchors + weekday | inherited (confirm) | no-burden |
| F11 | `rolling_leadlag.py` | `run_search` | causal rolling corr/beta/lead-lag | confirm | new-input |

(F10 convergence-density is fused into F0's `density` mode — not a standalone scanner.)

---

## 3. Run order

1. **F0 full triple search** — the long pole. C(117,3)=260,130 triples × variants (~5.0M), `MIN_PF=4.0` pre-gate trims. Run ALONE (likely hours / overnight). Its surviving triples are the input to step 3.
2. **F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9 → F11** — independent, no cross-dependency; run in this order (cheapest vocabulary first, heaviest — F11 rolling stats — last). Each fast relative to F0.
3. **F0 density mode** (`run_density`) over F0's surviving set — does requiring higher co-fire count improve survival vs the min?

Rationale: F0 first because it is the primary hypothesis and its output feeds density; the rest are parallelizable and cheap; density last because it needs F0's survivors.

---

## 4. The common result schema — the "simple signal" (one row per candidate)

Every scanner emits rows in ONE schema, so the master table is trivially comparable:

```
family        : F0..F11
script        : source .py
signal_def    : human-readable definition (family-specific string)
direction     : LONG / SHORT
d2d_mode      : confirm / invert / exempt / inherited
trades        : n
WR            : win rate %
agg_pf        : aggregate profit factor
worst_day_usd : worst single-day USD at target lot
hard_stop_days: count of days breaching -2500
folds_plus    : profitable folds out of 6
min_fold_pf   : weakest fold PF
spread_pf     : PF under spread stress
survival      : PASS / REJECT   (worst_day_usd > -2500)
```

`survival`, `folds_plus`, `min_fold_pf`, `agg_pf` are all produced by the shared `wf` primitives — identical computation across families.

---

## 5. How each runs — the orchestrator harness

A single new script — **`discovery_orchestrator.py`** (to build, Developer→Auditor; adds ZERO signal logic, only calls ratified `run_search` and normalizes output, so it is a light ratification, not a new scanner).

It:
1. Loads the baseline + oracle thresholds ONCE (shared across all families — no recompute).
2. Calls each family's `run_search` at FULL scope (full pool / all lags / all pairs / all windows — not the `main()` run-proof subsets).
3. Normalizes each family's returned rows to the common schema (section 4).
4. Writes one CSV per family: `results_F<n>_<script>.csv`.
5. Collates all into a master table: `discovery_master.csv`.

No scanner is modified (they stay ratified). The orchestrator imports and drives them. F0 (heaviest) can be run as its own step and its CSV dropped in, so the orchestrator doesn't have to hold the whole F0 search in one process.

---

## 6. Collection + collation

- Per-family CSVs land in a `discovery_results/` folder, common schema.
- `discovery_master.csv` = concatenation of all family CSVs + the `family` tag.
- Row count is the full candidate census (survivors + rejects) — nothing dropped at collection; filtering happens at selection, not collection (include-and-let-selection-sort).

---

## 7. Selection (step 14 output → step 15 validate)

Applied to `discovery_master.csv`, in this order (matches the locked survival-first doctrine):

1. **Survival gate (hard, first):** keep `survival == PASS` (worst_day_usd > -2500 at target lot). A high-PF REJECT is eliminated, not ranked.
2. **Persistence:** among survivors, require broad fold coverage — `folds_plus` 6/6 (tolerate 5/6 with scrutiny), and `min_fold_pf` not carried by one fold.
3. **Rank:** sort survivors by `(folds_plus ↓, min_fold_pf ↓, agg_pf ↓)`.
4. **Family attribution:** tag which families produced the OOS-dominant survivors — is the edge concentrated (one family) or regime-diversified (different families carrying different folds)?
5. **Regime read (post-hoc only):** with the survivors' per-fold behavior, read against the baseline regime map (correction / vol-spike / recovery / melt-up) — a diagnostic lens, NEVER an input to selection (no curve-fit to the news).

---

## 8. Invariants (hold for the whole phase)

- Oracle-only thresholds; the sacred layer is untouched; the EA stays frozen (sealed-data directive).
- The scanners' `main()` run-proofs are ARBITRARY subsets that REJECT — proof of execution, not findings. No run-proof number is ever cited as a result.
- Real results come only from the full orchestrated run. Report each candidate's raw numbers exactly; the survival gate makes a PASS mean something.
- New-derived-input families (F1, F2, F6, F8, F11) are analysis-only here; production export==live parity is a Stage-9 concern, not a discovery blocker.
- Nothing about the outcome is pre-judged. The run answers it.

---

## 9. Next action

Build `discovery_orchestrator.py` (Developer → Supervisor → Auditor) per section 5, then execute the run order in section 3. F0 first (alone), the rest collated, density last → `discovery_master.csv` → selection (section 7).
