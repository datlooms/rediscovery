import os
import sys
import glob
import json
import time
import shutil

# ═══════════════════════════════════════════════════════════════
#  equiDOT — F13 SINGLE-VARIABLE EXTREMES (standalone, NOT convergence)
#
#  A deliberately separate cave from the F0-F12 convergence families. It hunts
#  the simplest possible entry: ONE variable at ONE threshold that on its own
#  yields ~100% WR AND ~100% persistence AND fires often enough to be real (the
#  "Heart of the Ocean"). No triples, no convergence depth — single measurements.
#
#  HYPOTHESIS: the convergence work assumed one variable is never enough. Never
#  tested: is there a lone variable at an extreme tail (p95-p99 / p1-p5) that is
#  bulletproof alone? A clean NEGATIVE (singles don't carry it, convergence is
#  necessary) is a valuable documented finding.
#
#  SCAN, per condition:
#    - 88 D-adaptive FEAT: percentile SWEEP through the ratified oracle. hi side
#      {p50,60,70,80,90,95,97,99}; lo side {p50,40,30,20,10,5,3,1}. Swept by
#      feeding dots_thresholds its OWN compute_adaptive_thresholds through a
#      runtime-extended _D_SPEC (no source edit, no re-implementation), restored
#      after. Extreme tails are the primary target.
#    - 2 structural FEAT (VWAP_Z, OR_Position): the oracle's fixed structural
#      hi/lo (not percentile-swept — that is their ratified mechanism).
#    - 69 equality conditions (binary/state/side): scanned by ==value.
#  Each condition x {long, short} x {D2D-aligned, D2D-counter}. D2D stays the
#  perpetual gate (always computed); counter flips the polarity of that gate.
#
#  SCORING: every candidate runs through the RATIFIED engine (portfolio_
#  simulation_engine — the merged jar + runner + momentum-SL TM) via an injected
#  ==1 signal, and wf.py for the daily vector. true $1/pt.
#
#  SURVIVAL BAR (persistence CO-EQUAL with WR): a star needs ALL of
#    (1) WR at/near 100%, (2) 100% persistence (won every fold/week/weekday it
#    touched), (3) frequency >= 22 firings (>= weekly; ideal ~106 = daily).
#  Tiers: SURFACE >=90% WR (see the fall-off); CANDIDATE >=95% WR & >=22 firings
#  & full-span persistence; STAR 100% WR & 100% persistence & >= weekly.
#
#  GATING: standard gate (engine intrinsic ADX>=15 & Vol>50, solo Vol>=300) is
#  the primary. A tighter-gate variant is available via mask_window (AND-only).
#  A looser 'no-gate' variant would require loosening the engine's intrinsic
#  eligible gate, which is sacred entry infrastructure and is not modified here;
#  that variant is reported as not-run (needs an engine gate-parameter change
#  through the pipeline), never faked.
#
#  Infra: shard by variable (bounds per-worker swept-threshold memory), spawn MP
#  (12 workers stable / 16 freezes), live progress + ETA, atomic checkpoint /
#  crash-resume (.done written last), deterministic.
# ═══════════════════════════════════════════════════════════════

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
for _d in ('engine', 'scanners', 'orchestrator'):
    _p = os.path.join(_ROOT, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _baseline_dir():
    probe = 'equiDOT_recon171_step7_part1.csv'
    for cand in (_ROOT, os.path.join(_ROOT, 'data')):
        if os.path.exists(os.path.join(cand, probe)):
            return cand
    return _ROOT


import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import sequential_temporal as seq
import wf

FAMILY = 'F13'
INJ = '__F13_SIG'
HI_PCTS = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.97, 0.99]
LO_PCTS = [0.50, 0.40, 0.30, 0.20, 0.10, 0.05, 0.03, 0.01]
MIN_FIRINGS = 22
IDEAL_FIRINGS = 106
WEEKS_TOTAL = 22
WEEKS_NEAR = 20
WEEKDAYS_MIN = 5
N_WORKERS = 12
SHARD_VARS = 4

RESULTS_DIR = os.path.join(_ROOT, 'discovery_results')
OUT_CSV = os.path.join(RESULTS_DIR, 'results_F13_single_variable_extremes.csv')
SHARD_DIR = os.path.join(RESULTS_DIR, '_f13_shards')

_CTX = {}


def _pf(p):
    g = p[p > 0].sum()
    l = -p[p < 0].sum()
    if l == 0:
        return 999.0 if g > 0 else 0.0
    return round(float(g / l), 3)


