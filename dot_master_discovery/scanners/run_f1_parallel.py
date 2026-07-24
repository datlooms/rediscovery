import os
import sys
import shutil

# Self-bootstrap so this runs DIRECTLY (python scanners/run_f1_parallel.py) rather
# than through master.py — multiprocessing on Windows (spawn) re-imports the main
# module, which must be THIS file, not the launcher's runpy context. Idempotent:
# safe to re-run in spawned children. Resolves engine/ imports and the CWD-relative
# baseline the same way the launcher does.
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
from multiprocessing import Pool, Value
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import sequential_temporal as seq

# ═══════════════════════════════════════════════════════════════
#  equiDOT — F1 PARALLEL RUNNER (run_f1_parallel.py)
#  Parallelises the ratified F1 ordered-pair search (sequential_temporal.py,
#  238^2 x 15 lags x 2 dir = 1,699,320 candidates) across N_WORKERS.
#
#  ZERO new signal/TM/threshold logic. The per-candidate scoring path is
#  BYTE-IDENTICAL to serial sequential_temporal.run_search: this file only
#  reuses seq.pair_mask + seq.score_candidate (the ratified functions) via a
#  thin parallel-only helper (_score_pairs) that pairs an A-subset against the
#  full B-pool — because seq.run_search pairs cond_labels x cond_labels and
#  cannot take an A-subset vs full-B as-is. sequential_temporal.py is NOT
#  modified.
#
#  Baseline + oracle load ONCE in the parent, passed to workers via the Pool
#  initializer. Windows spawn-safe: top-level worker, __main__ guard.
#  Progress: start banner, a live line refreshed every PROGRESS_INTERVAL s
#  (% / done / total / elapsed / ETA / rate), per-chunk completion line, and
#  a final summary. Never silent for more than ~PROGRESS_INTERVAL s.
#  Output: discovery_results/results_F1_sequential_temporal.csv (14-col schema).
# ═══════════════════════════════════════════════════════════════

SCHEMA = ['family', 'script', 'signal_def', 'direction', 'd2d_mode', 'trades', 'WR',
          'agg_pf', 'worst_day_usd', 'hard_stop_days', 'folds_plus', 'min_fold_pf',
          'spread_pf', 'survival']
SCRIPT = 'sequential_temporal'
RESULTS_DIR = 'discovery_results'
OUT = os.path.join(RESULTS_DIR, 'results_F1_sequential_temporal.csv')
N_WORKERS = 8
ANCHOR = 'ST_Flip'
FLUSH = 200
PROGRESS_INTERVAL = 30.0

_G = {}


def _init(payload, counter):
    _G.update(payload)
    _G['counter'] = counter
    if seq.SEQ_COL not in _G['df'].columns:
        _G['df'][seq.SEQ_COL] = 0


def _row_from(a, b, k, direction, sc):
    return {'family': 'F1', 'script': SCRIPT, 'signal_def': f"{a} ->{k}-> {b}",
            'direction': direction, 'd2d_mode': 'confirm', 'trades': sc['trades'],
            'WR': sc['agg_wr'], 'agg_pf': sc['agg_pf'], 'worst_day_usd': sc['worst_day_usd'],
            'hard_stop_days': sc['hard_stop_days'], 'folds_plus': sc['profitable_folds'],
            'min_fold_pf': sc['min_fold_pf'], 'spread_pf': f"{sc['pf_base']}->{sc['pf_stress']}",
            'survival': sc['survival_pass']}


def _score_pairs(a_labels, b_labels, pool, df, month, anchor_event, lags, directions,
                 adaptive, structural, warmup, counter=None):
    rows = []
    local = 0
    for a in a_labels:
        am = pool[a]
        for b in b_labels:
            bm = pool[b]
            for k in lags:
                seqm = seq.pair_mask(am, bm, k, anchor_event)
                if int(seqm.sum()) < seq.MIN_TRADES:
                    local += len(directions)
                else:
                    for direction in directions:
                        sc = seq.score_candidate(df, seqm, direction, month,
                                                 adaptive, structural, warmup)
                        local += 1
                        if sc is not None:
                            rows.append(_row_from(a, b, k, direction, sc))
                if counter is not None and local >= FLUSH:
                    with counter.get_lock():
                        counter.value += local
                    local = 0
    if counter is not None and local:
        with counter.get_lock():
            counter.value += local
    return rows


def _worker(task):
    chunk_id, n_chunks, a_labels = task
    t0 = time.time()
    rows = _score_pairs(a_labels, _G['b_labels'], _G['pool'], _G['df'], _G['month'],
                        _G['anchor_event'], _G['lags'], _G['directions'],
                        _G['adaptive'], _G['structural'], _G['warmup'], _G['counter'])
    cand = len(a_labels) * len(_G['b_labels']) * len(_G['lags']) * len(_G['directions'])
    print(f"chunk {chunk_id + 1}/{n_chunks} done — {cand} candidates, {len(rows)} survivors, "
          f"{(time.time() - t0) / 60:.1f} min", flush=True)
    return rows


