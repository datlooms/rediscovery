# dot_master_discovery — DOT Master Discovery: Program Map & Inventory

Inventory and reconciliation of the `dot_master_discovery` pack. Every sha256 below is the first 12 hex chars, self-computed from the actual bytes.

**Entry point:** `master.py` is the single command that runs the whole pipeline (S0→S9). See **master_guide.md** to run it. This map is the file inventory; the build contract is **master_stage_spec.md**.


**2026-07-18 rename + Windows-UTF8 + verdict-softening pass.** Program renamed `stage8_discovery` → `dot_master_discovery`. All text file I/O now carries `encoding='utf-8'` (Windows cp1252 crashes on `→`/`×`/`≥`). S8 verdict softened to a quiet US30-baseline canary. The 5 sacred files stay **byte-identical** (their historical "Stage-8" phase comments are preserved under byte-lock — those name the dev phase, not the directory). Non-sacred scripts touched this pass (new shas above): master.py `db8957587844`, run_full_analysis `886ea8ca17fa`, analysis_engine `d9acd1ddc3fe`, single_variable_extremes `37e3a9075aea`, run_f1_parallel `230427fcbd04`, concurrence_profiler `554019e93069`. master.py also received later post-ratification patches (Windows UTF-8 file-I/O + natural-sort/S0 header-handling for >9 split parts + rebuild.py integration via shared `_packutil.py`) — committed-path logic unchanged, $92,347 re-verified REPRODUCED. **The Auditor-ratified master.py sha was `9f124a9160c8`; it is superseded by the current `db8957587844` — a fresh Auditor pass on `db8957587844` is pending.**

Headline reconciliation: the ratified scripts (engines, oracle, 13 scanners, orchestrator) are byte-identical between the pack and the project files. `master.py` orchestrates them and never rewrites them.

**Retired in the master-centric consolidation** (no longer current; superseded by `master.py` + `master_guide.md`): `RUN_STAGE8.md` (old runbook — run guide folded into master_guide.md, sha manifest folded into §5/§8 here), `DOT_stage8_program_map.md` (old multi-script pack manual), `stage8.py` (entry stub — `master.py` absorbed its CWD-relative resolver into S0). No current doc references these as live.

---

## 1. Directory Tree (annotated)

```
dot_master_discovery/
├── master.py                      SINGLE ENTRY POINT — one command runs S0→S9 (ingest→report)
├── master_guide.md                operator guide (how to run + every stage) — PRIMARY doc
├── discovery_map.md               THIS FILE — script/file inventory
├── data/                          SEALED BASELINE — equiDOT_recon171_step7_part1..8.csv (152,983 × 171, Jan19–Jun25)
├── engine/                        scoring engines + oracle + reconstruction + book/G scorers (see §5)
├── scanners/                      the F0–F13 family scanners + F0/F1 runners + F0→schema converter (see §3)
├── orchestrator/                  discovery_orchestrator.py — drives the family scanners (S3 delegates here)
├── reference/                     design docs (blueprint, pattern map) — LOCAL-ONLY
├── discovery/                     master.py output root — {raw,results,scored,contenders,committed}/ + master_report.md + .markers/
└── dots_results/                  F0 write-dir (raw/deduped survivors, results_F0) + read-dir for f0_to_schema /
                                   concurrence_profiler; materialised under discovery/ on a discover-fresh run
```

RETIRED (removed from the pack): `RUN_STAGE8.md`, `DOT_stage8_program_map.md`, `stage8.py` — see the note above.

---

## 2. Every Script by Function Group

### Data-ingest / export / reconstruction
| Script | Role | Inputs | Outputs |
|---|---|---|---|
| `engine/core.py` | Reconstruction pipeline. Maps the 256-col step-7 export → 171-col schema (`cols171 = cols256[:171]`; `NEW45 = cols171[126:]` = the 45 features added beyond the retired 126-col generation), stitching original OHLCV + recomputed cold-start features. Produces the sealed baseline. | original OHLCV + 256-col step-7 export | the `equiDOT_recon171_step7_part*.csv` baseline |
| `master.py` | **SINGLE ENTRY POINT.** One command runs S0→S9: ingest → oracle → discovery → filter → contenders → committed score → report. Sacred-parity gate at startup, checkpoint/resume, auto-split. Absorbs `stage8.py`'s resolver + `reproduce_dot.py`'s S8 logic. | `/data/*.csv`, optional `--book` | `/discovery/` tree + `master_report.md` |

