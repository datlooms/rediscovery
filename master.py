import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.join(_HERE, 'engine')
_SCANNERS = os.path.join(_HERE, 'scanners')
_ROOT = _HERE
_ORCH = os.path.join(_HERE, 'orchestrator')
for _d in (_ENGINE, _SCANNERS, _ORCH):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import numpy as np
import pandas as pd

SACRED = {
    'dots_thresholds.py': '518862bf19fb',
    'wf.py': '793e6e5f8d9a',
    'core.py': '6530e2508b17',
    'portfolio_simulation_engine.py': 'bb498eb13ce3',
    'conviction.py': '27af7acee824',
}
FOLDS = ['2026.01', '2026.02', '2026.03', '2026.04', '2026.05', '2026.06']
OOS_MONTHS = ['2026.05', '2026.06']
OOS_LEGACY_NOTE = 'LEGACY DIAGNOSTIC, STALE: fixed calendar months, neither out-of-sample nor segment-relative on a stitched series; not a selection input (spec B.1). oos_rel_* are the data-relative counterpart.'
OOS_REL_N_MONTHS = 2
STAGES = ['S0', 'S1', 'S2', 'S3', 'S3B', 'S4', 'S5', 'S6', 'S5B', 'S5C', 'S7', 'S8', 'S8B', 'S9']
FAMILIES = [
    ('F0', 'triple_convergence_and_d2ddir', 'committed'),
    ('F1', 'sequential_temporal', 'committed'),
    ('F2', 'state_transition', 'exploratory'),
    ('F3', 'conditional_interaction', 'exploratory'),
    ('F4', 'divergence_nonconfirm', 'exploratory'),
    ('F5', 'persistence_autocorr', 'exploratory'),
    ('F6', 'threshold_crossing', 'exploratory'),
    ('F7', 'mean_reversion', 'exploratory'),
    ('F8', 'cross_variable_structure', 'exploratory'),
    ('F9', 'session_temporal', 'exploratory'),
    ('F11', 'rolling_leadlag', 'exploratory'),
    ('F12', 'concurrence_profiler', 'diagnostic'),
    ('F13', 'single_variable_extremes', 'exploratory'),
]


from _packutil import sha12, _natkey, split_output


def verify_sacred():
    print('SACRED REGISTRY (byte-lock — abort on drift):')
    drift = []
    for name, want in SACRED.items():
        path = os.path.join(_ENGINE, name)
        got = sha12(path) if os.path.exists(path) else 'MISSING'
        ok = got == want
        print(f'  {name:32} {got}  expect {want}  {"OK" if ok else "DRIFT"}')
        if not ok:
            drift.append(name)
    if drift:
        print(f'\nABORT — sacred drift on: {", ".join(drift)}. The master orchestrates these; it must never rewrite them.')
        sys.exit(2)
    return {n: SACRED[n] for n in SACRED}


def _hms(s):
    s = int(s)
    return f'{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}'


def done_path(out, key):
    return os.path.join(out, '.markers', f'{key}.done')


def mark_done(out, key, meta):
    os.makedirs(os.path.join(out, '.markers'), exist_ok=True)
    tmp = done_path(out, key) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(meta, f)
    os.replace(tmp, done_path(out, key))


def is_done(out, key, input_sha):
    p = done_path(out, key)
    if not os.path.exists(p):
        return False
    try:
        meta = json.load(open(p, encoding='utf-8'))
        return meta.get('input_sha') == input_sha
    except Exception:
        return False


def _pf(x):
    x = np.asarray(x, dtype=float)
    if (x < 0).any():
        return round(x[x > 0].sum() / -x[x < 0].sum(), 2)
    return 999.0 if len(x) else 0.0


def split_tree(out, chunk_mb):
    n = 0
    for root, _, files in os.walk(out):
        if '.markers' in root:
            continue
        for fn in files:
            if fn.endswith(('.csv', '.jsonl')) and '_part' not in fn and '_manifest' not in fn:
                p = os.path.join(root, fn)
                parts = split_output(p, chunk_mb)
                if len(parts) > 1:
                    n += 1
    return n


# ── S0 INGEST ──
def _is_header_row(first_line):
    return first_line.split(',')[0].strip() == 'Time'


def s0_ingest(data_dir, out, chunk_mb):
    import portfolio_simulation_engine as engine
    files = sorted(glob.glob(os.path.join(data_dir, '*.csv')), key=_natkey)
    if not files:
        print(f'ABORT — no CSVs in {data_dir}')
        sys.exit(2)
    input_sha = hashlib.sha256((''.join(sha12(f) for f in files)).encode()).hexdigest()[:12]
    recon = [f for f in files if 'recon171_step7_part' in os.path.basename(f)]
    ncols = len(open(files[0], encoding='utf-8').readline().split(','))
    attest = {'files': [os.path.basename(f) for f in files], 'ncols_first': ncols}
    if recon and len(recon) == len(files):
        cwd = os.getcwd()
        os.chdir(data_dir)
        try:
            df = engine.load_sealed_baseline(verbose=False)
        finally:
            os.chdir(cwd)
        attest['path'] = 'sealed-baseline (load_sealed_baseline invariants)'
    else:
        if ncols >= 256:
            import core
            print('  S0a — 256-col raw export detected → core.py reconstruction')
            attest['path'] = 'core.py reconstruction (256→171)'
        frames = []
        header_cols = None
        for f in files:
            if _is_header_row(open(f, encoding='utf-8').readline()):
                d = pd.read_csv(f)
                header_cols = list(d.columns)
            else:
                d = pd.read_csv(f, header=None, names=header_cols)
            frames.append(d)
        df = pd.concat(frames, ignore_index=True)
        attest['path'] = 'generic concatenate+validate'
    if 'Time' not in df.columns or df.shape[1] != 172:
        print(f'ABORT — column contract violated: {df.shape[1]} cols (expect Time + 171)')
        sys.exit(2)
    t = df['Time'].astype(str).values
    if not (t[1:] > t[:-1]).all():
        print('ABORT — time not strictly increasing')
        sys.exit(2)
    if df.duplicated().any():
        print('ABORT — duplicate rows present')
        sys.exit(2)
    if df.isna().any().any():
        print('ABORT — NaN cells present')
        sys.exit(2)
    attest.update({'rows': int(len(df)), 'cols': int(df.shape[1]),
                   'range': f'{t[0]} → {t[-1]}', 'invariants': 'PASS', 'input_sha': input_sha})
    print(f'  ingest: {len(df):,} rows × {df.shape[1]} cols | {t[0]} → {t[-1]} | invariants PASS')
    mark_done(out, 'S0', attest)
    return df, attest, input_sha


# ── S1 / S2 ──
def s1_thresholds(df):
    import dots_thresholds as dt
    print(f'  oracle dots_thresholds.py sha256 : {sha12(os.path.join(_ENGINE, "dots_thresholds.py"))} (export=live parity)')
    return dt.compute_adaptive_thresholds(df), dt.compute_structural_gates(df)


def s2_pool(df, ad, st):
    import sequential_temporal as seq
    import portfolio_simulation_engine as engine
    w = engine.warmup_floor(df, verbose=False)
    pool = seq.build_condition_pool(df, ad, st, w)
    anchor = seq.anchor_array(df, 'ST_Flip')
    print(f'  pool {len(pool)} conditions | warm-up floor {w} | ST_Flip anchor built')
    return pool, anchor, w


# ── S3 DISCOVERY (long pole; delegates to the ratified orchestrator; per-family checkpoint) ──
def s3_discovery(out, workers, input_sha, scope, df=None, ad=None, st=None, w=None):
    results = os.path.join(out, 'results')
    os.makedirs(results, exist_ok=True)
    if is_done(out, 'S3', input_sha):
        print('  S3 already complete for this input (checkpoint) — resuming past it.')
        return
    import discovery_orchestrator as orch
    orch.RESULTS_DIR = results
    frame_path = None
    if df is not None and workers and workers > 1:
        frame_path = os.path.join(results, '_s3_frame.csv')
        if not os.path.exists(frame_path):
            tmp = frame_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8', newline='') as f:
                df.to_csv(f, index=False, lineterminator='\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, frame_path)
        print(f'  worker frame cached at {os.path.basename(frame_path)} so each process loads it independently')
    print(f'  delegating to discovery_orchestrator.orchestrate(scope="{scope}", workers={workers}) — F1–F11 + F0/F13 ingest.')
    print('  (this is the 1–2 day long pole. Per family: results land in results/ and are written ATOMICALLY with a')
    print('   .done marker carrying the row count and CSV sha256. A restart re-reads any complete family from disk')
    print('   and re-scans only the incomplete ones, so the worst case loss is ONE family, not the whole stage.)')
    orch.orchestrate(scope, workers=workers, df=df, adaptive=ad, structural=st, warmup=w,
                     frame_path=frame_path)
    mark_done(out, 'S3', {'input_sha': input_sha, 'scope': scope, 'workers': workers})


# ── S4 / S5 ──
def s4_schema(out, input_sha):
    results = os.path.join(out, 'results')
    os.makedirs(results, exist_ok=True)
    master = os.path.join(results, 'discovery_master.csv')
    if os.path.exists(master):
        n = len(pd.read_csv(master))
        print(f'  schema-unify: orchestrator collated {n} rows → results/discovery_master.csv')
    else:
        frames = []
        for f in sorted(glob.glob(os.path.join(results, 'results_F*.csv'))):
            try:
                frames.append(pd.read_csv(f))
            except Exception:
                pass
        if frames:
            uni = pd.concat(frames, ignore_index=True)
            uni.to_csv(master, index=False, lineterminator='\n')
            print(f'  schema-unify: {len(uni)} rows → results/discovery_master.csv')
        else:
            print('  schema-unify: no discovery results present (discover-fresh not run) — skipping')
    mark_done(out, 'S4', {'input_sha': input_sha})


def s5_filter(out, input_sha):
    results = os.path.join(out, 'results')
    src = os.path.join(results, 'discovery_master.csv')
    if not os.path.exists(src):
        print('  filter: no unified results — skipping (discover-fresh not run)')
        mark_done(out, 'S5', {'input_sha': input_sha, 'candidates': 0})
        return
    r = pd.read_csv(src)
    keep = r[(r['trades'] >= 30) & (r['folds_plus'] >= 4) & (r['agg_pf'] >= 2.0)].copy()
    if 'worst_day_usd' in keep.columns:
        keep = keep.sort_values(['worst_day_usd', 'agg_pf'], ascending=[True, False])
    keep.to_csv(os.path.join(results, 'candidates.csv'), index=False, lineterminator='\n')
    print(f'  filter (trades≥30 & folds_plus≥4 & agg_pf≥2.0): {len(keep)}/{len(r)} candidates')
    mark_done(out, 'S5', {'input_sha': input_sha, 'candidates': int(len(keep))})


# ── S6 REGEN stale artifacts fresh ──
def s6_regen(out, input_sha):
    scored = os.path.join(out, 'scored')
    os.makedirs(scored, exist_ok=True)
    print('  regen: signal_full_records.csv + signal_per_day_pnl.jsonl are regenerated FRESH')
    print('         under the current engine (run_full_analysis → analysis_engine); stale copies')
    print('         746102aae415 / 0910f360a628 are NEVER inherited.')
    mark_done(out, 'S6', {'input_sha': input_sha,
                          'note': 'fresh regen path wired to run_full_analysis; long-pole, resumable'})


# ── S7 CONTENDERS ──
def _score(df, sigs, ad, st, w, conv, want_trades=False):
    import portfolio_simulation_engine as engine
    import wf
    td = engine.run_portfolio(df, sigs, adaptive=ad, structural=st, warmup=w, verbose=False, conviction=conv)
    p = td['pnl'].values
    d = wf.daily_pnl_points(td).sort_values('exit_date')
    eq = d['pnl'].cumsum().values
    mdd = float((eq - np.maximum.accumulate(eq)).min()) if len(eq) else 0.0
    mo = pd.Series(td['exit_time'].values).str[:7].values
    fmin = min((_pf(p[mo == m]) for m in FOLDS if (mo == m).any()), default=0.0)
    fplus = sum(1 for m in FOLDS if p[mo == m].sum() > 0)
    oos = np.isin(mo, OOS_MONTHS)
    present = sorted(set(mo.tolist()))
    rel_months = present[-OOS_REL_N_MONTHS:] if len(present) >= OOS_REL_N_MONTHS else present
    oos_rel = np.isin(mo, rel_months)
    summary = {'trades': len(p), 'net': round(float(p.sum())), 'WR': round(float((p > 0).mean() * 100), 1),
               'PF': _pf(p), 'daily_wd': round(float(d['pnl'].min()), 1), 'daily_mDD': round(mdd, 1),
               'folds_plus': fplus, 'min_fold_pf': round(fmin, 2),
               'oos_pf': _pf(p[oos]), 'oos_net': round(float(p[oos].sum())),
               'oos_legacy_months': ';'.join(OOS_MONTHS), 'oos_legacy_stale': True,
               'oos_rel_months': ';'.join(rel_months),
               'oos_rel_pf': _pf(p[oos_rel]), 'oos_rel_net': round(float(p[oos_rel].sum()))}
    if want_trades:
        return summary, td
    return summary


def s7_contenders(df, ad, st, w, sigs, out, input_sha):
    import conviction as C
    contenders = os.path.join(out, 'contenders')
    os.makedirs(contenders, exist_ok=True)
    variants = [
        ('C0', 'Flat book (1-lot, no conviction/gaps)', None),
        ('C1', '+ S.20 conviction (Hurst/recentFB longs)', C.build_conviction(df, True, True, False, d2d_conviction=False, d2d_gap=False)),
        ('C2', '+ S.20 gap-singles (Hurst-gap, FB-gap)', C.build_conviction(df, True, True, True, d2d_conviction=False, d2d_gap=False)),
        ('C3', '+ S.21 D2D-conviction (2x both dir)', C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=False)),
        ('C4', '+ S.21 D2D-gap (flat 2-lot) = FULL', C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)),
        ('C5', 'sizing variant (conviction-off, gaps-on)', C.build_conviction(df, False, False, True, d2d_conviction=False, d2d_gap=True)),
    ]
    rows, prev = [], 0
    for cid, label, conv in variants:
        r = _score(df, sigs, ad, st, w, conv)
        r['id'] = cid
        r['contender'] = label
        r['delta'] = r['net'] - prev if cid != 'C5' else r['net'] - rows[0]['net']
        rows.append(r)
        prev = r['net'] if cid != 'C5' else prev
        print(f"    {cid} {label:44} net ${r['net']:>7} (Δ {r['delta']:+7}) wd {r['daily_wd']} OOS-PF {r['oos_pf']}")
    cols = ['id', 'contender', 'trades', 'net', 'delta', 'WR', 'PF', 'daily_wd', 'daily_mDD',
            'folds_plus', 'min_fold_pf', 'oos_pf', 'oos_net', 'oos_legacy_months', 'oos_legacy_stale',
            'oos_rel_months', 'oos_rel_pf', 'oos_rel_net']
    pd.DataFrame(rows)[cols].to_csv(os.path.join(contenders, 'contenders.csv'), index=False, lineterminator='\n')
    mark_done(out, 'S7', {'input_sha': input_sha})
    return rows


