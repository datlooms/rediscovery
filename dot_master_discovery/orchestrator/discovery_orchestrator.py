import sys
import os
import time
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

import sequential_temporal as f1
import state_transition as f2
import conditional_interaction as f3
import divergence_nonconfirm as f4
import persistence_autocorr as f5
import threshold_crossing as f6
import mean_reversion as f7
import cross_variable_structure as f8
import session_temporal as f9
import rolling_leadlag as f11

# ═══════════════════════════════════════════════════════════════
#  equiDOT — STAGE 8 DISCOVERY ORCHESTRATOR
#  Drives the 11 ratified family scanners at a chosen scope, normalizes
#  every returned row to ONE common schema, writes one CSV per family, and
#  collates discovery_master.csv. Adds ZERO signal logic, ZERO threshold /
#  TM reconstruction — it only calls the scanners' run_search and collects.
#
#  Baseline + oracle are loaded ONCE and passed into every scanner so
#  nothing recomputes. F0 is the heaviest (C(117,3)=260,130 triples with
#  density fused); it is run SEPARATELY and its CSV ingested (see ingest_f0
#  / the F0 note at the bottom), so the orchestrator never holds the full F0
#  search in-process.
#
#  Operator params (this run): target lot 1.0 (worst-day at 1 lot; scale
#  after). F0 internal pre-gate MIN_PF=2.0 is a TRIM in the F0 script, not a
#  selection cut. worst_day_usd is emitted RAW and is a ranking axis to
#  minimize toward 0 — NOT hard-gated at -2500. The only floor at collection
#  is each scanner's MIN_TRADES sample-size floor; no PF/worst-day selection
#  cut is baked in. Collect ALL candidates (survivors AND rejects).
# ═══════════════════════════════════════════════════════════════

RESULTS_DIR = "discovery_results"
SCHEMA = ['family', 'script', 'signal_def', 'direction', 'd2d_mode', 'trades', 'WR',
          'agg_pf', 'worst_day_usd', 'hard_stop_days', 'folds_plus', 'min_fold_pf',
          'spread_pf', 'survival']
F0_CSV = "results_F0_triple_convergence_and_d2ddir.csv"
F1_CSV = "results_F1_sequential_temporal.csv"

# Candidate-count guard: permutation families (F1) explode as O(pool^3). At
# 'full' the orchestrator PRINTS the computed candidate count and warns; the
# operator bounds the pool via SCOPE. It does not silently shrink the space.
MAX_CANDIDATES_WARN = 500000


def _metric_map(row):
    return {
        'trades': row['trades'], 'WR': row['agg_wr'], 'agg_pf': row['agg_pf'],
        'worst_day_usd': row['worst_day_usd'], 'hard_stop_days': row['hard_stop_days'],
        'folds_plus': row['profitable_folds'], 'min_fold_pf': row['min_fold_pf'],
        'spread_pf': f"{row['pf_base']}->{row['pf_stress']}", 'survival': row['survival_pass'],
    }


def _common(family, script, signal_def, direction, d2d_mode, row):
    r = {'family': family, 'script': script, 'signal_def': signal_def,
         'direction': direction, 'd2d_mode': d2d_mode}
    r.update(_metric_map(row))
    return r


