import sys
import os
import time
import hashlib
import json
import threading
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
                print(f"[F1] {n:,} ordered-pair candidates — heavy; chunked across workers on the A-label axis.")
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


HEARTBEAT_SECONDS = 60


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _family_paths(fam, script):
    csv = os.path.join(RESULTS_DIR, f"results_{fam}_{script}.csv")
    done = os.path.join(RESULTS_DIR, f"results_{fam}_{script}.done")
    return csv, done


def _write_atomic_csv(frame, path):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        frame.to_csv(f, index=False, lineterminator='\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _mark_family_done(csv_path, done_path, n_rows):
    payload = {'rows': int(n_rows), 'csv_sha256': _sha_file(csv_path),
               'schema_cols': len(SCHEMA)}
    tmp = done_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, done_path)


def family_is_complete(fam, script):
    csv, done = _family_paths(fam, script)
    if not (os.path.exists(csv) and os.path.exists(done)):
        return False, None
    try:
        meta = json.load(open(done, 'r', encoding='utf-8'))
    except Exception:
        return False, None
    if meta.get('csv_sha256') != _sha_file(csv):
        return False, None
    return True, meta


def resume_family(fam, script):
    csv, _done = _family_paths(fam, script)
    frame = pd.read_csv(csv)
    missing = [c for c in SCHEMA if c not in frame.columns]
    if missing:
        return None
    return frame[SCHEMA].to_dict('records')


def run_family(fam, script, mod, fmt, kw_builder, df, adaptive, structural, warmup):
    orig = df['D2D_Trend_Dir'].values.copy()
    kw = kw_builder(df, adaptive, structural, warmup)
    t0 = time.time()
    try:
        rows = mod.run_search(df, adaptive=adaptive, structural=structural, warmup=warmup, **kw)
    finally:
        df['D2D_Trend_Dir'] = orig
    common = fmt(rows, script)
    csv, done = _family_paths(fam, script)
    _write_atomic_csv(pd.DataFrame(common, columns=SCHEMA), csv)
    _mark_family_done(csv, done, len(common))
    print(f"[{fam}] {len(common)} rows -> {csv}  ({time.time() - t0:.1f}s)", flush=True)
    return common


CHUNK_AXIS = {'F1': ('cond_labels', 'lags'), 'F2': 'cond_labels', 'F3': 'base_pool',
              'F4': 'price_feats', 'F5': 'cond_labels', 'F6': 'cross_feats',
              'F7': 'stretch_feats', 'F8': 'pairs', 'F9': 'base_labels', 'F11': 'pairs'}
COST_ORDER = ['F1', 'F3', 'F9', 'F11', 'F4', 'F2', 'F7', 'F5', 'F8', 'F6']
TARGET_CHUNKS_PER_FAMILY = 64
_WCACHE = {}


def _axis_units(kw, axis):
    if isinstance(axis, tuple):
        sizes = [len(kw[a]) for a in axis]
        n = 1
        for x in sizes:
            n *= x
        return n, sizes
    return len(kw[axis]), [len(kw[axis])]


def _one_axis(kw, name, lo, hi):
    src = kw[name]
    if isinstance(src, dict):
        keys = list(src.keys())[lo:hi]
        return {k: src[k] for k in keys}
    return list(src)[lo:hi]


def _slice_axis(kw, axis, lo, hi):
    out = dict(kw)
    if not isinstance(axis, tuple):
        out[axis] = _one_axis(kw, axis, lo, hi)
        return out
    outer, inner = axis
    n_inner = len(kw[inner])
    i = lo // n_inner
    j = lo % n_inner
    out[outer] = _one_axis(kw, outer, i, i + 1)
    out[inner] = _one_axis(kw, inner, j, j + (hi - lo))
    return out