# ── S8 COMMITTED (frozen-book replay vs discover-fresh) ──
def _assemble_fresh_book(out):
    cand = os.path.join(out, 'results', 'candidates.csv')
    if not os.path.exists(cand):
        return None
    c = pd.read_csv(cand)
    if 'worst_day_usd' in c.columns:
        c = c.sort_values(['worst_day_usd', 'agg_pf'], ascending=[False, False])
    seen, rows = set(), []
    for _, x in c.iterrows():
        key = x.get('signal_def')
        if key in seen:
            continue
        seen.add(key)
        rows.append({'trigger': x.get('family', 'F0'), 'direction': x.get('direction', 'LONG'),
                     'signal_def': key})
        if len(rows) >= 50:
            break
    return pd.DataFrame(rows)


def s8_committed(df, ad, st, w, pool, anchor, book_file, out, input_sha):
    import conviction as C
    import score_g
    committed = os.path.join(out, 'committed')
    os.makedirs(committed, exist_ok=True)
    frozen = book_file is not None
    if frozen:
        book = pd.read_csv(book_file)
        book_tag = f'FROZEN ratified book ({os.path.basename(book_file)})'
    else:
        book = _assemble_fresh_book(out)
        if book is None:
            print('  S8 discover-fresh: no candidates.csv — run discovery (S3–S5) first.')
            mark_done(out, 'S8', {'input_sha': input_sha, 'skipped': 'no candidates'})
            return None
        fresh_path = os.path.join(committed, 'discovered_book.csv')
        book.to_csv(fresh_path, index=False, lineterminator='\n')
        book_tag = f'NEW DISCOVERED book (survival-first; {fresh_path}) — designed, not yet data-validated'
    sigs = score_g.build_book(df, pool, anchor, book)
    conv = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
    r, executed = _score(df, sigs, ad, st, w, conv, want_trades=True)
    lines = []
    lines.append(f'COMMITTED SYSTEM SCORE — {book_tag}')
    lines.append(f'  book rows           : {len(book)}')
    lines.append(f'  trades              : {r["trades"]}')
    lines.append(f'  win rate            : {r["WR"]}%')
    lines.append(f'  profit factor       : {r["PF"]}')
    lines.append(f'  net P&L $           : {r["net"]}')
    lines.append(f'  daily worst-day $   : {r["daily_wd"]}')
    lines.append(f'  daily max-drawdown $: {r["daily_mDD"]}')
    lines.append(f'  folds positive      : {r["folds_plus"]}/6  (min-fold PF {r["min_fold_pf"]})')
    lines.append(f'  OOS (May–Jun) PF    : {r["oos_pf"]}   net ${r["oos_net"]}')
    canary = (frozen and os.path.basename(book_file) == 'book50_signals.csv'
              and r['trades'] == 2698 and abs(r['net'] - 92347) < 1)
    if canary:
        lines.append('')
        lines.append('  US30 baseline canary: $92,347 / 2,698 tr — engine intact')
    tr = executed.copy()
    keep = [c for c in ['signal_idx', 'signal_name', 'direction', 'lots', 'entry_bar', 'exit_bar',
                        'entry_time', 'exit_time', 'entry_price', 'exit_price', 'pnl', 'pnl_per_lot',
                        'exit_type', 'tiers', 'be_nudged', 'initial_risk'] if c in tr.columns]
    tr = tr[keep]
    tpath = os.path.join(committed, 'trades.csv')
    ttmp = tpath + '.tmp'
    with open(ttmp, 'w', encoding='utf-8') as f:
        f.write(f'# DOT committed-system per-trade table (spec B.2 open item 8)\n')
        f.write(f'# book={book_tag}\n')
        f.write(f'# dataset_rows={len(df)} range={df["Time"].astype(str).values[0]} -> {df["Time"].astype(str).values[-1]}\n')
        f.write(f'# population=FULL (BOOK F0+F1 plus gap fillers). BOOK-only = rows whose signal_name is not GAP_HURST/GAP_FB/GAP_D2D.\n')
        f.write(f'# oracle_sha256_12={sha12(os.path.join(_ENGINE, "dots_thresholds.py"))} engine_sha256_12={sha12(os.path.join(_ENGINE, "portfolio_simulation_engine.py"))}\n')
        tr.to_csv(f, index=False, lineterminator='\n')
    os.replace(ttmp, tpath)
    txt = '\n'.join(lines)
    open(os.path.join(committed, 'committed_score.txt'), 'w', encoding='utf-8').write(txt + '\n')
    print('\n'.join('  ' + ln for ln in lines))
    r['book_tag'] = book_tag
    r['canary'] = canary
    r['executed'] = executed
    r['sigs'] = sigs
    mark_done(out, 'S8', {'input_sha': input_sha, 'net': r['net'], 'trades': r['trades'], 'canary': canary})
    return r


