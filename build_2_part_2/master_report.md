# DOT Master Report — US30 (sealed baseline)

## 1. Ingest attestation
- files: stitched_full.csv
- shape: 177,251 rows × 172 cols · range 2026.01.19 15:49 → 2026.07.21 17:09
- path: generic concatenate+validate · invariants: PASS

## 2. Sacred parity (byte-lock)
- `dots_thresholds.py` `518862bf19fb` OK
- `wf.py` `793e6e5f8d9a` OK
- `core.py` `6530e2508b17` OK
- `portfolio_simulation_engine.py` `bb498eb13ce3` OK
- `conviction.py` `27af7acee824` OK

## 3. Component build-up / contenders
| id | contender | net | Δ | WR | PF | daily wd | daily mDD | folds+ | min-PF | OOS PF | OOS net |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 | Flat book (1-lot, no conviction/gaps) | $60975 | +60975 | 91.3 | 4.65 | -547.0 | -698.7 | 6/6 | 4.0 | 5.09 | $18391 |
| C1 | + S.20 conviction (Hurst/recentFB longs) | $75981 | +15006 | 91.3 | 5.07 | -639.1 | -747.2 | 6/6 | 4.26 | 5.78 | $24031 |
| C2 | + S.20 gap-singles (Hurst-gap, FB-gap) | $95267 | +19286 | 90.9 | 5.0 | -565.3 | -673.4 | 6/6 | 4.01 | 5.42 | $28851 |
| C3 | + S.21 D2D-conviction (2x both dir) | $96622 | +1355 | 90.9 | 5.05 | -565.3 | -673.4 | 6/6 | 4.04 | 5.49 | $29298 |
| C4 | + S.21 D2D-gap (flat 2-lot) = FULL | $98205 | +1583 | 90.9 | 5.07 | -565.3 | -999.9 | 6/6 | 4.08 | 5.54 | $29602 |
| C5 | sizing variant (conviction-off, gaps-on) | $81858 | +20883 | 90.9 | 4.69 | -473.2 | -922.4 | 6/6 | 3.84 | 4.92 | $23515 |

## 4. Committed-system headline
- book: FROZEN ratified book (book50_signals.csv)
- **net $98205 | 3057 tr | WR 90.9% | PF 5.07 | daily wd -565.3 | daily mDD -999.9 | 6/6 folds min-PF 4.08 | OOS PF 5.54 | OOS net $29602**

## 5. Per-family coverage
- **measured verdicts (S3B, `family_evidence.csv`)**: DIAGNOSTIC 1, FUSED INTO F0 1, INSUFFICIENT-EVIDENCE 10, SELECTABLE 2
  - F0: SELECTABLE — measured from the committed book executed-trade table on this dataset
  - F1: SELECTABLE — measured from the committed book executed-trade table on this dataset
  - F2: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F3: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F4: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F5: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F6: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F7: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F8: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F9: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F10: FUSED INTO F0 — not a separate family; concurrence lens fused into F0, F12 is the diagnostic remnant
  - F11: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F12: INSUFFICIENT-EVIDENCE — no results file exists on any window; S3 discovery has not been run for this family on this dataset
  - F13: DIAGNOSTIC — negative SETTLED for F13 stated claim (single variable at an extreme as a standalone tradeable edge): its own scan reports 0 stars / 0 candidates, and