### Adaptive-threshold (oracle)
| Script | Role |
|---|---|
| `engine/dots_thresholds.py` | **SACRED oracle.** Mechanism-D rolling-2500 day-refreshed floor-index percentiles (`_floor_pct`) + structural gates (VWAP_Z ±2, OR_Position 0.80/0.20). Swept for p30/p90/p97 by runtime-extending `_D_SPEC` (never edited on disk). |

### Family scanners (F0–F13) — see §3 for the per-family table
`triple_convergence_and_d2ddir.py` (F0), `sequential_temporal.py` (F1), `state_transition.py` (F2), `conditional_interaction.py` (F3), `divergence_nonconfirm.py` (F4), `persistence_autocorr.py` (F5), `threshold_crossing.py` (F6), `mean_reversion.py` (F7), `cross_variable_structure.py` (F8), `session_temporal.py` (F9), `rolling_leadlag.py` (F11), `concurrence_profiler.py` (F12), `single_variable_extremes.py` (F13).

### Runners / filtering / schema
| Script | Role | Inputs | Outputs |
|---|---|---|---|
| `scanners/run_f0_full.py` | F0 full-run driver (sets F0 pre-gate MIN_PF, launches the triple-convergence scan). | baseline | `dots_results/` (raw + deduped survivors, results_F0) |
| `scanners/run_f1_parallel.py` | F1 parallel driver (self-bootstrapping MP). | baseline | F1 survivor CSV(s) |
| `scanners/f0_to_schema.py` | Converts F0 survivors → the common 14-col scanner schema. | `dots_results/deduped_survivors.csv` | schema-normalised F0 CSV |

### Scoring engines — see §5
`portfolio_simulation_engine.py`, `conviction.py`, `score_g.py`, `score_book50.py`, `analysis_engine.py`, `run_full_analysis.py`.

### Orchestration
| Script | Role |
|---|---|
| `orchestrator/discovery_orchestrator.py` | Drives the family scanners end-to-end (scan → filter → schema), progress/checkpoint coordination. |

### Walk-forward / reproduction
| Script | Role |
|---|---|
| `engine/wf.py` | **Byte-locked.** 6 monthly folds, survival-first scoring, `daily_pnl_points` (exit-day series used for daily worst-day / daily mDD). |
| `reproduce_dot.py` | Reproduction harness — **project-only, not in the pack** (see §7). |

---

## 3. Family Scanners F0–F13

| F | Script | Scans | Output in `discovery_results/` (or `dots_results/`) | Path |
|---|---|---|---|---|
| **F0** | `triple_convergence_and_d2ddir.py` | Triple-convergence (3 variables at extremes) + D2D-direction; fast-scan scorer, per-trade TM behaviour-identical to the engine. | `dots_results/raw_survivors.csv`, `deduped_survivors.csv`, `results_F0_triple_convergence_and_d2ddir.csv` | **COMMITTED** (BOOK-50 is drawn from F0 survivors) |
| **F1** | `sequential_temporal.py` | Sequential/temporal pairs (A →k→ B via ST_Flip anchor). | `F1_part1.csv`, `F1_part2.csv` | exploratory (2 F1 pairs entered BOOK-50) |
| **F2** | `state_transition.py` | Transition / regime-change. | `results_F2_*` | exploratory |
| **F3** | `conditional_interaction.py` | Conditional / context-gating. | `results_F3_*` | exploratory |
| **F4** | `divergence_nonconfirm.py` | Divergence / non-confirmation. | `results_F4_*` | exploratory |
| **F5** | `persistence_autocorr.py` | Persistence / autocorrelation. | `results_F5_*` | exploratory |
| **F6** | `threshold_crossing.py` | Threshold-crossing / momentum-ignition. | `results_F6_*` | exploratory |
| **F7** | `mean_reversion.py` | Mean-reversion-from-extreme. | `results_F7_*` | exploratory |
| **F8** | `cross_variable_structure.py` | Relative / cross-variable structure. | `results_F8_*` | exploratory |
| **F9** | `session_temporal.py` | Temporal / session / calendar conditioner. | `results_F9_*` | exploratory |
| **F10** | — | *Not a separate scanner: the concurrence lens was **FOLDED INTO F0** (lens null). F12 (`concurrence_profiler.py`) is the diagnostic remnant.* | — | **FOLDED INTO F0** |
| **F11** | `rolling_leadlag.py` | Cross-variable × windowed (rolling lead-lag / correlation). | `results_F11_*` | exploratory |
| **F12** | `concurrence_profiler.py` | Raw variable-depth concurrence **measurement** (does stacking depth predict outcome?). MEASURES, never selects. Secondary lens reads `dots_results/deduped_survivors.csv`. | 9 × `concurrence_*.csv` | exploratory / diagnostic |
| **F13** | `single_variable_extremes.py` | Single-variable extremes (percentile sweep, both dirs, both D2D polarities). Standalone, NOT convergence. | `results_F13_single_variable_extremes.csv` | exploratory — **documented negative** (0 stars / 0 candidates; convergence necessary) |