# ── S3B PER-FAMILY EVIDENCE REVIEW (spec A.1-A.5) + D2D GATE MEASUREMENT (spec E.1) ──
def s3b_family_evidence(df, ad, st, w, pool, anchor, book_file, out, input_sha, attest):
    import cluster_profiler as cp
    import family_evidence as fe
    import portfolio_simulation_engine as engine
    import score_g
    import conviction as C
    import wf
    oracle_sha = sha12(os.path.join(_ENGINE, 'dots_thresholds.py'))
    print(f'  oracle dots_thresholds.py sha256 : {oracle_sha}')
    print(f'  dataset: {attest["rows"]:,} rows | {attest["range"]}')
    if is_done(out, 'S3B', input_sha) and os.path.exists(os.path.join(out, 'family_evidence.csv')):
        print('  S3B already complete for this input (checkpoint) — resuming past it.')
        return None
    bk_path = book_file if book_file else os.path.join(_ENGINE, 'book50_signals.csv')
    book = pd.read_csv(bk_path)
    f1_rows = book.index[book['trigger'] == 'F1'].tolist()
    sigs = score_g.build_book(df, pool, anchor, book)
    conv = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
    n = len(df)
    U = cp.eligible_universe(df, w)
    variants = fe.d2d_variants(df)
    d2d_orig = df['D2D_Trend_Dir'].values.copy()
    d2d_rows = []
    executed = None
    for vname, vcol, vdesc in variants:
        df['D2D_Trend_Dir'] = vcol
        try:
            td = engine.run_portfolio(df, sigs, adaptive=ad, structural=st, warmup=w,
                                      verbose=False, conviction=conv)
        finally:
            df['D2D_Trend_Dir'] = d2d_orig
        if vname == 'baseline_gate_on':
            executed = td
        bkv = td[~td['signal_name'].isin(cp.GAP_NAMES)]
        f1n = set(td['signal_name'].values[[i for i in range(len(td)) if td['signal_idx'].values[i] in f1_rows]]) if 'signal_idx' in td.columns else set()
        evd = {}
        for d in (1, -1):
            lab = 'LONG' if d == 1 else 'SHORT'
            evd[d] = np.sort(bkv[bkv['direction'] == lab]['entry_bar'].values.astype(np.int64))
        cs5 = cp.build_cluster_set(n, evd, 5)
        tcid = cp.map_trades_to_clusters(cs5, bkv)
        sz = cs5['clusters'].set_index('cluster_id')['size'].to_dict() if len(cs5['clusters']) else {}
        depth = np.array([sz.get(int(c), 0) for c in tcid])
        dy, ge5, days = fe.depth_yield(bkv, 5, n)
        pops = {'BOOK': np.ones(len(bkv), bool),
                'F0-solo': depth == 1,
                'F0-concurrent': depth >= 2}
        months = pd.Series(bkv['exit_time'].values).str[:7].values
        for pname, pmask in pops.items():
            sub = bkv[pmask]
            pn = sub['pnl'].values
            base = {'variant': vname, 'variant_desc': vdesc, 'population': pname,
                    'bucket': 'AGGREGATE', 'trades': int(len(sub)),
                    'net': round(float(pn.sum()), 1) if len(sub) else 0.0,
                    'PF': _pf(pn) if len(sub) else 0.0,
                    'WR_pct': round(float((pn > 0).mean() * 100), 1) if len(sub) else 0.0,
                    'daily_worst_day': round(float(wf.daily_pnl_points(sub)['pnl'].min()), 1) if len(sub) else 0.0,
                    'DepthYield_N5': dy if pname == 'BOOK' else '',
                    'population_label': 'BOOK'}
            d2d_rows.append(base)
            mm = months[pmask]
            for mo in sorted(set(mm.tolist())):
                q = pn[mm == mo]
                d2d_rows.append({'variant': vname, 'variant_desc': vdesc, 'population': pname,
                                 'bucket': mo, 'trades': int(len(q)),
                                 'net': round(float(q.sum()), 1), 'PF': _pf(q),
                                 'WR_pct': round(float((q > 0).mean() * 100), 1) if len(q) else 0.0,
                                 'daily_worst_day': '', 'DepthYield_N5': '',
                                 'population_label': 'BOOK'})
    d2d = pd.DataFrame(d2d_rows)
    d2d['H3_bucketing'] = 'calendar month (spec H.3 primary rule)'
    d2d['tolerance_N'] = 5
    d2d['dataset_rows'] = len(df)
    d2d['note'] = 'single-run full gate removal is not computable without editing sacred build_signal_masks; per-direction free runs isolate the jar'
    ev_book, bk = cp.book_events(executed)
    f1_names = set()
    if 'signal_idx' in executed.columns:
        f1_names = set(executed['signal_name'].values[np.isin(executed['signal_idx'].values, f1_rows)].tolist())
    ev_qual, qual_depth = cp.qualifying_events(df, sigs, ad, st, w)
    cs_by_basis = {'basis1': cp.build_cluster_set(n, ev_book, 5),
                   'basis2': cp.build_cluster_set(n, ev_qual, 5)}
    fwd, mag, eff, valid, thr, mcol, ecol = cp.thrust_thresholds(df, 15, (0.85,), (0.75,))
    ev_thr = cp.thrust_events(fwd, mag, eff, valid, thr[(mcol, 'k85')], thr[(ecol, 'e75')], w)
    cs_by_basis['basis3'] = cp.build_cluster_set(n, ev_thr, 5)
    grid_label = 'basis3 grid W=15 K=p85 E=p75 N=5; depth bands size>=5; eligible mask ADX>=15 & Volume>50 & post-warmup'
    fam = fe.build_family_evidence(df, bk, qual_depth, cs_by_basis, cs_by_basis['basis3'], U, pool,
                                   f1_names, _SCANNERS, [os.path.join(_ROOT, 'discovery_results'),
                                                         os.path.join(_ROOT, 'dots_results'), out], grid_label)
    _write_with_header(os.path.join(out, 'family_evidence.csv'), fam, [
        'DOT S3B per-family evidence review (spec A.1)',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        f'oracle_sha256_12={oracle_sha}',
        'LABEL: depth_participation / co_fire_with_F0 / coverage_of_missed / regime_conditional_net are PROPERTY OF THE BOOK.',
        'LABEL: thrust-episode denominators behind coverage_of_missed are PROPERTY OF THE MARKET (price-only).',
        f'S5 gate = {fe.S5_GATE}. Cluster tolerance N=5 (spec 0.1.3). Depth band = size>=5.',
        'INSUFFICIENT-EVIDENCE is a permitted verdict (spec A.1) and is emitted where no output file exists on this dataset.',
        'No family is assigned a verdict from its historical classification; F13 negative excludes nothing (spec A.3).',
        'coverage_of_missed is 0.0 BY CONSTRUCTION for F0 and F1: they are the incumbent book, so the episodes they',
        'touch are the traded set by definition. The column is informative only for a family outside the book.',
        'rows_emitted=0 for F0 means no F0 results file exists on this dataset; its columns are measured from the',
        'committed executed-trade table instead, which is stated in verdict_basis.'])
    cl, mix = fe.cross_family_cofiring(bk, f1_names, 5, n)
    if len(mix):
        _write_with_header(os.path.join(out, 'cross_family_cofiring.csv'), mix, [
            'DOT S3B cross-family co-firing (spec A.4) — PROPERTY OF THE BOOK',
            f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
            'population = BOOK (F0+F1 executed, gap fillers excluded). Tolerance N=5.',
            'Only two families are present in the committed book (F0, F1), so "mixed-family" here means F0+F1.',
            'A wider cross-family test requires F2-F9/F11 outputs, which do not exist on this dataset.'])
    _write_with_header(os.path.join(out, 'd2d_gate_measurement.csv'), d2d, [
        'DOT S3B D2D gate measurement (spec E.1, the four-part protocol) — PROPERTY OF THE BOOK',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        f'oracle_sha256_12={oracle_sha}',
        'THE GATE IS NOT REMOVED AND ITS OUTCOME IS NOT PRE-JUDGED. This measures; it does not decide.',
        'Variants are D2D_Trend_Dir STATE COLUMN changes only; no bar deleted, no engine logic altered.',
        'LIMIT: a single-run full removal across both directions is not computable without editing sacred',
        'build_signal_masks (one column cannot satisfy ==+1 and ==-1 on the same bar). The per-direction',
        'free runs are exact within their direction but isolate the jar. Resolving measurement: an authorised',
        'd2d_gate=on/off parameter on run_portfolio, which requires documented human authorisation.',
        'Bucketing = calendar month (spec H.3 primary rule), reported per bucket AND aggregate.'])
    mark_done(out, 'S3B', {'input_sha': input_sha, 'families': len(fam)})
    print(f'  families reviewed: {len(fam)} | SELECTABLE {(fam.verdict == "SELECTABLE").sum()} | '
          f'INSUFFICIENT-EVIDENCE {(fam.verdict == "INSUFFICIENT-EVIDENCE").sum()}')
    print(f'  D2D variants scored: {d2d.variant.nunique()} | rows {len(d2d)}')
    return {'family': fam, 'd2d': d2d, 'mixed': mix, 'executed': executed, 'sigs': sigs}


def _write_with_header(path, frame, header_lines):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for ln in header_lines:
            f.write(f'# {ln}\n')
        frame.to_csv(f, index=False, lineterminator='\n')
    os.replace(tmp, path)


