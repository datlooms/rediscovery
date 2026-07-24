# master.py — Operator Guide

## Document index — which doc to open

| Document | What it's for |
|---|---|
| **master_guide.md** (this file) | **How to run it** — data-prep (`rebuild.py`) + the single entry point (`master.py`), every stage S0–S9, every output, `--book` vs no-book, resume, auto-split. Start here. |
| **discovery_map.md** | The script/file **inventory** — every file, sha256, canonical-vs-retired, the carry/drop manifest, project-vs-local reconciliation. |
| **master_stage_spec.md** | The **build contract** — the §1–§10 design spec `master.py` was built from (historical reference). |

*Retired (do not use as current): `RUN_STAGE8.md`, `DOT_stage8_program_map.md`, `stage8.py` — the pre-master multi-script pack workflow, superseded by `master.py` + this guide.*

## Preparing data — `rebuild.py`

Before `master.py`, prep a raw EA export into a validated baseline:

```
python rebuild.py                      # uses the newest CSV in raw/
python rebuild.py --in D:\path\export.csv   # or a specific file
```

`rebuild.py` reads the raw EA export (`<ASSET>_AUTO_EXPORT.csv` dropped in `raw/`), runs the reconstruction, validates the 172-col contract (Time + 171 features, time-strict / 0-dup / 0-NaN), **clears any old CSVs from `data/`**, and auto-splits the corrected output into `≤9MB` parts (header in part1 only, headerless continuation — the exact convention `master.py` S0 re-ingests) written straight into `data/`. It prints rows / cols / range / `invariants PASS` / the part list, and aborts loudly on any schema failure. It wires in `core.py`'s feature functions (`families`, `compute_new45`) for the recompute path; a fixed-EA export is already export=live-correct, so it is validated and split (consumed, not re-shifted — the EA's `.bin` seed supplied the warm-start).

One command runs the whole DOT pipeline: ingest a market export → compute thresholds → discover patterns → filter → rank the mechanism choices → score the committed system → write one report. `master.py` orchestrates the ratified scripts; it never rewrites them.

## The one command

```
python master.py --book book50_signals.csv      # REPLAY + VERIFY a ratified book
python master.py                                 # DISCOVER a fresh book from the data
```

- **With `--book`** the master replays the supplied frozen ratified book and scores it. This is the verification path. On the sealed US30 baseline it prints `net $92,347 / 2,698 tr → REPRODUCED`.
- **Without `--book`** the master runs full discovery and assembles a *fresh* book from the discovered candidates by the survival-first rule, then scores that. It is flagged as a new discovered book.

The only branch in the whole program is "was a book supplied?" — never "is this US30?". Stages S0–S7 are pure geometry (percentile-relative distributional patterns) and know nothing about the asset.

## Options

| flag | default | meaning |
|---|---|---|
| `--data DIR` | `/data` (falls back to the pack `data/`) | where the EA CSV export(s) live |
| `--out DIR` | `discovery/` | where all outputs land |
| `--book FILE` | *(none)* | supply a frozen ratified book to replay+verify; omit to discover fresh |
| `--workers N` | 12 (capped) | parallel worker bound |
| `--stage S0..S9` | *(all)* | run/resume a single stage; valid values are S0, S1, S2, S3, S3B, S4, S5, S6, S5B, S5C, S7, S8, S8B, S9 |
| `--market-label STR` | `US30 (sealed baseline)` | report tag only — never changes logic |
| `--chunk-mb N` | 9 | auto-split target size |

## What each stage does and where output lands

Everything lands under `--out` (default `discovery/`):

```
discovery/
  raw/          per-family survivor scans (discover-fresh path)
  results/      discovery_master.csv (unified 14-col) + candidates.csv (gate survivors)
  scored/       fresh signal_full_records + signal_per_day_pnl (regenerated, never inherited)
  contenders/   contenders.csv — the mechanism head-to-head
  committed/    committed_score.txt (+ discovered_book.csv on the no-book path)
  master_report.md
  .markers/     one .done per completed stage/family (checkpoint/resume)
```

