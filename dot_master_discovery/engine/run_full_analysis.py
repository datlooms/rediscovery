import os
import sys
import time
import json
import glob
import math
import shutil

# Self-bootstrap for the dot_master_discovery layout. This script lives in engine/
# (alongside portfolio_simulation_engine.py / dots_thresholds.py / wf.py /
# analysis_engine.py), so those imports resolve natively. All data paths are
# resolved as ABSOLUTES relative to this file — never the cwd — so the operator
# can run it from anywhere.
#
#   engine/            <- this file, analysis_engine.py, the ratified engine
#   discovery_results/ <- F0 input CSV + our output (signal_full_records.csv,
#                         signal_per_day_pnl.jsonl, _shards/ checkpoints)
#   data/ (or root)    <- the 8 baseline CSVs (equiDOT_recon171_step7_part*.csv)
#
# The ratified load_sealed_baseline() reads the baseline by BARE filename
# (CWD-relative, and it is byte-frozen so we must not edit it). We therefore
# chdir into the directory that actually holds those CSVs before scoring — after
# resolving every one of OUR paths to an absolute, so the chdir cannot affect
# input/output/checkpoint locations.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _baseline_dir():
    # first location containing the 8 baseline parts: package root (launcher
    # symlinks them there) or data/.
    probe = 'equiDOT_recon171_step7_part1.csv'
    for cand in (_ROOT, os.path.join(_ROOT, 'data')):
        if os.path.exists(os.path.join(cand, probe)):
            return cand
    return _ROOT


import numpy as np
import pandas as pd
from multiprocessing import Pool
import analysis_engine as ae

RESULTS_DIR_ABS = os.path.join(_ROOT, 'discovery_results')
F0_INPUT = os.path.join(RESULTS_DIR_ABS, 'results_F0_triple_convergence_and_d2ddir.csv')

# ═══════════════════════════════════════════════════════════════
#  equiDOT — FULL-FIELD ANALYSIS EXPORT (F0 triple-convergence, S.7)
#
#  Evaluates the F0 field (51,311 candidates) under the ratified S.7 TM, three
#  persistence scales, and writes a full per-signal record for every survivor of
#  a light quality gate. Scope is F0 triple-convergence ONLY (the validated
#  diamond book and the EA's native design).
#
#  GATE (write only if ALL): trades >= 30 AND agg_pf >= 2.0 AND folds_plus >= 4.
#  UNITS: $1/point/lot (P&L is in points; USD == points at lot 1.0). Figures
#  here are in POINTS; multiply by lot afterwards.
#
#  OUTPUT (new filenames, nothing existing touched):
#    signal_full_records.csv      — one row per survivor, full record
#    signal_per_day_pnl.jsonl      — {signal_key: {day: net}} per survivor (the
#                                    anti-fabrication per-day vector, exact)
#
#  CHECKPOINT / CRASH-RESUME (power-loss safe):
#    Work is partitioned into fixed shards of SHARD candidates. Each shard is
#    scored, then its rows are written to a TEMP file and atomically os.replace'd
#    into place as _shards/shard_<start>.csv + .jsonl. A shard's .done marker
#    is written LAST, so its presence proves both data files are fully on disk; a
#    hard kill mid-shard leaves no .done (and any .tmp is ignored), so on restart
#    that shard is simply re-run. Completed shards are skipped. The final step
#    concatenates all shard files. Deterministic: shard boundaries and
#    per-candidate scoring depend only on input order.
#
#  Multiprocessing: spawn start method (Windows production parity), one shard per
#  task, up to N_WORKERS in flight. Live progress bar + ETA over shards.
# ═══════════════════════════════════════════════════════════════

INPUTS = [
    ('F0', F0_INPUT),
]
OUT_CSV = os.path.join(RESULTS_DIR_ABS, 'signal_full_records.csv')
OUT_JSONL = os.path.join(RESULTS_DIR_ABS, 'signal_per_day_pnl.jsonl')
SHARD_DIR = os.path.join(RESULTS_DIR_ABS, '_shards')
MANIFEST = os.path.join(SHARD_DIR, 'field_manifest.csv')
SHARD = 500
N_WORKERS = 6

GATE_MIN_TRADES = 30
GATE_MIN_PF = 2.0
GATE_MIN_FOLDS = 4


# ── field manifest: the exact, ordered candidate list (deterministic) ────
def build_manifest():
    if os.path.exists(MANIFEST):
        return pd.read_csv(MANIFEST)
    frames = []
    for family, path in INPUTS:
        d = pd.read_csv(path, usecols=['family', 'signal_def', 'direction', 'd2d_mode'])
        d = d[d['family'] == family].copy()
        frames.append(d)
    field = pd.concat(frames, ignore_index=True)
    field = field.reset_index(drop=True)
    field['cand_id'] = np.arange(len(field))
    os.makedirs(SHARD_DIR, exist_ok=True)
    tmp = MANIFEST + '.tmp'
    field.to_csv(tmp, index=False, lineterminator='\n')
    os.replace(tmp, MANIFEST)
    return field


def signal_key(family, direction, d2d_mode, signal_def):
    return f"{family}|{direction}|{d2d_mode}|{signal_def}"


# ── one shard (worker) ───────────────────────────────────────────────────
_CTX = {}


def _init():
    os.chdir(_baseline_dir())  # so the CWD-relative ratified loader finds the baseline
    _CTX['ctx'] = ae.build_context()
    _CTX['orig'] = ae.orig_d2d(_CTX['ctx'])