def _chunk_bounds(n_items, target=TARGET_CHUNKS_PER_FAMILY, unit_cap=None):
    if n_items <= 0:
        return []
    size = 1 if n_items <= target else -(-n_items // target)
    if unit_cap is not None:
        size = min(size, unit_cap)
    return [(i, min(i + size, n_items)) for i in range(0, n_items, size)]


def _bounds_for(fam, kw):
    axis = CHUNK_AXIS[fam]
    n_units, sizes = _axis_units(kw, axis)
    if isinstance(axis, tuple):
        return _chunk_bounds(n_units, target=n_units, unit_cap=sizes[1]), n_units
    return _chunk_bounds(n_units), n_units


def _chunk_paths(fam, script, idx):
    csv = os.path.join(RESULTS_DIR, f"results_{fam}_{script}_c{idx:04d}.csv")
    done = os.path.join(RESULTS_DIR, f"results_{fam}_{script}_c{idx:04d}.done")
    return csv, done


def chunk_is_complete(fam, script, idx):
    csv, done = _chunk_paths(fam, script, idx)
    if not (os.path.exists(csv) and os.path.exists(done)):
        return False
    try:
        meta = json.load(open(done, 'r', encoding='utf-8'))
    except Exception:
        return False
    return meta.get('csv_sha256') == _sha_file(csv)


def _worker_context(scope, frame_path, fam):
    if _WCACHE.get('frame_path') != frame_path:
        _WCACHE.clear()
        _WCACHE['frame_path'] = frame_path
        _WCACHE['df'] = pd.read_csv(frame_path)
        _WCACHE['warmup'] = engine.warmup_floor(_WCACHE['df'], verbose=False)
        _WCACHE['adaptive'] = dt.compute_adaptive_thresholds(_WCACHE['df'])
        _WCACHE['structural'] = dt.compute_structural_gates(_WCACHE['df'])
        _WCACHE['kw'] = {}
        _WCACHE['builders'] = _scope(scope)
    df = _WCACHE['df']
    if fam not in _WCACHE['kw']:
        _WCACHE['kw'][fam] = _WCACHE['builders'][fam](df, _WCACHE['adaptive'],
                                                      _WCACHE['structural'], _WCACHE['warmup'])
    return df, _WCACHE['adaptive'], _WCACHE['structural'], _WCACHE['warmup'], _WCACHE['kw'][fam]


def run_chunk_rows(fam, script, df, adaptive, structural, warmup, kw, lo, hi):
    spec = {f[0]: f for f in FAMILIES}[fam]
    mod, fmt = spec[2], spec[3]
    sub = _slice_axis(kw, CHUNK_AXIS[fam], lo, hi)
    orig = df['D2D_Trend_Dir'].values.copy()
    try:
        if fam == 'F1':
            import run_f1_parallel as f1p
            month = pd.Series(df['Time'].values).str[:7].values
            anchor_event = f1.anchor_array(df, kw['anchor'])
            a_labels = sub['cond_labels']
            b_labels = list(kw['cond_labels'])
            lags = sub['lags']
            expected = len(a_labels) * len(b_labels) * len(lags) * len(kw['directions'])
            common = f1p._score_pairs(a_labels, b_labels, kw['pool'], df, month, anchor_event,
                                      lags, kw['directions'], adaptive, structural, warmup)
            return common, expected
        rows = mod.run_search(df, adaptive=adaptive, structural=structural, warmup=warmup, **sub)
    finally:
        df['D2D_Trend_Dir'] = orig
    return fmt(rows, script), None


def _chunk_worker(payload):
    fam, script, scope, results_dir, frame_path, idx, lo, hi = payload
    import discovery_orchestrator as orch
    orch.RESULTS_DIR = results_dir
    if orch.chunk_is_complete(fam, script, idx):
        return (fam, idx, -1, 0.0, hi - lo)
    df, adaptive, structural, warmup, kw = orch._worker_context(scope, frame_path, fam)
    t0 = time.time()
    common, expected = orch.run_chunk_rows(fam, script, df, adaptive, structural, warmup, kw, lo, hi)
    if expected is not None:
        cpath = os.path.join(results_dir, f"results_{fam}_{script}_c{idx:04d}.cand")
        tmpc = cpath + '.tmp'
        with open(tmpc, 'w', encoding='utf-8') as fh:
            fh.write(str(int(expected)))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmpc, cpath)
    csv, done = orch._chunk_paths(fam, script, idx)
    orch._write_atomic_csv(pd.DataFrame(common, columns=SCHEMA), csv)
    orch._mark_family_done(csv, done, len(common))
    return (fam, idx, len(common), time.time() - t0, hi - lo)


