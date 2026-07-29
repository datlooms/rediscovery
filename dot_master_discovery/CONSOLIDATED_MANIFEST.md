# dot_master_discovery — consolidated manifest

Total files: 102 — NEW 3, MODIFIED 6, UNCHANGED FROM MAIN 93 (of which 60 are F13 shard files).

| file | sha256[:12] | status | role |
|---|---|---|---|
| `QUICK_START.md` | `a72909479618` | MODIFIED | operator quick start, runnable standalone |
| `_packutil.py` | `6c8f2a3a7d04` | UNCHANGED FROM MAIN | shared helpers (natural-sort, auto-split); no import side effects |
| `discovery_map.md` | `f306f398e0ee` | MODIFIED | file inventory + canonical/retired status |
| `discovery_results/results_F13_single_variable_extremes.csv` | `ca7aafdb7f80` | UNCHANGED FROM MAIN | discovery output / support file |
| `engine/analysis_engine.py` | `d9acd1ddc3fe` | UNCHANGED FROM MAIN | F0 tic-proof scorer core |
| `engine/book50_signals.csv` | `e86a52244501` | UNCHANGED FROM MAIN | the frozen ratified 50-signal book |
| `engine/cluster_profiler.py` | `070bb2aa7aaa` | MODIFIED | S8B cluster-participation profiler + reach (spec D) |
| `engine/conviction.py` | `27af7acee824` | UNCHANGED FROM MAIN | SACRED conviction/gap builder |
| `engine/core.py` | `6530e2508b17` | UNCHANGED FROM MAIN | SACRED reconstruction pipeline |
| `engine/dots_thresholds.py` | `518862bf19fb` | UNCHANGED FROM MAIN | SACRED oracle — mechanism D thresholds |
| `engine/family_evidence.py` | `f27ec344125f` | NEW | S3B family evidence review + D2D gate measurement (spec A, E.1) |
| `engine/portfolio_simulation_engine.py` | `bb498eb13ce3` | UNCHANGED FROM MAIN | SACRED ratified trade engine |
| `engine/run_full_analysis.py` | `886ea8ca17fa` | UNCHANGED FROM MAIN | F0 analysis driver (S6 regen) |
| `engine/score_book50.py` | `1bdf9ceec75f` | MODIFIED | flat BOOK-50 scorer |
| `engine/score_g.py` | `3129aecec634` | UNCHANGED FROM MAIN | book construction + option-map scorer |
| `engine/selection.py` | `52c194f6b303` | NEW | S5B selection layer (spec C, D.1-D.2, G, H) |
| `engine/wf.py` | `793e6e5f8d9a` | UNCHANGED FROM MAIN | SACRED walk-forward folds (month-literal; never imported by selection) |
| `engine/wf_selection.py` | `00cded3e2119` | NEW | S5C walk-forward on the selection process (spec I) |
| `master.py` | `2c11b70871c4` | MODIFIED | SINGLE ENTRY POINT — orchestrates S0-S9 incl. S3B/S5B/S5C/S8B |
| `master_guide.md` | `88a814f96554` | MODIFIED | full operator guide: every stage, every output |
| `orchestrator/discovery_orchestrator.py` | `31165e9a17df` | UNCHANGED FROM MAIN | drives the family scanners (S3) |
| `raw/.gitkeep` | `e3b0c44298fc` | UNCHANGED FROM MAIN | drop the raw EA export here |
| `raw/readme.txt` | `bbde30c0aa32` | UNCHANGED FROM MAIN | drop the raw EA export here |
| `rebuild.py` | `609580a417fe` | UNCHANGED FROM MAIN | data-prep: raw EA export -> validated 171-col baseline -> data/ |
| `reference/equiDOT_discovery_blueprint.md` | `423e6e60c38e` | UNCHANGED FROM MAIN | design reference doc |
| `reference/equiDOT_discovery_pattern_map.md` | `1a7a9d423381` | UNCHANGED FROM MAIN | design reference doc |
| `scanners/concurrence_profiler.py` | `554019e93069` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/conditional_interaction.py` | `7908ed0c5fbc` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/cross_variable_structure.py` | `5594fa73a7d3` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/divergence_nonconfirm.py` | `a95c521cd55c` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/f0_to_schema.py` | `f878d3b46c8b` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/mean_reversion.py` | `868bc7edf5fe` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/persistence_autocorr.py` | `cd3afbfe6994` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/rolling_leadlag.py` | `08848774ca1c` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/run_f0_full.py` | `8a8a276cfbef` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/run_f1_parallel.py` | `230427fcbd04` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/sequential_temporal.py` | `cda5b7459077` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/session_temporal.py` | `2e5f1703aaa2` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/single_variable_extremes.py` | `37e3a9075aea` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/state_transition.py` | `8cb42c9d9891` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/threshold_crossing.py` | `147deb44d1b5` | UNCHANGED FROM MAIN | family scanner (F0-F13) |
| `scanners/triple_convergence_and_d2ddir.py` | `5ed2221e5339` | UNCHANGED FROM MAIN | family scanner (F0-F13) |

60 `discovery_results/_f13_shards/shard_*.csv|.done` files: all UNCHANGED FROM MAIN, F13 crash-resume intermediates.