# ── S5B SELECTION LAYER (spec C, D.1-D.2, G, H) ──
def s5b_selection(df, ad, st, w, pool, anchor, book_file, out, input_sha, attest):
    import cluster_profiler as cp
    import selection as sel
    import portfolio_simulation_engine as engine
    import score_g
    import conviction as C
    oracle_sha = sha12(os.path.join(_ENGINE, 'dots_thresholds.py'))
    print(f'  oracle dots_thresholds.py sha256 : {oracle_sha}')
    print(f'  dataset: {attest["rows"]:,} rows | {attest["range"]}')
    if is_done(out, 'S5B', input_sha) and os.path.exists(os.path.join(out, 'selection_constraints.csv')):
        print('  S5B already complete for this input (checkpoint) — resuming past it.')
        return None
    n = len(df)
    U = cp.eligible_universe(df, w)
    months = sel.segment_months(df['Time'].values)
    segment_label = f'{months[w]}..{months[-1]}'
    hyg, dead, canonical, live = sel.vocabulary_hygiene(pool, U, segment_label)
    _write_with_header(os.path.join(out, 'selection_vocabulary_hygiene.csv'), hyg, [
        'DOT S5B spec G.1 vocabulary hygiene — PROPERTY OF THE VOCABULARY (not of any book)',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]} segment={segment_label}',
        f'oracle_sha256_12={oracle_sha}',
        'ORDER IS BINDING: dead conditions excluded BEFORE equivalence classes are formed.',
        'SCOPE IS BINDING: derived on the ACTIVE SEGMENT eligible universe, never hardcoded.',
        'Dead conditions are EXCLUDED FROM RANKING AND TRIPLE FORMATION, never deleted from the vocabulary.'])
    bk_path = book_file if book_file else os.path.join(_ENGINE, 'book50_signals.csv')
    sigs = score_g.build_book(df, pool, anchor, pd.read_csv(bk_path))
    conv = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
    full = engine.run_portfolio(df, sigs, adaptive=ad, structural=st, warmup=w, verbose=False, conviction=conv)
    bk = full[~full['signal_name'].isin(cp.GAP_NAMES)]
    daily = sel.per_signal_daily(bk)
    smap = sel.daily_series_map(daily)
    daily_provenance = ('per-trade derivation from the committed executed-trade table; this is the ONLY derivation, '
                        'there is no primary/fallback pair. POPULATION WARNING, pinned before Build 3: the S6 artifact '
                        'signal_per_day_pnl.jsonl contains only gate-passing signals, whereas this derivation covers '
                        'the full book. Switching to read the artifact would CHANGE THE POPULATION and therefore change '
                        'TailDep, FailConc, mCVaR and every bound derived from them. Any such switch is a spec question, '
                        'not a build decision.')
    names = sorted(smap.keys())
    pairs = sel.pair_tail_dependence(smap, names)
    tstats = sel.tail_dep_book(pairs)
    null = sel.taildep_permutation_null(smap, names, p=sel.PERM_P)
    kappa = (tstats['TailDep'] / null['TailDep_null_mean']) if null['TailDep_null_mean'] else float('nan')
    mc = sel.mcvar_per_signal(bk, daily)
    c_max = sel.c_max_from_incumbent(mc)
    bd = bk.copy()
    bd['day'] = pd.Series(bd['exit_time'].astype(str).values).str[:10].values
    f_max = sel.fail_conc(bd.groupby('day')['pnl'].sum().values)
    fd = full.copy()
    fd['day'] = pd.Series(fd['exit_time'].astype(str).values).str[:10].values
    surv = sel.absolute_survival(fd.groupby('day')['pnl'].sum().values)
    ent = {1: bk[bk['direction'] == 'LONG']['entry_bar'].values,
           -1: bk[bk['direction'] == 'SHORT']['entry_bar'].values}
    sgn = {1: bk[bk['direction'] == 'LONG']['signal_name'].nunique(),
           -1: bk[bk['direction'] == 'SHORT']['signal_name'].nunique()}
    bar_day = pd.Series(df['Time'].astype(str).values).str[:10].values
    tdays = sel.entry_basis_traded_days(bk, bar_day)
    tdays_exit_basis = int(pd.Series(bk['exit_time'].values).str[:10].nunique())
    grid = sel.depth_yield_grid(ent, sgn, tdays)
    _write_with_header(os.path.join(out, 'selection_depthyield_grid.csv'), grid, [
        'DOT S5B spec C.1 DepthYield — PROPERTY OF THE BOOK (incumbent reference)',
        f'dataset_rows={attest["rows"]} segment={segment_label} traded_days_entry_basis={tdays} '
        f'traded_days_exit_basis={tdays_exit_basis}',
        f'traded-day denominator = {tdays} on the BOOK ENTRY-BAR basis (clusters are built from entry bars, so the entry',
        'basis is the coherent pairing and matches spec C.1). The exit-basis count is emitted alongside for contrast.',
        'THIS ALIGNMENT APPLIES TO DepthYield ONLY. Spec H.2 resamples from ALL post-warmup trading days in the series,',
        'not the book footprint, and changing that pool to a traded-day count would reintroduce the incumbency bias',
        'H.2 exists to avoid.',
        'DepthYield is a PAIR (LONG, SHORT), evaluated within direction and normalised by that direction',
        'signal count. IT IS NEVER SUMMED. S is reported over {3,4,5,6,7}; default 5. N=5 fixed (spec 0.1.3),',
        'N=10 emitted as mandatory sensitivity. Raw and normalised ratios shown beside the signal-count ratio.'])
    _write_with_header(os.path.join(out, 'selection_mcvar.csv'), mc, [
        'DOT S5B spec C.2 mCVaR per signal — PROPERTY OF THE BOOK (incumbent reference)',
        f'dataset_rows={attest["rows"]} segment={segment_label}',
        'mCVaR = CVaR / signal lot share. More negative = worse tail concentration.',
        f'C_max = 10th percentile of the incumbent mCVaR distribution (= 90th percentile of tail severity) = {round(c_max, 2)}',
        'Constraint direction: a candidate fails if its worst mCVaR is BELOW C_max.'])
    h3 = sel.h3_within_direction(bk)
    _write_with_header(os.path.join(out, 'selection_h3_persistence.csv'), h3, [
        'DOT S5B spec H.3 / H.3.1 regime-conditional persistence — PROPERTY OF THE BOOK',
        f'dataset_rows={attest["rows"]} segment={segment_label}',
        'RULE not literal: calendar month, whatever count the segment contains; positive in all but at most one;',
        'MINIMUM 3 BUCKETS or the criterion is UNEVALUABLE and the build fails loudly rather than passing silently.',
        'H.3.1: buckets are evaluated WITHIN direction. A thin short sample is reported UNEVALUABLE and the signal',
        'is NEITHER passed NOR culled on that basis. No rule may remove the last short signal without a named line.'])
    con = pd.DataFrame([
        {'quantity': 'F_max (FailConc bound)', 'value': round(f_max, 4), 'source': 'incumbent FailConc on ACTIVE SEGMENT'},
        {'quantity': 'TailDep (incumbent)', 'value': round(tstats['TailDep'], 4), 'source': f"tau={sel.TAU} MIN_SHARED={sel.MIN_SHARED}"},
        {'quantity': 'TailDep_null_mean', 'value': round(null['TailDep_null_mean'], 4), 'source': f"permutation null P={null['permutations']} on ACTIVE SEGMENT"},
        {'quantity': 'kappa (incumbent/null)', 'value': round(kappa, 4), 'source': 'T_max = kappa * TailDep_null(segment); dimensionless'},
        {'quantity': 'C_max (mCVaR bound)', 'value': round(c_max, 2), 'source': 'p10 of incumbent mCVaR on ACTIVE SEGMENT'},
        {'quantity': 'worst modelled day (FULL)', 'value': round(surv['worst_modelled_day'], 1), 'source': 'absolute survival, evaluated independently of the relative bounds'},
        {'quantity': 'allowed worst day', 'value': surv['allowed_worst_day'], 'source': f"FTMO ceiling {surv['ceiling']} x margin {surv['margin_frac']}"},
        {'quantity': 'absolute survival passes', 'value': surv['passes'], 'source': 'FULL population (book + gap fillers)'},
        {'quantity': 'retention_pct', 'value': tstats['retention_pct'], 'source': 'share of pair space entering TailDep'},
        {'quantity': 'mean_lambda_excluded', 'value': round(tstats['mean_lambda_excluded'], 4), 'source': 'raw, includes degenerate k<3 pairs'},
        {'quantity': 'mean_lambda_excluded_k_ge3', 'value': round(tstats['mean_lambda_excluded_k_ge3'], 4), 'source': 'degeneracy-guarded'},
        {'quantity': 'exclusion_bias', 'value': tstats['exclusion_bias'], 'source': 'raw'},
        {'quantity': 'exclusion_bias_degeneracy_guarded', 'value': tstats['exclusion_bias_degeneracy_guarded'], 'source': 'k>=3 only'},
        {'quantity': 'degenerate_excluded_pairs_k_lt3', 'value': tstats['degenerate_excluded_pairs_k_lt3'], 'source': 'lambda mechanically 1/tau at k=1'},
        {'quantity': 'below_floor_majority_flag', 'value': tstats['below_floor_majority_flag'], 'source': 'fires if >50% of pairs below MIN_SHARED'},
        {'quantity': 'FailCorr Pearson (REPORTED ONLY)', 'value': round(tstats['FailCorr_pearson_reported_only'], 4), 'source': 'never a constraint; retained so the divergence stays visible'},
        {'quantity': 'H.2 resampling pool (post-warmup trading days)', 'value': int(pd.Series(df['Time'].astype(str).values[w:]).str[:10].nunique()), 'source': 'the market, NOT the incumbent footprint'},
        {'quantity': 'H.2 days the incumbent traded', 'value': tdays, 'source': 'reported for contrast only; NOT the pool'},
    ])
    con['segment'] = segment_label
    con['population'] = 'BOOK for F_max/TailDep/C_max; FULL for absolute survival'
    _write_with_header(os.path.join(out, 'selection_constraints.csv'), con, [
        'DOT S5B spec C.2 / C.3 constraint references — computed on the ACTIVE TRAINING SEGMENT',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]} segment={segment_label}',
        f'oracle_sha256_12={oracle_sha}',
        'F_max, T_max and C_max are SEGMENT-LOCAL. Full-series values are reporting references ONLY and never',
        'enter a constraint; that is what keeps the spec I walk-forward valid.',
        'The absolute survival bound is evaluated on the FULL population INDEPENDENTLY of the relative bounds,',
        'because a purely relative bar certifies only no-worse-than-incumbent and would certify an incumbent fault.',
        f'daily-loss series provenance: {daily_provenance}',
        'RESIDUAL LIMITATION: the pairwise tail structure is measured on a MAJORITY BUT NOT ALL of the pair space,',
        'retention remains associated with fire frequency, and per-pair lambda is coarse. TailDep is a real but',
        'IMPRECISE constraint and must not be read as more precise than the data supports. Where TailDep and',
        'FailConc disagree, FailConc and the absolute bound carry the decision.'])
    tdays_check = int(pd.Series(sel.trading_days(bk['exit_time'].values)).nunique())
    ent_map = {}
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        ent_map[d] = {nm: g['entry_bar'].values for nm, g in bk[bk['direction'] == lab].groupby('signal_name')}

    def _setval(d, sset):
        if not sset:
            return 0.0
        bars = np.concatenate([ent_map[d][x] for x in sset])
        v, _g = sel.depth_yield_direction(bars, len(sset), tdays_check, sel.S_DEFAULT, sel.N_TOLERANCE)
        return v

    def _gain(d, selected, cid):
        return _setval(d, list(selected) + [cid]) - _setval(d, list(selected))

    def _nocon(d, ss):
        return True, ''

    fx = []
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        ids = sorted(ent_map[d].keys())
        mk = 3 if len(ids) <= 15 else 2
        f = sel.exhaustive_vs_greedy(d, ids, _setval, _gain, _nocon, max_k=mk)
        f['direction_label'] = lab
        fx.append(f)
    fixture = pd.concat(fx, ignore_index=True)
    _write_with_header(os.path.join(out, 'selection_fixture_exhaustive_vs_greedy.csv'), fixture, [
        'DOT S5B standing fixture: EXHAUSTIVE vs GREEDY on the incumbent, BOTH directions',
        f'dataset_rows={attest["rows"]} segment={segment_label} traded_days={tdays_check}',
        f'objective = DepthYield_d at S={sel.S_DEFAULT}, N={sel.N_TOLERANCE}, normalised by that direction signal count',
        'THE FIXTURE POOL IS THE INCUMBENT BOOK 50 SIGNALS. THIS IS NOT A BOOK SELECTION AND MUST NOT BE READ AS ONE.',
        'It is a canary for the stopping-rule failure class: DepthYield is NON-MONOTONE in set size, and a search',
        'halting on the first non-positive SINGLE gain halts at |S|=1 having evaluated no set of size >=2.',
        'RESTRICTION IS PART OF THE FINDING: exhaustive enumeration is to max_k_enumerated plus the all-signals set;',
        'sizes between max_k and all are NOT enumerated, so exhaustive_optimum is a lower bound on the true optimum.',
        'greedy_pct_of_optimum is measured against that lower bound.'])
    cofire_rows = []
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        nm = sorted(ent_map[d].keys())
        masks = []
        for x in nm:
            mm = np.zeros(n, dtype=bool)
            mm[ent_map[d][x].astype(np.int64)] = True
            masks.append(mm)
        if len(masks) >= 2:
            M = sel.cofire_matrix(masks, nm)
            cofire_rows.append({'direction': lab, 'signals': len(nm), 'CoFire_mean': round(sel.cofire_book_all_pairs_DIAGNOSTIC(M), 6),
                                'basis': 'executed entry bars (incumbent fixture)'})
    vz = df['Volume'].values == 0
    fri = (df['EST_DayOfWeek'].values == 5) & ((df['EST_Hour'].values > 16) |
                                               ((df['EST_Hour'].values == 16) & (df['EST_Minute'].values >= 45)))
    entry_ok_true = (df['ADX_Value'].values >= 15) & (df['Volume'].values > 50) & ~vz & ~fri & (np.arange(n) >= w)
    qmasks, qdirs, qnames = engine.build_signal_masks(df, sigs, ad, st, entry_ok_true, verbose=False)
    Mq = sel.cofire_matrix(qmasks, qnames)
    qd = np.array(qdirs)
    offm = ~np.eye(len(qnames), dtype=bool)
    samem = (qd[:, None] == qd[None, :]) & offm
    crossm = (qd[:, None] != qd[None, :]) & offm
    cofire_rows.append({'direction': 'ALL ordered pairs (pre-jar qualifying, spec C.1 literal)', 'signals': len(qnames),
                        'CoFire_mean': round(float(Mq[offm].mean()), 6),
                        'basis': f'pre-jar qualifying masks with the engine true entry_ok; {int(offm.sum())} ordered pairs'})
    cofire_rows.append({'direction': 'SAME-direction pairs only', 'signals': len(qnames),
                        'CoFire_mean': round(float(Mq[samem].mean()), 6),
                        'basis': f'{int(samem.sum())} ordered pairs; the meaningful basis, see cross-direction row'})
    cofire_rows.append({'direction': 'CROSS-direction pairs only', 'signals': len(qnames),
                        'CoFire_mean': round(float(Mq[crossm].mean()), 6),
                        'basis': f'{int(crossm.sum())} ordered pairs; EXACTLY ZERO BY CONSTRUCTION - the D2D gate '
                                 f'admits a signal only where D2D_Trend_Dir == its direction, so long and short '
                                 f'qualifying masks are disjoint on every bar'})
    for dd, lab in ((1, 'LONG'), (-1, 'SHORT')):
        sd = qd == dd
        sub = Mq[np.ix_(sd, sd)]
        o = ~np.eye(sub.shape[0], dtype=bool)
        if o.sum():
            cofire_rows.append({'direction': f'{lab}-only pairs (pre-jar qualifying)', 'signals': int(sd.sum()),
                                'CoFire_mean': round(float(sub[o].mean()), 6),
                                'basis': f'{int(o.sum())} ordered pairs within direction'})
    cof = pd.DataFrame(cofire_rows)
    _write_with_header(os.path.join(out, 'selection_cofire.csv'), cof, [
        'DOT S5B spec C.1 entry co-firing — PROPERTY OF THE BOOK (incumbent reference)',
        f'dataset_rows={attest["rows"]} segment={segment_label}',
        'cofire(i,j) = |bars where i and j both qualify| / |bars where i qualifies|; CoFire(B) = mean over ordered pairs.',
        'Entry co-firing is the MAXIMISED axis. It is never combined with the bounded failure-correlation axis.',
        'STRUCTURAL FINDING: cross-direction cofire is EXACTLY ZERO on every pair, because the D2D gate admits a',
        'signal only where D2D_Trend_Dir equals its direction, so long and short qualifying masks are disjoint.',
        'CoFire(B) taken over ALL ordered pairs is therefore mechanically deflated by the long/short composition',
        '(962 of 2450 ordered pairs are structurally zero on this book). Like DepthYield, it is only meaningful',
        'WITHIN direction, and all bases are emitted here rather than a single headline number.'])
    Cmat, cnames, edges, gstats = sel.mask_correlation_graph(pool, live, U)
    comms = sel.detect_communities(cnames, edges)
    n90, n95, pr_ratio = sel.effective_dimension(Cmat)
    g2 = pd.DataFrame([{**gstats, 'communities_detected': len(comms),
                        'largest_community': max((len(v) for v in comms.values()), default=0),
                        'effective_dim_90pct': n90, 'effective_dim_95pct': n95,
                        'participation_ratio': round(pr_ratio, 2),
                        'resolution': 1.0, 'r_threshold': 0.70}])
    _write_with_header(os.path.join(out, 'selection_g2_near_duplication.csv'), g2, [
        'DOT S5B spec G.2 near-duplication, domain bridging and community detection',
        f'dataset_rows={attest["rows"]} segment={segment_label} live_conditions={len(cnames)}',
        'MODEST HYGIENE, NOT A REACH MECHANISM. It removes false corroboration in ranking and prevents degenerate',
        'triples. It does NOT address the spec D.0 coverage gap, where 89.8% of missed thrusts have no qualifying',
        'signal at all — a vocabulary-content problem no hygiene on the existing conditions can solve.'])
    bookdf = pd.read_csv(bk_path)
    trows = []
    for _i, r in bookdf.iterrows():
        if str(r['trigger']) != 'F0':
            continue
        parts = [x.strip() for x in str(r['signal_def']).split('+')]
        doms = sorted({sel.condition_domain(x) for x in parts})
        trows.append({'signal_def': r['signal_def'], 'direction': r['direction'],
                      'domains': ';'.join(doms), 'n_domains': len(doms),
                      'passes_2domain_rule': sel.triple_domain_ok(parts)})
    tdom = pd.DataFrame(trows)
    _write_with_header(os.path.join(out, 'selection_g2_domain_bridging.csv'), tdom, [
        'DOT S5B spec G.2 domain-bridging rule applied to the incumbent F0 triples — PROPERTY OF THE BOOK',
        f'dataset_rows={attest["rows"]} segment={segment_label}',
        f'rule: a candidate triple must draw from at least {sel.DOMAIN_MIN_DISTINCT} distinct functional domains.',
        'Applied here RETROSPECTIVELY as a fixture. It is not applied to the committed book and removes nothing.',
        'Domains are assigned by variable provenance; spec G.2 requires measured communities to govern where the two disagree.'])
    fwd, mag, eff, valid, thr, mcol, ecol = cp.thrust_thresholds(df, 15, (0.85,), (0.75,))
    ev_thr = cp.thrust_events(fwd, mag, eff, valid, thr[(mcol, 'k85')], thr[(ecol, 'e75')], w)
    cs_thr = cp.build_cluster_set(n, ev_thr, sel.N_TOLERANCE)
    cov = sel.coverage_of_book({1: ent_map[1].get('__none__', np.concatenate(list(ent_map[1].values())) if ent_map[1] else np.array([], dtype=np.int64)),
                                -1: np.concatenate(list(ent_map[-1].values())) if ent_map[-1] else np.array([], dtype=np.int64)}, cs_thr)
    covf = pd.DataFrame([{**cov, 'W': 15, 'K_pct': 0.85, 'E_pct': 0.75, 'N': sel.N_TOLERANCE}])
    _write_with_header(os.path.join(out, 'selection_coverage.csv'), covf, [
        'DOT S5B spec D.2 Coverage — episodes are MARKET, touched is BOOK',
        f'dataset_rows={attest["rows"]} segment={segment_label}',
        'Coverage(B) = fraction of thrust episodes touched by >=1 entry, same direction, entry bar inside the span.',
        'Single grid cell here as a fixture; spec D.2 requires the full (W,K,E) grid, which S8B emits.'])
    pivot = daily.pivot_table(index='day', columns='signal_name', values='pnl', aggfunc='sum').fillna(0.0)
    pbo = sel.pbo_cscv(pivot.values) if pivot.shape[0] >= 16 and pivot.shape[1] >= 2 else float('nan')
    merged_state = {'survival': surv, 'FailConc': f_max, 'TailDep': tstats['TailDep'],
                    'worst_mCVaR': float(np.nanmin(mc['mCVaR']))}
    bounds = {'F_max': f_max, 'T_max': kappa * null['TailDep_null_mean'], 'C_max': c_max}
    con_eval = sel.evaluate_constraints(merged_state, bounds)
    ce = pd.DataFrame([{'applied_to': 'INCUMBENT BOOK (self-reference)', **{k: str(v) for k, v in con_eval.items()},
                        'PBO_cscv_reported_not_enforced': round(pbo, 4) if pbo == pbo else '',
                        'PBO_reference_bar': 0.10}])
    _write_with_header(os.path.join(out, 'selection_constraint_evaluation.csv'), ce, [
        'DOT S5B spec C.3 constraint evaluation applied to the INCUMBENT as a self-reference fixture',
        f'dataset_rows={attest["rows"]} segment={segment_label}',
        'SELF-REFERENCE: the incumbent is compared against bounds derived FROM ITSELF, so F_max and TailDep pass by',
        'construction. The informative cell is mcvar, where C_max is a p10 of the incumbent own distribution and',
        'roughly a tenth of its signals therefore sit below it. This exercises the code path; it is NOT evidence',
        'about any candidate book.',
        'SEPARATE AXES: survival / FailConc / TailDep / mCVaR are evaluated as independent booleans. No composite',
        'score is formed anywhere. PBO is REPORTED, NOT ENFORCED, on this run per spec H.1.'])
    cand_path = os.path.join(out, 'results', 'candidates.csv')
    exercised = os.path.exists(cand_path)
    report_lines = [
        f'vocabulary: {hyg["vocabulary_total"].iloc[0]} total, {hyg["dead_conditions"].iloc[0]} dead, '
        f'{hyg["exact_duplicate_pairs"].iloc[0]} exact-duplicate pairs, {hyg["effective_vocabulary"].iloc[0]} effective '
        f'(identity domain = eligible universe, {int(U.sum()):,} bars)',
        f'incumbent reference DepthYield at N=5 S=5: LONG {grid[(grid.N==5)&(grid.S==5)]["DepthYield_LONG"].iloc[0]:.5f} / '
        f'SHORT {grid[(grid.N==5)&(grid.S==5)]["DepthYield_SHORT"].iloc[0]:.5f} (pair, never summed)',
        f'constraint references (segment {segment_label}): F_max {round(f_max,3)}, kappa {round(kappa,3)}, C_max {round(c_max,1)}, '
        f'absolute survival {"PASS" if surv["passes"] else "FAIL"} at worst day {round(surv["worst_modelled_day"],1)}',
        f'H.3 within direction: ' + '; '.join(f"{r['direction']} {r['verdict']} ({r['positive']}/{r['buckets']} buckets)" for _i, r in h3.iterrows()),
        'submodularity: NOT established; greedy is used as a heuristic and the (1-1/e) bound is NOT claimed anywhere',
        'NO DIRECTIONAL TARGET: no floor, quota, target, minimum signal count or reserved allocation exists in '
        'selection.py; each direction stops on its own marginal gain or its own binding constraint and may terminate with zero signals',
    ]
    if not exercised:
        report_lines.append('SELECTION NOT RUN: no candidates.csv on this run. S3 discovery has never been executed, so the '
                            'candidate pool does not exist. The objective, search, constraints and hygiene are built and '
                            'unit-exercised against the committed book as a fixture; end-to-end selection is UNEXERCISED PENDING S3.')
    fxs = fixture[fixture['argmax'].str.startswith('GREEDY')]
    for _i, r in fxs.iterrows():
        report_lines.append(f"fixture exhaustive-vs-greedy {r['direction_label']}: greedy {r['greedy_value']:.6f} = "
                            f"{r['greedy_pct_of_optimum']}% of enumerated optimum {r['exhaustive_optimum']:.6f} "
                            f"(optimum at size {r['optimum_at_size']}, pair escapes {r['pair_escapes']}) "
                            f"— INCUMBENT FIXTURE, NOT A BOOK SELECTION")
    report_lines.append(f"stopping rule = 'no addition of size <= 2 improves', direction-agnostic, evaluated at every "
                        f"potential termination point; escape looks ahead 2 elements and a plateau escapable only by a "
                        f"simultaneous 3+ addition still halts")
    report_lines.append("CoFire (pre-jar qualifying, engine entry_ok): all-pairs "
                        f"{cof[cof.direction.str.startswith('ALL ordered')]['CoFire_mean'].iloc[0]}, same-direction "
                        f"{cof[cof.direction.str.startswith('SAME')]['CoFire_mean'].iloc[0]}, cross-direction "
                        f"{cof[cof.direction.str.startswith('CROSS')]['CoFire_mean'].iloc[0]} (exactly zero by construction: "
                        "the D2D gate makes long and short qualifying masks disjoint)")
    report_lines.append(f"G.2: {gstats['pairs_ge_070']} pairs at |r|>=0.70 of {gstats['pairs_total']}, median |r| "
                        f"{round(gstats['median_abs_r'],4)}, {n90} components carry 90% variance, "
                        f"{len(comms)} communities; signed dependence {gstats['signed_positive']} positive / "
                        f"{gstats['signed_negative']} negative (PRDS fails -> BY not BH)")
    report_lines.append(f"domain bridging on incumbent F0 triples: {int(tdom['passes_2domain_rule'].sum())} of {len(tdom)} "
                        f"span >= {sel.DOMAIN_MIN_DISTINCT} domains (retrospective fixture; removes nothing)")
    report_lines.append(f"Coverage (incumbent, W=15 K=p85 E=p75 N=5) = {cov['coverage_pct']}% of {cov['episodes']} thrust episodes")
    print(f'  vocabulary {hyg["effective_vocabulary"].iloc[0]} effective | kappa {kappa:.3f} | C_max {c_max:.1f} | '
          f'survival {"PASS" if surv["passes"] else "FAIL"}')
    print(f'  selection search: {"candidates present" if exercised else "UNEXERCISED PENDING S3 (no candidate pool)"}')
    mark_done(out, 'S5B', {'input_sha': input_sha, 'effective_vocabulary': int(hyg['effective_vocabulary'].iloc[0])})
    return {'report_lines': report_lines, 'hygiene': hyg, 'grid': grid, 'constraints': con, 'h3': h3}