def candidate_invariant(fam, script, n_chunks, expected_total):
    if expected_total is None:
        return True, 'n/a'
    got = 0
    for idx in range(n_chunks):
        cpath = os.path.join(RESULTS_DIR, f"results_{fam}_{script}_c{idx:04d}.cand")
        if not os.path.exists(cpath):
            return False, 'missing per-chunk candidate count'
        got += int(open(cpath, 'r', encoding='utf-8').read().strip())
    if got != expected_total:
        return False, f'{got} != {expected_total}'
    return True, f'{got} == {expected_total}'


def collate_family_chunks(fam, script, n_chunks, expected_total=None):
    ok, detail = candidate_invariant(fam, script, n_chunks, expected_total)
    if not ok and detail != 'missing per-chunk candidate count':
        raise SystemExit(f"ABORT [{fam}] CANDIDATE-COUNT INVARIANT FAILED: sum of per-chunk candidate "
                         f"counts {detail}. Chunking changed the search space; results are NOT trustworthy.")
    frames = []
    for idx in range(n_chunks):
        if not chunk_is_complete(fam, script, idx):
            return False, 0
        csv, _d = _chunk_paths(fam, script, idx)
        try:
            frames.append(pd.read_csv(csv))
        except pd.errors.EmptyDataError:
            frames.append(pd.DataFrame(columns=SCHEMA))
    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SCHEMA)
    csv, done = _family_paths(fam, script)
    _write_atomic_csv(merged[SCHEMA], csv)
    _mark_family_done(csv, done, len(merged))
    return True, len(merged)