- **S0 Ingest & validate.** Reads every `*.csv` in `--data`, detects header vs headerless continuation parts, concatenates in filename order, and asserts the contract: `Time` + 171 features, time strictly increasing, zero duplicate rows, zero NaN. A raw 256-col export is routed through `core.py` first (S0a); a clean 171-col EA drop ingests directly. Any violation aborts loudly and says why. The attestation (rows × cols, range, invariants) goes into the report.
- **S1 Adaptive thresholds.** The oracle (`dots_thresholds.py`) computes per-bar hi/lo percentiles and structural gates. Its sha256 is printed every run — that is the export=live parity check.
- **S2 Pool & anchors.** Builds the scannable condition vocabulary, the `ST_Flip` anchor, and the warm-up floor.
- **S3 Family discovery** *(discover-fresh path only; the long pole)*. Delegates to the ratified `discovery_orchestrator` to run all 13 families (F0 committed, F1–F13). Results land in `results/`. Crash-resumable per family.
- **S3B Per-family evidence review + D2D gate measurement.** One evidence row per family F0–F13 grounded in the actual output files, with depth participation across the three S8B bases, cross-family co-firing, and a verdict per family — `INSUFFICIENT-EVIDENCE` is a permitted and expected verdict where no output exists on this dataset. Also runs the four-part D2D gate measurement (baseline, inverted, per-direction ungated). → `family_evidence.csv`, `cross_family_cofiring.csv`, `d2d_gate_measurement.csv`.
- **S4 Schema unify.** Collates the family results into `results/discovery_master.csv` (common 14-column schema).
- **S5 Candidate filter.** Keeps rows passing the auditor-validated gate `trades ≥ 30 AND folds_plus ≥ 4 AND agg_pf ≥ 2.0`, carrying worst-day for survival-first ranking → `results/candidates.csv`.
- **S6 Full-field scoring (regen).** Regenerates `signal_full_records.csv` + `signal_per_day_pnl.jsonl` *fresh* under the current engine. The stale pre-S.19/S.20/D2D copies are never inherited.
- **S5B Selection layer.** Re-derives §G.1 vocabulary hygiene (dead conditions excluded *before* equivalence classes; domain = the eligible universe), the §C.2 constraint references (F_max, T_max via a per-segment permutation null, C_max, absolute survival), the §C.1 DepthYield grid as a per-direction pair, §H.3 persistence within direction, and the exhaustive-vs-greedy fixture on both directions. → `selection_*.csv`.
- **S5C Walk-forward on the selection process.** Derives the split count from an executability floor (≥60 post-warmup trading days AND ≥3 monthly buckets), applies a 1,440-bar embargo, re-derives every bound inside each training segment, asserts oracle causality over all threshold keys, runs the per-split random-triple null through a single-touch guard, and writes an append-only attestation trail. → `wf_*.csv`, `.wf_attest.jsonl`.
- **S7 Contender head-to-head.** Scores C0 (flat) → C4 (full) plus a sizing variant through the ratified engine, each with net / WR / PF / daily worst-day / daily mDD / 6-fold min-PF / OOS, and the delta each mechanism buys. This validates every committed choice on the data itself → `contenders/contenders.csv`.
- **S8 Committed-system score.** With `--book`: loads that book, scores it, prints the `REPRODUCED / MISMATCH` self-check (does not re-select). Without `--book`: assembles a fresh book from `candidates.csv` (survival-first rank → overlap-dedup → cap) and scores it. → `committed/committed_score.txt`.
- **S8B Cluster-participation profile + reach.** Profiles every candidate condition against three cluster bases and emits the §D reach measurements. → `cluster_participation_profile.csv`, `reach_*.csv`.
- **S9 Report & split.** Writes `master_report.md` and auto-splits every oversized output.

## How to read the report