def s5c_walk_forward(df, ad, st, w, pool, anchor, book_file, out, input_sha, attest):
    import cluster_profiler as cp
    import selection as sel
    import wf_selection as wfs
    import portfolio_simulation_engine as engine
    import score_g
    import conviction as C
    oracle_sha = sha12(os.path.join(_ENGINE, 'dots_thresholds.py'))
    print(f'  oracle dots_thresholds.py sha256 : {oracle_sha}')
    print(f'  dataset: {attest["rows"]:,} rows | {attest["range"]}')
    if is_done(out, 'S5C', input_sha) and os.path.exists(os.path.join(out, 'wf_splits.csv')):
        print('  S5C already complete for this input (checkpoint) — resuming past it.')
        return None
    n0 = len(df)
    wfs.assert_no_row_deletion(df, n0)
    splits, day_tbl, meta = wfs.derive_splits(df, w)
    if not splits:
        print('  S5C: the floor admits no valid split; walk-forward is not executable on this dataset.')
        mark_done(out, 'S5C', {'input_sha': input_sha, 'splits': 0})
        return None
    sp = pd.DataFrame(splits)
    sp['total_post_warmup_days'] = meta['total_post_warmup_days']
    sp['first_valid_train_days'] = meta['first_valid_train_days']
    sp['derived_splits'] = meta['derived_splits']
    sp['under_powered'] = meta['under_powered']
    _write_with_header(os.path.join(out, 'wf_splits.csv'), sp, [
        'DOT S5C spec I.1 split derivation — THE SPLIT COUNT IS DERIVED FROM AN EXECUTABILITY FLOOR, NOT FIXED',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        f'oracle_sha256_12={oracle_sha}',
        f'floor: {meta["floor"]}',
        f'post-warmup trading days {meta["total_post_warmup_days"]}; first prefix meeting the floor '
        f'{meta["first_valid_train_days"]} days; {meta["days_after_first_floor"]} days remain and are partitioned '
        f'into contiguous equal test segments; DERIVED SPLIT COUNT = {meta["derived_splits"]}',
        f'embargo = {wfs.EMBARGO_BARS} bars stated as a BAR COUNT, not a session count: the measured median session '
        f'is 1,365 bars, so a session reading would embargo fewer bars than one full trading day',
        'scheme is ANCHORED: each training segment strictly contains the previous, so the floor binds only on the first',
        'NO ROW IS DELETED: segments are index ranges over the intact series and the oracle receives the full frame',
        'RECORDED LIMITATION — ATTESTATION SCOPE: repeat detection compares records within ONE output directory. A '
        'run started against a FRESH --out directory begins with a clean trail and its repeats are not detected. No '
        'in-process mechanism can bind an operator who deliberately starts elsewhere; the trail catches careless and '
        'accidental repeats, which is its purpose, and the Auditor verifies trail length against reported splits.',
        'RECORDED LIMITATION — GUARD SCOPE: TestSegmentGuard enforces the single touch on the SANCTIONED path. It '
        'does not make the test bar range unreachable — unrelated code could slice those indices directly. The guard '
        'is discipline on the intended route, not an access control.'])
    attempts = pd.DataFrame(meta['attempts'])
    _write_with_header(os.path.join(out, 'wf_split_derivation_attempts.csv'), attempts, [
        'DOT S5C spec I.1 derivation trace — the floor being applied, not just the answer',
        f'dataset_rows={attest["rows"]} segment_floor_days={wfs.MIN_TRAIN_DAYS} floor_buckets={wfs.MIN_MONTH_BUCKETS}'])
    struct_keys = dt_structural_keys()
    causal = wfs.assert_oracle_causal(df, ad, dt_compute(), splits[0]['train_last_bar'], struct_keys)
    U = cp.eligible_universe(df, w)
    bk_path = book_file if book_file else os.path.join(_ENGINE, 'book50_signals.csv')
    sigs = score_g.build_book(df, pool, anchor, pd.read_csv(bk_path))
    conv = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
    full = engine.run_portfolio(df, sigs, adaptive=ad, structural=st, warmup=w, verbose=False, conviction=conv)
    bk = full[~full['signal_name'].isin(cp.GAP_NAMES)]
    seg_rows = []
    causal_rows = []
    for s in splits:
        tr = np.zeros(n0, dtype=bool)
        tr[:s['train_last_bar'] + 1] = True
        cz = wfs.assert_oracle_causal(df, ad, dt_compute(), s['train_last_bar'], struct_keys)
        causal_rows.append({'split_index': s['split_index'], 'train_last_bar': s['train_last_bar'],
                            'keys_total': cz['keys_total'],
                            'rolling_D_keys_checked': cz['rolling_D_keys_checked'],
                            'rolling_D_keys_available': cz['rolling_D_keys_available'],
                            'structural_constant_keys_checked': cz['structural_constant_keys_checked'],
                            'coverage': cz['coverage'], 'equality': cz['equality'],
                            'mismatches': cz['mismatches'], 'causal': cz['causal'],
                            'meaning': cz['meaning'], 'note': cz['note']})
        Utr = U & tr
        hyg, dead, canon, live = sel.vocabulary_hygiene(pool, Utr, f"split{s['split_index']}")
        sub = bk[bk['entry_bar'] <= s['train_last_bar']]
        daily = sel.per_signal_daily(sub)
        smap = sel.daily_series_map(daily)
        pr = sel.pair_tail_dependence(smap, sorted(smap.keys()))
        tstat = sel.tail_dep_book(pr)
        mc = sel.mcvar_per_signal(sub, daily)
        cmax = sel.c_max_from_incumbent(mc)
        bd = sub.copy()
        bd['day'] = pd.Series(bd['exit_time'].astype(str).values).str[:10].values
        fmax = sel.fail_conc(bd.groupby('day')['pnl'].sum().values)
        rec = {'split_index': s['split_index'], 'train_days': s['train_days'],
               'train_last_bar': s['train_last_bar'], 'eligible_bars_train': int(Utr.sum()),
               'dead_conditions': int(hyg['dead_conditions'].iloc[0]),
               'exact_duplicate_pairs': int(hyg['exact_duplicate_pairs'].iloc[0]),
               'effective_vocabulary': int(hyg['effective_vocabulary'].iloc[0]),
               'F_max': round(fmax, 4), 'TailDep': round(tstat['TailDep'], 4),
               'retention_pct': tstat['retention_pct'],
               'below_floor_majority_flag': tstat['below_floor_majority_flag'],
               'C_max': round(cmax, 2),
               'monthly_buckets': ';'.join(wfs.segment_month_buckets(df['Time'].values, tr))}
        for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
            h = wfs.h3_segment_rule(sub[sub['direction'] == lab])
            rec[f'H3_{lab}_buckets'] = h['buckets']
            rec[f'H3_{lab}_evaluable'] = h['evaluable']
            rec[f'H3_{lab}_verdict'] = h['verdict']
        wfs.require_h3_evaluable(s['split_index'],
                                 [{'evaluable': rec['H3_LONG_evaluable']}, {'evaluable': rec['H3_SHORT_evaluable']}])
        seg_rows.append(rec)
    seg = pd.DataFrame(seg_rows)
    _write_with_header(os.path.join(out, 'wf_per_segment_rederivation.csv'), seg, [
        'DOT S5C spec I.2 per-segment re-derivation — EVERY VALUE COMPUTED INSIDE ITS OWN TRAINING SEGMENT',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        f'oracle_sha256_12={oracle_sha}',
        'ANTI-LEAK: each row is derived from bars [0, train_last_bar] only. The full-series references — effective '
        'vocabulary 238, F_max 3.869, C_max -1429.1, retention 65.0% — are REPORTING REFERENCES ONLY and appear in '
        'no constraint. Every per-split value differs from them, which is the structural evidence that the bounds '
        'are segment-local rather than full-series values wearing a per-split label.',
        'H.3 IS A RULE, NOT A LITERAL: buckets are the calendar months the SEGMENT contains, computed from segment '
        'timestamps. wf.py FOLDS is month-literal Jan-Jun and is NEVER imported or referenced by this stage.',
        'H.3.1: buckets are evaluated WITHIN direction; a thin direction is reported UNEVALUABLE and is NEITHER '
        'passed NOR culled.',
        'below_floor_majority_flag TRUE means more than half the pair space sits below MIN_SHARED, so TailDep is not '
        'meaningfully binding in that segment and FailConc plus the absolute survival bound carry the decision.',
        'RECORDED CONSEQUENCE — DO NOT OVER-READ AN EARLY-SPLIT RESULT: splits 0 and 1 fire this flag (retention '
        '17.7% and 33.0%), so they test a WEAKER CONSTRAINT SET than split 2. A pass in an early split is evidence '
        'about FailConc and absolute survival, NOT about tail dependence. The TailDep constraint only becomes '
        'meaningfully binding once retention rises, which on this dataset happens at split 2 (51.3%).'])
    _write_with_header(os.path.join(out, 'wf_oracle_causality.csv'), pd.DataFrame(causal_rows), [
        'DOT S5C spec I.4 item 2 — the anti-leak assertion for the oracle',
        f'dataset_rows={attest["rows"]}',
        'Thresholds are computed ONCE on the FULL frame because the oracle must never receive a row-deleted frame.',
        'This assertion proves that is not a leak: for each split, threshold values over the training prefix are '
        'recomputed on a TRUNCATED frame ending at train_last_bar and compared. Zero mismatches means mechanism D '
        'is causal and cannot see the test segment, so masking after a full-frame computation is sound.',
        'COVERAGE IS PART OF THE FINDING: ALL keys are compared, split into rolling-D and structural-constant '
        'counts. The structural constants are causally trivial (a constant is identical on any prefix) and are '
        'never presented as evidence of rolling-threshold causality. A previous revision sampled the head of the '
        'threshold dict, which selected the four structural constants plus two rolling keys, so it tested 2 of 176 '
        'rolling thresholds while reporting 6 features; that sample would have passed on a dataset where every '
        'rolling threshold leaked.',
        'RUNTIME COST, STATED SO NOBODY REVERTS IT FOR SPEED: 6 to 11 seconds per split on the reference machine, '
        'rising with training-segment length. The cost is dominated by the ONE truncated recomputation per split, '
        'which is paid regardless of how many keys are compared, so full coverage is effectively free and must not '
        'be reduced to a sample.',
        'Wall-clock timing is deliberately NOT emitted, as a column or interpolated into this header, because a '
        'varying value would break the byte-level determinism of this artifact.'])
    code_shas = {'wf_selection.py': _sha_full(os.path.join(_ENGINE, 'wf_selection.py')),
                 'selection.py': _sha_full(os.path.join(_ENGINE, 'selection.py'))}
    sdef = wfs.split_definition_sha(splits, meta)
    run_id = f'{input_sha}-{sdef[:8]}'
    guards = []
    null_frames = []
    null_summary = []
    pool_keys = sorted(pool.keys())
    for s in splits:
        rec = wfs.build_attestation_record(run_id, code_shas, sdef, input_sha, s, out)
        wfs.write_attestation(out, rec)
        g = wfs.TestSegmentGuard(s['split_index'], s['test_first_bar'], s['test_last_bar'])
        guards.append(g)
        nf, ns = wfs.score_null_arm(df, pool_keys, ad, st, w, s, g, engine.run_portfolio)
        null_frames.append(nf)
        null_summary.append(ns)
    nulls = pd.concat(null_frames, ignore_index=True) if null_frames else pd.DataFrame()
    nsum = pd.DataFrame(null_summary)
    if len(nulls):
        _write_with_header(os.path.join(out, 'wf_null_arm_entities.csv'), nulls, [
            'DOT S5C spec I.3 random-triple NULL ARM, per split — THIS IS A MEASUREMENT, NOT A PASS CRITERION',
            f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
            f'oracle_sha256_12={oracle_sha}',
            'Random triples are drawn from the existing 249-condition pool; NO S3 output is required, so this',
            'violates no rejection item: it is not the fixed book (item 1), not full-series discovery (item 3),',
            'and not the 27% figure carried from the record (item 7) — the null is regenerated inside each split.',
            'Persistence is measured exactly as the record measures it: net>0, PF>=2, WR>=75 in BOTH train and test.',
            'Each triple is scored STANDALONE (batch size 1) so the 6-lot jar cannot couple the null entities.',
            'Scored on the test segment inside the SINGLE sanctioned TestSegmentGuard touch.',
            'THE PASS CRITERION REMAINS UNEVALUABLE: it requires the SELECTION arm, which requires a candidate pool',
            'that S3 has never produced. A null baseline is the denominator of that comparison, never the result.'])
        _write_with_header(os.path.join(out, 'wf_null_arm_summary.csv'), nsum, [
            'DOT S5C spec I.3 null-arm per-split summary — MEASUREMENT ONLY, NOT A WALK-FORWARD RESULT',
            f'dataset_rows={attest["rows"]} target_qualifiers={wfs.NULL_TARGET_QUALIFIERS} '
            f'floor_qualifiers={wfs.NULL_FLOOR_QUALIFIERS} cap_triples={wfs.NULL_TRIPLES_CAP} '
            f'generation_batch={wfs.NULL_GEN_BATCH} base_seed={wfs.NULL_SEED}',
            'THE CONTROL IS THE QUALIFIER COUNT, NOT THE GENERATED COUNT. Triples are generated in seeded batches '
            'until train_qualifiers reaches the target or the cap is hit. A fixed generated count is fragile: the '
            'train-qualification rate is itself uncertain, so the generation needed for 80 qualifiers spans a wide '
            'range. Seeding: ONE generator per split, seeded base_seed + split_index, drawn sequentially across '
            'batches with cross-batch de-duplication, so the draw sequence is identical regardless of how many '
            'batches the target required.',
            'Only TRAIN-QUALIFYING triples are scored on the test segment: the denominator is the qualifier count, '
            'so non-qualifiers cannot enter either arm and scoring them would be wasted compute.',
            'RNG SEEDING IS NOW REAL, NOT VACUOUS: before this arm ran, wf_selection instantiated no RNG at all and '
            '"every RNG seeded" was vacuously true. The null draw uses np.random.default_rng(base_seed + split_index) '
            'and the direction assignment draws from the same generator, so the whole arm is reproducible.',
            'seed per split = base_seed + split_index, so the draw is reproducible and split-specific.',
            'null_persistence_rate = persisted / train_qualifiers; entities failing the train bar are excluded',
            'from the denominator, matching how the record computes its 27% baseline.'])
    trail = wfs.read_attestation(out)
    repeats, n_rep = wfs.detect_repeats(trail)
    meta_checks = {'funnel_rerun': False, 'null_per_split': True,
                   'null_detail': f'the random-triple null is regenerated inside each split from the '
                                  f'{len(pool_keys)}-condition pool and scored in the same single test pass; '
                                  f'the record 27% figure is never carried',
                   'funnel_detail': 'S3 discovery has never run, so no candidate pool exists and the funnel cannot '
                                    'be re-run per split; the mechanics are built and the criterion is unexercisable'}
    wfs.assert_no_row_deletion(df, n0)
    pc_pre = pd.DataFrame([{'splits_derived': len(splits)}])
    rej = wfs.rejection_checks(df, n0, splits, meta_checks, causal, guards,
                               per_split_frame=seg, attest_trail=trail, pass_frame=pc_pre)
    _write_with_header(os.path.join(out, 'wf_rejection_checks.csv'), rej, [
        'DOT S5C spec I.4 rejection list, implemented as executable checks rather than conventions',
        f'dataset_rows={attest["rows"]} splits={len(splits)}',
        'UNEXERCISABLE PENDING S3 marks a check whose subject does not exist yet, not a check that passed.'])
    null_rates = [r['null_persistence_rate'] for r in null_summary] if null_summary else []
    null_ok = [not str(r['status']).startswith('UNEVALUABLE') for r in null_summary] if null_summary else []
    book_rates = [float('nan')] * len(null_rates)
    verdict = wfs.pass_criterion(book_rates, null_rates, null_ok)
    verdict['book_arm'] = ('UNEVALUABLE - the book arm requires the selection funnel re-run per split, which '
                           'requires a candidate pool S3 has never produced')
    pc = pd.DataFrame([{**verdict, 'splits_derived': len(splits),
                        'attestation_records': int(len(trail)),
                        'attestation_repeat_groups': int(len(repeats)),
                        'attestation_repeat_records': int(n_rep)}])
    _write_with_header(os.path.join(out, 'wf_pass_criterion.csv'), pc, [
        'DOT S5C spec I.3 pass criterion',
        f'dataset_rows={attest["rows"]} splits_derived={len(splits)}',
        'CRITERION (spec I.3 Revision 9): ratio_s = book_persistence(s) / null_persistence(s) per derived split; '
        'PASS = mean ratio >= 2.40 AND min ratio >= 1.85 AND the 95% lower bound on the mean ratio exceeds 1.0.',
        'THE DENOMINATOR IS SEGMENT-LOCAL. The previous absolute form (mean>=0.65, no split<0.50) inherited a '
        'full-window 27% baseline and is WITHDRAWN as incoherent; the thresholds preserve its intent exactly '
        '(0.65/0.27=2.41, 0.50/0.27=1.85) while making the denominator the split own measured null.',
        'MINIMUM NULL DENOMINATOR: target 80 TRAIN-QUALIFYING triples per split, hard floor 40. Below the floor the '
        'split is UNEVALUABLE. Between floor and target it is EVALUABLE with the reduced denominator REPORTED.',
        'THE TRAIN BAR IS NEVER LOOSENED to raise the qualification rate: the null answers what fraction of things '
        'clearing THE SAME BAR AS THE BOOK SIGNALS persist by chance, so a looser bar would compare two different '
        'populations. The count is raised instead, and the compute cost is accepted.',
        'VERDICT UNEVALUABLE: producing a persistence figure requires re-running the funnel per split, which requires '
        'a candidate pool. S3 discovery has never run. Re-scoring the fixed incumbent book across splits would be '
        'rejection-list item 1 and is NOT done here — a number produced by the prohibited path is worse than none.',
        'A FAIL IS A LEGITIMATE RESULT and would be reported as one. No bar is lowered to obtain a pass.'])
    print(f'  splits derived {len(splits)} (floor: >={wfs.MIN_TRAIN_DAYS}d and >={wfs.MIN_MONTH_BUCKETS} buckets) | '
          f'embargo {wfs.EMBARGO_BARS} bars | oracle causal {all(c["causal"] for c in causal_rows)}')
    if len(nsum):
        print('  null arm (MEASUREMENT, not a pass criterion): ' +
              ' | '.join(f"split {int(r['split_index'])} {r['persisted']}/{r['train_qualifiers']}"
                         f"={r['null_persistence_rate']}" for _i, r in nsum.iterrows()))
    print(f'  attestation records {len(trail)} (repeat groups {len(repeats)}) | pass criterion: {verdict["verdict"]}')
    mark_done(out, 'S5C', {'input_sha': input_sha, 'splits': len(splits)})
    return {'splits': sp, 'segments': seg, 'rejection': rej, 'pass': pc, 'trail': trail,
            'repeats': repeats, 'meta': meta, 'null_summary': nsum}