# ── per-family scope builders: return kwargs for run_search ──────────────
def _scope(kind):
    proof = kind == 'proof'

    def f1_kw(df, adaptive, structural, warmup):
        pool = f1.build_condition_pool(df, adaptive, structural, warmup)
        labels = f1.scorable_pool(pool, warmup)
        if proof:
            labels = [l for l in ['ADX_Value:hi', 'Momentum_Value:hi', 'Sqz_State:==1',
                                  'RangeOsc_State:==1'] if l in labels]
            lags = [3, 5]
        else:
            lags = f1.LAGS
        n = len(labels) ** 2 * len(lags) * 2
        if not proof:
            print(f"[F1] full scope = {len(labels)}^2 x {len(lags)} lags x 2 dir = {n:,} candidates")
            if n > MAX_CANDIDATES_WARN:
                print(f"[F1 WARN] {n:,} ordered-pair candidates — heavy; run F1 out-of-process.")
        return dict(pool=pool, cond_labels=labels, lags=lags, anchor='ST_Flip',
                    directions=['LONG', 'SHORT'])

    def f2_kw(df, adaptive, structural, warmup):
        states = ['Sqz_State', 'ADX_Rising', 'RangeOsc_State'] if proof else f2.STATE_CANDIDATES
        pool = f2.build_transition_pool(df, states, warmup)
        return dict(pool=pool, cond_labels=list(pool.keys()), directions=['LONG', 'SHORT'])

    def f3_kw(df, adaptive, structural, warmup):
        if proof:
            base_labels = ['ADX_Value:hi', 'Momentum_Value:hi']
            states = ['AT_Regime_ST', 'Sqz_State']
        else:
            feats = list(dt._D_COLS) + ['VWAP_Z', 'OR_Position']
            base_labels = [f"{ft}:{t}" for ft in feats for t in ('hi', 'lo')]
            states = f3.GATE_STATES
        base_pool = f3.build_base_pool(df, base_labels, adaptive, structural)
        gate_masks = f3.build_gate_masks(df, states, warmup)
        return dict(base_pool=base_pool, gate_masks=gate_masks, directions=['LONG', 'SHORT'])

    def f4_kw(df, adaptive, structural, warmup):
        if proof:
            price = ['VWAP_Z', 'KAMA_Dist_ATR']
            flow = ['Micro_OrderFlowDelta', 'OBV_Macd']
        else:
            price, flow = f4.PRICE_FEATS, f4.FLOW_FEATS
        return dict(price_feats=price, flow_feats=flow, d2d_modes=['invert', 'exempt'],
                    orig=df['D2D_Trend_Dir'].values.copy())

    def f5_kw(df, adaptive, structural, warmup):
        states = ['Micro_AutoCorr', 'Efficiency_Ratio', 'KAMA_Slope'] if proof else f5.STATE_FEATS
        labels = [f"{s}:{t}" for s in states for t in ('hi', 'lo')]
        return dict(cond_labels=labels, directions=['LONG', 'SHORT'])

    def f6_kw(df, adaptive, structural, warmup):
        feats = ['Slope_Accel_ST', 'Momentum_Value', 'OBV_Velocity'] if proof else f6.CROSS_FEATS
        return dict(cross_feats=feats, roc_filter=None)

    def f7_kw(df, adaptive, structural, warmup):
        feats = ['VWAP_Z', 'KAMA_Dist_ATR', 'Session_High_Dist_ATR'] if proof else f7.STRETCH_FEATS
        return dict(stretch_feats=feats, d2d_modes=['invert', 'exempt'],
                    orig=df['D2D_Trend_Dir'].values.copy())

    def f8_kw(df, adaptive, structural, warmup):
        return dict(pairs=f8.PAIRS, directions=['LONG', 'SHORT'])

    def f9_kw(df, adaptive, structural, warmup):
        if proof:
            base_labels = ['ADX_Value:hi', 'Momentum_Value:hi', 'VWAP_Z:hi']
            weekdays = None
        else:
            feats = list(dt._D_COLS) + ['VWAP_Z', 'OR_Position']
            base_labels = [f"{ft}:hi" for ft in feats] + [f"{ft}:lo" for ft in feats]
            weekdays = f9.weekday_masks(df)
        sessions = f9.session_masks(df)
        return dict(base_labels=base_labels, sessions=sessions, weekdays=weekdays,
                    directions=['LONG', 'SHORT'])

    def f11_kw(df, adaptive, structural, warmup):
        windows = [60] if proof else f11.WINDOWS
        return dict(pairs=f11.PAIRS, windows=windows, relations=f11.RELATIONS,
                    directions=['LONG', 'SHORT'])

    return {'F1': f1_kw, 'F2': f2_kw, 'F3': f3_kw, 'F4': f4_kw, 'F5': f5_kw,
            'F6': f6_kw, 'F7': f7_kw, 'F8': f8_kw, 'F9': f9_kw, 'F11': f11_kw}


# ── per-family signal_def / d2d_mode formatters ──────────────────────────
def _rows_F1(rows, s):
    return [_common('F1', s, f"{r['A']} ->{r['k']}-> {r['B']}",
                    r['direction'], 'confirm', r) for r in rows]


def _rows_F2(rows, s):
    return [_common('F2', s, r['transition'], r['direction'], 'confirm', r) for r in rows]


def _rows_F3(rows, s):
    return [_common('F3', s, f"{r['base']} GATED-BY {r['gate']}", r['direction'], 'confirm', r)
            for r in rows]


def _rows_F4(rows, s):
    return [_common('F4', s, f"{r['price']} NOT-CONFIRMED-BY {r['nonconfirm_flow']}",
                    r['direction'], r['d2d'], r) for r in rows]


def _rows_F5(rows, s):
    return [_common('F5', s, r['condition'], r['direction'], 'confirm', r) for r in rows]


def _rows_F6(rows, s):
    return [_common('F6', s, f"{r['feat']} {r['cross']}(level={r['level']}) ROC={r['roc']}",
                    r['direction'], 'confirm', r) for r in rows]


def _rows_F7(rows, s):
    return [_common('F7', s, f"FADE {r['stretched']}", r['direction'], r['d2d'], r) for r in rows]


def _rows_F8(rows, s):
    return [_common('F8', s, r['relation'], r['direction'], 'confirm', r) for r in rows]


def _rows_F9(rows, s):
    return [_common('F9', s, f"{r['base']} IN-SESSION {r['session']}", r['direction'],
                    'confirm', r) for r in rows]


