# DOT MASTER DISCOVERY — QUICK START (2 brain cells, 6am edition)

Two commands, in order: `python rebuild.py` (prep the data), then `python master.py` (run it). That's the whole thing.

--------------------------------------------------------
## STEP 1 — get the data out of MT4
Open MT4. Load the chart/asset you want (e.g. **BTCUSD**).
- **NEW asset?** Set the EA lookback to **65K** once, so it builds that asset's KAMA `.bin` seed. Let it run and export.
- Already done before? Just let it export.

--------------------------------------------------------
## STEP 2 — find the file the EA wrote
It lands here (one file, named after the asset):
```
C:\Users\d\AppData\Roaming\MetaQuotes\Terminal\9303753997FFC7FE093FBA504590C18A\MQL4\Files\<ASSET>_AUTO_EXPORT.csv
```
Example: `BTCUSD_AUTO_EXPORT.csv`

--------------------------------------------------------
## STEP 3 — copy that CSV into the pack's raw\ folder
```
C:\Users\d\Documents\GitHub\DOT\dot_master_discovery\raw\
```
Just drop it in there. Any asset name is fine.

--------------------------------------------------------
## STEP 4 — prep the data
Open a terminal in the pack root (`dot_master_discovery`), run:
```
python rebuild.py
```
It corrects the data, splits it, and drops the parts into `data\`.
**Look for this line:**
```
invariants : PASS
```
If it says PASS -> good, the parts are in `data\`. If it says FAIL or ABORT -> the export is bad; re-export from MT4.

--------------------------------------------------------
## STEP 5 — run the system
Pick ONE:
```
python master.py
```
-> **Discover fresh** on the new data (1-2 DAYS, leave it running). If the PC crashes/reboots, run the SAME command again -- it resumes. See "WHAT ACTUALLY RESUMES" below for exactly what is kept and what is lost.
```
python master.py --book engine\book50_signals.csv
```
-> **Score the ratified book** on this data instead (fast).

--------------------------------------------------------
## STEP 6 — read the answers
Results land in `discovery\`:
- `discovery\master_report.md`  -- the summary, read this first
- `discovery\committed\`        -- the committed-system score and the per-trade table
- `discovery\contenders\`       -- the mechanism head-to-head
- `discovery\family_evidence.csv` -- what each of the 14 families actually produced, with a verdict
- `discovery\selection_*.csv`     -- the selection layer: hygiene, bounds, DepthYield, persistence
- `discovery\wf_*.csv`            -- the walk-forward: splits, per-segment bounds, null arm, rejection checks
- `discovery\cluster_participation_profile.csv` and `reach_*.csv` -- depth and reach measurements

On the ORIGINAL US30 baseline you'll see a quiet line: `US30 baseline canary: $92,347 / 2,698 tr -- engine intact`. On any other data you just get the numbers -- that's normal (different data, different numbers).

--------------------------------------------------------
## THE ONLY DECISION YOU EVER MAKE
- `python master.py`                                  -> DISCOVER on new data (slow)
- `python master.py --book engine\book50_signals.csv` -> CHECK/score the known book (fast)
That's it.

--------------------------------------------------------
## 2 THINGS THAT CAN GO WRONG

1. Top of the output says **DRIFT** instead of a row of **OK**s
   -> STOP. A locked file got changed/corrupted. Don't use the result. (It refuses to run anyway.) Tell Ticky.
2. It says `python` is not recognised
   -> try `python3` instead of `python`. Same command otherwise.

--------------------------------------------------------
## HANDY (only if you care)
- `python rebuild.py --in D:\path\to\SOME_EXPORT.csv`  = prep a specific file (skip the raw\ folder)
- `python master.py --stage S8`   = skip everything, just re-score (fast check)
- valid `--stage` values, in run order: `S0 S1 S2 S3 S3B S4 S5 S6 S5B S5C S7 S8 S8B S9`
  - `S3`  = the 1-2 day family discovery scan (the long pole; only runs on the no-book path)
  - `S3B` = per-family evidence review + the D2D gate measurement
  - `S5B` = the selection layer (hygiene, bounds, DepthYield, persistence)
  - `S5C` = the walk-forward on the selection process (splits, embargo, null arm, attestation)
  - `S8B` = cluster participation + reach
- `python master.py --data D:\somewhere`  = use a different data folder
- `--chunk-mb 9` = auto-cuts big files into <=9MB pieces so you can upload them without splitting by hand (already the default; both scripts use it)

Full version: `master_guide.md` (same folder).

--------------------------------------------------------
## WHAT THE FULL DISCOVERY SCAN ACTUALLY DOES
Running `python master.py` with NO `--book` is the real scan. In order it will:
1. ingest and validate your data (S0-S2)
2. run all 13 family scanners -- **this is the 1-2 day part** (S3)
3. review what each family produced and measure the D2D gate (S3B)
4. unify and filter to candidates (S4-S6)
5. run the selection layer and the walk-forward on it (S5B, S5C)
6. score contenders and the committed system (S7, S8, S8B)
7. write `discovery\master_report.md` (S9)

--------------------------------------------------------
## WHAT ACTUALLY RESUMES (read this before you commit two days)

**Between stages:** every stage writes a `.done` marker. A completed stage is never re-run.

**Inside S3, the 1-2 day stage:** each of the 10 in-process families writes its own CSV **atomically** (temp file -> fsync -> rename) and then a `.done` marker holding that CSV's sha256. On restart the orchestrator re-reads every family whose CSV matches its marker and re-scans only the rest. A CSV that was half-written when the power went is caught by the sha mismatch and re-run rather than trusted.

**True worst-case loss if the machine dies at the worst possible moment:**

| what | resumes? | worst case lost |
|---|---|---|
| completed stages (S0-S2, S3B, S5B, ...) | yes | nothing |
| completed families inside S3 | yes, read back from disk | nothing |
| the family that was mid-scan | no | **that one family's scan** |
| F13 (single-variable extremes) | yes, per shard | one shard |
| F1 parallel runner | yes, per chunk | one chunk |
| F2-F9, F11 | all-or-nothing per family | that family only |

So the honest answer: **you lose at most one family's worth of work, not the stage.** On the measured proof scope the slowest family was ~35s; on the full scope expect hours, so it is still worth not killing a run casually.

--------------------------------------------------------
## HOW MANY WORKERS? (`--workers`, default 2)

`--workers` controls how many of the 10 discovery families run at once in S3. **Each worker loads its own copy of the data**, so memory is the limit, not cores.

| workers | roughly resident | verdict on an 8 GB machine |
|---|---|---|
| 1 | ~0.7 GB | always safe, slowest |
| **2 (default)** | **~1.5 GB** | **safe, recommended** |
| 3 | ~2.2 GB | usually fine |
| 6 | ~4.4 GB | risky with Process Lasso and a browser open |
| 10 | ~7.2 GB | **will probably be killed by Windows** |

Measured on the 177,251-row dataset: ~733 MB per worker once thresholds are built. The default is deliberately 2, not your core count — raise it only if you can watch memory.

**If a worker is killed for memory**, the run does NOT silently hang: the parent prints `*** A WORKER PROCESS DIED WITHOUT RAISING ***`, keeps every family already finished, and completes the rest one at a time. You lose no completed work.

**How to tell a working run from a hung one:** S3 prints a heartbeat line every 60 seconds while a family is running, plus `[family i of N]` with a running ETA. If you see nothing for several minutes, it is genuinely stuck.

That's it, Animal. Two commands. One decision. Sleep.