**Committed path:** F0 (→ BOOK-50) + the 2 F1 pairs adopted into BOOK-50. Everything else (F2–F13) is exploratory/diagnostic. **F10 is FOLDED INTO F0** (concurrence lens null; F12 is the diagnostic remnant) — not a gap; the family set is complete. This line previously carried a stale GAP flag contradicting the Resolution status below; corrected per spec §1.4.

---

## 4. Data Export Handling (raw export → sealed baseline)

Lineage, oldest → current:

1. **Retired 126-col generation** (`64_186_*`, `equiDOT_recon_part*`) — superseded.
2. **Intermediate 64_236_* / 64_246_* generations** — superseded.
3. **256-col step-7 export** (`64_256_*`) — the current raw export input to `core.py`.
4. **`core.py` reconstruction** — `cols171 = cols256[:171]`; `NEW45 = cols171[126:]` (the 45 variables added on top of the old 126). Takes correct original OHLCV + recomputes cold-start features (KAMA/HarmVol/PoC warm-start), applies the δ shift correction, and writes the **sealed 171-col baseline**.
5. **Sealed baseline** — `data/equiDOT_recon171_step7_part1..8.csv` (152,983 × 171, Jan 19 → Jun 25). This is the FINAL discovery/scoring surface for Stages 8–10.