## 6. S8B cluster-participation profile
- output: `cluster_participation_profile.csv` — 2988 rows (249 conditions x basis x N x grid cell)
- eligible universe: 103,214 bars | eligibility: (ADX_Value >= 15) & (Volume > 50) & post-warmup; Volume==0 and Friday-close exclusions OUT
- **SCOPE LIMIT: the vocabulary is SINGLE CONDITIONS; the book's signals are TRIPLES. A single condition's profile is not a signal's value; do not select a book directly from this CSV. It is an input to selection, not a selection rule.**
- **BASIS-3 BOUNDARY: the thrust label is forward-looking by construction and can never become a live gate or entry condition.**
- basis-3 overlap with size>=5 book cluster spans:
  - W=15 K=p85 E=p75 N=5: 142/4744 episodes intersect = 3.0% | thrust bars inside deep clusters 4.0% | deep-cluster bars that are thrust 15.2%
  - W=15 K=p85 E=p75 N=10: 132/4154 episodes intersect = 3.2% | thrust bars inside deep clusters 4.1% | deep-cluster bars that are thrust 17.9%
  - W=15 K=p90 E=p75 N=5: 105/3981 episodes intersect = 2.6% | thrust bars inside deep clusters 3.7% | deep-cluster bars that are thrust 9.8%
  - W=15 K=p90 E=p75 N=10: 99/3507 episodes intersect = 2.8% | thrust bars inside deep clusters 3.6% | deep-cluster bars that are thrust 11.4%
  - W=30 K=p85 E=p75 N=5: 103/3302 episodes intersect = 3.1% | thrust bars inside deep clusters 3.6% | deep-cluster bars that are thrust 13.6%
  - W=30 K=p85 E=p75 N=10: 100/2679 episodes intersect = 3.7% | thrust bars inside deep clusters 3.5% | deep-cluster bars that are thrust 15.2%
  - W=30 K=p90 E=p75 N=5: 78/2808 episodes intersect = 2.8% | thrust bars inside deep clusters 3.6% | deep-cluster bars that are thrust 9.9%
  - W=30 K=p90 E=p75 N=10: 74/2271 episodes intersect = 3.3% | thrust bars inside deep clusters 3.5% | deep-cluster bars that are thrust 11.3%

## 7. S5B selection layer — §H decisions and §C constraint references
- vocabulary: 249 total, 7 dead, 4 exact-duplicate pairs, 238 effective (identity domain = eligible universe, 103,214 bars)
- incumbent reference DepthYield at N=5 S=5: LONG 0.02503 / SHORT 0.00757 (pair, never summed)
- constraint references (segment 2026.01..2026.07): F_max 3.869, kappa 1.252, C_max -1429.1, absolute survival PASS at worst day -565.3
- H.3 within direction: LONG PASS (7/7 buckets); SHORT PASS (6/7 buckets)
- submodularity: NOT established; greedy is used as a heuristic and the (1-1/e) bound is NOT claimed anywhere
- NO DIRECTIONAL TARGET: no floor, quota, target, minimum signal count or reserved allocation exists in selection.py; each direction stops on its own marginal gain or its own binding constraint and may terminate with zero signals
- SELECTION NOT RUN: no candidates.csv on this run. S3 discovery has never been executed, so the candidate pool does not exist. The objective, search, constraints and hygiene are built and unit-exercised against the committed book as a fixture; end-to-end selection is UNEXERCISED PENDING S3.
- fixture exhaustive-vs-greedy LONG: greedy 0.022131 = 88.41% of enumerated optimum 0.025033 (optimum at size 37, pair escapes 2) — INCUMBENT FIXTURE, NOT A BOOK SELECTION
- fixture exhaustive-vs-greedy SHORT: greedy 0.012295 = 100.0% of enumerated optimum 0.012295 (optimum at size 2, pair escapes 1) — INCUMBENT FIXTURE, NOT A BOOK SELECTION
- stopping rule = 'no addition of size <= 2 improves', direction-agnostic, evaluated at every potential termination point; escape looks ahead 2 elements and a plateau escapable only by a simultaneous 3+ addition still halts
- CoFire (pre-jar qualifying, engine entry_ok): all-pairs 0.02714, same-direction 0.044685, cross-direction 0.0 (exactly zero by construction: the D2D gate makes long and short qualifying masks disjoint)
- G.2: 100 pairs at |r|>=0.70 of 29161, median |r| 0.0332, 126 components carry 90% variance, 175 communities; signed dependence 14469 positive / 14692 negative (PRDS fails -> BY not BH)
- domain bridging on incumbent F0 triples: 47 of 48 span >= 2 domains (retrospective fixture; removes nothing)
- Coverage (incumbent, W=15 K=p85 E=p75 N=5) = 1.707% of 4744 thrust episodes

## 8. Stale-artifact note
- signal_full_records / signal_per_day_pnl: regenerated fresh this run (S6) — stale 746102aae415 / 0910f360a628 NOT inherited