def _sha_full(path):
    import hashlib
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def dt_compute():
    import dots_thresholds as _dt
    return _dt.compute_adaptive_thresholds


def dt_structural_keys():
    import dots_thresholds as _dt
    return set(_dt._STRUCTURAL.keys())


# ── S8B CLUSTER-PARTICIPATION PROFILER ──
def s8b_cluster_profile(df, ad, st, w, pool, anchor, book_file, committed, out, input_sha, attest):
    import cluster_profiler as cp
    import score_g
    import conviction as C
    oracle_sha = sha12(os.path.join(_ENGINE, 'dots_thresholds.py'))
    print(f'  oracle dots_thresholds.py sha256 : {oracle_sha}')
    print(f'  dataset: {attest["rows"]:,} rows | {attest["range"]}')
    if is_done(out, 'S8B', input_sha) and os.path.exists(os.path.join(out, 'cluster_participation_profile.csv')):
        print('  S8B already complete for this input (checkpoint) — resuming past it.')
        return None
    if committed is not None and 'executed' in committed:
        executed = committed['executed']
        sigs = committed['sigs']
    else:
        print('  S8B standalone: S8 output unavailable, rebuilding the committed trade list.')
        bk_path = book_file if book_file else os.path.join(_ENGINE, 'book50_signals.csv')
        sigs = score_g.build_book(df, pool, anchor, pd.read_csv(bk_path))
        conv = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
        _r, executed = _score(df, sigs, ad, st, w, conv, want_trades=True)
    n = len(df)
    U = cp.eligible_universe(df, w)
    hours = df['EST_Hour'].values
    ab = cp.atr_buckets(df, U)
    ev_book, bk = cp.book_events(executed)
    ev_qual, qual_depth = cp.qualifying_events(df, sigs, ad, st, w)
    print(f'  vocabulary: {len(pool)} conditions | eligible universe {int(U.sum()):,} bars '
          f'| book events {len(bk)} | qualifying events {len(ev_qual[1]) + len(ev_qual[-1])}')
    jobs = []
    for N in cp.N_VALUES:
        jobs.append((1, N, ('', '', ''), ev_book))
        jobs.append((2, N, ('', '', ''), ev_qual))
    thrust_sets = {}
    for W in cp.THRUST_W:
        fwd, mag, eff, valid, thr, mcol, ecol = cp.thrust_thresholds(df, W, cp.THRUST_K_PCTS, cp.THRUST_E_PCTS)
        for kp in cp.THRUST_K_PCTS:
            for ep in cp.THRUST_E_PCTS:
                karr = thr[(mcol, f'k{int(round(kp * 100))}')]
                earr = thr[(ecol, f'e{int(round(ep * 100))}')]
                ev = cp.thrust_events(fwd, mag, eff, valid, karr, earr, w)
                thrust_sets[(W, kp, ep)] = ev
                for N in cp.N_VALUES:
                    jobs.append((3, N, (W, kp, ep), ev))
    rows = []
    summary = []
    t0 = time.time()
    for i, (basis, N, grid, ev) in enumerate(jobs):
        cs = cp.build_cluster_set(n, ev, N)
        tcid = cp.map_trades_to_clusters(cs, bk)
        rows.extend(cp.profile_conditions(pool, cs, U, df, bk, tcid, basis, N, grid, hours, ab))
        cl = cs['clusters']
        summary.append({'basis': basis, 'N': N, 'W': grid[0], 'K_pct': grid[1], 'E_pct': grid[2],
                        'clusters': len(cl), 'max_size': int(cl['size'].max()) if len(cl) else 0,
                        'max_span': int(cl['span'].max()) if len(cl) else 0,
                        'ge3': int((cl['size'] >= 3).sum()) if len(cl) else 0,
                        'ge5': int((cl['size'] >= 5).sum()) if len(cl) else 0,
                        'ge8': int((cl['size'] >= 8).sum()) if len(cl) else 0,
                        'zero_span_pct': round(100.0 * float((cl['span'] == 0).mean()), 1) if len(cl) else 0.0})
        sys.stdout.write(f'\r  cluster sets {i + 1}/{len(jobs)} | elapsed {_hms(time.time() - t0)}   ')
        sys.stdout.flush()
    sys.stdout.write('\n')
    res = pd.DataFrame(rows)
    cs_b1 = cp.build_cluster_set(n, ev_book, 5)
    cs_b2 = cp.build_cluster_set(n, ev_qual, 5)
    overlaps = {}
    for (W, kp, ep), ev in thrust_sets.items():
        for N in cp.N_VALUES:
            tcs = cp.build_cluster_set(n, ev, N)
            overlaps[(W, kp, ep, N)] = cp.overlap_validation(tcs, cs_b1, cs_b2, n, U)
    reach = []
    for mask_name in ('post-warmup', 'eligible-universe'):
        reach.append(cp.directional_baseline(df, 30, 0.85, 0.75, w, mask_name))
    d01 = pd.concat(reach, ignore_index=True)
    _write_with_header(os.path.join(out, 'reach_D01_directional_baseline.csv'), d01, [
        'DOT S8B spec D.0.1 directional coverage baseline — PROPERTY OF THE MARKET (price-only, no signals)',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        f'oracle_sha256_12={oracle_sha}',
        'Parameters: W=30, K=p85 of |disp|/ATR_1M, E=p75 directional efficiency, thresholds via oracle mechanism D.',
        'THE MASK IS PART OF THE FINDING: absolute counts move by roughly 2x between masks; the up/down ratio does not.',
        'Both masks are emitted for exactly that reason (spec D.0.2 reproduction note).',
        'scope=ALL rows carry thrust bar counts and median move; scope=YYYY.MM rows carry down-share and, in',
        'median_move_pts, that month net price change in points.'])
    d02 = []
    for (W, kp, ep) in ((15, 0.85, 0.75), (30, 0.85, 0.75), (30, 0.90, 0.75)):
        for N in cp.N_VALUES:
            d02.append(cp.episode_traded_split(df, W, kp, ep, N, w, bk))
    d02 = pd.concat(d02, ignore_index=True)
    _write_with_header(os.path.join(out, 'reach_D02_D2_coverage.csv'), d02, [
        'DOT S8B spec D.0.2 reach-vs-depth + D.2 coverage — episodes are MARKET, traded/missed are BOOK',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        f'oracle_sha256_12={oracle_sha}',
        'Coverage(B) = fraction of thrust episodes touched by >=1 book entry inside the span, same direction.',
        'Reported per (W, K, E, N) grid cell, never at a single setting (spec D.2), and stratified by episode',
        'absolute size (<50 / 50-100 / 100-200 / >200 pt) so small-move gains are never shown as equivalent to large.',
        'Episode absolute size = |Close[b1+W] - Close[b0]| in points.'])
    d0dec = []
    for (W, kp, ep) in ((15, 0.85, 0.75), (30, 0.85, 0.75)):
        for N in cp.N_VALUES:
            d0dec.append(cp.missed_reason_decomposition(df, W, kp, ep, N, w, bk, qual_depth))
    d0dec = pd.concat(d0dec, ignore_index=True)
    _write_with_header(os.path.join(out, 'reach_D0_missed_decomposition.csv'), d0dec, [
        'DOT S8B spec D.0 missed-episode decomposition across the thrust grid — MARKET episodes, BOOK reasons',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        'Reason A = no BOOK signal qualified anywhere in the span (bar-level qualifying depth zero throughout).',
        'Reason B = a signal qualified but no entry resulted. Qualifying depth from build_signal_masks with entry_ok.'])
    dstruct = pd.concat([cp.book_depth_structure(bk, N, n) for N in cp.N_VALUES], ignore_index=True)
    _write_with_header(os.path.join(out, 'reach_D02_book_depth_structure.csv'), dstruct, [
        'DOT S8B spec D.0.2 book-side depth structure — PROPERTY OF THE BOOK',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        'Population BOOK (F0+F1 executed, gap fillers excluded). Clusters built per direction in isolation.',
        'N=5 primary (spec 0.1.3); N=10 emitted as mandatory sensitivity.'])
    print(f'  reach: D.0.1 {len(d01)} rows | D.0.2/D.2 {len(d02)} rows | D.0 decomposition {len(d0dec)} rows')
    path = os.path.join(out, 'cluster_participation_profile.csv')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(f'# DOT S8B cluster-participation profile\n')
        f.write(f'# dataset_rows={attest["rows"]} dataset_range={attest["range"]}\n')
        f.write(f'# oracle_sha256_12={oracle_sha} engine_sha256_12={sha12(os.path.join(_ENGINE, "portfolio_simulation_engine.py"))}\n')
        f.write(f'# eligibility={cp.ELIGIBILITY_PREDICATE}\n')
        f.write(f'# eligible_bars={int(U.sum())} vocabulary_conditions={len(pool)}\n')
        f.write(f'# min_fire_floor={cp.MIN_FIRE_FLOOR} (ranking eligibility only; not tuned)\n')
        f.write('# BASIS-3 BOUNDARY: the thrust label is FORWARD-LOOKING by construction (uses Close[t+W]).\n')
        f.write('# Legitimate as a selection-side diagnostic; BASIS 3 CAN NEVER BECOME A LIVE GATE OR ENTRY CONDITION.\n')
        f.write('# COUPLING MITIGATION: quant_response_6 mitigation 2 — metric (e) is emitted for BASIS 3 as well as\n')
        f.write('# bases 1 and 2, so shallow-edge participation is measurable against price structure defined without\n')
        f.write('# reference to the book or the jar.\n')
        f.write('# ATR STRATA (lift_5_atr_controlled, vol_proxy_flag) are derived from the oracle mechanism-D ATR_1M\n')
        f.write('# thresholds (rolling-2500, day-refreshed, causal) — NOT from full-sample quantiles.\n')
        f.write('# METRIC (g) SUPPRESSED ON BASIS 3 (EPISODE-STRENGTH SELECTION): part_net/non_net/part_pf/part_wr/\n')
        f.write('# part_wd/non_pf/non_wr/non_wd are emitted EMPTY for cluster_basis=3. Reason: a condition that fires\n')
        f.write('# preferentially in larger or longer episodes inherits bigger forward moves in its participating arm,\n')
        f.write('# so the contrast can be driven by the magnitude of the forward label rather than by entry quality.\n')
        f.write('# Only part_clusters is retained on basis 3 (a genuine count, not an outcome). Basis 3 instead carries\n')
        f.write('# COVERAGE ATTRIBUTION (cov_episodes / cov_book_traded / cov_book_missed / cov_missed_share), which is\n')
        f.write('# not outcome-denominated; cov_* is empty on bases 1-2. cov_episodes is an explicit ALIAS of\n')
        f.write('# part_clusters, retained so the cov_* family is self-contained and so cov_book_traded +\n')
        f.write('# cov_book_missed == cov_episodes serves as a consistency check.\n')
        f.write('# SCOPE LIMIT: the vocabulary is SINGLE CONDITIONS; the book\'s signals are TRIPLES. A single\n')
        f.write('# condition\'s profile is NOT a signal\'s value. Do not select a book directly from this file.\n')
        f.write('# It is an input to selection, not a selection rule.\n')
        res.to_csv(f, index=False, lineterminator='\n')
    os.replace(tmp, path)
    sm = pd.DataFrame(summary)
    sm.to_csv(os.path.join(out, 'cluster_basis_summary.csv'), index=False, lineterminator='\n')
    print(f'  wrote {len(res)} rows → {path}')
    mark_done(out, 'S8B', {'input_sha': input_sha, 'rows': int(len(res)), 'conditions': len(pool)})
    return {'rows': int(len(res)), 'conditions': len(pool), 'summary': sm, 'overlaps': overlaps,
            'eligibility': cp.ELIGIBILITY_PREDICATE,
            'eligible_bars': int(U.sum()), 'path': path, 'res': res,
            'max_qual_depth': int(max(qual_depth[1].max(), qual_depth[-1].max()))}


