import os
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  equiDOT — ANALYSIS ENGINE (F0 triple-convergence, S.7 trade management)
#
#  ONE trade management = S.7, reused BIT-FOR-BIT: every signal is scored by
#  engine.run_portfolio (the ratified locked TM). Nothing here reconstructs SL /
#  BE / LeapFrog / Friday-close. The only per-signal step is turning an F0
#  signal_def back into an entry mask via the RATIFIED engine.condition_mask,
#  then injecting it as a one-column '==1' signal — proven identical to a native
#  engine run.
#
#    F0  'featA:thrA + featB:thrB + featC:thrC'  -> AND of engine.condition_mask,
#        three conditions simultaneously on the same bar, D2D-aligned.
#
#  Scope is F0 triple-convergence ONLY (the validated diamond book and the EA's
#  native design). No F1 sequential / anchor logic.
#
#  Three persistence scales, all from REAL bar timestamps (no fold indices):
#    Monthly     : the 6 wf folds (Jan19-31, Feb, Mar, Apr, May, Jun1-25)
#    Weekly      : ISO-week folds (year, week) — trades/WR/PF/net/sign
#    Day-of-week : Sun..Fri pooled — trades/WR/PF/net (EST_DayOfWeek 0..5)
#
#  Standalone scoring per signal. The in-book/portfolio layer is NOT computed
#  here; it is derived later from the exported per-CALENDAR-DAY P&L vector.
#  Units: $1/point/lot via wf.points_to_usd (corrected constant).
#
#  Thresholds: dots_thresholds oracle, SACRED, unchanged. Zero reconstruction.
#
#  Layout: this file lives in dot_master_discovery/engine/ alongside the ratified
#  engine. load_sealed_baseline() reads the baseline by bare filename (CWD-
#  relative); the driver (run_full_analysis.py) chdirs into the baseline
#  directory in each worker before build_context() is called, so the loader
#  resolves correctly regardless of where the operator runs from.
# ═══════════════════════════════════════════════════════════════

INJ_COL = '__ANALYSIS_SIG'


# ── context (built once per process) ─────────────────────────────────────
def build_context():
    df = engine.load_sealed_baseline(verbose=False)
    warmup = engine.warmup_floor(df, verbose=False)
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    times = df['Time'].values.astype(str)
    day = np.array([t[:10].replace('.', '-') for t in times])          # calendar day
    month = pd.Series(times).str[:7].values                            # wf fold key
    dts = pd.to_datetime(pd.Series(times).str[:10], format='%Y.%m.%d')
    iso = dts.dt.isocalendar()
    iso_week = (iso['year'].astype(int) * 100 + iso['week'].astype(int)).values
    dow = df['EST_DayOfWeek'].values                                   # 1=Mon..5=Fri
    if INJ_COL not in df.columns:
        df[INJ_COL] = 0
    return {'df': df, 'warmup': warmup, 'adaptive': adaptive, 'structural': structural,
            'day': day, 'month': month, 'iso_week': iso_week, 'dow': dow}


# ── signal_def -> entry mask (ratified builder only) ─────────────────────
def f0_mask(ctx, signal_def):
    parts = [p.strip() for p in signal_def.split('+')]
    if len(parts) != 3:
        raise ValueError(f"F0 signal_def not a triple: {signal_def}")
    m = np.ones(len(ctx['df']), dtype=bool)
    for p in parts:
        feat, thr = p.rsplit(':', 1)
        m &= engine.condition_mask(ctx['df'], feat.strip(), thr.strip(),
                                   ctx['adaptive'], ctx['structural'])
    return m


def build_mask(ctx, family, signal_def):
    if family == 'F0':
        return f0_mask(ctx, signal_def)
    raise ValueError(f"analysis engine scoped to F0 only, got {family}")


# ── S.7 scoring (bit-for-bit via engine.run_portfolio) ───────────────────
def _apply_d2d(df, mode, direction, orig):
    # F0/F1 in this field are almost all 'confirm'; invert/exempt handled via the
    # sanctioned input-column reconstruction (D2D is gate-only in the engine).
    if mode == 'confirm':
        df['D2D_Trend_Dir'] = orig
    elif mode == 'invert':
        df['D2D_Trend_Dir'] = -orig
    elif mode == 'exempt':
        df['D2D_Trend_Dir'] = np.full(len(df), direction, dtype=orig.dtype)
    else:
        raise ValueError(f"unknown d2d mode '{mode}'")


def score_signal(ctx, family, signal_def, direction, d2d_mode, orig):
    df = ctx['df']
    mask = build_mask(ctx, family, signal_def)
    df[INJ_COL] = mask.astype(int)
    dir_int = 1 if direction == 'LONG' else -1
    _apply_d2d(df, d2d_mode, dir_int, orig)
    sig = pd.DataFrame([{'feat_1': INJ_COL, 'thresh_1': '==1',
                         'feat_2': INJ_COL, 'thresh_2': '==1',
                         'feat_3': INJ_COL, 'thresh_3': '==1',
                         'direction': direction}])
    try:
        td = engine.run_portfolio(df, sig, mask_window=None, adaptive=ctx['adaptive'],
                                  structural=ctx['structural'], warmup=ctx['warmup'],
                                  verbose=False)
    finally:
        df['D2D_Trend_Dir'] = orig
    return td


# ── metrics ──────────────────────────────────────────────────────────────
def _pf(pnls):
    g = pnls[pnls > 0].sum()
    l = -pnls[pnls < 0].sum()
    if l == 0:
        return 999.0 if g > 0 else 0.0
    return round(float(g / l), 3)