class _Heartbeat:
    def __init__(self, label, interval=HEARTBEAT_SECONDS):
        self._label = label
        self._interval = interval
        self._stop = threading.Event()
        self._t0 = time.time()
        self._thread = None

    def __enter__(self):
        def beat():
            while not self._stop.wait(self._interval):
                mins = (time.time() - self._t0) / 60.0
                print(f"    ... {self._label} still running ({mins:.1f} min elapsed)", flush=True)
        self._thread = threading.Thread(target=beat, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        return False


def _hms(seconds):
    seconds = int(max(0, seconds))
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


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


def parity_check(scope='proof', workers=1, df=None, adaptive=None, structural=None, warmup=None,
                 families=None):
    if df is None:
        df = engine.load_sealed_baseline(verbose=False) if hasattr(engine, 'load_sealed_baseline') else None
    if warmup is None:
        warmup = engine.warmup_floor(df, verbose=False)
    if adaptive is None:
        adaptive = dt.compute_adaptive_thresholds(df)
    if structural is None:
        structural = dt.compute_structural_gates(df)
    builders = _scope(scope)
    names = families or [f[0] for f in FAMILIES]
    print(f"PARITY HARNESS — chunked vs unchunked, scope={scope}, {len(names)} families", flush=True)
    all_pass = True
    for fam, script, mod, fmt in FAMILIES:
        if fam not in names:
            continue
        kw = builders[fam](df, adaptive, structural, warmup)
        bounds, n_units = _bounds_for(fam, kw)
        orig_s = df['D2D_Trend_Dir'].values.copy()
        try:
            serial = fmt(mod.run_search(df, adaptive=adaptive, structural=structural,
                                        warmup=warmup, **kw), script)
        finally:
            df['D2D_Trend_Dir'] = orig_s
        exp_one = None
        if fam == 'F1':
            exp_one = len(kw['cond_labels']) ** 2 * len(kw['lags']) * len(kw['directions'])
        parts = []
        cand = 0
        for lo, hi in bounds:
            rows, exp = run_chunk_rows(fam, script, df, adaptive, structural, warmup, kw, lo, hi)
            parts.extend(rows)
            if exp is not None:
                cand += exp
        a = pd.DataFrame(serial, columns=SCHEMA)
        b = pd.DataFrame(parts, columns=SCHEMA)
        key = list(SCHEMA)
        a = a.sort_values(key).reset_index(drop=True)
        b = b.sort_values(key).reset_index(drop=True)
        same = a.equals(b)
        cand_txt = ''
        if exp_one is not None:
            cand_ok = cand == exp_one
            same = same and cand_ok
            cand_txt = f" | candidates {cand} vs {exp_one} {'OK' if cand_ok else 'MISMATCH'}"
        print(f"  {fam:4} {len(bounds):5} chunks | serial {len(a):5} rows | chunked {len(b):5} rows "
              f"| {'PASS' if same else 'FAIL'}{cand_txt}", flush=True)
        all_pass = all_pass and same
        del kw
    print(f"PARITY {'PASS' if all_pass else 'FAIL'} — chunking changes nothing a scanner computes"
          if all_pass else "PARITY FAIL — chunking altered results; do NOT run a long scan", flush=True)
    return all_pass


def orchestrate(scope='proof', workers=1, df=None, adaptive=None, structural=None,
                warmup=None, frame_path=None):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"equiDOT — discovery orchestrator | scope={scope} | workers={workers} | target lot 1.0", flush=True)
    if df is None:
        print("  no frame injected — loading the sealed baseline from the working directory", flush=True)
        df = engine.load_sealed_baseline()
        adaptive = None
        structural = None
        warmup = None
    else:
        print(f"  using the INGESTED frame from S0: {len(df):,} rows x {df.shape[1]} cols "
              f"({df['Time'].astype(str).values[0]} -> {df['Time'].astype(str).values[-1]})", flush=True)
    if warmup is None:
        warmup = engine.warmup_floor(df)
    if adaptive is None:
        adaptive = dt.compute_adaptive_thresholds(df)
    if structural is None:
        structural = dt.compute_structural_gates(df)
    builders = _scope(scope)
    f1_csv_present = os.path.exists(os.path.join(RESULTS_DIR, F1_CSV))
    schedule = [(fam, script, mod, fmt) for fam, script, mod, fmt in FAMILIES
                if not (fam == 'F1' and f1_csv_present)]
    total = len(schedule)
    pending = []
    resumed = []
    for fam, script, mod, fmt in schedule:
        complete, meta = family_is_complete(fam, script)
        if complete:
            resumed.append((fam, script, meta))
        else:
            pending.append((fam, script, mod, fmt))
    if resumed:
        print(f"  RESUME: {len(resumed)} of {total} families already complete on disk — reading back, not re-scanning:",
              flush=True)
        for fam, script, meta in resumed:
            print(f"    [{fam}] skipped, resumed from disk ({meta['rows']} rows, sha {meta['csv_sha256'][:12]})",
                  flush=True)
    print(f"  {len(pending)} of {total} families to run this pass", flush=True)
    durations = []
    import multiprocessing as _mp
    if _mp.parent_process() is not None and workers and workers > 1:
        print("  already inside a worker process — running sequentially to prevent recursive spawn", flush=True)
        workers = 1
    ran_parallel = False
    if workers and workers >= 1 and pending and frame_path is not None:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        from concurrent.futures.process import BrokenProcessPool
        import multiprocessing as _mp2
        plan = []
        expected_cands = {}
        for fam, script, _mod, _fmt in pending:
            kw = builders[fam](df, adaptive, structural, warmup)
            bounds, n_axis = _bounds_for(fam, kw)
            if fam == 'F1':
                expected_cands[fam] = (len(kw['cond_labels']) ** 2 * len(kw['lags'])
                                       * len(kw['directions']))
            plan.append((fam, script, n_axis, bounds))
            del kw
        order = {f: i for i, f in enumerate(COST_ORDER)}
        plan.sort(key=lambda r: order.get(r[0], 999))
        queue = []
        already = 0
        for fam, script, _n, bounds in plan:
            for idx, (lo, hi) in enumerate(bounds):
                if chunk_is_complete(fam, script, idx):
                    already += 1
                    continue
                queue.append((fam, script, scope, RESULTS_DIR, frame_path, idx, lo, hi))
        total_chunks = sum(len(b) for _f, _s, _n, b in plan)
        print(f"  CHUNK PLAN: {total_chunks} chunks across {len(plan)} families "
              f"(axis split, {TARGET_CHUNKS_PER_FAMILY} chunks max per family, "
              f"independent of worker count):", flush=True)
        for fam, script, n_axis, bounds in plan:
            print(f"    {fam:4} axis '{CHUNK_AXIS[fam]}' = {n_axis} items -> {len(bounds)} chunks", flush=True)
        if already:
            print(f"  RESUME: {already} of {total_chunks} chunks already complete on disk", flush=True)
        nw = min(workers, max(1, len(queue)))
        print(f"  running {len(queue)} pending chunks across {nw} worker processes from ONE queue — "
              f"a worker that finishes takes the next chunk of ANY family, so no thread idles while "
              f"work remains and the last family gets every worker", flush=True)
        print(f"  submission order is longest-family-first (scheduling only; collation is by axis order, "
              f"so output cannot depend on it)", flush=True)
        fam_secs = {}
        fam_units = {}
        pend_units = {}
        for pl in queue:
            pend_units[pl[0]] = pend_units.get(pl[0], 0) + (pl[7] - pl[6])
        t0 = time.time()
        died = False
        try:
            with _Heartbeat(f"S3 chunk queue ({len(queue)} chunks)"):
                with ProcessPoolExecutor(max_workers=nw,
                                         mp_context=_mp2.get_context('spawn')) as ex:
                    futures = {ex.submit(_chunk_worker, pl): (pl[0], pl[5]) for pl in queue}
                    done_n = 0
                    for fut in as_completed(futures):
                        fam, idx = futures[fut]
                        try:
                            fam_r, idx_r, n_rows, secs, units = fut.result()
                        except BrokenProcessPool:
                            died = True
                            break
                        except Exception as exc:
                            print(f"  [{fam} c{idx:04d}] worker raised {type(exc).__name__}: {exc}", flush=True)
                            continue
                        done_n += 1
                        if n_rows >= 0:
                            fam_secs[fam_r] = fam_secs.get(fam_r, 0.0) + secs
                            fam_units[fam_r] = fam_units.get(fam_r, 0) + units
                        pend_units[fam_r] = pend_units.get(fam_r, 0) - units
                        el = time.time() - t0
                        pct = 100.0 * done_n / len(queue)
                        serial = 0.0
                        unmeasured = []
                        for f_, u_ in pend_units.items():
                            if u_ <= 0:
                                continue
                            if fam_units.get(f_):
                                serial += u_ * (fam_secs[f_] / fam_units[f_])
                            else:
                                unmeasured.append(f_)
                        eta_txt = (f"ETA {_hms(serial / nw)}" if not unmeasured
                                   else f"ETA >= {_hms(serial / nw)} ({len(unmeasured)} unmeasured: "
                                        f"{','.join(sorted(unmeasured))})")
                        if serial <= 0 and unmeasured:
                            eta_txt = f"ETA forming ({len(unmeasured)} families unmeasured)"
                        note = 'resumed' if n_rows < 0 else f'{n_rows} survivors in {secs:.1f}s'
                        print(f"  [{done_n}/{len(queue)} {pct:5.1f}%] {fam_r} c{idx_r:04d} {note} "
                              f"| elapsed {_hms(el)} | {eta_txt} "
                              f"| {done_n / el * 60 if el > 0 else 0:.1f} chunks/min", flush=True)
        except BrokenProcessPool:
            died = True
        if died:
            print("", flush=True)
            print("  *** A WORKER PROCESS DIED WITHOUT RAISING — almost always the OS killing it for memory. ***",
                  flush=True)
            print("  Completed CHUNKS are on disk and will NOT be re-scanned. Completing the rest",
                  flush=True)
            print("  sequentially in this process. If this recurs, lower --workers.", flush=True)
            print("", flush=True)
        for fam, script, _n, bounds in plan:
            ok, n_rows = collate_family_chunks(fam, script, len(bounds), expected_cands.get(fam))
            if ok:
                inv = candidate_invariant(fam, script, len(bounds), expected_cands.get(fam))[1]
                print(f"  [{fam}] collated {len(bounds)} chunks -> {n_rows} rows "
                      f"| candidate invariant {inv}", flush=True)
        ran_parallel = not died
        pending = [(fam, script, mod, fmt) for fam, script, mod, fmt in pending
                   if not family_is_complete(fam, script)[0]]
        if pending and ran_parallel:
            ran_parallel = False
    if pending and not ran_parallel:
        for i, (fam, script, mod, fmt) in enumerate(pending, 1):
            mean = (sum(durations) / len(durations)) if durations else None
            eta = f" | ETA {_hms(mean * (len(pending) - i + 1))}" if mean else ""
            print(f"  [family {i} of {len(pending)}] {fam} ({script}) starting{eta}", flush=True)
            t0 = time.time()
            with _Heartbeat(f"{fam} ({script})"):
                run_family(fam, script, mod, fmt, builders[fam], df, adaptive, structural, warmup)
            durations.append(time.time() - t0)
            print(f"  [family {i} of {len(pending)}] {fam} done in {_hms(durations[-1])}", flush=True)
    all_rows = []
    for fam, script, _mod, _fmt in schedule:
        complete, meta = family_is_complete(fam, script)
        if not complete:
            print(f"  [{fam}] WARNING: no complete output on disk after this pass; excluded from collation",
                  flush=True)
            continue
        rows = resume_family(fam, script)
        if rows is None:
            print(f"  [{fam}] WARNING: output missing schema columns; excluded from collation", flush=True)
            continue
        all_rows.extend(rows)
    if f1_csv_present:
        all_rows.extend(ingest_f1())
    all_rows.extend(ingest_f0())
    master = pd.DataFrame(all_rows, columns=SCHEMA)
    master_path = os.path.join(RESULTS_DIR, "discovery_master.csv")
    _write_atomic_csv(sort_master(master), master_path)
    print(f"\nCollated {len(master)} candidates -> {master_path} "
          f"(sorted: folds_plus, min_fold_pf, worst_day_usd, agg_pf, WR; no rows dropped)", flush=True)
    by_fam = master.groupby('family').size().to_dict()
    print(f"Per-family counts: {by_fam}", flush=True)


# ── F0 NOTE ──────────────────────────────────────────────────────────────
# F0 (triple_convergence_and_d2ddir.py) is run SEPARATELY at full scope with
# its internal MIN_PF pre-gate = 2.0 (trim only), then converted to the
# common SCHEMA and saved as discovery_results/results_F0_..._d2ddir.csv,
# which this orchestrator ingests. F0 is not called in-process because the
# C(117,3) triple search must not be held in one process with the others.


if __name__ == '__main__':
    orchestrate(sys.argv[1] if len(sys.argv) > 1 else 'proof')