def build_context():
    os.chdir(_baseline_dir())
    df = engine.load_sealed_baseline(verbose=False)
    warmup = engine.warmup_floor(df, verbose=False)
    structural = dt.compute_structural_gates(df)
    times = df['Time'].values.astype(str)
    day = np.array([t[:10] for t in times])
    month = pd.Series(times).str[:7].values
    dts = pd.to_datetime(pd.Series(times).str[:10], format='%Y.%m.%d')
    iso = dts.dt.isocalendar()
    iso_week = (iso['year'].astype(int) * 100 + iso['week'].astype(int)).values
    dow = df['EST_DayOfWeek'].values
    d2d_orig = df['D2D_Trend_Dir'].values.copy()
    if INJ not in df.columns:
        df[INJ] = 0
    return {'df': df, 'warmup': warmup, 'structural': structural, 'day': day,
            'month': month, 'iso_week': iso_week, 'dow': dow, 'd2d_orig': d2d_orig}


def swept_thresholds(df, feats):
    saved = dict(dt._D_SPEC)
    spec = {}
    for f in feats:
        for p in HI_PCTS:
            spec[(f, f'hi_{int(round(p*100)):02d}')] = (f, p)
        for p in LO_PCTS:
            spec[(f, f'lo_{int(round(p*100)):02d}')] = (f, p)
    try:
        dt._D_SPEC.clear()
        dt._D_SPEC.update(spec)
        out = dt.compute_adaptive_thresholds(df)
    finally:
        dt._D_SPEC.clear()
        dt._D_SPEC.update(saved)
    return out


def condition_masks(ctx, feat):
    df = ctx['df']
    vals = df[feat].values
    out = []
    thr = swept_thresholds(df, [feat])
    for p in HI_PCTS:
        t = thr[(feat, f'hi_{int(round(p*100)):02d}')]
        out.append((f'{feat}:hi@p{int(round(p*100))}', vals > t))
    for p in LO_PCTS:
        t = thr[(feat, f'lo_{int(round(p*100)):02d}')]
        out.append((f'{feat}:lo@p{int(round(p*100))}', vals < t))
    return out


STRUCT_CONST = {'VWAP_Z': (2.0, -2.0), 'OR_Position': (0.80, 0.20)}


def _structural_masks(ctx, feat):
    df = ctx['df']
    vals = df[feat].values
    hi_c, lo_c = STRUCT_CONST[feat]
    mh = vals > hi_c
    ml = vals < lo_c
    if feat == 'OR_Position':
        gate = ctx['structural']['OR_Position']
        mh = mh & gate
        ml = ml & gate
    return [(f'{feat}:hi', mh), (f'{feat}:lo', ml)]


def _equality_masks(ctx, feat, values):
    df = ctx['df']
    vals = df[feat].values
    return [(f'{feat}:=={v}', vals == v) for v in values]


def score_candidate(ctx, base_mask, direction, d2d_mode, tighter=None):
    df = ctx['df']
    d2d_orig = ctx['d2d_orig']
    dir_int = 1 if direction == 'LONG' else -1
    df[INJ] = base_mask.astype(int)
    if d2d_mode == 'aligned':
        df['D2D_Trend_Dir'] = d2d_orig
    else:
        df['D2D_Trend_Dir'] = -d2d_orig
    sig = pd.DataFrame([{'feat_1': INJ, 'thresh_1': '==1', 'feat_2': INJ, 'thresh_2': '==1',
                         'feat_3': INJ, 'thresh_3': '==1', 'direction': direction}])
    try:
        td = engine.run_portfolio(df, sig, mask_window=tighter, adaptive={},
                                  structural=ctx['structural'], warmup=ctx['warmup'],
                                  verbose=False)
    finally:
        df['D2D_Trend_Dir'] = d2d_orig
    d2d_gate = (d2d_orig == dir_int) if d2d_mode == 'aligned' else (d2d_orig == -dir_int)
    firings = int((base_mask & d2d_gate).sum())
    return td, firings