`master_report.md` has: (1) ingest attestation, (2) the sacred sha registry, (3) the C0→C4 contender build-up with each delta, (4) the committed headline (and the BOOK-50 REPRODUCED verdict on the baseline), (5) per-family coverage, (6) the stale-artifact regeneration note. The headline line is the bottom line; the contender table shows exactly how each mechanism earned its place.

## Dropping in a new market

1. Put the new market's EA export (one big CSV or N chunks, any filename) in `--data`. It must carry the same 171-feature schema.
2. Run `python master.py --market-label BTC` (no `--book`) to discover and score a fresh book for that market, or `--book <ratified_book.csv>` to replay a ratified book against it.
3. The oracle self-calibrates its percentiles to the new data — nothing in the code is US30-specific.

> **Known-and-accepted:** the no-book / new-market book-selection rule (S8 discover-fresh branch) is *designed but not yet data-validated* — its first live use is the first fresh-discovery run on a real non-baseline export. The `--book` frozen-book path is fully ratified and simply replays the supplied book.

## Resuming after a crash

Every stage writes a `.done` marker recording the input sha. Re-running the same command skips any stage whose `.done` exists and whose inputs are unchanged, and resumes the rest. A 1–2 day discovery run survives interruption: `python master.py` again (or `--stage S3`) picks up where it stopped. If the input data changes, markers invalidate automatically and the affected stages re-run.

## Sacred files (never edited by the master)

`dots_thresholds.py`, `wf.py`, `core.py`, `portfolio_simulation_engine.py`, `conviction.py` are byte-locked. The master prints all five shas at startup and aborts on any drift. No stage computes a threshold except through the oracle; no stage opens a trade except through the ratified engine.

## Coding conventions (standing rules for all pack scripts)

- **All file I/O uses `encoding='utf-8'`** — Windows defaults to cp1252 and crashes on non-ASCII (arrows `→`, `×`, `≥`). Every `open(..., 'w'/'a')` and every text `open(..., 'r')` in the pack carries `encoding='utf-8'`. Binary opens (`'rb'`/`'wb'`) are exempt.
- LF line endings; no inline comments.

## Changelog

- **2026-07-18** — Fixed `rebuild.py` crash: it borrowed helpers via `import master`, which coupled it to master's startup and could leave `_natkey`/`split_output` unresolved (AttributeError at the split step). Moved both helpers into a side-effect-free **`_packutil.py`** imported by both `rebuild.py` and `master.py`; importing rebuild's deps no longer triggers master's sequence. Verified full round-trip: rebuild → data/ parts → master ingests → $92,347. shas: rebuild `609580a417fe`, master `db8957587844`, _packutil `6c8f2a3a7d04`.

- **2026-07-18** — Added **`rebuild.py`** (data-prep): raw EA export → validated 171-col baseline → auto-split into `data/`. Wires in `core.py`'s feature functions. Also fixed `master.py` S0 to re-ingest the split convention (header-in-part1 + headerless continuation) and sort parts by **natural (numeric) order** so >9 parts reassemble correctly; split output is zero-padded. sha now `ec1bd550bfba`.

- **2026-07-18** — `master.py` patched for Windows UTF-8 file I/O (no logic change); re-verified the committed system reproduces **$92,347 / 2,698 tr** on Windows. sha now `b18f554953fd` (was the Auditor-ratified `9f124a9160c8`).
- **2026-07-18** — Program renamed `stage8_discovery` → **`dot_master_discovery`** ("DOT Master Discovery"). Directory + all docs updated; sacred files byte-identical (their historical "Stage-8" phase comments are preserved under byte-lock).
- **2026-07-18** — S8 committed-score verdict softened: the canonical check is now a quiet, neutral **US30 baseline canary** that fires only on the recognized sealed baseline (`book50_signals.csv` and trades==2,698 & net==$92,347). All other data (SP500, US100, fresh exports, other books) prints the headline numbers only — no `REPRODUCED`/`MISMATCH`/verdict line. Different data producing different numbers is the expected outcome.