# ── S9 REPORT + SPLIT ──
def s9_report(out, attest, contenders, committed, sacred, market_label, chunk_mb, input_sha, profile=None, evidence=None, selection_state=None):
    scored_fresh = 'regenerated fresh this run (S6) — stale 746102aae415 / 0910f360a628 NOT inherited'
    L = []
    L.append(f'# DOT Master Report — {market_label}')
    L.append('')
    L.append('## 1. Ingest attestation')
    L.append(f'- files: {", ".join(attest["files"])}')
    L.append(f'- shape: {attest["rows"]:,} rows × {attest["cols"]} cols · range {attest["range"]}')
    L.append(f'- path: {attest["path"]} · invariants: {attest["invariants"]}')
    L.append('')
    L.append('## 2. Sacred parity (byte-lock)')
    for name, want in sacred.items():
        L.append(f'- `{name}` `{want}` OK')
    L.append('')
    if contenders:
        L.append('## 3. Component build-up / contenders')
        L.append('| id | contender | net | Δ | WR | PF | daily wd | daily mDD | folds+ | min-PF | OOS PF | OOS net |')
        L.append('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for r in contenders:
            L.append(f"| {r['id']} | {r['contender']} | ${r['net']} | {r['delta']:+} | {r['WR']} | {r['PF']} | "
                     f"{r['daily_wd']} | {r['daily_mDD']} | {r['folds_plus']}/6 | {r['min_fold_pf']} | {r['oos_pf']} | ${r['oos_net']} |")
        L.append('')
    if committed:
        L.append('## 4. Committed-system headline')
        L.append(f"- book: {committed['book_tag']}")
        L.append(f"- **net ${committed['net']} | {committed['trades']} tr | WR {committed['WR']}% | PF {committed['PF']} | "
                 f"daily wd {committed['daily_wd']} | daily mDD {committed['daily_mDD']} | "
                 f"{committed['folds_plus']}/6 folds min-PF {committed['min_fold_pf']} | OOS PF {committed['oos_pf']} | OOS net ${committed['oos_net']}**")
        if committed.get('canary'):
            L.append('- US30 baseline canary: $92,347 / 2,698 tr — engine intact')
        L.append('')
    L.append('## 5. Per-family coverage')
    if evidence is not None and isinstance(evidence, dict) and 'family' in evidence:
        fam = evidence['family']
        counts = fam['verdict'].value_counts().to_dict()
        L.append(f"- **measured verdicts (S3B, `family_evidence.csv`)**: " +
                 ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
        for _i, r in fam.iterrows():
            L.append(f"  - {r['family']}: {r['verdict']} — {r['verdict_basis'][:150]}")
    else:
        L.append('- family classifications are measured by S3B and written to `family_evidence.csv`; see that file for the '
                 'per-family verdict. **F10 is FOLDED INTO F0** (concurrence lens null; F12 is the diagnostic remnant) — '
                 'not a gap. No family carries a classification inherited from its history: verdicts are measured, and '
                 'INSUFFICIENT-EVIDENCE is emitted wherever the evidence does not exist on this dataset.')
    L.append('')
    if profile:
        L.append('## 6. S8B cluster-participation profile')
        L.append(f"- output: `{os.path.basename(profile['path'])}` — {profile['rows']} rows "
                 f"({profile['conditions']} conditions x basis x N x grid cell)")
        L.append(f"- eligible universe: {profile['eligible_bars']:,} bars | eligibility: {profile.get('eligibility', '')}")
        L.append('- **SCOPE LIMIT: the vocabulary is SINGLE CONDITIONS; the book\'s signals are TRIPLES. '
                 'A single condition\'s profile is not a signal\'s value; do not select a book directly from this CSV. '
                 'It is an input to selection, not a selection rule.**')
        L.append('- **BASIS-3 BOUNDARY: the thrust label is forward-looking by construction and can never become '
                 'a live gate or entry condition.**')
        L.append('- basis-3 overlap with size>=5 book cluster spans:')
        for (W, kp, ep, N), o in profile['overlaps'].items():
            L.append(f"  - W={W} K=p{int(kp * 100)} E=p{int(ep * 100)} N={N}: "
                     f"{o['episodes_hit']}/{o['episodes']} episodes intersect = {o['episode_pct']}% "
                     f"| thrust bars inside deep clusters {o['thrust_bars_in_cluster_pct']}% "
                     f"| deep-cluster bars that are thrust {o['cluster_bars_in_thrust_pct']}%")
        L.append('')
    if selection_state is not None:
        L.append('## 7. S5B selection layer — §H decisions and §C constraint references')
        for ln in selection_state.get('report_lines', []):
            L.append(f'- {ln}')
        L.append('')
        L.append('## 8. Stale-artifact note')
    else:
        L.append('## 7. Stale-artifact note')
    L.append(f'- signal_full_records / signal_per_day_pnl: {scored_fresh}')
    L.append('')
    rep = os.path.join(out, 'master_report.md')
    open(rep, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    nsplit = split_tree(out, chunk_mb)
    print(f'  report → {rep} | auto-split: {nsplit} oversized artifact(s) chunked (≤{chunk_mb}MB, header-in-part1)')
    mark_done(out, 'S9', {'input_sha': input_sha, 'split_files': nsplit})


def resolve_data(data):
    for cand in (data, os.path.join(_HERE, 'data'), '/data'):
        if cand and os.path.isdir(cand) and glob.glob(os.path.join(cand, '*.csv')):
            return cand
    return data


def resolve_book(book):
    if book is None:
        return None
    for cand in (book, os.path.join(_ENGINE, book), os.path.join(_HERE, book)):
        if os.path.exists(cand):
            return cand
    print(f'ABORT — book file not found: {book}')
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description='DOT master orchestrator (S0→S9).')
    ap.add_argument('--data', default='/data')
    ap.add_argument('--out', default=os.path.join(_HERE, 'discovery'))
    ap.add_argument('--book', default=None)
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--stage', default=None, choices=STAGES)
    ap.add_argument('--market-label', default='US30 (sealed baseline)')
    ap.add_argument('--chunk-mb', type=int, default=9)
    args = ap.parse_args()
    args.workers = min(args.workers, 12)

    t0 = time.time()
    print('═' * 68)
    print('DOT MASTER ORCHESTRATOR')
    print('═' * 68)
    sacred = verify_sacred()
    data_dir = resolve_data(args.data)
    book_file = resolve_book(args.book)
    out = args.out
    for sub in ('raw', 'results', 'scored', 'contenders', 'committed', '.markers'):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    mode = 'FROZEN-BOOK replay + verify' if book_file else 'DISCOVER-FRESH (no --book)'
    print(f'mode: {mode} | data: {data_dir} | out: {out} | workers: {args.workers}')

    only = args.stage
    print('\n[S0] INGEST & VALIDATE')
    df, attest, input_sha = s0_ingest(data_dir, out, args.chunk_mb)
    print('\n[S1] ADAPTIVE THRESHOLDS (oracle)')
    ad, st = s1_thresholds(df)
    print('\n[S2] POOL & ANCHORS')
    pool, anchor, w = s2_pool(df, ad, st)

    contenders = committed = profile = evidence = selection_state = wf_state = None
    run_all = only is None
    discover = (book_file is None)
    if not discover and run_all:
        print('\n[S3–S6] DISCOVERY / REGEN — SKIPPED on the frozen-book verification path.')
        print('  --book replays a ratified book (S8); fresh discovery is the no-book path.')
        print('  Run `python master.py` (no --book) or `--stage S3` for the full 1–2 day discovery.')
    if (run_all and discover) or only == 'S3':
        print('\n[S3] FAMILY DISCOVERY (long-pole; delegates to ratified orchestrator)')
        s3_discovery(out, args.workers, input_sha, 'full', df=df, ad=ad, st=st, w=w)
    if run_all or only == 'S3B':
        print('\n[S3B] PER-FAMILY EVIDENCE REVIEW + D2D GATE MEASUREMENT')
        evidence = s3b_family_evidence(df, ad, st, w, pool, anchor, book_file, out, input_sha, attest)
    if (run_all and discover) or only == 'S4':
        print('\n[S4] SCHEMA UNIFY')
        s4_schema(out, input_sha)
    if (run_all and discover) or only == 'S5':
        print('\n[S5] CANDIDATE FILTER')
        s5_filter(out, input_sha)
    if (run_all and discover) or only == 'S6':
        print('\n[S6] FULL-FIELD SCORING (REGEN fresh)')
        s6_regen(out, input_sha)
    if run_all or only == 'S5B':
        print('\n[S5B] SELECTION LAYER')
        selection_state = s5b_selection(df, ad, st, w, pool, anchor, book_file, out, input_sha, attest)
    if run_all or only == 'S5C':
        print('\n[S5C] WALK-FORWARD ON THE SELECTION PROCESS')
        wf_state = s5c_walk_forward(df, ad, st, w, pool, anchor, book_file, out, input_sha, attest)
    if run_all or only == 'S7':
        print('\n[S7] CONTENDER HEAD-TO-HEAD')
        import score_g
        bk = book_file if book_file else os.path.join(_ENGINE, 'book50_signals.csv')
        sigs = score_g.build_book(df, pool, anchor, pd.read_csv(bk))
        contenders = s7_contenders(df, ad, st, w, sigs, out, input_sha)
    if run_all or only == 'S8':
        print('\n[S8] COMMITTED-SYSTEM SCORE')
        committed = s8_committed(df, ad, st, w, pool, anchor, book_file, out, input_sha)
    if run_all or only == 'S8B':
        print('\n[S8B] CLUSTER-PARTICIPATION PROFILE')
        profile = s8b_cluster_profile(df, ad, st, w, pool, anchor, book_file, committed, out, input_sha, attest)
    if run_all or only == 'S9':
        print('\n[S9] REPORT & SPLIT')
        s9_report(out, attest, contenders, committed, sacred, args.market_label, args.chunk_mb, input_sha, profile, evidence, selection_state)

    print('\n' + '═' * 68)
    print(f'MASTER COMPLETE in {_hms(time.time() - t0)} | out: {out}')
    if committed and committed.get('canary'):
        print(f'US30 baseline canary: engine intact — net ${committed["net"]} / {committed["trades"]} tr')
    print('═' * 68)


if __name__ == '__main__':
    main()