def summarize(ctx, td, mask_bars, label, direction, d2d_mode, gating):
    n = len(td)
    rec = {'family': FAMILY, 'signal_def': label, 'direction': direction,
           'd2d_mode': d2d_mode, 'gating': gating, 'trades': n, 'total_firings': n,
           'firings_per_week': round(n / 22.0, 2), 'firings_per_day': round(n / 106.0, 3),
           'mask_bars': mask_bars}
    if n == 0:
        rec.update({'WR': 0.0, 'wr_pre_fc': 0.0, 'wr_post_fc': 0.0, 'agg_pf': 0.0,
                    'worst_day_usd': 0.0, 'folds_plus': 0, 'persistence': 0.0, 'weeks_present': 0, 'weeks_won': 0,
                    'weekdays_present': 0, 'weekdays_won': 0, 'exit_FC': 0, 'exit_EOD': 0,
                    'survival': False, 'tier': 'none'})
        return rec
    pnl = td['pnl'].values
    exit_bar = td['exit_bar'].values
    wins = pnl > 0
    et = td['exit_type'].values
    non_fc = et != 'FC'
    rec['wr_post_fc'] = round(float(wins.mean() * 100), 1)
    rec['wr_pre_fc'] = round(float(wins[non_fc].mean() * 100), 1) if non_fc.sum() else 0.0
    rec['WR'] = rec['wr_post_fc']
    rec['agg_pf'] = _pf(pnl)
    dd = ctx['day'][exit_bar]
    daily = {k: pnl[dd == k].sum() for k in np.unique(dd)}
    rec['worst_day_usd'] = round(float(min(daily.values())), 1)
    mm = ctx['month'][exit_bar]
    folds = {}
    for label2, mkey in wf.FOLDS:
        m = mm == mkey
        if m.sum():
            folds[label2] = pnl[m].sum()
    folds_present = len(folds)
    folds_won = sum(1 for v in folds.values() if v > 0)
    rec['folds_plus'] = folds_won
    ww = ctx['iso_week'][exit_bar]
    weeks = {k: pnl[ww == k].sum() for k in np.unique(ww)}
    rec['weeks_present'] = len(weeks)
    rec['weeks_won'] = int(sum(1 for v in weeks.values() if v > 0))
    dw = ctx['dow'][exit_bar]
    wkd = {k: pnl[dw == k].sum() for k in np.unique(dw)}
    rec['weekdays_present'] = len(wkd)
    rec['weekdays_won'] = int(sum(1 for v in wkd.values() if v > 0))
    rec['exit_FC'] = int((et == 'FC').sum())
    rec['exit_EOD'] = int((et == 'EOD').sum())
    span_present = folds_present + rec['weeks_present'] + rec['weekdays_present']
    span_won = folds_won + rec['weeks_won'] + rec['weekdays_won']
    rec['persistence'] = round(span_won / span_present * 100, 1) if span_present else 0.0
    full_folds = folds_won == len(wf.FOLDS)
    full_span = (full_folds and rec['weeks_present'] >= WEEKS_TOTAL
                 and rec['weeks_won'] == rec['weeks_present']
                 and rec['weekdays_present'] >= WEEKDAYS_MIN
                 and rec['weekdays_won'] == rec['weekdays_present'])
    near_span = (full_folds and rec['weeks_present'] >= WEEKS_NEAR
                 and rec['weeks_won'] == rec['weeks_present']
                 and rec['weekdays_present'] >= WEEKDAYS_MIN
                 and rec['weekdays_won'] == rec['weekdays_present'])
    freq_ok = n >= MIN_FIRINGS
    rec['survival'] = bool(rec['wr_post_fc'] >= 95 and freq_ok and near_span)
    if rec['wr_post_fc'] >= 100 and freq_ok and full_span:
        rec['tier'] = 'STAR'
    elif rec['survival']:
        rec['tier'] = 'candidate'
    elif rec['wr_post_fc'] >= 90:
        rec['tier'] = 'surface'
    else:
        rec['tier'] = 'none'
    return rec


def _eq_values(ctx, feat):
    v = ctx['df'][feat].values
    u = sorted(int(x) for x in np.unique(v))
    return [x for x in u if len(u) <= 12 or x in (-1, 0, 1, 2, -2)]


def process_shard(task):
    idx, feats, families = task
    done = os.path.join(SHARD_DIR, f'shard_{idx:04d}.done')
    if os.path.exists(done):
        return (idx, -1)
    ctx = _CTX['ctx']
    rows = []
    for feat, kind in zip(feats, families):
        if kind == 'adaptive':
            masks = condition_masks(ctx, feat)
        elif kind == 'structural':
            masks = _structural_masks(ctx, feat)
        else:
            masks = _equality_masks(ctx, feat, _eq_values(ctx, feat))
        for label, bm in masks:
            for direction in ('LONG', 'SHORT'):
                for d2d_mode in ('aligned', 'counter'):
                    td, mask_bars = score_candidate(ctx, bm, direction, d2d_mode)
                    rec = summarize(ctx, td, mask_bars, label, direction, d2d_mode, 'standard')
                    if rec['WR'] >= 90 or rec['trades'] >= MIN_FIRINGS:
                        rows.append(rec)
    tmp = os.path.join(SHARD_DIR, f'shard_{idx:04d}.csv.tmp')
    pd.DataFrame(rows).to_csv(tmp, index=False, lineterminator='\n')
    os.replace(tmp, os.path.join(SHARD_DIR, f'shard_{idx:04d}.csv'))
    with open(done, 'w', encoding='utf-8') as f:
        f.write(f'{len(rows)} surfaced\n')
    return (idx, len(rows))