**Splitting.** The baseline ships pre-split into 8 parts (`part1..8`). F1 output is split into `F1_part1.csv` / `F1_part2.csv`. **RESOLVED — `master.py` S9 provides the canonical splitter** (`split_output`/`split_tree`): every `/discovery/` artifact over `--chunk-mb` (default 9) splits on row boundaries, header in part1 only, continuation parts headerless (the baseline's convention, so the master re-ingests its own outputs), with a `_manifest.txt` of per-part shas. The prior external/ad-hoc F1 part-split is superseded.

---

## 5. The Engines

| Script | sha256[:12] | Role | Status |
|---|---|---|---|
| `engine/dots_thresholds.py` | `518862bf19fb` | Oracle (mechanism-D percentiles + structural gates). | **SACRED — byte-locked** |
| `engine/wf.py` | `793e6e5f8d9a` | Walk-forward (6 folds, daily series, survival-first). | **SACRED — byte-locked** |
| `engine/core.py` | `6530e2508b17` | Reconstruction pipeline (256→171, 126→171 lineage). | **SACRED — byte-locked** |
| `engine/portfolio_simulation_engine.py` | `bb498eb13ce3` | Ratified TM: S.7 + S.12 runner + S.15 jar + S.19 momentum-SL + S.20 conviction/gaps + **D2D Roles 1&2** (short_mult, 2-lot D2D-gap bypass, per-trade lock, warm-up guard). Sole trade path. | ratified (current) |
| `engine/conviction.py` | `27af7acee824` | S.20 + D2D conviction/gap builder (`long_mult`, `short_mult`, `gap_hurst`, `gap_fb`, `gap_d2d_dir` with Vol≥300 gate). | ratified (current) |
| `engine/score_g.py` | `3129aecec634` | D2D crown-jewel option-map scorer (DOT-alone / +Role2 / +Role1 / crown), population breakdown, daily wd + daily mDD. Reproduces **$92,347** canonical. | ratified (current) |
| `engine/score_book50.py` | `f2db7eb592a6` | Flat BOOK-50 scorer (reproduces the flat book $58,277). | current |
| `engine/analysis_engine.py` | `d9acd1ddc3fe` | F0 tic-proof scorer core (per-signal folds/weeks/dow via injected ==1). | current (but see §6) |
| `engine/run_full_analysis.py` | `886ea8ca17fa` | F0 analysis driver → `signal_full_records.csv` + `signal_per_day_pnl.jsonl`. | current engine, **stale outputs — see §6** |
| `reproduce_dot.py` | *(project-only)* | Reproduction harness. | **not in pack** |

Oracle / wf / core are byte-identical to the project copies (§7) and must stay so.

---

## 6. Canonical vs Superseded

**Superseded data generations (correctly ABSENT from the pack):**
- `126-col` generation (`64_186_*`, `equiDOT_recon_part*`) and the `64_236_*` / `64_246_*` intermediates. Superseded by the sealed 171-col step-7 baseline in `data/`. None are in the pack — correct.

**Version-skewed OUTPUTS (present in project, flagged stale):**
- `signal_full_records.csv` (project sha `746102aae415`) and `signal_per_day_pnl.jsonl` (project sha `0910f360a628`) are produced by `run_full_analysis.py` / `analysis_engine.py`. These were generated by an **earlier engine state** (pre-S.19/S.20/D2D) and carry the version-skewed per-signal P&L field. **They are STALE relative to the current ratified TM** and must be regenerated before any use against the committed system. The scripts that produce them are current; the *artifacts* are the stale pieces. The master must NOT carry these two files as-is.

**Current/canonical outputs:**
- `results_F0_triple_convergence_and_d2ddir.csv`, `raw_survivors.csv`, `deduped_survivors.csv` (F0 discovery, drives BOOK-50), `F1_part1/2.csv` (F1 pairs), `results_F13_single_variable_extremes.csv` (documented negative), `book50_signals.csv` (the 50-signal book). These are canonical.

**Deprecated figures (documented in the map, not files):** the modelled `$90,103` (S.20 harness) and `$92,567` (D2D modelled) are superseded by the built-system canonical `$92,347` (gap-path engine; ~$220 admission-timing displacement, immaterial).

---

## 7. Present-in-Project vs Local-Only — THE KEY DELIVERABLE

**Legend:** MATCH = byte-identical to the project copy (sha shown); LOCAL-ONLY = in the pack but not uploaded to project (⇒ upload); PROJECT-ONLY = in project but not carried in the pack.

### 7a. Pack files present in the project (all byte-identical)
| Pack path | sha256[:12] | Project parity |
|---|---|---|
| `engine/portfolio_simulation_engine.py` | `bb498eb13ce3` | MATCH |
| `engine/conviction.py` | `27af7acee824` | MATCH |
| `engine/score_g.py` | `3129aecec634` | MATCH |
| `engine/score_book50.py` | `f2db7eb592a6` | MATCH |
| `engine/analysis_engine.py` | `d9acd1ddc3fe` | MATCH |
| `engine/run_full_analysis.py` | `886ea8ca17fa` | MATCH |
| `engine/wf.py` | `793e6e5f8d9a` | MATCH |
| `engine/core.py` | `6530e2508b17` | MATCH |
| `engine/dots_thresholds.py` | `518862bf19fb` | MATCH |
| `engine/book50_signals.csv` | `e86a52244501` | MATCH |
| `orchestrator/discovery_orchestrator.py` | `31165e9a17df` | MATCH |
| `scanners/triple_convergence_and_d2ddir.py` (F0) | `5ed2221e5339` | MATCH |
| `scanners/sequential_temporal.py` (F1) | `cda5b7459077` | MATCH |
| `scanners/state_transition.py` (F2) | `8cb42c9d9891` | MATCH |
| `scanners/conditional_interaction.py` (F3) | `7908ed0c5fbc` | MATCH |
| `scanners/divergence_nonconfirm.py` (F4) | `a95c521cd55c` | MATCH |
| `scanners/persistence_autocorr.py` (F5) | `cd3afbfe6994` | MATCH |
| `scanners/threshold_crossing.py` (F6) | `147deb44d1b5` | MATCH |
| `scanners/mean_reversion.py` (F7) | `868bc7edf5fe` | MATCH |
| `scanners/cross_variable_structure.py` (F8) | `5594fa73a7d3` | MATCH |
| `scanners/session_temporal.py` (F9) | `2e5f1703aaa2` | MATCH |
| `scanners/rolling_leadlag.py` (F11) | `08848774ca1c` | MATCH |
| `scanners/concurrence_profiler.py` (F12) | `554019e93069` | MATCH |
| `scanners/single_variable_extremes.py` (F13) | `37e3a9075aea` | MATCH |
| `scanners/f0_to_schema.py` | `f878d3b46c8b` | MATCH |
| `scanners/run_f0_full.py` | `8a8a276cfbef` | MATCH |
| `scanners/run_f1_parallel.py` | `230427fcbd04` | MATCH |
| `master.py` | `db8957587844` | run entry point (S0 re-ingests split parts, natural-sort) |
| `rebuild.py` | `609580a417fe` | data-prep entry point (raw export → data/) |
| `engine/family_evidence.py` | *(see manifest)* | S3B per-family evidence review + D2D gate measurement (spec A.1–A.5, E.1) |
| `engine/selection.py` | *(see manifest)* | S5B selection layer: objective, per-direction greedy, constraints, hygiene (spec C, D.1–D.2, G, H) |
| `engine/wf_selection.py` | *(see manifest)* | S5C walk-forward on the selection process (spec I) |
| `engine/cluster_profiler.py` | *(see manifest)* | S8B cluster-participation profiler + §D reach measurements |
| `_packutil.py` | `6c8f2a3a7d04` | shared helpers (natural-sort + auto-split), no import side-effects |
| `master_guide.md` | `027be57e8634` | current operator doc |
| `data/equiDOT_recon171_step7_part1..8.csv` | `9b27119ab564` … `3605299a3fa1` | MATCH (all 8 parts) |
| `discovery_results/results_F13_single_variable_extremes.csv` | `ca7aafdb7f80` | MATCH |

### 7b. LOCAL-ONLY — in the pack, NOT in project (⇒ **UPLOAD LIST**)
| Pack path | sha256[:12] | Note |
|---|---|---|
| `reference/equiDOT_discovery_blueprint.md` | `423e6e60c38e` | design doc — upload |
| `reference/equiDOT_discovery_pattern_map.md` | `1a7a9d423381` | design doc — upload |
| `discovery_results/_f13_shards/` (30 shard CSVs + `.done`) | *(per-shard)* | F13 crash-resume checkpoints — intermediate/regenerable; upload only if the shard trail is wanted |
| `discovery_map.md` (this file) | *(new)* | upload |

### 7c. PROJECT-ONLY — in project, NOT carried in the pack (discovery outputs & harness)
| Project file | project sha256[:12] | What it is |
|---|---|---|
| `results_F0_triple_convergence_and_d2ddir.csv` | `1d90b7ddf5fa` | F0 committed output (belongs in `dots_results/`) |
| `raw_survivors.csv` | `a3886a9e220a` | F0 raw survivors (`dots_results/`) |
| `deduped_survivors.csv` | `9ffe64974c03` | F0 deduped survivors — read by F12/f0_to_schema (`dots_results/`) |
| `F1_part1.csv` | `ebc511444d82` | F1 output |
| `F1_part2.csv` | `3d7928c3a7bb` | F1 output |
| `signal_full_records.csv` | `746102aae415` | **STALE / version-skewed (§6)** |
| `signal_per_day_pnl.jsonl` | `0910f360a628` | **STALE / version-skewed (§6)** |
| `reproduce_dot.py` | *(in project)* | reproduction harness — not in pack |

To give the pack a self-contained discovery surface, 7c belongs under a materialised `dots_results/` (F0 outputs) and `discovery_results/` (F1). They are currently only in the project root.

### 7d. Project files outside pack scope (context, not dot_master_discovery)
Governance/context files present in the project that are **not** part of the discovery pack and need no reconciliation into it: `equiDOT.cs`, `equiDOT_KAMA_US30_cash_1.bin`, `equiDOT_adaptive_thresholds_stage.md`, the `non_negotiables_*.txt` set, `DOT_progress_and_rd_plan.md`, `DOT_execution_sequence.md`, `DOT_readme.md`, `DOT_codebase_map.md`, `DOT_handover_blueprint.txt`, `DOT_anti_curvefit_guide.md`, `DOT_backtest_guide.txt`, `DOT_post_update_checklist.txt`, `DOT_linear_development_schedule.txt`, `DOT_rule_master_spec.txt`, `DOT_dev_plan.txt`, `quant_auditor_phase_1_closing.txt`, `DOT_signal_dictionary.xlsx`, `DOT_signal_overview.xlsx`, `DOT_performance_record.xlsx`.

---

### 7e. RETIRED (master-centric consolidation — removed from the pack, not current)
| File | last sha256[:12] | superseded by |
|---|---|---|
| `RUN_STAGE8.md` | `e40025aa3bb6` | run guide → `master_guide.md`; sha manifest → this file (§5, §7) |
| `DOT_stage8_program_map.md` | `ec33a285c233` | `master_guide.md` (stages) + `discovery_map.md` (inventory) |
| `stage8.py` | `8e8f59d80e23` | `master.py` S0 (CWD-relative resolver absorbed) |

Deprecated figures (not files): modelled `$90,103` (S.20 harness) / `$92,567` (D2D modelled) → superseded by built `$92,347` (the `master.py --book` acceptance headline).

---

## 8. Canonical carry-vs-drop manifest (master consolidation)

**CARRY** — `master.py` orchestrates all of these (byte-identical):
- **Sacred (5):** `dots_thresholds.py` `518862bf19fb`, `wf.py` `793e6e5f8d9a`, `core.py` `6530e2508b17`, `portfolio_simulation_engine.py` `bb498eb13ce3`, `conviction.py` `27af7acee824`.
- **Scoring:** `score_g.py` `3129aecec634`, `score_book50.py` `f2db7eb592a6`, `analysis_engine.py` `d9acd1ddc3fe`, `run_full_analysis.py` `886ea8ca17fa`.
- **13 scanners + runners:** F0–F13 per §3/§10 of the spec; `run_f0_full.py` `8a8a276cfbef`, `run_f1_parallel.py` `230427fcbd04`, `f0_to_schema.py` `f878d3b46c8b`; `discovery_orchestrator.py` `31165e9a17df`.
- **Book + entry:** `book50_signals.csv` `e86a52244501` (frozen US30 book); `master.py` (folds in `reproduce_dot.py`'s S8 logic).

**DROP** — never carried:
- `signal_full_records.csv` `746102aae415`, `signal_per_day_pnl.jsonl` `0910f360a628` — STALE (pre-S.19/S.20/D2D); regenerated fresh by S6.
- Retired 126-col (`64_186_*`) / `64_236_*` / `64_246_*` generations — superseded by the sealed 171-col baseline.

**ACCEPTANCE:** `python master.py --book book50_signals.csv` → net $92,347 / 2,698 tr → **REPRODUCED**.

---

## Stage list (current)

`S0 → S1 → S2 → S3 → S3B → S4 → S5 → S6 → S5B → S5C → S7 → S8 → S8B → S9`. S3B, S5B, S5C and S8B were added by the discovery redesign; no existing stage was renumbered. S5C is named for the selection layer it validates and is dispatched after S5B.

## Resolution status (all reconciled in the master build)
1. **F10** — FOLDED INTO F0 (concurrence lens null; F12 profiler is the diagnostic remnant). Not a gap; the family set is complete.
2. **`dots_results/`** — `master.py` materialises the F0 outputs under `/discovery/` on a discover-fresh run (S3→S4).
3. **`signal_full_records.csv` / `signal_per_day_pnl.jsonl` (stale)** — `master.py` S6 REGENERATES them fresh under the current engine; the stale copies (`746102aae415` / `0910f360a628`) are never carried.
4. **Canonical splitter** — `master.py` S9 auto-split (see §4).
5. **Docs** — `master_guide.md` (run) + `discovery_map.md` (inventory) + `master_stage_spec.md` (build contract) are the current surface; `RUN_STAGE8.md` / `DOT_stage8_program_map.md` / `stage8.py` are retired (§7e).