def _shard_paths(start):
    return (os.path.join(SHARD_DIR, f'shard_{start:08d}.csv'),
            os.path.join(SHARD_DIR, f'shard_{start:08d}.jsonl'),
            os.path.join(SHARD_DIR, f'shard_{start:08d}.done'))


def process_shard(task):
    start, rows = task
    pq_path, jsonl_path, done_path = _shard_paths(start)
    if os.path.exists(done_path):
        return (start, -1)  # already complete; skip
    ctx = _CTX['ctx']
    orig = _CTX['orig']
    recs, perday = [], []
    for r in rows:
        try:
            rec = ae.evaluate(ctx, r['family'], r['signal_def'], r['direction'],
                              r['d2d_mode'], orig)
        except Exception as e:
            recs.append({'signal_def': r['signal_def'], 'family': r['family'],
                         'direction': r['direction'], 'd2d_mode': r['d2d_mode'],
                         '_error': str(e)[:200], 'trades': 0, 'agg_pf': 0.0,
                         'folds_plus': 0, '_gated_out': True})
            continue
        if rec.get('_empty') or rec['trades'] < GATE_MIN_TRADES or \
                rec['agg_pf'] < GATE_MIN_PF or rec['folds_plus'] < GATE_MIN_FOLDS:
            continue
        day = rec.pop('per_day_pnl')
        weekly = rec.pop('weekly')
        rec['weekly_json'] = json.dumps(weekly, separators=(',', ':'))
        rec.pop('_empty', None)
        key = signal_key(r['family'], r['direction'], r['d2d_mode'], r['signal_def'])
        rec['signal_key'] = key
        recs.append(rec)
        perday.append(json.dumps({key: day}, separators=(',', ':')))
    # atomic write: temp -> replace. .done marker last, so its presence proves
    # both data files are fully on disk.
    tmp_pq = pq_path + '.tmp'
    pd.DataFrame(recs).to_csv(tmp_pq, index=False, lineterminator='\n')
    os.replace(tmp_pq, pq_path)
    tmp_j = jsonl_path + '.tmp'
    with open(tmp_j, 'w', encoding='utf-8') as f:
        f.write('\n'.join(perday) + ('\n' if perday else ''))
    os.replace(tmp_j, jsonl_path)
    with open(done_path, 'w', encoding='utf-8') as f:
        f.write(f"{len(rows)} candidates, {len(recs)} survivors\n")
    return (start, len(recs))


# ── progress / eta ───────────────────────────────────────────────────────
def _hms(s):
    s = int(s)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _bar(done, total, start_t, width=32):
    frac = done / total if total else 1.0
    fill = int(frac * width)
    el = time.time() - start_t
    rate = done / el if el > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    sys.stdout.write(f"\r[{('#' * fill).ljust(width)}] {100 * frac:5.1f}% | "
                     f"{done:,}/{total:,} shards | elapsed {_hms(el)} | ETA {_hms(eta)} | "
                     f"{rate * SHARD:.0f} cand/s   ")
    sys.stdout.flush()


# ── driver ───────────────────────────────────────────────────────────────
def run(n_workers=N_WORKERS):
    t0 = time.time()
    field = build_manifest()
    total = len(field)
    starts = list(range(0, total, SHARD))
    print(f"=== FULL-FIELD ANALYSIS (F0+F1, S.7) ===")
    print(f"field: {total:,} candidates | shard {SHARD} | {len(starts)} shards | "
          f"workers {n_workers} | gate trades>={GATE_MIN_TRADES} pf>={GATE_MIN_PF} "
          f"folds+>={GATE_MIN_FOLDS}")

    remaining = [s for s in starts if not os.path.exists(_shard_paths(s)[2])]
    done_already = len(starts) - len(remaining)
    print(f"resume: {done_already}/{len(starts)} shards already complete; "
          f"{len(remaining)} to do", flush=True)

    recs_field = field.to_dict('records')
    tasks = [(s, recs_field[s:s + SHARD]) for s in remaining]

    completed = done_already
    if tasks:
        with Pool(n_workers, initializer=_init) as p:
            for _ in p.imap_unordered(process_shard, tasks):
                completed += 1
                _bar(completed, len(starts), t0)
    sys.stdout.write("\n")

    # concatenate all shard outputs -> final files (atomic)
    print("assembling final output ...", flush=True)
    pq_files = sorted(glob.glob(os.path.join(SHARD_DIR, 'shard_*.csv')))
    parts = []
    for f in pq_files:
        try:
            parts.append(pd.read_csv(f))
        except pd.errors.EmptyDataError:
            continue  # zero-survivor shard (no header/rows) — legitimately empty
    survivors = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    tmp = OUT_CSV + '.tmp'
    survivors.to_csv(tmp, index=False, lineterminator='\n')
    os.replace(tmp, OUT_CSV)

    jsonl_files = sorted(glob.glob(os.path.join(SHARD_DIR, 'shard_*.jsonl')))
    tmp = OUT_JSONL + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as out:
        for jf in jsonl_files:
            with open(jf, encoding='utf-8') as f:
                shutil.copyfileobj(f, out)
    os.replace(tmp, OUT_JSONL)

    n_surv = len(survivors)
    print(f"=== DONE | {total:,} scored | {n_surv:,} survivors written | "
          f"elapsed {_hms(time.time() - t0)} ===")
    print(f"  {OUT_CSV}  ({n_surv:,} rows)")
    print(f"  {OUT_JSONL}    (per-day P&L vectors)")
    print(f"  checkpoints in {SHARD_DIR}/ (safe to delete after a clean finish)")
    return survivors


if __name__ == '__main__':
    import multiprocessing as mp
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
    run(int(sys.argv[1]) if len(sys.argv) > 1 else N_WORKERS)