def _bucket(td, keys):
    # td aligned with a same-length key array; returns {key: (trades,wr,pf,net)}
    out = {}
    pnl = td['pnl'].values
    for kv in np.unique(keys):
        m = keys == kv
        p = pnl[m]
        n = int(m.sum())
        out[kv] = (n, round(float((p > 0).sum() / n * 100.0), 1) if n else 0.0,
                   _pf(p), round(float(p.sum()), 1))
    return out


def _exit_bar_key(ctx, td, which):
    # bucket a trade by the calendar attribute of its EXIT bar (no look-ahead:
    # the trade is fully closed at exit_bar; bucketing a realised P&L by its own
    # close time uses only past/known information).
    return ctx[which][td['exit_bar'].values]


def summarize(ctx, td, family, signal_def, direction, d2d_mode):
    rec = {'signal_def': signal_def, 'family': family, 'direction': direction,
           'd2d_mode': d2d_mode}
    n = len(td)
    if n == 0:
        rec.update({'trades': 0, 'WR': 0.0, 'agg_pf': 0.0, 'net_pts': 0.0,
                    'worst_day': 0.0, 'folds_plus': 0, 'min_fold_pf': 0.0})
        rec['_empty'] = True
        return rec
    pnl = td['pnl'].values
    rec['trades'] = n
    rec['WR'] = round(float((pnl > 0).sum() / n * 100.0), 1)
    rec['agg_pf'] = _pf(pnl)
    rec['net_pts'] = round(float(pnl.sum()), 1)

    # ---- per-day (calendar) P&L vector — the anti-fabrication core ----
    exit_day = _exit_bar_key(ctx, td, 'day')
    day_keys = np.unique(exit_day)
    day_net = {str(k): round(float(pnl[exit_day == k].sum()), 1) for k in day_keys}
    rec['per_day_pnl'] = day_net
    day_vals = np.array(list(day_net.values()))
    rec['worst_day'] = round(float(day_vals.min()), 1) if len(day_vals) else 0.0

    # ---- monthly (wf folds) ----
    exit_month = _exit_bar_key(ctx, td, 'month')
    fold_plus = 0
    fold_pfs = []
    for label, mkey in wf.FOLDS:
        m = exit_month == mkey
        p = pnl[m]
        nt = int(m.sum())
        pf = _pf(p) if nt else 0.0
        net = round(float(p.sum()), 1)
        rec[f'fold_{label}_pf'] = pf
        rec[f'fold_{label}_trades'] = nt
        rec[f'fold_{label}_net'] = net
        if net > 0:
            fold_plus += 1
        if nt > 0:
            fold_pfs.append(pf)
    rec['folds_plus'] = fold_plus
    rec['min_fold_pf'] = min(fold_pfs) if fold_pfs else 0.0

    # ---- weekly (ISO) ----
    exit_week = _exit_bar_key(ctx, td, 'iso_week')
    wk = _bucket(td, exit_week)
    weekly = []
    for kv in sorted(wk):
        nt, w, pf, net = wk[kv]
        weekly.append({'iso': int(kv), 'trades': nt, 'WR': w, 'pf': pf, 'net': net,
                       'sign': int(np.sign(net))})
    rec['weekly'] = weekly
    wnets = np.array([w['net'] for w in weekly]) if weekly else np.array([])
    rec['worst_week'] = round(float(wnets.min()), 1) if len(wnets) else 0.0

    # ---- day-of-week (Sun..Fri pooled) ----
    # EST_DayOfWeek: 0=Sun (US30 Sunday-evening open), 1=Mon .. 5=Fri. Sunday MUST
    # be included or closed-on-Sunday trades drop out and dow nets stop summing.
    exit_dow = _exit_bar_key(ctx, td, 'dow')
    names = {0: 'Sun', 1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri'}
    for d, nm in names.items():
        m = exit_dow == d
        p = pnl[m]
        nt = int(m.sum())
        rec[f'dow_{nm}_trades'] = nt
        rec[f'dow_{nm}_WR'] = round(float((p > 0).sum() / nt * 100.0), 1) if nt else 0.0
        rec[f'dow_{nm}_pf'] = _pf(p) if nt else 0.0
        rec[f'dow_{nm}_net'] = round(float(p.sum()), 1)

    # ---- exit distribution ----
    for et in ['SL', 'BE', 'LF', 'FC', 'EOD']:
        m = td['exit_type'].values == et
        rec[f'exit_{et}_count'] = int(m.sum())
        rec[f'exit_{et}_pnl'] = round(float(pnl[m].sum()), 1)

    # ---- risk texture ----
    order = np.argsort(td['exit_bar'].values, kind='stable')
    seq_pnl = pnl[order]
    rec['longest_losing_streak'] = _max_run(seq_pnl < 0)
    day_sorted = [day_net[str(k)] for k in sorted(day_net, key=lambda x: x)]
    day_chron = [day_net[k] for k in sorted(day_net)]
    rec['max_consecutive_losing_days'] = _max_run(np.array(day_chron) < 0)

    rec['_empty'] = False
    return rec


def _max_run(boolarr):
    best = cur = 0
    for b in boolarr:
        cur = cur + 1 if b else 0
        best = max(best, cur)
    return int(best)


# ── one candidate end to end ─────────────────────────────────────────────
def evaluate(ctx, family, signal_def, direction, d2d_mode, orig):
    td = score_signal(ctx, family, signal_def, direction, d2d_mode, orig)
    return summarize(ctx, td, family, signal_def, direction, d2d_mode)


def orig_d2d(ctx):
    return ctx['df']['D2D_Trend_Dir'].values.copy()
