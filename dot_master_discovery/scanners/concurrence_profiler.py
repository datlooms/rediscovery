import os
import sys
import shutil

# Self-bootstrap so this runs DIRECTLY (python scanners/concurrence_profiler.py)
# rather than through master.py — multiprocessing on Windows (spawn) re-imports
# the main module, which must be THIS file, not the launcher's runpy context.
# Idempotent: safe to re-run in spawned children. Resolves engine/ imports and
# the CWD-relative baseline exactly as the launcher does. (Same pattern as the
# ratified run_f1_parallel.py.)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ('engine', 'scanners', 'orchestrator'):
    _p = os.path.join(_ROOT, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(_ROOT)
for _n in os.listdir(os.path.join(_ROOT, 'data')):
    if _n.endswith('.csv') and not os.path.exists(os.path.join(_ROOT, _n)):
        try:
            os.symlink(os.path.join(_ROOT, 'data', _n), os.path.join(_ROOT, _n))
        except (OSError, NotImplementedError):
            shutil.copy2(os.path.join(_ROOT, 'data', _n), os.path.join(_ROOT, _n))

import time
import math
import gc
from multiprocessing import Pool, Value
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf
import sequential_temporal as seq

# ═══════════════════════════════════════════════════════════════
#  equiDOT — FAMILY 12: RAW VARIABLE CONCURRENCE PROFILER
#
#  THIS SCRIPT IS A MEASUREMENT, NOT A SELECTION. It prunes nothing, concludes
#  nothing, recommends nothing. It emits seven tables; the QRA reads them.
#
#  The question: does raw stacking DEPTH predict outcome? The triplet (k=3) is
#  an arbitrary imposition; a frozen signal list encodes the regime that made
#  it. Here there is no triplet, no signal list, no survivor filter in the
#  PRIMARY view — only the 249 ratified scan conditions, direction-aligned.
#
#  DEPTH RANGE. F10 was ruled degenerate over bands k=1..10. Measured per-bar
#  co-fire distribution (post-warmup): LONG median 27, p95 48, max 81; SHORT
#  median 23, p95 40, max 61. Every band tested sat at or below the 5th
#  percentile; k>=10 captures ~100% of bars. Degeneracy was guaranteed by
#  construction, not by the phenomenon. The outcome map here sweeps the
#  DISCRIMINATING range k = 15..81 step 1 — the band that was never entered,
#  carried all the way to LONG's measured maximum depth (81). Truncating the top
#  of the range would be the F10 error in miniature: the deepest stacks are
#  exactly where a monotone depth->outcome relation should be strongest. SHORT's
#  measured maximum is 61, so k>61 emits empty SHORT cells — correct and
#  expected; empty cells carry the full key set.
#
#  Alignment (per the F10 rule):
#     long-aligned  = FEAT_':hi' + equality '==v' with v > 0
#     short-aligned = FEAT_':lo' + equality '==v' with v < 0
#     '==0' neutral conditions excluded from the directional tally
#
#  Per-fold columns on the outcome map: fold1..fold6 are in wf.FOLDS order —
#  fold1 Jan(19-31), fold2 Feb, fold3 Mar, fold4 Apr, fold5 May, fold6 Jun(1-25).
#  fold{i}_pf answers whether the DEPTH -> OUTCOME relation held INSIDE each
#  month (a single dominant fold can manufacture apparent monotonicity in the
#  aggregate); fold{i}_trades exposes folds too thin to be meaningful.
#
#  STAGE ORDER (regime labels are computed FIRST so every table can be tagged):
#    1 depth -> 2 events -> 3 entry_order -> 4 outcome_map (RATIFIED, untouched)
#    -> 6 regimes -> 5 composition (regime-aware) -> 5b category_depth
#    -> 7 d2d_flips -> 8 null_baseline.
#
#  WHY REGIME-AWARE COMPOSITION: measured on the F0 export, LONG and SHORT share
#  97.4% of VARIABLES and 94.7% of mirrored conditions, but only 3.3% of mirrored
#  TRIPLETS survive (2.5% among the six-of-six persisters) — a 28x gap. The
#  variables mirror; the COMBINATIONS do not. The triplet is the wrong unit. So
#  stage 5 no longer computes one global clustering (which averages regimes
#  together and hides the phenomenon) but one clustering per (direction x regime),
#  plus a variable-level view with hi/lo collapsed and a cross-regime stability
#  measure. The question is now: how do variables cluster freely, and does that
#  clustering change by regime?
#
#  STAGE 5b CAUSALITY: cluster membership there DECIDES WHICH CONDITIONS COUNT
#  toward category depth, so it GATES ENTRIES and is a signal input. It is fit
#  ONCE on the leading burn-in window (fold 1) and applied forward-only, using the
#  CAUSAL regime labels; the burn-in fold is excluded from scoring. Stage 5's own
#  clustering gates nothing and may therefore use the full-sample descriptive
#  labels (every such row is flagged causal=False).
#
#  STAGE 8 NULL: circular shift of the depth arrays (preserves autocorrelation,
#  event shape, marginal distribution; destroys alignment with price). NOT an
#  i.i.d. shuffle, which would destroy event structure and give an unfairly weak
#  null. Shifting depth removes information; it cannot import future information.
#
#  Contract: oracle-only masks (engine.condition_mask via the ratified
#  sequential_temporal.build_condition_pool 249-pool builder); ZERO independent
#  threshold computation; ZERO TM reconstruction (engine.run_portfolio is the
#  sole trade path); scoring on the locked wf 6-fold, survival-first;
#  worst_day_usd RAW at lot 1.0 (ranking axis, never hard-gated). D2D is a
#  SEARCHED dimension (confirm / invert / exempt) via the sanctioned
#  column-reconstruction (snapshot / feed / restore in finally) — D2D is
#  gate-only in the engine (L79 read, L89 gate), so the swap cannot reach
#  TM / pnl / direction.
#
#  CLUSTERING AND THE CAUSAL BOUNDARY (stages 5 and 6). No taxonomy is imposed
#  or inherited (the 8 "market structures" in the 76-signal dictionary are a
#  human taxonomy of SIGNAL types and are NOT used here). n_clusters is chosen
#  by an objective criterion (silhouette; BIC reported) and the full sweep table
#  is emitted so the choice is inspectable. Two distinct label sets exist:
#
#    DESCRIPTIVE (non-causal, gates NOTHING): the stage-6 n-sweep table
#    (silhouette / BIC / RSS / chosen), cluster_validation (bars, share,
#    mean_run_len_bars, n_runs) and fold_occupancy; and all of stage 5
#    (co-occurrence membership + event composition vectors). These are fitted on
#    the full post-warmup sample and admit no trade. They are reporting only.
#
#    CAUSAL (gates entries): the regime labels used by the regime_outcome rows.
#    Option (a) of the correction: z-score mu/sigma AND k-means centroids are fit
#    ONCE on a leading burn-in window (fold 1, Jan(19-31), post-warmup) and labels
#    are then assigned FORWARD-ONLY to later bars by nearest-centroid. No future
#    bar influences any label that admits a trade at bar t. Fold 1 is the burn-in
#    and is therefore in-sample: it is EXCLUDED from regime_outcome scoring, so
#    only folds 2-6 (Feb..Jun) are scoreable. Each regime_outcome row carries a
#    folds_scored column naming the folds that actually contributed trades.
#    Chosen over (b) expanding-window refit because one centroid set keeps cluster
#    identity stable across folds; refitting permutes cluster IDs at each boundary
#    and would make "cluster c" incomparable between months.
#
#  DEPENDENCY: k-means and silhouette are implemented in numpy below. Choice
#  (b) of the brief — the operator's environment has only numpy 2.4.4 and
#  pandas 3.0.2 (Python 3.12.3), so NO new dependency is introduced and there
#  is nothing to pip install.
#
#  Run DIRECTLY (not via master.py):
#     python scanners\concurrence_profiler.py           (full)
#     python scanners\concurrence_profiler.py proof      (bounded + parity)
#     python scanners\concurrence_profiler.py 16         (full, 16 workers)
# ═══════════════════════════════════════════════════════════════

RESULTS_DIR = 'discovery_results'
SEQ_COL = '__F12DEPTH'
N_WORKERS = 8
PROGRESS_INTERVAL = 30.0
FLUSH = 4

# Outcome-map grid (stage 4): the discriminating band, step 1, fully covered.
K_MIN, K_MAX, K_STEP = 15, 81, 1
DURATIONS = [1, 2, 3, 4, 5, 6, 7, 8]
DIRECTIONS = ['LONG', 'SHORT']
D2D_MODES = ['confirm', 'invert', 'exempt']

# Event onset floors (stage 2): inside the real range, spanning median..p99.
ONSET_FLOORS = [20, 25, 30, 35, 40, 45, 50]

# Stage 5/6 parameters
COMPOSITION_FLOOR = 30
CLUSTER_N_SWEEP = list(range(2, 13))
SIL_SAMPLE = 2000
KMEANS_ITERS = 60
KMEANS_RESTARTS = 4
SEED = 20260710
REGIME_VARS = ['ADX_Value', 'ATR_1M', 'Efficiency_Ratio', 'Micro_Hurst',
               'Micro_FractalDim', 'Micro_VolOfVol', 'Sqz_State', 'RangeOsc_State',
               'AT_Regime_ST', 'AT_Regime_LT', 'Bars_Since_Flip',
               'Trend_Concordance', 'Trend_Conflict']
# Reduced grid for the regime-conditioned outcome map (stage 6), documented.
REGIME_K = [20, 30, 40, 50]
REGIME_DUR = 1

# Stage 7 parameters
FLIP_LOOKBACK = 25
COUNTER_FLOOR = 30
COUNTER_MARGIN = 5

# ── Amendment-2 constants ────────────────────────────────────────────────
# Stage 5 (per-regime composition)
MIN_STACK_BARS = 500      # a (direction x regime) cell below this is EMITTED with
                          # skipped=True and n_bars, never silently omitted.
K_DEEP = 40               # deep-stack threshold, inside the discriminating band
                          # (LONG p90=43, SHORT p90=36), for regime_deep_composition.
TOP_PAIRS_N = 40          # top co-occurring condition pairs emitted per regime.

# Stage 5b (category depth -> outcome). Cluster membership GATES ENTRIES, so it is
# fit causally on the burn-in fold only (see causal_category_membership).
CAT_K_STEP = 2            # step for the marginal per-cluster depth sweep
CAT_DURATIONS = [1, 2, 3, 4]
CAT_MODES = ['confirm', 'invert']
CAT_DOM_K = [20, 30, 40, 50, 60]        # total-depth values for the dominant variant
CAT_DOM_SHARE = [0.30, 0.40, 0.50, 0.60]  # cluster share of the stack
CAT_DOM_DURATIONS = [1, 2]

# Stage 6 extended regime outcome map
REGIME_MODES = ['confirm', 'invert']

# Stage 8 (null baseline). CIRCULAR SHIFT preserves depth autocorrelation, event
# shape and marginal distribution while destroying alignment with price. An
# i.i.d. shuffle would destroy event structure and give an unfairly weak null.
N_PERM = 20
MIN_SHIFT = 5000          # offsets drawn from [MIN_SHIFT, n - MIN_SHIFT]
NULL_K = [20, 30, 40, 50, 60]
NULL_DURATIONS = [1, 2]
NULL_MODES = ['confirm']

_G = {}


# ── small utilities ──────────────────────────────────────────────────────
def _fmt_hms(s):
    s = int(s)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _stamp(stage, msg):
    print(f"[{stage}] {msg}", flush=True)


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def run_lengths(binary):
    # consecutive-run length ending at each bar (1-based); 0 where binary is 0.
    b = binary.astype(np.int64)
    idx = np.arange(len(b))
    reset = np.where(b == 0, idx + 1, 0)
    start = np.maximum.accumulate(reset)
    return np.where(b == 1, idx + 1 - start, 0)


def _depth_quantiles(v):
    # CONSOLE REPORTING ONLY — a description of the depth distribution. It feeds
    # no mask, no level, no entry. The k grid is a fixed documented constant and
    # is never derived from this. (Sorted-index, not np.percentile, so the file
    # contains no percentile call anywhere.)
    s = np.sort(v)
    n = len(s)
    return [int(s[min(int(n * p), n - 1)]) for p in (0.05, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)]


def align_pool(pool):
    long_lbls, short_lbls = [], []
    for lbl in pool:
        feat, thr = lbl.split(':', 1)
        if thr == 'hi':
            long_lbls.append(lbl)
        elif thr == 'lo':
            short_lbls.append(lbl)
        elif thr.startswith('=='):
            v = int(thr[2:])
            if v > 0:
                long_lbls.append(lbl)
            elif v < 0:
                short_lbls.append(lbl)
    return sorted(long_lbls), sorted(short_lbls)


def depth_arrays(pool, long_lbls, short_lbls, d2d):
    dl = np.sum(np.vstack([pool[l] for l in long_lbls]), axis=0).astype(np.int32)
    ds = np.sum(np.vstack([pool[l] for l in short_lbls]), axis=0).astype(np.int32)
    aligned = np.where(d2d == 1, dl, np.where(d2d == -1, ds, 0)).astype(np.int32)
    return dl, ds, aligned


def apply_d2d(df, mode, dir_int, orig):
    if mode == 'confirm':
        df['D2D_Trend_Dir'] = orig
    elif mode == 'invert':
        df['D2D_Trend_Dir'] = -orig
    elif mode == 'exempt':
        df['D2D_Trend_Dir'] = np.full(len(df), dir_int, dtype=orig.dtype)
    else:
        raise ValueError(f"unknown d2d mode '{mode}'")


def score_mask(df, mask, direction, d2d_mode, orig, month, adaptive, structural, warmup):
    # Sole trade path: engine.run_portfolio + the locked wf 6-fold.
    df[SEQ_COL] = mask.astype(int)
    dir_int = 1 if direction == 'LONG' else -1
    apply_d2d(df, d2d_mode, dir_int, orig)
    sig = pd.DataFrame([{'feat_1': SEQ_COL, 'thresh_1': '==1',
                         'feat_2': SEQ_COL, 'thresh_2': '==1',
                         'feat_3': SEQ_COL, 'thresh_3': '==1',
                         'direction': direction}])
    fold_rows, fold_trades = [], []
    for label, mkey in wf.FOLDS:
        td = engine.run_portfolio(df, sig, mask_window=(month == mkey), adaptive=adaptive,
                                  structural=structural, warmup=warmup, verbose=False)
        fold_rows.append(wf.fold_metrics(td, label))
        if len(td):
            fold_trades.append(td)
    all_trades = pd.concat(fold_trades, ignore_index=True) if fold_trades \
        else pd.DataFrame(columns=['pnl', 'exit_time'])
    n = len(all_trades)
    pnls = all_trades['pnl'].values if n else np.array([])
    daily = wf.daily_pnl_points(all_trades)
    daily_usd = wf.points_to_usd(daily['pnl'].values) if len(daily) else np.array([])
    fold_pfs = [r['pf'] for r in fold_rows if r['trades'] > 0]
    pf_base, pf_stress = wf.spread_stress(all_trades)
    out = {'trades': n,
           'WR': round((pnls > 0).sum() / n * 100.0, 1) if n else 0.0,
           'agg_pf': round(wf.pf_from_pnls(pnls), 2),
           'worst_day_usd': round(float(daily_usd.min()), 1) if len(daily_usd) else 0.0,
           'hard_stop_days': int((daily_usd <= -wf.DAILY_LOSS_CEILING_USD).sum()),
           'folds_plus': sum(1 for r in fold_rows if r['total_pnl'] > 0),
           'min_fold_pf': min(fold_pfs) if fold_pfs else 0.0,
           'spread_pf': f"{pf_base}->{pf_stress}"}
    # Per-fold PF and trade counts, in wf.FOLDS order (Jan..Jun). folds_plus says a
    # cell was profitable each fold; these say whether the DEPTH -> OUTCOME relation
    # held each fold. Trade counts expose folds too thin to be meaningful, which an
    # aggregate hides. wf already computed these; they were previously discarded.
    for i, r in enumerate(fold_rows, 1):
        out[f'fold{i}_pf'] = r['pf']
        out[f'fold{i}_trades'] = r['trades']
    return out


def trades_at(df, entry_mask, direction, d2d_mode, orig, adaptive, structural, warmup):
    df[SEQ_COL] = entry_mask.astype(int)
    dir_int = 1 if direction == 'LONG' else -1
    apply_d2d(df, d2d_mode, dir_int, orig)
    sig = pd.DataFrame([{'feat_1': SEQ_COL, 'thresh_1': '==1',
                         'feat_2': SEQ_COL, 'thresh_2': '==1',
                         'feat_3': SEQ_COL, 'thresh_3': '==1',
                         'direction': direction}])
    td = engine.run_portfolio(df, sig, mask_window=None, adaptive=adaptive,
                              structural=structural, warmup=warmup, verbose=False)
    if len(td) == 0:
        return {}
    return dict(zip(td['entry_time'].values, td['pnl'].values))


# ── numpy k-means + silhouette (descriptive only; never feeds an entry) ──
def _kmeanspp(X, k, rng):
    c = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = np.min(np.sum((X[:, None, :] - np.array(c)[None, :, :]) ** 2, axis=2), axis=1)
        tot = d.sum()
        probs = d / tot if tot > 0 else np.full(len(X), 1.0 / len(X))
        c.append(X[rng.choice(len(X), p=probs)])
    return np.array(c)


def kmeans(X, k, iters=KMEANS_ITERS, restarts=KMEANS_RESTARTS, seed=SEED):
    best_lab, best_cen, best_rss = None, None, np.inf
    for r in range(restarts):
        rng = np.random.default_rng(seed + r)
        cen = _kmeanspp(X, k, rng)
        lab = np.zeros(len(X), dtype=int)
        for _ in range(iters):
            d = np.sum((X[:, None, :] - cen[None, :, :]) ** 2, axis=2)
            new = np.argmin(d, axis=1)
            if np.array_equal(new, lab):
                break
            lab = new
            for j in range(k):
                m = lab == j
                if m.any():
                    cen[j] = X[m].mean(axis=0)
        rss = float(np.sum((X - cen[lab]) ** 2))
        if rss < best_rss:
            best_lab, best_cen, best_rss = lab.copy(), cen.copy(), rss
    return best_lab, best_cen, best_rss


def silhouette(X, lab, sample=SIL_SAMPLE, seed=SEED):
    rng = np.random.default_rng(seed)
    if len(X) > sample:
        idx = rng.choice(len(X), sample, replace=False)
        X, lab = X[idx], lab[idx]
    if len(set(lab.tolist())) < 2:
        return 0.0
    D = np.sqrt(np.maximum(np.sum((X[:, None, :] - X[None, :, :]) ** 2, axis=2), 0.0))
    s = np.zeros(len(X))
    for i in range(len(X)):
        same = lab == lab[i]
        same[i] = False
        a = D[i][same].mean() if same.any() else 0.0
        b = np.inf
        for j in set(lab.tolist()):
            if j == lab[i]:
                continue
            o = lab == j
            if o.any():
                b = min(b, D[i][o].mean())
        s[i] = 0.0 if max(a, b) == 0 else (b - a) / max(a, b)
    return float(s.mean())


def bic_kmeans(X, rss, k):
    n, d = X.shape
    if rss <= 0:
        return -np.inf
    return float(n * d * math.log(rss / (n * d)) + k * (d + 1) * math.log(n))


def zscore(X):
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    return (X - mu) / sd


# ── parallel stage 4: outcome map ────────────────────────────────────────
def _init(payload, counter):
    _G.update(payload)
    _G['counter'] = counter
    if SEQ_COL not in _G['df'].columns:
        _G['df'][SEQ_COL] = 0


def _config_rows(cfgs, df, depth_long, depth_short, orig, month, adaptive, structural,
                 warmup, counter=None):
    rows = []
    cache = {}
    local = 0
    try:
        for (k, dur, direction, mode) in cfgs:
            key = (k, direction)
            if key not in cache:
                depth = depth_long if direction == 'LONG' else depth_short
                cache[key] = run_lengths(depth >= k)
            mask = cache[key] >= dur
            if int(mask.sum()) == 0:
                sc = {'trades': 0, 'WR': 0.0, 'agg_pf': 0.0, 'worst_day_usd': 0.0,
                      'hard_stop_days': 0, 'folds_plus': 0, 'min_fold_pf': 0.0,
                      'spread_pf': '0.0->0.0'}
                for i in range(1, len(wf.FOLDS) + 1):
                    sc[f'fold{i}_pf'] = 0.0
                    sc[f'fold{i}_trades'] = 0
            else:
                sc = score_mask(df, mask, direction, mode, orig, month, adaptive,
                                structural, warmup)
            sc.update({'peak_depth_k': k, 'duration_at_depth': dur,
                       'direction': direction, 'd2d_mode': mode,
                       'bars_at_config': int(mask.sum())})
            rows.append(sc)
            local += 1
            if counter is not None and local >= FLUSH:
                with counter.get_lock():
                    counter.value += local
                local = 0
    finally:
        df['D2D_Trend_Dir'] = orig
    if counter is not None and local:
        with counter.get_lock():
            counter.value += local
    return rows


def _worker(task):
    cid, n_chunks, cfgs = task
    t0 = time.time()
    rows = _config_rows(cfgs, _G['df'], _G['depth_long'], _G['depth_short'], _G['orig'],
                        _G['month'], _G['adaptive'], _G['structural'], _G['warmup'],
                        _G['counter'])
    print(f"chunk {cid + 1}/{n_chunks} done — {len(cfgs)} configs, "
          f"{(time.time() - t0) / 60:.1f} min", flush=True)
    return rows


def _chunks(items, n):
    k = math.ceil(len(items) / n)
    return [items[i:i + k] for i in range(0, len(items), k)]


def _monitor(counter, total, start, ready_fn, stage, interval):
    while not ready_fn():
        time.sleep(interval)
        el = time.time() - start
        done = min(int(counter.value), total)
        rate = done / el if el > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else 0.0
        sys.stdout.write(f"\r[{stage}] {100.0 * done / total if total else 0:5.1f}% | "
                         f"{done:,}/{total:,} | elapsed {_fmt_hms(el)} | ETA {_fmt_hms(eta)} | "
                         f"{rate:.2f}/s   ")
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()


COLS4 = ['peak_depth_k', 'duration_at_depth', 'direction', 'd2d_mode', 'bars_at_config',
         'trades', 'WR', 'agg_pf', 'worst_day_usd', 'hard_stop_days', 'folds_plus',
         'min_fold_pf', 'spread_pf'] \
    + [f'fold{i}_pf' for i in range(1, 7)] \
    + [f'fold{i}_trades' for i in range(1, 7)]


def stage4_outcome_map(ctx, k_vals, durations, directions, modes, n_workers, interval,
                       write=True, tag='concurrence_outcome_map.csv'):
    cfgs = [(k, d, dr, m) for k in k_vals for d in durations for dr in directions for m in modes]
    chunks = _chunks(cfgs, n_workers)
    counter = Value('L', 0)
    payload = dict(df=ctx['df'], depth_long=ctx['depth_long'], depth_short=ctx['depth_short'],
                   orig=ctx['orig'], month=ctx['month'], adaptive=ctx['adaptive'],
                   structural=ctx['structural'], warmup=ctx['warmup'])
    t0 = time.time()
    _stamp('STAGE 4', f"outcome map: {len(cfgs):,} configs "
                      f"(k {min(k_vals)}..{max(k_vals)} x dur {min(durations)}..{max(durations)} "
                      f"x {len(directions)} dir x {len(modes)} d2d) across {len(chunks)} chunks")
    with Pool(n_workers, initializer=_init, initargs=(payload, counter)) as p:
        res = p.map_async(_worker, [(i, len(chunks), c) for i, c in enumerate(chunks)])
        _monitor(counter, len(cfgs), t0, res.ready, 'STAGE 4', interval)
        rows = [r for wr in res.get() for r in wr]
    if write:
        out = os.path.join(RESULTS_DIR, tag)
        pd.DataFrame(rows, columns=COLS4).to_csv(out, index=False, lineterminator='\n')
        _stamp('STAGE 4', f"{len(rows)} rows -> {out}  ({_fmt_hms(time.time() - t0)})")
    return rows


# ── generic parallel runner for stages 6-ext / 5b / 8 ────────────────────
#  Stage 4's runner above is RATIFIED and is not touched. This is a separate,
#  parallel scorer for the amendment-2 stages. Masks are reconstructed INSIDE
#  the worker from arrays shipped in the Pool initializer.
_GG = {}


def _init_gen(payload, counter):
    _GG.update(payload)
    _GG['counter'] = counter
    if SEQ_COL not in _GG['df'].columns:
        _GG['df'][SEQ_COL] = 0


def _mask_for(cfg, G):
    kind = cfg['kind']
    direction = cfg['direction']
    depth = G['depth_long'] if direction == 'LONG' else G['depth_short']
    if kind == 'regime':
        m = run_lengths(depth >= cfg['k']) >= cfg['duration']
        return m & (G['lab_causal'] == cfg['cluster'])
    if kind == 'cat_marginal':
        cd = G['cat_depth'][(direction, cfg['regime'], cfg['cluster'])]
        m = run_lengths(cd >= cfg['k']) >= cfg['duration']
        return m & (G['lab_causal'] == cfg['regime'])
    if kind == 'cat_dominant':
        cd = G['cat_depth'][(direction, cfg['regime'], cfg['cluster'])]
        tot = np.maximum(depth, 1)
        share_ok = (cd / tot) >= cfg['share']
        m = run_lengths((depth >= cfg['k']) & share_ok) >= cfg['duration']
        return m & (G['lab_causal'] == cfg['regime'])
    if kind == 'null':
        d = np.roll(depth, cfg['shift'])
        return run_lengths(d >= cfg['k']) >= cfg['duration']
    raise ValueError(f"unknown mask kind '{kind}'")


def _gen_rows(cfgs, G, counter=None):
    rows = []
    local = 0
    df = G['df']
    try:
        for cfg in cfgs:
            mask = _mask_for(cfg, G)
            if int(mask.sum()) == 0:
                sc = {'trades': 0, 'WR': 0.0, 'agg_pf': 0.0, 'worst_day_usd': 0.0,
                      'hard_stop_days': 0, 'folds_plus': 0, 'min_fold_pf': 0.0,
                      'spread_pf': '0.0->0.0'}
                for i in range(1, len(wf.FOLDS) + 1):
                    sc[f'fold{i}_pf'] = 0.0
                    sc[f'fold{i}_trades'] = 0
            else:
                sc = score_mask(df, mask, cfg['direction'], cfg['d2d_mode'], G['orig'],
                                G['month'], G['adaptive'], G['structural'], G['warmup'])
            fold_names = [f[0] for f in wf.FOLDS]
            contributed = [fold_names[i - 1] for i in range(1, len(wf.FOLDS) + 1)
                           if sc[f'fold{i}_trades'] > 0]
            sc.update({k: v for k, v in cfg.items() if k != 'kind'})
            sc['bars_at_config'] = int(mask.sum())
            sc['folds_scored'] = '|'.join(contributed) if contributed else 'none'
            sc['causal'] = cfg['kind'] != 'null'
            rows.append(sc)
            local += 1
            if counter is not None and local >= FLUSH:
                with counter.get_lock():
                    counter.value += local
                local = 0
    finally:
        df['D2D_Trend_Dir'] = G['orig']
    if counter is not None and local:
        with counter.get_lock():
            counter.value += local
    return rows


def _gen_worker(task):
    cid, n_chunks, cfgs = task
    t0 = time.time()
    rows = _gen_rows(cfgs, _GG, _GG['counter'])
    print(f"chunk {cid + 1}/{n_chunks} done — {len(cfgs)} configs, "
          f"{(time.time() - t0) / 60:.1f} min", flush=True)
    return rows


def run_parallel_configs(ctx, cfgs, stage, n_workers, interval, extra=None):
    if not cfgs:
        return []
    payload = dict(df=ctx['df'], depth_long=ctx['depth_long'], depth_short=ctx['depth_short'],
                   orig=ctx['orig'], month=ctx['month'], adaptive=ctx['adaptive'],
                   structural=ctx['structural'], warmup=ctx['warmup'],
                   lab_causal=ctx['lab_causal'])
    if extra:
        payload.update(extra)
    chunks = _chunks(cfgs, n_workers)
    counter = Value('L', 0)
    t0 = time.time()
    gc.collect()
    _stamp(stage, f"{len(cfgs):,} configs across {len(chunks)} chunks")
    with Pool(n_workers, initializer=_init_gen, initargs=(payload, counter)) as p:
        res = p.map_async(_gen_worker, [(i, len(chunks), c) for i, c in enumerate(chunks)])
        _monitor(counter, len(cfgs), t0, res.ready, stage, interval)
        rows = [r for wr in res.get() for r in wr]
    return rows
# ── stage 1: per-bar depth ───────────────────────────────────────────────
def stage1_depth_bars(ctx, write=True):
    t0 = time.time()
    df, w = ctx['df'], ctx['warmup']
    sl = slice(w, len(df))
    out = pd.DataFrame({'Time': df['Time'].values[sl],
                        'depth_long': ctx['depth_long'][sl],
                        'depth_short': ctx['depth_short'][sl],
                        'depth_d2d_aligned': ctx['depth_aligned'][sl],
                        'd2d_dir': ctx['orig'][sl],
                        'regime': ctx['lab_desc'][sl],
                        'regime_causal': ctx['lab_causal'][sl],
                        'causal': False})
    for c in ctx['regime_vars']:
        out[c] = df[c].values[sl]
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_depth_bars.csv')
        out.to_csv(p, index=False, lineterminator='\n')
        _stamp('STAGE 1', f"{len(out)} rows -> {p}  ({time.time() - t0:.1f}s)")
    ql = _depth_quantiles(ctx['depth_long'][sl])
    qs = _depth_quantiles(ctx['depth_short'][sl])
    _stamp('STAGE 1', f"depth_long p5/25/50/75/90/95/99 = {ql} "
                      f"| depth_short = {qs}")
    return out


# ── stage 2: concurrence events (lifecycle) ──────────────────────────────
COLS2 = ['direction', 'onset_floor', 'start_time', 'end_time', 'onset_depth', 'peak_depth',
         'bars_at_peak', 'duration_bars', 'build_rate', 'decay_rate', 'onset_pnl',
         'onset_bar', 'peak_bar', 'regime_at_onset', 'regime_at_peak',
         'regime_causal_at_onset', 'causal']


def _events_for(depth, floor, warmup):
    rl = run_lengths(depth >= floor)
    starts = np.where(rl == 1)[0]
    starts = starts[starts >= warmup]
    evs = []
    for s in starts:
        e = s
        while e + 1 < len(rl) and rl[e + 1] > 0:
            e += 1
        evs.append((s, e))
    return evs


def stage2_events(ctx, floors, write=True):
    t0 = time.time()
    df, w = ctx['df'], ctx['warmup']
    times = df['Time'].values
    rows, ev_index = [], {}
    for direction in DIRECTIONS:
        depth = ctx['depth_long'] if direction == 'LONG' else ctx['depth_short']
        for floor in floors:
            evs = _events_for(depth, floor, w)
            if not evs:
                continue
            onset = np.zeros(len(df), dtype=bool)
            onset[[s for s, _ in evs]] = True
            pnl_map = trades_at(df, onset, direction, 'confirm', ctx['orig'],
                                ctx['adaptive'], ctx['structural'], w)
            for s, e in evs:
                seg = depth[s:e + 1]
                pk = int(seg.max())
                pk_off = int(seg.argmax())
                bars_pk = int((seg == pk).sum())
                build = (pk - int(seg[0])) / pk_off if pk_off > 0 else 0.0
                tail = (e - (s + pk_off))
                decay = (pk - int(seg[-1])) / tail if tail > 0 else 0.0
                rows.append({'direction': direction, 'onset_floor': floor,
                             'start_time': times[s], 'end_time': times[e],
                             'onset_depth': int(seg[0]), 'peak_depth': pk,
                             'bars_at_peak': bars_pk, 'duration_bars': int(e - s + 1),
                             'build_rate': round(build, 3), 'decay_rate': round(decay, 3),
                             'onset_pnl': pnl_map.get(times[s], np.nan),
                             'onset_bar': int(s), 'peak_bar': int(s + pk_off),
                             'regime_at_onset': int(ctx['lab_desc'][s]),
                             'regime_at_peak': int(ctx['lab_desc'][s + pk_off]),
                             'regime_causal_at_onset': int(ctx['lab_causal'][s]),
                             'causal': False})
            ev_index[(direction, floor)] = evs
    df['D2D_Trend_Dir'] = ctx['orig']
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_events.csv')
        pd.DataFrame(rows, columns=COLS2).to_csv(p, index=False, lineterminator='\n')
        _stamp('STAGE 2', f"{len(rows)} events (floors {floors}) -> {p}  ({time.time() - t0:.1f}s)")
    return rows, ev_index


# ── stage 3: entry order within events ───────────────────────────────────
COLS3 = ['direction', 'onset_floor', 'regime', 'causal', 'condition', 'events_joined',
         'early_joiner_frac', 'late_joiner_frac', 'mean_join_offset']


def stage3_entry_order(ctx, ev_index, write=True):
    t0 = time.time()
    pool = ctx['pool']
    lab_desc = ctx['lab_desc']
    rows = []
    # regime=-1 is the global aggregate (retained); regimes 0..n-1 slice the same
    # events by the DESCRIPTIVE regime at onset. Gates nothing -> causal=False.
    for (direction, floor), evs in ev_index.items():
        lbls = ctx['long_lbls'] if direction == 'LONG' else ctx['short_lbls']
        depth = ctx['depth_long'] if direction == 'LONG' else ctx['depth_short']
        for regime in [-1] + list(range(ctx['n_desc'])):
            sel = [(s, e) for s, e in evs if regime == -1 or int(lab_desc[s]) == regime]
            if not sel:
                continue
            stats = {l: {'n': 0, 'early': 0, 'late': 0, 'offs': []} for l in lbls}
            for s, e in sel:
                pk_off = int(depth[s:e + 1].argmax())
                build_len = max(pk_off, 1)
                q1 = build_len / 4.0
                for l in lbls:
                    seg = pool[l][s:e + 1]
                    if not seg.any():
                        continue
                    off = int(np.argmax(seg))
                    st = stats[l]
                    st['n'] += 1
                    st['offs'].append(off)
                    if off <= q1:
                        st['early'] += 1
                    elif off > build_len:
                        st['late'] += 1
            for l, st in stats.items():
                if st['n'] == 0:
                    continue
                rows.append({'direction': direction, 'onset_floor': floor, 'regime': regime,
                             'causal': False, 'condition': l, 'events_joined': st['n'],
                             'early_joiner_frac': round(st['early'] / st['n'], 4),
                             'late_joiner_frac': round(st['late'] / st['n'], 4),
                             'mean_join_offset': round(float(np.mean(st['offs'])), 3)})
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_entry_order.csv')
        pd.DataFrame(rows, columns=COLS3).to_csv(p, index=False, lineterminator='\n')
        _stamp('STAGE 3', f"{len(rows)} rows -> {p}  ({time.time() - t0:.1f}s)")
    return rows


# ── stage 5: composition (co-occurrence clustering, no hand labels) ──────
# ── stage 5: composition, per (direction x regime) ───────────────────────
#  DESCRIPTIVE ONLY — gates nothing, so it may use the full-sample descriptive
#  regime labels (lab_desc). Every row carries causal=False. regime=-1 denotes
#  the global/all-bars view, retained for comparison. A single global clustering
#  averages regimes together and hides the phenomenon; hence the per-regime cells.
def _jaccard(M):
    inter = M @ M.T
    cnt = M.sum(axis=1)
    union = cnt[:, None] + cnt[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def _var_of(lbl):
    return lbl.split(':', 1)[0]


def _cluster_conditions(J, lbls, n_sweep, direction, regime, rows):
    best = (None, -2.0, None)
    for n in n_sweep:
        if n >= len(lbls):
            continue
        lab, cen, rss = kmeans(J, n)
        sil = silhouette(J, lab)
        rows.append({'row_type': 'sweep', 'causal': False, 'direction': direction,
                     'regime': regime, 'n_clusters': n, 'silhouette': round(sil, 4),
                     'bic': round(bic_kmeans(J, rss, n), 1), 'rss': round(rss, 3),
                     'chosen': False, 'skipped': False})
        if sil > best[1]:
            best = (n, sil, lab)
    for r in rows:
        if r['row_type'] == 'sweep' and r['direction'] == direction and \
                r['regime'] == regime and r['n_clusters'] == best[0]:
            r['chosen'] = True
    return best[0], best[2]


def stage5_composition(ctx, ev_index, n_sweep, write=True):
    t0 = time.time()
    pool, w = ctx['pool'], ctx['warmup']
    lab_desc = ctx['lab_desc']
    stacked = ctx['depth_aligned'] >= COMPOSITION_FLOOR
    stacked[:w] = False
    rows, out = [], []
    memb = {}
    regimes = [-1] + list(range(ctx['n_desc']))
    for direction in DIRECTIONS:
        lbls = ctx['long_lbls'] if direction == 'LONG' else ctx['short_lbls']
        depth = ctx['depth_long'] if direction == 'LONG' else ctx['depth_short']
        for regime in regimes:
            cell = stacked if regime == -1 else (stacked & (lab_desc == regime))
            n_bars = int(cell.sum())
            if n_bars < MIN_STACK_BARS:
                # thin cell: EMITTED, never silently omitted
                out.append({'row_type': 'cell_status', 'causal': False, 'direction': direction,
                            'regime': regime, 'n_bars': n_bars, 'skipped': True,
                            'min_stack_bars': MIN_STACK_BARS})
                continue
            out.append({'row_type': 'cell_status', 'causal': False, 'direction': direction,
                        'regime': regime, 'n_bars': n_bars, 'skipped': False,
                        'min_stack_bars': MIN_STACK_BARS})
            M = np.vstack([pool[l][cell] for l in lbls]).astype(np.float64)
            J = _jaccard(M)
            n_best, lab = _cluster_conditions(J, lbls, n_sweep, direction, regime, rows)
            if n_best is None:
                continue
            memb[(direction, regime)] = {l: int(c) for l, c in zip(lbls, lab)}
            for l, c in memb[(direction, regime)].items():
                out.append({'row_type': 'condition_membership', 'causal': False,
                            'direction': direction, 'regime': regime, 'key': l,
                            'variable': _var_of(l), 'cluster': int(c)})
            # VARIABLE-level view, hi/lo collapsed: does V group with W in regime 1
            # and with X in regime 2? (the operator's exact question)
            vmap = {}
            for l, c in memb[(direction, regime)].items():
                vmap.setdefault(_var_of(l), []).append(int(c))
            for v, cs in vmap.items():
                dom = max(set(cs), key=cs.count)
                out.append({'row_type': 'variable_membership', 'causal': False,
                            'direction': direction, 'regime': regime, 'key': v,
                            'variable': v, 'cluster': dom,
                            'value': round(cs.count(dom) / len(cs), 4)})
            # top co-occurring pairs, so the grouping is inspectable without the matrix
            iu = np.triu_indices(len(lbls), k=1)
            order = np.argsort(-J[iu])[:TOP_PAIRS_N]
            for o in order:
                i, j = iu[0][o], iu[1][o]
                out.append({'row_type': 'cluster_pairs', 'causal': False, 'direction': direction,
                            'regime': regime, 'key': f"{lbls[i]} + {lbls[j]}",
                            'value': round(float(J[i, j]), 4),
                            'cluster': memb[(direction, regime)][lbls[i]],
                            'cluster_b': memb[(direction, regime)][lbls[j]]})
            # which conditions/variables dominate the DEEP stacks in this regime
            deep = cell & (depth >= K_DEEP)
            nd = int(deep.sum())
            if nd:
                for l in lbls:
                    f = float(pool[l][deep].mean())
                    if f > 0:
                        out.append({'row_type': 'regime_deep_composition', 'causal': False,
                                    'direction': direction, 'regime': regime, 'key': l,
                                    'variable': _var_of(l), 'value': round(f, 4),
                                    'k_deep': K_DEEP, 'deep_bars': nd})

    # cross-regime stability: for condition c, the fraction of other conditions that
    # share c's cluster in regime r AND in regime s, averaged over regime pairs.
    for direction in DIRECTIONS:
        lbls = ctx['long_lbls'] if direction == 'LONG' else ctx['short_lbls']
        regs = [r for r in range(ctx['n_desc']) if (direction, r) in memb]
        if len(regs) < 2:
            continue
        for a in range(len(regs)):
            for b in range(a + 1, len(regs)):
                ra, rb = regs[a], regs[b]
                ma, mb = memb[(direction, ra)], memb[(direction, rb)]
                agree = np.mean([[(ma[x] == ma[y]) == (mb[x] == mb[y])
                                  for y in lbls if y != x] for x in lbls])
                out.append({'row_type': 'cross_regime_stability', 'causal': False,
                            'direction': direction, 'regime': -1,
                            'key': f"pairwise_agreement r{ra} vs r{rb}",
                            'value': round(float(agree), 4)})
        for x in lbls:
            fr = []
            for a in range(len(regs)):
                for b in range(a + 1, len(regs)):
                    ma, mb = memb[(direction, regs[a])], memb[(direction, regs[b])]
                    same_a = {y for y in lbls if y != x and ma[y] == ma[x]}
                    same_b = {y for y in lbls if y != x and mb[y] == mb[x]}
                    uni = same_a | same_b
                    fr.append(len(same_a & same_b) / len(uni) if uni else 1.0)
            out.append({'row_type': 'cross_regime_stability', 'causal': False,
                        'direction': direction, 'regime': -1, 'key': x,
                        'variable': _var_of(x), 'value': round(float(np.mean(fr)), 4)})

    # event composition, plus the regime label at the peak bar
    for (direction, floor), evs in ev_index.items():
        depth = ctx['depth_long'] if direction == 'LONG' else ctx['depth_short']
        lbls = ctx['long_lbls'] if direction == 'LONG' else ctx['short_lbls']
        m = memb.get((direction, -1))
        if not m:
            continue
        for s, e in evs:
            pb = s + int(depth[s:e + 1].argmax())
            act = [m[l] for l in lbls if pool[l][pb]]
            if not act:
                continue
            for c in sorted(set(m.values())):
                out.append({'row_type': 'event_composition', 'causal': False,
                            'direction': direction, 'regime': int(lab_desc[pb]),
                            'key': f"{ctx['df']['Time'].values[s]}|floor{floor}|cluster{c}",
                            'cluster': c, 'value': round(act.count(c) / len(act), 4)})
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_composition.csv')
        pd.concat([pd.DataFrame(rows), pd.DataFrame(out)],
                  ignore_index=True).to_csv(p, index=False, lineterminator='\n')
        _stamp('STAGE 5', f"{len(rows)} sweep rows + {len(out)} composition rows "
                          f"({len(regimes)} regimes incl. global -1) -> {p}  "
                          f"({time.time() - t0:.1f}s)")
    rows.clear()
    out.clear()
    gc.collect()
    return memb


# ── stage 5b: category depth -> outcome  (CAUSAL — membership gates entries) ──
#  Engine concept: when enough variables WITHIN a category reach extremes, and
#  enough stack concurrently, fire.
#  *** Cluster membership here DECIDES WHICH CONDITIONS COUNT toward category
#  depth, so it GATES ENTRIES and is a signal input. It is therefore fit ONCE on
#  the leading burn-in window (fold 1, post-warmup) and applied FORWARD-ONLY.
#  Regime labels used are the CAUSAL ones. The burn-in fold is excluded from
#  scoring (lab_causal == -1 there), so fold1_trades == 0 on every row. A
#  full-sample clustering that gates a trade is the defect the Auditor rejected;
#  it is not reintroduced here. ***
def causal_category_membership(ctx, n_sweep):
    df, w = ctx['df'], ctx['warmup']
    pool, months = ctx['pool'], ctx['month']
    burn_key = wf.FOLDS[0][1]
    idx = np.arange(len(df))
    burn = (months == burn_key) & (idx >= w)
    stacked = ctx['depth_aligned'] >= COMPOSITION_FLOOR
    memb, status = {}, []
    for direction in DIRECTIONS:
        lbls = ctx['long_lbls'] if direction == 'LONG' else ctx['short_lbls']
        for regime in range(ctx['n_causal']):
            cell = burn & stacked & (ctx['lab_burn'] == regime)
            n_bars = int(cell.sum())
            if n_bars < MIN_STACK_BARS:
                status.append({'row_type': 'cell_status', 'causal': True, 'direction': direction,
                               'regime': regime, 'n_bars': n_bars, 'skipped': True,
                               'min_stack_bars': MIN_STACK_BARS,
                               'note': 'burn-in stacked bars below floor'})
                continue
            status.append({'row_type': 'cell_status', 'causal': True, 'direction': direction,
                           'regime': regime, 'n_bars': n_bars, 'skipped': False,
                           'min_stack_bars': MIN_STACK_BARS, 'note': 'burn-in fit'})
            M = np.vstack([pool[l][cell] for l in lbls]).astype(np.float64)
            J = _jaccard(M)
            sink = []
            n_best, lab = _cluster_conditions(J, lbls, n_sweep, direction, regime, sink)
            if n_best is None:
                continue
            memb[(direction, regime)] = {l: int(c) for l, c in zip(lbls, lab)}
    return memb, status


def build_category_depth(ctx, memb):
    # depth_within_cluster_c[bar], using burn-in-fit membership applied forward-only.
    cat = {}
    for (direction, regime), m in memb.items():
        lbls = ctx['long_lbls'] if direction == 'LONG' else ctx['short_lbls']
        for c in sorted(set(m.values())):
            members = [l for l in lbls if m[l] == c]
            cat[(direction, regime, c)] = np.sum(
                np.vstack([ctx['pool'][l] for l in members]), axis=0).astype(np.int32)
    return cat


def stage5b_category_depth(ctx, n_sweep, n_workers, interval, proof=False, write=True,
                           return_cfgs=False):
    t0 = time.time()
    memb, status = causal_category_membership(ctx, n_sweep)
    cat = build_category_depth(ctx, memb)
    cfgs = []
    durs = CAT_DURATIONS[:2] if proof else CAT_DURATIONS
    dom_durs = CAT_DOM_DURATIONS[:1] if proof else CAT_DOM_DURATIONS
    dom_k = CAT_DOM_K[:2] if proof else CAT_DOM_K
    dom_share = CAT_DOM_SHARE[:2] if proof else CAT_DOM_SHARE
    items = list(cat.items())
    if proof:
        items = items[:2]  # proof-only bound on categories; full scope uses all
    for (direction, regime, c), arr in items:
        reach = int(arr[ctx['lab_causal'] == regime].max()) if (ctx['lab_causal'] == regime).any() else 0
        if reach < 2:
            continue
        ks = list(range(2, reach + 1, CAT_K_STEP))
        if proof:
            ks = ks[:2]
        for k in ks:
            for d in durs:
                for m in CAT_MODES:
                    cfgs.append({'kind': 'cat_marginal', 'variant': 'marginal',
                                 'direction': direction, 'regime': regime, 'cluster': c,
                                 'k': k, 'duration': d, 'd2d_mode': m, 'share': np.nan})
        for k in dom_k:
            for s in dom_share:
                for d in dom_durs:
                    for m in CAT_MODES:
                        cfgs.append({'kind': 'cat_dominant', 'variant': 'dominant',
                                     'direction': direction, 'regime': regime, 'cluster': c,
                                     'k': k, 'duration': d, 'd2d_mode': m, 'share': s})
    _stamp('STAGE 5b', f"causal membership from burn-in fold '{wf.FOLDS[0][0]}' | "
                       f"{len(cat)} (direction x regime x cluster) categories | "
                       f"grid {len(cfgs):,} configs")
    if return_cfgs:
        return cfgs, cat
    rows = run_parallel_configs(ctx, cfgs, 'STAGE 5b', n_workers, interval,
                                extra={'cat_depth': cat})
    for r in rows:
        r['peak_depth_k'] = r.pop('k')
        r['duration_at_depth'] = r.pop('duration')
        r['row_type'] = 'category_outcome'
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_category_depth.csv')
        pd.concat([pd.DataFrame(status), pd.DataFrame(rows)],
                  ignore_index=True).to_csv(p, index=False, lineterminator='\n')
        _stamp('STAGE 5b', f"{len(rows)} scored rows + {len(status)} cell_status -> {p}  "
                           f"({_fmt_hms(time.time() - t0)})")
    return rows, cat


# ── stage 8: null baseline (circular shift) ──────────────────────────────
#  Does the depth -> outcome relation survive a null in which depth's own
#  structure is preserved but its alignment with price is destroyed? A CIRCULAR
#  SHIFT preserves autocorrelation, event shape and marginal distribution; an
#  i.i.d. shuffle would destroy event structure and give an unfairly weak null.
#  Shifting depth cannot import future information into a label — it removes
#  information — so this introduces no look-ahead.
def stage8_null_baseline(ctx, observed_rows, n_workers, interval, proof=False, write=True,
                         return_cfgs=False):
    t0 = time.time()
    n = len(ctx['df'])
    n_perm = 3 if proof else N_PERM
    ks = NULL_K[:2] if proof else NULL_K
    durs = NULL_DURATIONS[:1] if proof else NULL_DURATIONS
    rng = np.random.default_rng(SEED)
    shifts = rng.integers(MIN_SHIFT, n - MIN_SHIFT, size=n_perm).tolist()
    cfgs = [{'kind': 'null', 'direction': d, 'k': k, 'duration': dur, 'd2d_mode': m,
             'shift': int(s), 'perm': i}
            for i, s in enumerate(shifts) for k in ks for dur in durs
            for d in DIRECTIONS for m in NULL_MODES]
    _stamp('STAGE 8', f"circular-shift null: {n_perm} permutations "
                      f"(min shift {MIN_SHIFT}) x {len(ks)} k x {len(durs)} dur x "
                      f"{len(DIRECTIONS)} dir = {len(cfgs):,} configs")
    if return_cfgs:
        return cfgs
    rows = run_parallel_configs(ctx, cfgs, 'STAGE 8', n_workers, interval)
    obs = {(r['peak_depth_k'], r['duration_at_depth'], r['direction'], r['d2d_mode']): r
           for r in observed_rows}
    out = []
    nul = pd.DataFrame(rows)
    for k in ks:
        for dur in durs:
            for d in DIRECTIONS:
                for m in NULL_MODES:
                    g = nul[(nul.k == k) & (nul.duration == dur) & (nul.direction == d) &
                            (nul.d2d_mode == m)]
                    o = obs.get((k, dur, d, m))
                    if o is None or len(g) == 0:
                        continue
                    row = {'peak_depth_k': k, 'duration_at_depth': dur, 'direction': d,
                           'd2d_mode': m, 'n_perm': len(g), 'min_shift': MIN_SHIFT,
                           'method': 'circular_shift'}
                    for stat in ['agg_pf', 'WR', 'folds_plus', 'worst_day_usd']:
                        v = g[stat].values.astype(float)
                        sv = np.sort(v)
                        row[f'null_{stat}_mean'] = round(float(v.mean()), 4)
                        row[f'null_{stat}_sd'] = round(float(v.std()), 4)
                        row[f'null_{stat}_p5'] = round(float(sv[int(0.05 * len(sv))]), 4)
                        row[f'null_{stat}_p50'] = round(float(sv[len(sv) // 2]), 4)
                        row[f'null_{stat}_p95'] = round(float(sv[min(int(0.95 * len(sv)), len(sv) - 1)]), 4)
                        row[f'null_{stat}_max'] = round(float(sv[-1]), 4)
                        row[f'observed_{stat}'] = o[stat]
                        row[f'p_value_{stat}'] = round(float((v >= o[stat]).mean()), 4)
                    out.append(row)
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_null_baseline.csv')
        pd.DataFrame(out).to_csv(p, index=False, lineterminator='\n')
        _stamp('STAGE 8', f"{len(out)} cells ({len(rows)} permutation scores) -> {p}  "
                          f"({_fmt_hms(time.time() - t0)})")
    return out


# ── stage 6: regime clustering + regime-conditioned outcome map ──────────
#  DESCRIPTIVE labels (full-sample) drive the sweep / validation / occupancy rows
#  and gate NOTHING. CAUSAL labels (burn-in fit, forward-only assignment) are the
#  ONLY labels that touch an entry mask. See the causal-boundary note in the
#  header. Rows are tagged with a `causal` column so the boundary is auditable.
def zscore_with(X, mu, sd):
    return (X - mu) / sd


def causal_regime_labels(ctx, n_sweep):
    # Fit mu/sigma and centroids ONCE on the leading burn-in window (fold 1,
    # post-warmup). Assign labels forward-only to every later bar. Burn-in bars
    # get -1: they are in-sample and are never scored.
    df, w = ctx['df'], ctx['warmup']
    months = ctx['month']
    burn_key = wf.FOLDS[0][1]
    idx = np.arange(len(df))
    burn = (months == burn_key) & (idx >= w)
    later = (months != burn_key) & (idx >= w)
    Xraw = np.column_stack([df[c].values.astype(float) for c in ctx['regime_vars']])
    Xb = Xraw[burn]
    mu, sd = Xb.mean(axis=0), Xb.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    Zb = zscore_with(Xb, mu, sd)
    rng = np.random.default_rng(SEED)
    sub = rng.choice(len(Zb), min(6000, len(Zb)), replace=False)
    Zs = Zb[sub]
    sweep, best = [], (None, -2.0)
    for n in n_sweep:
        lab, cen, rss = kmeans(Zs, n)
        sil = silhouette(Zs, lab)
        sweep.append({'row_type': 'causal_sweep', 'causal': True, 'n_clusters': n,
                      'silhouette': round(sil, 4), 'bic': round(bic_kmeans(Zs, rss, n), 1),
                      'rss': round(rss, 1), 'chosen': False})
        if sil > best[1]:
            best = (n, sil)
    n_best = best[0]
    for r in sweep:
        r['chosen'] = (r['n_clusters'] == n_best)
    _, cen, _ = kmeans(Zs, n_best)
    lab = np.full(len(df), -1, dtype=int)
    Zl = zscore_with(Xraw[later], mu, sd)
    lab[later] = np.argmin(np.sum((Zl[:, None, :] - cen[None, :, :]) ** 2, axis=2), axis=1)
    # Burn-in bars get FIT-ONLY labels (they depend on burn-in data alone, so they
    # are causal). They live in a SEPARATE array: lab_causal stays -1 on the burn-in
    # fold so that no fold-1 bar can ever be admitted as a trade. lab_burn is used
    # only to partition burn-in bars when fitting stage-5b category membership.
    lab_burn = np.full(len(df), -1, dtype=int)
    lab_burn[burn] = np.argmin(np.sum((Zb[:, None, :] - cen[None, :, :]) ** 2, axis=2), axis=1)
    _stamp('STAGE 6', f"CAUSAL labels: burn-in fold '{wf.FOLDS[0][0]}' ({int(burn.sum())} bars) "
                      f"fits mu/sigma + centroids; n={n_best} (sil {best[1]:.4f}); "
                      f"forward-only labels on {int(later.sum())} bars; burn-in fold excluded "
                      f"from scoring")
    return lab, n_best, sweep, lab_burn


def compute_regime_labels(ctx, n_sweep):
    # Computed BEFORE composition so stages 1/2/3/5/5b/7 can tag rows by regime.
    # Two label sets: lab_desc (full-sample, DESCRIPTIVE, gates nothing) and
    # lab_causal (burn-in fit, forward-only, the ONLY labels that gate an entry).
    df, w = ctx['df'], ctx['warmup']
    X = zscore(np.column_stack([df[c].values[w:].astype(float) for c in ctx['regime_vars']]))
    rng = np.random.default_rng(SEED)
    sub = rng.choice(len(X), min(6000, len(X)), replace=False)
    Xs = X[sub]
    sweep, best = [], (None, -2.0)
    for n in n_sweep:
        lab, cen, rss = kmeans(Xs, n)
        sil = silhouette(Xs, lab)
        sweep.append({'row_type': 'sweep', 'causal': False, 'n_clusters': n,
                      'silhouette': round(sil, 4), 'bic': round(bic_kmeans(Xs, rss, n), 1),
                      'rss': round(rss, 1), 'chosen': False})
        if sil > best[1]:
            best = (n, sil)
    n_desc = best[0]
    for r in sweep:
        r['chosen'] = (r['n_clusters'] == n_desc)
    _, cen, _ = kmeans(Xs, n_desc)
    lab_desc = np.full(len(df), -1, dtype=int)
    lab_desc[w:] = np.argmin(np.sum((X[:, None, :] - cen[None, :, :]) ** 2, axis=2), axis=1)
    _stamp('REGIMES', f"descriptive n_clusters by silhouette = {n_desc} "
                      f"(sil {best[1]:.4f}); gates nothing")
    lab_causal, n_causal, causal_sweep, lab_burn = causal_regime_labels(ctx, n_sweep)
    ctx.update({'lab_desc': lab_desc, 'n_desc': n_desc, 'desc_sweep': sweep,
                'lab_causal': lab_causal, 'n_causal': n_causal, 'causal_sweep': causal_sweep,
                'lab_burn': lab_burn})
    return ctx


def stage6_regimes(ctx, k_vals, n_workers, interval, write=True):
    # Descriptive rows (gate nothing) + CAUSAL regime-conditioned outcome map swept
    # across the stage-4 k range, both confirm and invert, with per-fold columns.
    t0 = time.time()
    w = ctx['warmup']
    rows = list(ctx['desc_sweep'])
    lab_desc, n_desc = ctx['lab_desc'], ctx['n_desc']
    months_pw = ctx['month'][w:]
    ld = lab_desc[w:]
    for c in range(n_desc):
        m = ld == c
        rl = run_lengths(m)
        ends = np.where((rl > 0) & (np.append(rl[1:], 0) == 0))[0]
        rows.append({'row_type': 'cluster_validation', 'causal': False, 'n_clusters': n_desc,
                     'cluster': c, 'bars': int(m.sum()), 'share': round(m.mean(), 4),
                     'mean_run_len_bars': round(float(rl[ends].mean()) if len(ends) else 0.0, 2),
                     'n_runs': int(len(ends))})
        for label, mkey in wf.FOLDS:
            fm = m & (months_pw == mkey)
            rows.append({'row_type': 'fold_occupancy', 'causal': False, 'n_clusters': n_desc,
                         'cluster': c, 'fold': label, 'bars': int(fm.sum()),
                         'share_of_fold': round(fm.sum() / max((months_pw == mkey).sum(), 1), 4)})
    rows.extend(ctx['causal_sweep'])

    cfgs = [{'kind': 'regime', 'cluster': c, 'direction': d, 'k': k, 'duration': REGIME_DUR,
             'd2d_mode': m}
            for c in range(ctx['n_causal']) for d in DIRECTIONS for k in k_vals
            for m in REGIME_MODES]
    out = run_parallel_configs(ctx, cfgs, 'STAGE 6', n_workers, interval)
    for r in out:
        r['row_type'] = 'regime_outcome'
        r['n_clusters'] = ctx['n_causal']
        r['peak_depth_k'] = r.pop('k')
        r['duration_at_depth'] = r.pop('duration')
    rows.extend(out)
    ctx['df']['D2D_Trend_Dir'] = ctx['orig']
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_regimes.csv')
        pd.DataFrame(rows).to_csv(p, index=False, lineterminator='\n')
        _stamp('STAGE 6', f"{len(rows)} rows ({len(out)} causal regime_outcome) -> {p}  "
                          f"({time.time() - t0:.1f}s)")
    return rows


# ── stage 7: D2D flip relationship ───────────────────────────────────────
def stage7_d2d_flips(ctx, write=True):
    t0 = time.time()
    df, w = ctx['df'], ctx['warmup']
    times = df['Time'].values
    d2d = ctx['orig']
    flip = np.zeros(len(df), dtype=bool)
    flip[1:] = d2d[1:] != d2d[:-1]
    flip[:w] = False
    rows = []
    pnl_maps = {}
    for direction in DIRECTIONS:
        di = 1 if direction == 'LONG' else -1
        m = flip & (d2d == di)
        if m.any():
            pnl_maps[direction] = trades_at(df, m, direction, 'confirm', ctx['orig'],
                                            ctx['adaptive'], ctx['structural'], w)
    df['D2D_Trend_Dir'] = ctx['orig']
    for b in np.where(flip)[0]:
        new_dir = int(d2d[b])
        if new_dir == 0:
            continue
        direction = 'LONG' if new_dir == 1 else 'SHORT'
        depth_new = ctx['depth_long'] if new_dir == 1 else ctx['depth_short']
        lo = max(b - FLIP_LOOKBACK, 0)
        pre = depth_new[lo:b]
        if len(pre) < 2:
            continue
        slope = float(np.polyfit(np.arange(len(pre)), pre.astype(float), 1)[0])
        pnl = pnl_maps.get(direction, {}).get(times[b], np.nan)
        rows.append({'row_type': 'flip', 'time': times[b], 'direction': direction,
                     'lookback_bars': FLIP_LOOKBACK,
                     'pre_depth_mean': round(float(pre.mean()), 2),
                     'pre_depth_max': int(pre.max()),
                     'pre_depth_slope': round(slope, 4),
                     'depth_at_flip': int(depth_new[b]),
                     'depth_gain_pre': int(depth_new[b] - pre[0]),
                     'flip_pnl': pnl,
                     'good_flip': (pnl > 0) if pnl == pnl else np.nan,
                     'counter_margin': np.nan,
                     'regime': int(ctx['lab_desc'][b]),
                     'regime_causal': int(ctx['lab_causal'][b]), 'causal': False})
    # candidate counter-D2D bars: opposite-side stack dominates while D2D still
    # reads the old direction. Objective, no taxonomy: opposite depth high AND
    # exceeding aligned depth by a margin. EMITTED ONLY — never acted on here.
    opp = np.where(d2d == 1, ctx['depth_short'], np.where(d2d == -1, ctx['depth_long'], 0))
    alg = ctx['depth_aligned']
    cnt = (opp >= COUNTER_FLOOR) & ((opp - alg) >= COUNTER_MARGIN)
    cnt[:w] = False
    for b in np.where(cnt)[0]:
        rows.append({'row_type': 'counter_d2d_bar', 'time': times[b],
                     'direction': 'SHORT' if d2d[b] == 1 else 'LONG',
                     'lookback_bars': np.nan, 'pre_depth_mean': np.nan,
                     'pre_depth_max': np.nan, 'pre_depth_slope': np.nan,
                     'depth_at_flip': int(opp[b]), 'depth_gain_pre': np.nan,
                     'flip_pnl': np.nan, 'good_flip': np.nan,
                     'counter_margin': int(opp[b] - alg[b]),
                     'regime': int(ctx['lab_desc'][b]),
                     'regime_causal': int(ctx['lab_causal'][b]), 'causal': False})
    if write:
        p = os.path.join(RESULTS_DIR, 'concurrence_d2d_flips.csv')
        pd.DataFrame(rows).to_csv(p, index=False, lineterminator='\n')
        n_f = sum(1 for r in rows if r['row_type'] == 'flip')
        n_c = len(rows) - n_f
        _stamp('STAGE 7', f"{n_f} flips + {n_c} candidate counter-D2D bars -> {p} "
                          f"({time.time() - t0:.1f}s)")
    return rows


# ── context ──────────────────────────────────────────────────────────────
def build_context(secondary=False, base=None):
    # `base` reuses an already-loaded baseline + oracle + condition pool. The
    # secondary view differs ONLY in which aligned conditions it counts, so it
    # must never load a second copy of the 152,983 x 171 frame.
    if base is None:
        df = engine.load_sealed_baseline()
        warmup = engine.warmup_floor(df)
        verify_live(df, REGIME_VARS + ['D2D_Trend_Dir', 'ST_Flip_Event'])
        adaptive = dt.compute_adaptive_thresholds(df)
        structural = dt.compute_structural_gates(df)
        pool = seq.build_condition_pool(df, adaptive, structural, warmup)
    else:
        df, warmup = base['df'], base['warmup']
        adaptive, structural, pool = base['adaptive'], base['structural'], base['pool']
    long_lbls, short_lbls = align_pool(pool)
    if secondary:
        keep = survivor_conditions()
        long_lbls = [l for l in long_lbls if l in keep]
        short_lbls = [l for l in short_lbls if l in keep]
    orig = df['D2D_Trend_Dir'].values.copy()
    dl, ds, da = depth_arrays(pool, long_lbls, short_lbls, orig)
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    ctx = {'df': df, 'warmup': warmup, 'adaptive': adaptive, 'structural': structural,
           'pool': pool, 'long_lbls': long_lbls, 'short_lbls': short_lbls,
           'depth_long': dl, 'depth_short': ds, 'depth_aligned': da, 'orig': orig,
           'month': pd.Series(df['Time'].values).str[:7].values,
           'regime_vars': REGIME_VARS}
    if base is not None:
        for k in ('lab_desc', 'n_desc', 'lab_causal', 'n_causal', 'lab_burn'):
            if k in base:
                ctx[k] = base[k]
    return ctx


def survivor_conditions():
    # SECONDARY view only: conditions appearing in F0's deduped survivors.
    # Never touches the PRIMARY view.
    p = os.path.join('dots_results', 'deduped_survivors.csv')
    if not os.path.exists(p):
        _stamp('SECONDARY', f"{p} not found — secondary view skipped.")
        return set()
    s = pd.read_csv(p)
    keep = set()
    for _, r in s.iterrows():
        for i in (1, 2, 3):
            keep.add(f"{r[f'feat_{i}']}:{r[f'thresh_{i}']}")
    return keep


# ── parity (proof mode) ──────────────────────────────────────────────────
def _key4(r):
    return (r['peak_depth_k'], r['duration_at_depth'], r['direction'], r['d2d_mode'])


def parity_check(ctx, k_vals, durations, n_workers, proof=True):
    # Covers stage 4 (ratified path), stage 5b and stage 8 (generic path).
    ok_all, details = True, []

    par = stage4_outcome_map(ctx, k_vals, durations, DIRECTIONS, D2D_MODES, 1,
                             2.0, write=False)
    cfgs = [(k, d, dr, m) for k in k_vals for d in durations for dr in DIRECTIONS
            for m in D2D_MODES]
    ser = _config_rows(cfgs, ctx['df'], ctx['depth_long'], ctx['depth_short'], ctx['orig'],
                       ctx['month'], ctx['adaptive'], ctx['structural'], ctx['warmup'])
    ok, det = _compare(sorted(par, key=_key4), sorted(ser, key=_key4), COLS4, 'stage4')
    ok_all &= ok
    details.append(det)

    for stage, cfgs_g, extra in _parity_generic_cfgs(ctx, n_workers, proof):
        parg = run_parallel_configs(ctx, cfgs_g, f'PARITY {stage}', 1, 2.0, extra=extra)
        G = dict(df=ctx['df'], depth_long=ctx['depth_long'], depth_short=ctx['depth_short'],
                 orig=ctx['orig'], month=ctx['month'], adaptive=ctx['adaptive'],
                 structural=ctx['structural'], warmup=ctx['warmup'],
                 lab_causal=ctx['lab_causal'])
        if extra:
            G.update(extra)
        serg = _gen_rows(cfgs_g, G)
        cols = sorted(set(parg[0].keys()) & set(serg[0].keys())) if parg and serg else []
        ok, det = _compare(sorted(parg, key=_keyg), sorted(serg, key=_keyg), cols, stage)
        ok_all &= ok
        details.append(det)

    print(f"\n[PARITY] {'PASS' if ok_all else 'FAIL'} — " + " | ".join(details))
    return ok_all


def _keyg(r):
    return (str(r.get('variant', '')), r.get('direction'), r.get('d2d_mode'),
            float(r.get('peak_depth_k', r.get('k', 0)) or 0),
            float(r.get('duration_at_depth', r.get('duration', 0)) or 0),
            float(r.get('regime', -9) if r.get('regime') is not None else -9),
            float(r.get('cluster', -9) if r.get('cluster') is not None else -9),
            float(r.get('share', -9) if r.get('share') == r.get('share') else -9),
            float(r.get('perm', -9) if r.get('perm') is not None else -9))


def _compare(p, s, cols, tag):
    if len(p) != len(s):
        return False, f"{tag}: LEN {len(p)} vs {len(s)}"
    for rp, rs in zip(p, s):
        for c in cols:
            a, b = rp.get(c), rs.get(c)
            if a != b and not (a != a and b != b):
                return False, f"{tag}: mismatch {c} ({a} vs {b})"
    return True, f"{tag}: PASS {len(p)} rows x {len(cols)} cols"


def _parity_generic_cfgs(ctx, n_workers, proof):
    out = []
    cfgs5b, cat = stage5b_category_depth(ctx, [2, 3], n_workers, 2.0, proof=True,
                                         return_cfgs=True)
    out.append(('stage5b', cfgs5b[:8], {'cat_depth': cat}))
    cfgs8 = stage8_null_baseline(ctx, [], n_workers, 2.0, proof=True, return_cfgs=True)
    out.append(('stage8', cfgs8[:8], None))
    return out


# ── drivers ──────────────────────────────────────────────────────────────
def run(proof=False, n_workers=N_WORKERS):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    t0 = time.time()
    k_vals = [20, 30] if proof else list(range(K_MIN, K_MAX + 1, K_STEP))
    durs = [1, 2] if proof else DURATIONS
    floors = [30, 40] if proof else ONSET_FLOORS
    nsw = [2, 3, 4] if proof else CLUSTER_N_SWEEP
    if proof:
        n_workers = min(n_workers, 2)
    ctx = build_context()
    n_cfg = len(k_vals) * len(durs) * len(DIRECTIONS) * len(D2D_MODES)
    print(f"\n=== F12 CONCURRENCE PROFILER | {'PROOF' if proof else 'FULL'} | "
          f"start {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"PRIMARY pool: {len(ctx['long_lbls'])} long-aligned + {len(ctx['short_lbls'])} "
          f"short-aligned of {len(ctx['pool'])} conditions (no triplet, no signal list, "
          f"no survivor filter)")
    print(f"Outcome-map grid (stage 4, ratified): k {min(k_vals)}..{max(k_vals)} x "
          f"dur {durs} x {len(DIRECTIONS)} dir x {len(D2D_MODES)} d2d = {n_cfg:,} configs | "
          f"workers {n_workers}")
    print(f"Stage order: 1 depth | 2 events | 3 entry_order | 4 outcome_map | "
          f"6 regimes | 5 composition (regime-aware) | 5b category_depth | "
          f"7 d2d_flips | 8 null_baseline\n", flush=True)

    # Regime labels FIRST so every downstream table can be regime-tagged.
    compute_regime_labels(ctx, nsw)

    stage1_depth_bars(ctx)
    _, ev_index = stage2_events(ctx, floors)
    stage3_entry_order(ctx, ev_index)
    ok = True
    if proof:
        ok = parity_check(ctx, k_vals, durs, n_workers, proof=True)
    observed = stage4_outcome_map(ctx, k_vals, durs, DIRECTIONS, D2D_MODES, n_workers,
                                  PROGRESS_INTERVAL)
    stage6_regimes(ctx, k_vals, n_workers, PROGRESS_INTERVAL)
    stage5_composition(ctx, ev_index, nsw)
    stage5b_category_depth(ctx, nsw, n_workers, PROGRESS_INTERVAL, proof=proof)
    ev_index.clear()
    gc.collect()
    stage7_d2d_flips(ctx)
    stage8_null_baseline(ctx, observed, n_workers, PROGRESS_INTERVAL, proof=proof)

    # SECONDARY view (comparison lens): same measurement, conditions restricted to
    # those appearing in F0's deduped survivors. On the real survivors file this is
    # 231 of the 249 conditions (113 long + 103 short aligned, against the primary's
    # 117 + 110) with max reachable depth 84 — so the two views are NEAR-IDENTICAL
    # and the ceiling below trims nothing. That near-identity is itself the finding:
    # F0's survivors do not draw on a special subset of variables. The ceiling logic
    # is retained only because it is safe — it can drop k-values above this pool's
    # maximum reachable depth, which are necessarily empty cells — and it announces
    # itself ONLY when it actually binds.
    keep = survivor_conditions()
    if keep:
        ctx2 = build_context(secondary=True, base=ctx)
        maxd = int(max(ctx2['depth_long'].max(), ctx2['depth_short'].max()))
        k_sec = [k for k in k_vals if k <= maxd] or list(range(1, max(maxd, 1) + 1))
        binds = len(k_sec) != len(k_vals)
        note = (f" -> ceiling BINDS: k grid {min(k_sec)}..{max(k_sec)} "
                f"({len(k_vals) - len(k_sec)} k-values above max depth dropped as "
                f"necessarily-empty)") if binds else " -> ceiling does not bind: full primary k grid used"
        _stamp('SECONDARY', f"survivor-only pool: {len(ctx2['long_lbls'])} long + "
                            f"{len(ctx2['short_lbls'])} short conditions "
                            f"(primary: {len(ctx['long_lbls'])} + {len(ctx['short_lbls'])}) | "
                            f"max reachable depth {maxd}{note}")
        stage4_outcome_map(ctx2, k_sec, durs, DIRECTIONS, D2D_MODES, n_workers,
                           PROGRESS_INTERVAL, tag='concurrence_outcome_map_secondary.csv')

    print(f"\n=== DONE | total elapsed {_fmt_hms(time.time() - t0)} ===")
    for f in ['concurrence_depth_bars.csv', 'concurrence_events.csv',
              'concurrence_entry_order.csv', 'concurrence_outcome_map.csv',
              'concurrence_composition.csv', 'concurrence_category_depth.csv',
              'concurrence_regimes.csv', 'concurrence_d2d_flips.csv',
              'concurrence_null_baseline.csv']:
        print(f"  {os.path.join(RESULTS_DIR, f)}")
    if proof:
        print(f"\n[PARITY] {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == '__main__':
    # Force the SPAWN start method. This is what Windows uses natively, so the
    # tested path and the operator's path are identical; on Linux it also avoids
    # the fork-after-threads deadlock that a later Pool inherits once numpy/pandas
    # have started worker threads in the parent (observed as a silent hang after a
    # stage's chunks complete). Stage 4's ratified code is unchanged — only the
    # process start method is set, once, before any Pool is created.
    import multiprocessing as _mp
    try:
        _mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == 'proof':
        run(proof=True)
    else:
        run(proof=False, n_workers=int(sys.argv[1]) if len(sys.argv) > 1 else N_WORKERS)