def _chunks(labels, n):
    k = math.ceil(len(labels) / n)
    return [labels[i:i + k] for i in range(0, len(labels), k)]


def _fmt_hms(s):
    s = int(s)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _monitor(counter, total, start, ready_fn, interval):
    while not ready_fn():
        time.sleep(interval)
        el = time.time() - start
        done = min(int(counter.value), total)
        rate = done / el if el > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else 0.0
        pct = 100.0 * done / total if total else 0.0
        sys.stdout.write(f"\r[F1] {pct:5.1f}% | {done:,}/{total:,} | elapsed {_fmt_hms(el)} | "
                         f"ETA {_fmt_hms(eta)} | {rate:.1f}/s   ")
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()


def _prepare():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    pool_all = seq.build_condition_pool(df, adaptive, structural, warmup)
    scor = seq.scorable_pool(pool_all, warmup)
    month = pd.Series(df['Time'].values).str[:7].values
    anchor_event = seq.anchor_array(df, ANCHOR)
    return df, warmup, adaptive, structural, pool_all, scor, month, anchor_event


def run_parallel(a_labels, b_labels, lags, pool_all, df, warmup, adaptive, structural,
                 month, anchor_event, n_workers, interval, write, scor_size):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    pool = {l: pool_all[l] for l in set(a_labels) | set(b_labels)}
    directions = ['LONG', 'SHORT']
    total = len(a_labels) * len(b_labels) * len(lags) * len(directions)
    chunks = _chunks(a_labels, n_workers)
    counter = Value('L', 0)
    payload = dict(df=df, adaptive=adaptive, structural=structural, warmup=warmup,
                   pool=pool, b_labels=b_labels, lags=lags, directions=directions,
                   month=month, anchor_event=anchor_event)
    start = time.time()
    print(f"[F1] parallel start {time.strftime('%Y-%m-%d %H:%M:%S')} | scorable pool {scor_size} | "
          f"A-labels {len(a_labels)} in {len(chunks)} chunks | workers {n_workers} | "
          f"total candidates {total:,}", flush=True)
    with Pool(n_workers, initializer=_init, initargs=(payload, counter)) as p:
        res = p.map_async(_worker, [(i, len(chunks), c) for i, c in enumerate(chunks)])
        _monitor(counter, total, start, res.ready, interval)
        worker_rows = res.get()
    rows = [r for wr in worker_rows for r in wr]
    el = time.time() - start
    if write:
        pd.DataFrame(rows, columns=SCHEMA).to_csv(OUT, index=False, lineterminator='\n')
        print(f"[F1] done — elapsed {_fmt_hms(el)} | {len(rows)} survivors -> {OUT}", flush=True)
    else:
        print(f"[F1] done — elapsed {_fmt_hms(el)} | {len(rows)} survivors (no write)", flush=True)
    return rows


def run_full(n_workers=N_WORKERS):
    df, warmup, adaptive, structural, pool_all, scor, month, anchor_event = _prepare()
    return run_parallel(scor, scor, seq.LAGS, pool_all, df, warmup, adaptive, structural,
                        month, anchor_event, n_workers, PROGRESS_INTERVAL, True, len(scor))


def _key(r):
    return (r['signal_def'], r['direction'], r['d2d_mode'])


def run_proof(n_workers=4):
    df, warmup, adaptive, structural, pool_all, scor, month, anchor_event = _prepare()
    small = [l for l in ['ADX_Value:hi', 'Momentum_Value:hi', 'Sqz_State:==1',
                         'RangeOsc_State:==1'] if l in scor]
    lags = [3, 5]
    print(f"\n[PROOF] A=B={small} lags={lags} workers={n_workers}")
    par = run_parallel(small, small, lags, pool_all, df, warmup, adaptive, structural,
                       month, anchor_event, n_workers, 2.0, False, len(scor))
    serial = seq.run_search(df, pool_all, small, lags, ANCHOR, ['LONG', 'SHORT'],
                            adaptive, structural, warmup)
    ser = [_row_from(r['A'], r['B'], r['k'], r['direction'], r) for r in serial]
    p = sorted(par, key=_key)
    s = sorted(ser, key=_key)
    ok = len(p) == len(s)
    detail = f"{len(p)} parallel vs {len(s)} serial rows"
    if ok:
        for rp, rs in zip(p, s):
            for c in SCHEMA:
                if rp[c] != rs[c]:
                    ok = False
                    detail = f"mismatch {c}: {rp[c]} vs {rs[c]} @ {rp['signal_def']} {rp['direction']}"
                    break
            if not ok:
                break
    print(f"\n[PARITY] {'PASS' if ok else 'FAIL'} — {detail} "
          f"(sorted by signal_def+direction+d2d_mode, all 14 columns compared)")
    return ok


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'proof':
        run_proof(int(sys.argv[2]) if len(sys.argv) > 2 else 4)
    else:
        run_full(int(sys.argv[1]) if len(sys.argv) > 1 else N_WORKERS)