def _rows_F11(rows, s):
    return [_common('F11', s, f"{r['A']}<->{r['B']} N={r['N']} {r['relation']}",
                    r['direction'], 'confirm', r) for r in rows]


FAMILIES = [
    ('F1', 'sequential_temporal', f1, _rows_F1),
    ('F2', 'state_transition', f2, _rows_F2),
    ('F3', 'conditional_interaction', f3, _rows_F3),
    ('F4', 'divergence_nonconfirm', f4, _rows_F4),
    ('F5', 'persistence_autocorr', f5, _rows_F5),
    ('F6', 'threshold_crossing', f6, _rows_F6),
    ('F7', 'mean_reversion', f7, _rows_F7),
    ('F8', 'cross_variable_structure', f8, _rows_F8),
    ('F9', 'session_temporal', f9, _rows_F9),
    ('F11', 'rolling_leadlag', f11, _rows_F11),
]


def run_family(fam, script, mod, fmt, kw_builder, df, adaptive, structural, warmup):
    orig = df['D2D_Trend_Dir'].values.copy()
    kw = kw_builder(df, adaptive, structural, warmup)
    t0 = time.time()
    try:
        rows = mod.run_search(df, adaptive=adaptive, structural=structural, warmup=warmup, **kw)
    finally:
        df['D2D_Trend_Dir'] = orig  # F4/F7 mutate the gate column; always restore
    common = fmt(rows, script)
    out = os.path.join(RESULTS_DIR, f"results_{fam}_{script}.csv")
    pd.DataFrame(common, columns=SCHEMA).to_csv(out, index=False, lineterminator='\n')
    print(f"[{fam}] {len(common)} rows -> {out}  ({time.time()-t0:.1f}s)")
    return common


def ingest_f0():
    path = os.path.join(RESULTS_DIR, F0_CSV)
    if not os.path.exists(path):
        print(f"[F0] {path} not found — run F0 separately and drop its common-schema CSV here "
              f"(see F0 note). Skipping F0 at collation.")
        return []
    df0 = pd.read_csv(path)
    missing = [c for c in SCHEMA if c not in df0.columns]
    if missing:
        raise ValueError(f"F0 CSV missing schema columns: {missing}")
    print(f"[F0] ingested {len(df0)} rows from {path}")
    return df0[SCHEMA].to_dict('records')


def ingest_f1():
    path = os.path.join(RESULTS_DIR, F1_CSV)
    if not os.path.exists(path):
        return []
    df1 = pd.read_csv(path)
    missing = [c for c in SCHEMA if c not in df1.columns]
    if missing:
        raise ValueError(f"F1 CSV missing schema columns: {missing}")
    print(f"[F1] ingested {len(df1)} rows from {path} (in-process F1 skipped)")
    return df1[SCHEMA].to_dict('records')


def sort_master(master_df):
    # persistence PRIMARY, then within-fold floor, then survival axis, then PF/WR
    return master_df.sort_values(
        by=['folds_plus', 'min_fold_pf', 'worst_day_usd', 'agg_pf', 'WR'],
        ascending=[False, False, True, False, False]).reset_index(drop=True)


def orchestrate(scope='proof'):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"equiDOT — Stage 8 discovery orchestrator | scope={scope} | target lot 1.0")
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    builders = _scope(scope)
    all_rows = []
    f1_csv_present = os.path.exists(os.path.join(RESULTS_DIR, F1_CSV))
    for fam, script, mod, fmt in FAMILIES:
        if fam == 'F1' and f1_csv_present:
            continue
        all_rows.extend(run_family(fam, script, mod, fmt, builders[fam],
                                   df, adaptive, structural, warmup))
    if f1_csv_present:
        all_rows.extend(ingest_f1())
    all_rows.extend(ingest_f0())
    master = pd.DataFrame(all_rows, columns=SCHEMA)
    master_path = os.path.join(RESULTS_DIR, "discovery_master.csv")
    sort_master(master).to_csv(master_path, index=False, lineterminator='\n')
    print(f"\nCollated {len(master)} candidates -> {master_path} "
          f"(sorted: folds_plus, min_fold_pf, worst_day_usd, agg_pf, WR; no rows dropped)")
    by_fam = master.groupby('family').size().to_dict()
    print(f"Per-family counts: {by_fam}")


# ── F0 NOTE ──────────────────────────────────────────────────────────────
# F0 (triple_convergence_and_d2ddir.py) is run SEPARATELY at full scope with
# its internal MIN_PF pre-gate = 2.0 (trim only), then converted to the
# common SCHEMA and saved as discovery_results/results_F0_..._d2ddir.csv,
# which this orchestrator ingests. F0 is not called in-process because the
# C(117,3) triple search must not be held in one process with the others.


if __name__ == '__main__':
    orchestrate(sys.argv[1] if len(sys.argv) > 1 else 'proof')