def _init():
    _CTX['ctx'] = build_context()


def _hms(s):
    s = int(s)
    return f'{s//3600}:{(s%3600)//60:02d}:{s%60:02d}'


def build_worklist(ctx):
    from dots_thresholds import _D_SPEC, _STRUCTURAL
    adaptive_feats = sorted(set(c for (c, _) in _D_SPEC.values()))
    structural_feats = sorted(set(f for (f, _) in _STRUCTURAL))
    pool = seq.build_condition_pool(ctx['df'], dt.compute_adaptive_thresholds(ctx['df']),
                                    ctx['structural'], ctx['warmup'])
    eqs = {}
    for lbl in pool:
        if ':==' in lbl:
            eqs.setdefault(lbl.split(':==')[0], True)
    items = [(f, 'adaptive') for f in adaptive_feats]
    items += [(f, 'structural') for f in structural_feats]
    items += [(f, 'equality') for f in sorted(eqs)]
    return items


def run(n_workers=N_WORKERS):
    from multiprocessing import Pool
    t0 = time.time()
    os.makedirs(SHARD_DIR, exist_ok=True)
    ctx = build_context()
    items = build_worklist(ctx)
    shards = [items[i:i + SHARD_VARS] for i in range(0, len(items), SHARD_VARS)]
    tasks = []
    for i, sh in enumerate(shards):
        tasks.append((i, [f for f, _ in sh], [k for _, k in sh]))
    total = len(tasks)
    remaining = [t for t in tasks if not os.path.exists(os.path.join(SHARD_DIR, f'shard_{t[0]:04d}.done'))]
    done0 = total - len(remaining)
    print(f'=== F13 SINGLE-VARIABLE EXTREMES ===')
    print(f'{len(items)} variables | {total} shards ({SHARD_VARS} vars/shard) | '
          f'workers {n_workers} | resume {done0}/{total} done', flush=True)
    completed = done0
    if remaining:
        with Pool(n_workers, initializer=_init) as p:
            for _ in p.imap_unordered(process_shard, remaining):
                completed += 1
                el = time.time() - t0
                rate = (completed - done0) / el if el > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                sys.stdout.write(f'\r  {completed}/{total} shards | elapsed {_hms(el)} | ETA {_hms(eta)}   ')
                sys.stdout.flush()
    sys.stdout.write('\n')
    parts = []
    for f in sorted(glob.glob(os.path.join(SHARD_DIR, 'shard_*.csv'))):
        try:
            parts.append(pd.read_csv(f))
        except pd.errors.EmptyDataError:
            continue
    res = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(res):
        res = res.sort_values(['persistence', 'WR', 'total_firings'],
                              ascending=[False, False, False]).reset_index(drop=True)
    tmp = OUT_CSV + '.tmp'
    res.to_csv(tmp, index=False, lineterminator='\n')
    os.replace(tmp, OUT_CSV)
    stars = res[res.tier == 'STAR'] if len(res) else res
    cands = res[res.tier == 'candidate'] if len(res) else res
    print(f'=== DONE | {len(res)} surfaced (>=90% WR or >=22 firings) | '
          f'{len(cands)} candidates | {len(stars)} STARS | elapsed {_hms(time.time()-t0)} ===')
    print(f'  {OUT_CSV}')
    if len(stars):
        print('  STARS:')
        for _, r in stars.iterrows():
            print(f"    {r.signal_def} {r.direction}/{r.d2d_mode} WR={r.WR} firings={r.total_firings} persist={r.persistence}")
    elif len(cands):
        print('  CANDIDATES (>=95% WR, >=22 firings, full-span):')
        for _, r in cands.head(20).iterrows():
            print(f"    {r.signal_def} {r.direction}/{r.d2d_mode} WR={r.WR} firings={r.total_firings} persist={r.persistence}")
    else:
        print('  NEGATIVE: no candidate-tier single-variable signal. Convergence is necessary.')
    return res


if __name__ == '__main__':
    import multiprocessing as mp
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
    run(int(sys.argv[1]) if len(sys.argv) > 1 else N_WORKERS)
