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
-> **Discover fresh** on the new data (1-2 DAYS, leave it running). If the PC crashes/reboots, run the SAME command again -- it resumes, does NOT start over.
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

It checkpoints after every stage. If the machine reboots, run the same command again and it resumes.

That's it, Animal. Two commands. One decision. Sleep.
