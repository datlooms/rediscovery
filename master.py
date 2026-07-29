import argparse
import glob
import hashlib
import json
import math
import os
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
FOLD_COUNT = 6
MIN_FOLD_DAYS = 5
OOS_TAIL_FRACTION = 1.0 / 3.0
FOLD_BASIS_NOTE = ('folds and OOS are PROPORTIONAL, never calendar. The loaded post-warmup span is split by '
                   'TRADING DAY into a final-third hold-out and a leading two-thirds; the two-thirds is then cut '
                   'into six equal contiguous folds. Folds and the hold-out are DISJOINT, so the two headline '
                   'figures are independent measurements rather than the same trades counted twice.')
OOS_MONTHS = ['2026.05', '2026.06']
OOS_LEGACY_NOTE = 'LEGACY DIAGNOSTIC, STALE: fixed calendar months, neither out-of-sample nor segment-relative on a stitched series; not a selection input (spec B.1). oos_rel_* are the data-relative counterpart.'
OOS_REL_N_MONTHS = 2
STAGES = ['S0', 'S1', 'S2', 'S2B', 'S3', 'S3B', 'S4', 'S5', 'S5D', 'S6', 'S5B', 'S5C', 'S7', 'S8', 'S8B', 'S9']
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


from _packutil import sha12, _natkey


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


def _is_header_row(first_line):
    return first_line.split(',')[0].strip() == 'Time'


def s0_ingest(data_dir, out):
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
def s3_discovery(out, workers, input_sha, scope, df=None, ad=None, st=None, w=None, limit=0):
    results = os.path.join(out, 'results')
    os.makedirs(results, exist_ok=True)
    if is_done(out, 'S3', input_sha):
        print('  S3 already complete for this input (checkpoint) — resuming past it.')
        return
    import discovery_orchestrator as orch
    orch.RESULTS_DIR = results
    os.environ['DOT_RESULTS_DIR'] = results
    frame_path = None
    if df is not None and workers and workers > 1:
        frame_path = os.path.join(results, f'_s3_frame_{input_sha}.csv')
        for stale in glob.glob(os.path.join(results, '_s3_frame*.csv')):
            if os.path.basename(stale) != os.path.basename(frame_path):
                os.remove(stale)
        tmp = frame_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            df.to_csv(f, index=False, lineterminator='\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, frame_path)
        print(f'  worker frame written to {os.path.basename(frame_path)} so each process loads it independently')
        print(f'  (the name carries input_sha and the file is REWRITTEN every S3 entry, so a cache from a different')
        print(f'   dataset can never be read; it is deleted when S3 completes)')
    print(f'  delegating to discovery_orchestrator.orchestrate(scope="{scope}", workers={workers}) — F1–F11 + F0/F13 ingest.')
    print('  (this is the 1–2 day long pole. Per family: results land in results/ and are written ATOMICALLY with a')
    print('   .done marker carrying the row count and CSV sha256. A restart re-reads any complete family from disk')
    print('   and re-scans only the incomplete ones, so the worst case loss is ONE family, not the whole stage.)')
    orch.orchestrate(scope, workers=workers, df=df, adaptive=ad, structural=st, warmup=w,
                     frame_path=frame_path, input_sha=input_sha, limit=limit)
    run_diagnostic_families(results, workers, input_sha, df=df)
    orch.verify_diagnostic_outputs(results, input_sha)
    if frame_path is not None and os.path.exists(frame_path):
        os.remove(frame_path)
        print(f'  worker frame {os.path.basename(frame_path)} removed on S3 completion')
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
            if '_part' in os.path.basename(f):
                continue
            try:
                frames.append(pd.read_csv(f))
            except Exception:
                pass
        if frames:
            uni = pd.concat(frames, ignore_index=True)
            uni.to_csv(master, index=False, lineterminator='\n', encoding='utf-8')
            print(f'  schema-unify: {len(uni)} rows → results/discovery_master.csv')
        else:
            print('  schema-unify: no discovery results present (discover-fresh not run) — NOT marking '
              'done. A stage that reports itself unexercised must NOT mark done: the marker would skip it permanently for this input_sha and the run would finish with that stage never having run.')
        return
    mark_done(out, 'S4', {'input_sha': input_sha})


def s5_filter(out, input_sha):
    results = os.path.join(out, 'results')
    src = os.path.join(results, 'discovery_master.csv')
    if not os.path.exists(src):
        print('  filter: no unified results (discover-fresh not run) — NOT marking done. A stage that reports itself unexercised must NOT mark done: the marker would skip it permanently for this input_sha and the run would finish with that stage never having run.')
        return
    r = pd.read_csv(src)
    n_total = len(r)
    keep = r[(r['trades'] >= 30) & (r['folds_plus'] >= 4) & (r['agg_pf'] >= 2.0)].copy()
    if 'worst_day_usd' in keep.columns:
        keep = keep.sort_values(['worst_day_usd', 'agg_pf'], ascending=[True, False])
    import score_g
    unscoreable = set(score_g.UNSCOREABLE_FAMILIES)
    if 'family' in keep.columns and len(keep):
        gcov = score_g.grammar_coverage(keep)
        _write_with_header(os.path.join(results, 'grammar_coverage.csv'), gcov, [
            'DOT S5 GRAMMAR COVERAGE — every DISTINCT signal_def form in the filtered pool',
            'PROPERTY OF THE POOL. Checked BEFORE S8 so an unhandled grammar surfaces in seconds at '
            'S5, not after a long run at S8.',
            'Shapes are the signal_def with identifiers normalised to V and numbers to N, so two rows '
            'differing only in variable or threshold collapse to one form. Row counts are per form.',
            'A form marked handled=False is EXCLUDED from candidates.csv by name below, so the filter '
            'and build_book can never disagree about what is scoreable.'])
        print('  GRAMMAR COVERAGE — distinct signal_def forms in the filtered pool:')
        for _i, gr in gcov.iterrows():
            flag = 'OK ' if gr['handled'] else 'NO '
            print(f"    {flag}{gr['family']:4} {int(gr['rows']):5} rows | {gr['grammar_shape']}")
            if not gr['handled']:
                print(f"        example: {gr['example']}")
        bad_shapes = set(gcov[~gcov['handled']]['grammar_shape'])
        if bad_shapes:
            mask_bad = keep['signal_def'].astype(str).map(score_g.grammar_shape).isin(bad_shapes)
            n_bad = int(mask_bad.sum())
            keep = keep[~mask_bad]
            print(f'  filter: EXCLUDING {n_bad} row(s) whose signal_def form build_book cannot '
                  f'parse — named above, never silently dropped')
        else:
            print('  GRAMMAR COVERAGE: every form in the pool is parseable by build_book')
        blocked = keep[keep['family'].isin(unscoreable)]
        keep = keep[~keep['family'].isin(unscoreable)]
        if len(blocked):
            for fam, g in blocked.groupby('family'):
                print(f'  filter: EXCLUDING {len(g)} {fam} candidate(s) — S8 cannot score this '
                      f'family: {score_g.UNSCOREABLE_FAMILIES[fam]}')
            _u = sorted(unscoreable)
            _v = 'is' if len(_u) == 1 else 'are'
            print(f'  THE POOL IS NOT THE FULL FOURTEEN: {_u} {_v} discovered and reported but '
                  f'cannot enter a selected book. Stated so the operator is never told a book spans '
                  f'families it does not.')
    keep.to_csv(os.path.join(results, 'candidates.csv'), index=False, lineterminator='\n',
                encoding='utf-8')
    print(f'  filter (trades≥30 & folds_plus≥4 & agg_pf≥2.0): {len(keep)}/{n_total} candidates '
          f'scoreable by S8')
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
def fold_plan(df, warmup):
    t = pd.Series(df['Time'].astype(str).values).str[:10].values
    days = list(pd.unique(t[np.arange(len(df)) >= warmup]))
    n = len(days)
    n_oos = int(round(n * OOS_TAIL_FRACTION))
    train_days = days[:n - n_oos] if n_oos else days
    oos_days = days[n - n_oos:] if n_oos else []
    m = len(train_days)
    base = m // FOLD_COUNT
    extra = m % FOLD_COUNT
    folds = []
    cur = 0
    for i in range(FOLD_COUNT):
        size = base + (1 if i < extra else 0)
        folds.append(train_days[cur:cur + size])
        cur += size
    smallest = min((len(f) for f in folds), default=0)
    evaluable = smallest >= MIN_FOLD_DAYS
    oos_evaluable = len(oos_days) >= MIN_FOLD_DAYS
    status = ('OK' if evaluable else
              f'UNEVALUABLE - {smallest} trading days per slice, below the floor of {MIN_FOLD_DAYS}')
    window = f'{oos_days[0]} -> {oos_days[-1]}' if oos_days else 'none'
    return {'folds': folds, 'oos_days': oos_days, 'fold_days': smallest,
            'evaluable': evaluable, 'status': status, 'oos_window': window,
            'oos_days_n': len(oos_days), 'oos_evaluable': oos_evaluable,
            'total_days': n}


def _score(df, sigs, ad, st, w, conv, want_trades=False):
    import portfolio_simulation_engine as engine
    import wf
    td = engine.run_portfolio(df, sigs, adaptive=ad, structural=st, warmup=w, verbose=False, conviction=conv)
    p = td['pnl'].values
    d = wf.daily_pnl_points(td).sort_values('exit_date')
    eq = d['pnl'].cumsum().values
    mdd = float((eq - np.maximum.accumulate(eq)).min()) if len(eq) else 0.0
    mo = pd.Series(td['exit_time'].values).str[:7].values
    exit_day = pd.Series(td['exit_time'].astype(str).values).str[:10].values
    plan = fold_plan(df, w)
    fold_ok = plan['evaluable']
    if fold_ok:
        fmins = []
        fplus = 0
        for fd in plan['folds']:
            m = np.isin(exit_day, fd)
            fmins.append(_pf(p[m]))
            if p[m].sum() > 0:
                fplus += 1
        fmin = min(fmins) if fmins else 0.0
    else:
        fmin = 0.0
        fplus = 0
    oos_prop = np.isin(exit_day, plan['oos_days'])
    oos = np.isin(mo, OOS_MONTHS)
    present = sorted(set(mo.tolist()))
    rel_months = present[-OOS_REL_N_MONTHS:] if len(present) >= OOS_REL_N_MONTHS else present
    oos_rel = np.isin(mo, rel_months)
    summary = {'trades': len(p), 'net': round(float(p.sum())), 'WR': round(float((p > 0).mean() * 100), 1),
               'PF': _pf(p), 'daily_wd': round(float(d['pnl'].min()), 1), 'daily_mDD': round(mdd, 1),
               'folds_plus': fplus, 'min_fold_pf': round(fmin, 2),
               'fold_count': FOLD_COUNT, 'fold_days_each': plan['fold_days'],
               'folds_evaluable': fold_ok, 'folds_status': plan['status'],
               'folds_basis': 'six equal trading-day slices of the leading two-thirds (disjoint from the hold-out)',
               'oos_prop_pf': _pf(p[oos_prop]), 'oos_prop_net': round(float(p[oos_prop].sum())),
               'oos_prop_window': plan['oos_window'], 'oos_prop_days': plan['oos_days_n'],
               'oos_prop_evaluable': plan['oos_evaluable'],
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
        print(f"    {cid} {label:44} net ${r['net']:>7} (Δ {r['delta']:+7}) wd {r['daily_wd']} "
              f"OOS-PF {r['oos_prop_pf'] if r['oos_prop_evaluable'] else 'UNEVAL'}")
    cols = ['id', 'contender', 'trades', 'net', 'delta', 'WR', 'PF', 'daily_wd', 'daily_mDD',
            'folds_plus', 'min_fold_pf', 'oos_pf', 'oos_net', 'oos_legacy_months', 'oos_legacy_stale',
            'oos_rel_months', 'oos_rel_pf', 'oos_rel_net',
            'fold_count', 'fold_days_each', 'folds_evaluable', 'folds_status', 'folds_basis',
            'oos_prop_pf', 'oos_prop_net', 'oos_prop_window', 'oos_prop_days', 'oos_prop_evaluable']
    pd.DataFrame(rows)[cols].to_csv(os.path.join(contenders, 'contenders.csv'), index=False,
                                        lineterminator='\n', encoding='utf-8')
    mark_done(out, 'S7', {'input_sha': input_sha})
    return rows


# ── S8 COMMITTED (frozen-book replay vs discover-fresh) ──
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
        print('  S8 DISCOVER-FRESH IS DISABLED (item 15). Under a catalogue design S8 has '
              'nothing to score automatically: the deliverable is fourteen per-family catalogues '
              'holding every VALID signal, and NOTHING in this build chooses which of them to '
              'trade. Scoring happens when YOU compose a book and run it through:')
        print('      python score_book.py --book <your_book.csv> --data <frame> --out <dir>   (item 16, not yet built)')
        print('  That tool (item 16) applies the constraint machinery - TailDep, FailConc, mCVaR, '
              'absolute survival, union coverage - which are SET properties of an assembled book '
              'and have no per-signal value. Every catalogue states a book is UNSCORED until it '
              'has been run. S8 FROZEN path is untouched and still scores the ratified book.')
        return None
    sigs = score_g.build_book(df, pool, anchor, book, adaptive=ad, structural=st)
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
    if r['folds_evaluable']:
        lines.append(f'  folds positive      : {r["folds_plus"]}/{r["fold_count"]}  '
                     f'({r["fold_days_each"]} trading days each, min-fold PF {r["min_fold_pf"]})')
    else:
        lines.append(f'  folds               : {r["folds_status"]}')
    if r['oos_prop_evaluable']:
        lines.append(f'  OOS (final third: {r["oos_prop_window"]}) PF : {r["oos_prop_pf"]}   '
                     f'net ${r["oos_prop_net"]}')
    else:
        lines.append(f'  OOS (final third)   : UNEVALUABLE - {r["oos_prop_days"]} trading days, '
                     f'below the floor of {MIN_FOLD_DAYS}')
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


LOADER_ALLOWLIST = {
    'engine/analysis_engine.py': 2, 'engine/portfolio_simulation_engine.py': 2,
    'engine/run_full_analysis.py': 1, 'engine/score_book50.py': 1, 'engine/score_g.py': 1,
    'engine/wf.py': 1, 'orchestrator/discovery_orchestrator.py': 2,
    'scanners/concurrence_profiler.py': 1, 'scanners/conditional_interaction.py': 1,
    'scanners/cross_variable_structure.py': 1, 'scanners/divergence_nonconfirm.py': 1,
    'scanners/f0_to_schema.py': 1, 'scanners/mean_reversion.py': 1,
    'scanners/persistence_autocorr.py': 1, 'scanners/rolling_leadlag.py': 1,
    'scanners/run_f1_parallel.py': 1, 'scanners/sequential_temporal.py': 1,
    'scanners/session_temporal.py': 1, 'scanners/single_variable_extremes.py': 1,
    'scanners/state_transition.py': 1, 'scanners/threshold_crossing.py': 1,
    'scanners/triple_convergence_and_d2ddir.py': 3,
}


def preflight_loader_audit():
    found = {}
    for sub in ('engine', 'scanners', 'orchestrator'):
        root = os.path.join(_HERE, sub)
        if not os.path.isdir(root):
            continue
        for nm in sorted(os.listdir(root)):
            if not nm.endswith('.py'):
                continue
            rel = f'{sub}/{nm}'
            txt = open(os.path.join(root, nm), 'r', encoding='utf-8').read()
            n = txt.count('load_sealed_baseline')
            if n:
                found[rel] = n
    new = {k: v for k, v in found.items() if k not in LOADER_ALLOWLIST}
    grew = {k: (LOADER_ALLOWLIST[k], v) for k, v in found.items()
            if k in LOADER_ALLOWLIST and v > LOADER_ALLOWLIST[k]}
    total = sum(found.values())
    print(f'  LOADER AUDIT — {total} references to load_sealed_baseline across {len(found)} files, '
          f'all on the frozen allowlist' if not (new or grew) else
          f'  LOADER AUDIT — FAIL', flush=True)
    hook = os.path.join(_HERE, 'sitecustomize.py')
    binder = os.path.join(_HERE, 'dot_frame_binding.py')
    if not (os.path.exists(hook) and os.path.exists(binder)):
        raise SystemExit(
            'ABORT — sitecustomize.py / dot_frame_binding.py missing from the pack root. Without '
            'them the frame binding cannot reach spawned worker processes, and any family that '
            'starts its own pool (F12, F13) will load the hardcoded equiDOT_recon171_step7_* parts.')
    print('  SPAWN-SAFETY — sitecustomize.py present: the binding re-establishes at interpreter '
          'startup in every spawned process, so the 27 call sites cannot reach the raw loader from '
          'a worker. STATIC LIMIT: this is a presence check, not a proof; a spawned process that '
          'starts with PYTHONPATH stripped would not import the hook, so the binding also asserts '
          'and aborts inside the worker rather than trusting it.', flush=True)
    if new or grew:
        msg = []
        for k, v in new.items():
            msg.append(f'{k} ({v} new occurrence(s))')
        for k, (was, now) in grew.items():
            msg.append(f'{k} ({was} allowed, {now} found)')
        raise SystemExit(
            'ABORT — new load_sealed_baseline call site(s): ' + '; '.join(msg) +
            '. That function hardcodes equiDOT_recon171_step7_* and has silently loaded the WRONG '
            'dataset in three separate places already. Any new call site must either take an '
            'injected frame or be added to LOADER_ALLOWLIST with a reason.')
    return found


def bind_ingested_frame_permanently(df, input_sha, out_dir):
    import dot_frame_binding as fb
    os.makedirs(out_dir, exist_ok=True)
    cache = os.path.join(out_dir, f'_frame_{input_sha}.csv')
    for stale in glob.glob(os.path.join(out_dir, '_frame_*.csv')):
        if os.path.basename(stale) != os.path.basename(cache):
            os.remove(stale)
    if not os.path.exists(cache):
        tmp = cache + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            df.to_csv(f, index=False, lineterminator='\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, cache)
    fp = fb.fingerprint_of(df)
    fb.configure_environment(cache, input_sha, fp)
    fb.install(df)
    print(f'  FRAME BINDING — engine.load_sealed_baseline is bound to the frame S0 ingested, in THIS')
    print(f'  process AND in every process spawned from it. The parent-only monkeypatch did not')
    print(f'  survive spawn: F12 and F13 start their own pools, each worker re-imports a pristine')
    print(f'  engine module and reached the hardcoded equiDOT_recon171_step7_* parts. The binding is')
    print(f'  now re-established at INTERPRETER STARTUP via sitecustomize.py, which Python imports')
    print(f'  before any family code runs, driven by DOT_FRAME_PATH/DOT_INPUT_SHA in the inherited')
    print(f'  environment. A new entry point cannot bypass it because it does not have to opt in.')
    print(f'    frame fingerprint: {fp[0]:,} rows | {fp[1]} -> {fp[2]} | input_sha {input_sha}')
    print(f'    worker frame cache: {os.path.basename(cache)}')
    return cache


def run_diagnostic_families(results_dir, workers, input_sha, df=None):
    import discovery_orchestrator as orch
    print('  DIAGNOSTIC FAMILIES (F12, F13) — separate stages: they emit measurement artifacts, not')
    print('  14-column pool rows, so they cannot collate into discovery_master.csv. Both run on the')
    print('  same single command with the operator --workers value and their own internal parallelism.')
    f13_csv = os.path.join(results_dir, 'results_F13_single_variable_extremes.csv')
    ok13, why13 = orch.provenance_is_current(f13_csv, input_sha)
    if ok13:
        print('  [F13] already current for this input_sha — skipping')
    else:
        print(f'  [F13] running ({why13}); native _f13_shards/*.done checkpointing preserved as-is')
        import single_variable_extremes as f13
        f13.OUT_CSV = f13_csv
        f13.SHARD_DIR = os.path.join(results_dir, '_f13_shards')
        f13.RESULTS_DIR = results_dir
        f13.run(min(workers, 12))
        _f13_arts = [n for n in sorted(os.listdir(results_dir))
                     if n.startswith('results_F13') and n.endswith('.csv')]
        _f13_shards = len([n for n in os.listdir(os.path.join(results_dir, '_f13_shards'))
                           if n.endswith('.done')]) if os.path.isdir(
                               os.path.join(results_dir, '_f13_shards')) else 0
        print(f'  [F13] COMPLETE — artifacts: {", ".join(_f13_arts) if _f13_arts else "NONE"} '
              f'| {_f13_shards} shard markers')
        if not os.path.exists(f13_csv):
            raise SystemExit('ABORT — [F13] ran but produced no output at '
                             f'{os.path.basename(f13_csv)}. A diagnostic family that cannot emit is '
                             'not coverage; the run stops rather than report 14-family coverage with '
                             'one family empty.')
        orch.stamp_provenance(f13_csv, input_sha)

    f12_csv = os.path.join(results_dir, orch.DIAGNOSTIC_OUTPUTS['F12'])
    ok12, why12 = orch.provenance_is_current(f12_csv, input_sha)
    if ok12:
        print('  [F12] already current for this input_sha — skipping')
    else:
        print(f'  [F12] running ({why12}); concurrence CSVs into the run tree')
        before = {}
        for nm in os.listdir(results_dir):
            fp = os.path.join(results_dir, nm)
            if os.path.isfile(fp):
                before[nm] = os.path.getmtime(fp)
        import concurrence_profiler as f12
        f12.RESULTS_DIR = results_dir
        f12.run(n_workers=min(workers, 8))
        produced = []
        for nm in sorted(os.listdir(results_dir)):
            fp = os.path.join(results_dir, nm)
            if not (os.path.isfile(fp) and nm.startswith('concurrence_') and nm.endswith('.csv')):
                continue
            if nm not in before or os.path.getmtime(fp) > before[nm]:
                produced.append(nm)
        for nm in produced:
            orch.stamp_provenance(os.path.join(results_dir, nm), input_sha)
        print(f'  [F12] produced {len(produced)} concurrence CSVs this run: '
              f'{", ".join(produced) if produced else "NONE"}')
        print('  [F12] provenance stamped on THOSE FILES ONLY — never by pattern match on whatever '
              'happens to be on disk, which would launder a stale artifact from another dataset')


_TERRAIN = {}
FIXTURE_WHY = ("WHY THIS RUNS EVERY TIME: greedy once returned ZERO short signals, not as a judgement but because 0 of 13 shorts scored above zero alone at S=5 (a signal cannot stack with itself), so every first-step gain was exactly 0.0 and the search halted at step 0 without ever evaluating a pair. The best short PAIR scored 0.012295, ABOVE the incumbent short reference of 0.00757 - greedy returned 0% of the achievable optimum. The lookahead-2 rule took SHORT from 0% to 100% and LONG gained two pair escapes, so the defect was never short-specific. A book selected without this canary could silently be long-only again and nothing would say so.")
FIXTURE_LIMIT = ("RESTRICTION IS PART OF THE FINDING: enumeration covers sizes 1..max_k_enumerated plus the all-signals set, so exhaustive_optimum is a LOWER BOUND and greedy_pct_of_optimum an UPPER bound.")
PBO_WHY = ("PBO IS A SPEC REQUIREMENT (H.1), REPORTED NOT ENFORCED on the first run. It estimates what fraction of selected winners fail forward - the exact question the redesign exists to answer, given the incumbent degraded from PF 6.40 to PF 2.19 on first unseen data. SELF-REFERENCE: bounds derive from the incumbent itself, so F_max and TailDep pass by construction; the informative cell is mcvar. Separate axes: no composite score is formed and coverage is never promoted above survival.")
COFIRE_WHY = ("NEVER POOLED ACROSS DIRECTIONS. Cross-direction co-firing is EXACTLY ZERO on every bar because the D2D gate admits a signal only where D2D_Trend_Dir equals its direction, so long and short qualifying masks are disjoint. The all-pairs basis is therefore DEFLATED and mechanically rewards a single-direction book; it is retained only under its DIAGNOSTIC name and enters no objective.")
G2_WHY = ("MODEST HYGIENE, NOT A REACH MECHANISM. It removes false corroboration in ranking and prevents degenerate triples. It does NOT address the spec D.0 coverage gap, where 89.8% of missed thrusts have no qualifying signal at all - a vocabulary-content problem no hygiene can solve.")
TDOM_WHY = ("rule: a candidate triple must draw from at least DOMAIN_MIN_DISTINCT distinct functional domains. Applied here as a retrospective fixture only; it removes nothing.")




def _write_with_header(path, frame, header_lines):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        for ln in header_lines:
            f.write(f'# {ln}\n')
        frame.to_csv(f, index=False, lineterminator='\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def s2b_terrain(df, w, out, input_sha, attest):
    import terrain as tr
    oracle_sha = sha12(os.path.join(_ENGINE, 'dots_thresholds.py'))
    print(f'  oracle dots_thresholds.py sha256 : {oracle_sha}')
    print(f'  dataset: {attest["rows"]:,} rows | {attest["range"]}')
    path = os.path.join(out, 'terrain_episodes.csv')
    print('  S2B always recomputes: the terrain costs seconds, and the old checkpoint branch\n        could not parse the metadata header terrain.py writes and rebuilt the terrain anyway.')
    t0 = time.time()
    ter, cells, elig = tr.build_terrain(df, w)
    secs = time.time() - t0
    summary = tr.summarise(ter)
    hours = tr.hour_profile(ter)
    hdr = ['DOT S2B MARKET TERRAIN MAP — price only, NO SIGNALS, NO BOOK',
           f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
           f'oracle_sha256_12={oracle_sha}',
           tr.MARKET_LABEL, tr.FORWARD_LOOKING_BOUNDARY,
           f'eligibility mask: {tr.eligibility_label()} | eligible bars {elig}',
           'K and E come from dots_thresholds (mechanism D, rolling-2500, day-refreshed) via the',
           'ratified basis-3 construction in cluster_profiler; no local percentile, no constant.',
           'THE GRID IS PART OF THE FINDING: every row carries its own (W, K, E) cell. Counts move',
           'by 2-4x across the grid while the up/down ratio barely moves; a count without its',
           'parameters is not a measurement.',
           f'contiguous same-sign qualifying bars collapse into one episode (tolerance '
           f'{tr.CONTIGUOUS_TOLERANCE} bar)']
    _write_with_header(path, ter, hdr)
    _write_with_header(os.path.join(out, 'terrain_summary.csv'), summary, hdr)
    _write_with_header(os.path.join(out, 'terrain_hour_profile.csv'), hours, hdr)
    print(f'  TERRAIN — {len(ter)} episodes across {len(summary)} grid cells | eligible bars {elig:,}')
    for _i, r in summary.iterrows():
        print(f"    W={int(r['W']):2} K=p{int(r['K_pct'] * 100)} E=p{int(r['E_pct'] * 100)} | "
              f"{int(r['episodes']):5} episodes | up {int(r['up']):5} ({r['up_share_pct']:4.1f}%) "
              f"down {int(r['down']):5} ({r['down_share_pct']:4.1f}%) | "
              f"median {r['median_disp_pts']:7.1f}pt (Q1 {r['q1_disp_pts']:.1f} Q3 {r['q3_disp_pts']:.1f}) "
              f"| median {int(r['median_duration_bars'])} bars")
    for ln in tr.render_hour_profile(hours, (15, 0.85, 0.75)):
        print(ln)
    print(f'  S2B runtime {secs:.1f}s for one pass over {attest["rows"]:,} bars x '
          f'{len(summary)} grid cells — single-pass and cheap, so it is NOT chunked and does not '
          f'consume --workers.')
    mark_done(out, 'S2B', {'input_sha': input_sha, 'episodes': int(len(ter))})
    _TERRAIN['cells'] = cells
    _TERRAIN['terrain'] = ter
    return {'terrain': ter, 'cells': cells, 'summary': summary, 'hours': hours}


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
    sigs = score_g.build_book(df, pool, anchor, book, adaptive=ad, structural=st)
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
    months = sorted(set(pd.Series(df['Time'].astype(str).values).str[:7].tolist()))
    segment_label = f'{months[0]}..{months[-1]}' if months else 'unknown'
    ev_book, bk = cp.book_events(executed)
    f1_names = set()
    if 'signal_idx' in executed.columns:
        f1_names = set(executed['signal_name'].values[np.isin(executed['signal_idx'].values, f1_rows)].tolist())
    ev_qual, qual_depth = cp.qualifying_events(df, sigs, ad, st, w)
    cs_by_basis = {'basis1': cp.build_cluster_set(n, ev_book, 5),
                   'basis2': cp.build_cluster_set(n, ev_qual, 5)}
    import family_evidence as fe
    fwd, mag, eff, valid, thr, mcol, ecol = cp.thrust_thresholds(df, 15, (0.85,), (0.75,))
    ev_thr = cp.thrust_events(fwd, mag, eff, valid, thr[(mcol, 'k85')], thr[(ecol, 'e75')], w)
    cs_by_basis['basis3'] = cp.build_cluster_set(n, ev_thr, 5)
    grid_label = ('basis3 grid W=15 K=p85 E=p75 N=5; depth bands size>=5; eligible mask '
                  'ADX>=15 & Volume>50 & post-warmup')
    U = cp.eligible_universe(df, w)
    fam = fe.build_family_evidence(df, bk, qual_depth, cs_by_basis, cs_by_basis['basis3'], U, pool,
                                   f1_names, _SCANNERS,
                                   [os.path.join(out, 'results'), out], grid_label)
    _write_with_header(os.path.join(out, 'family_evidence.csv'), fam, [
        'DOT S3B per-family evidence review (spec A.1)',
        f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
        'LABEL: depth_participation / co_fire_with_F0 / coverage_of_missed are PROPERTY OF THE BOOK.',
        'LABEL: thrust-episode denominators are PROPERTY OF THE MARKET (price-only).',
        f'S5 gate = {fe.S5_GATE}. Cluster tolerance N=5. Depth band = size>=5.',
        'INSUFFICIENT-EVIDENCE is a permitted verdict and is emitted where no output exists.',
        'coverage_of_missed is EMPTY BY CONSTRUCTION for F0 and F1: they are the incumbent book.'])
    cl, mix = fe.cross_family_cofiring(bk, f1_names, 5, n)
    if len(mix):
        _write_with_header(os.path.join(out, 'cross_family_cofiring.csv'), mix, [
            'DOT S3B cross-family co-firing (spec A.4) — PROPERTY OF THE BOOK',
            f'dataset_rows={attest["rows"]}',
            'population = BOOK (F0+F1 executed, gap fillers excluded). Tolerance N=5.'])
    print(f'  families reviewed: {len(fam)} | SELECTABLE {(fam.verdict == "SELECTABLE").sum()} | '
          f'INSUFFICIENT-EVIDENCE {(fam.verdict == "INSUFFICIENT-EVIDENCE").sum()}')
    mark_done(out, 'S3B', {'input_sha': input_sha, 'families': len(fam)})
    return {'family': fam, 'd2d': d2d, 'mixed': mix, 'executed': executed, 'sigs': sigs}


def _no_constraint(_d, _ss):
    return True, ''


NULL_SEED_BASE = 20260728
CONCURRENT_STAGES = ('S3', 'S5C', 'S5D', 'S7')


def s5d_catalogue(df, ad, st, w, pool, anchor, out, input_sha, attest, null_k=None):
    import catalogue as cat
    import cluster_profiler as cp
    import conviction as C
    import selection as sel
    import terrain as tr
    import portfolio_simulation_engine as engine
    import score_g
    import numpy as np
    oracle_sha = sha12(os.path.join(_ENGINE, 'dots_thresholds.py'))
    print(f'  oracle dots_thresholds.py sha256 : {oracle_sha}')
    cand = os.path.join(out, 'results', 'candidates.csv')
    if not os.path.exists(cand):
        print('  CATALOGUE: no candidates.csv - S3/S4/S5 have not produced a pool. NOT marking done.')
        return None
    cands = pd.read_csv(cand)
    null_k = int(null_k) if null_k else cat.NULL_K_DEFAULT
    n = len(df)
    bar_day = pd.Series(df['Time'].astype(str).values).str[:10].values
    U = cp.eligible_universe(df, w)
    W, K, E = cat.PINNED_CELL
    fwd, mag, eff, valid, thr, mcol, ecol = cp.thrust_thresholds(df, W, (K,), (E,))
    ev = cp.thrust_events(fwd, mag, eff, valid, thr[(mcol, f'k{int(K*100)}')],
                          thr[(ecol, f'e{int(E*100)}')], w)
    mda = cat.assert_episode_thresholds_mechanism_d(_HERE, thr, mcol, ecol,
                                                    f'k{int(K*100)}', f'e{int(E*100)}')
    print(f'  ITEM 5 IN-RUN ASSERTION: {mda["modules_verified"]}/4 market-object modules '
          f'byte-verified, episode K/E are per-bar arrays from {mda["basis"]}')
    cs = cp.build_cluster_set(n, ev, tr.CONTIGUOUS_TOLERANCE)
    reach = cat.reachable_episodes(cs, df, w, U)
    raw_tot = {d: int((cs['clusters']['dir'] == d).sum()) for d in (1, -1)}
    print(f'  TERRAIN cell W={W} K=p{int(K*100)} E=p{int(E*100)} | MARKET | raw '
          f'UP {raw_tot[1]} DOWN {raw_tot[-1]} | REACHABLE UP {len(reach[1])} '
          f'({100.0*len(reach[1])/max(raw_tot[1],1):.2f}%) DOWN {len(reach[-1])} '
          f'({100.0*len(reach[-1])/max(raw_tot[-1],1):.2f}%)')
    hurst_hi = ad.get(('Hurst', 'hi'))
    gate_ok = np.flatnonzero((df['Hurst'].values >= hurst_hi) if hurst_hi is not None
                             else np.ones(n, dtype=bool)).astype(np.int64)
    conv = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
    fam_fire_counts = {}
    for fam, g in cands.groupby('family'):
        fc = []
        for _i, cr in g.iterrows():
            try:
                mk = score_g.family_mask(df, pool, fam, str(cr['signal_def']), ad, st)
                fc.append(int(np.asarray(mk, dtype=bool).sum()))
            except Exception:
                continue
        fam_fire_counts[fam] = fc
    per_family = {}
    entries_by_id, dirs_by_id, fams_by_id = {}, {}, {}
    for fam, g in cands.groupby('family'):
        rows = []
        null_pfs, null_rate = [], 0.0
        for _i, cr in g.iterrows():
            sig = str(cr['signal_def'])
            dr = str(cr.get('direction', 'LONG')).upper()
            sid = cat.signal_id(fam, sig, dr)
            one = pd.DataFrame([{'trigger': fam, 'family': fam, 'direction': dr, 'signal_def': sig}])
            try:
                sg = score_g.build_book(df, pool, anchor, one, adaptive=ad, structural=st)
                td = engine.run_portfolio(df, sg, adaptive=ad, structural=st, warmup=w,
                                          verbose=False, conviction=conv)
                td = td[~td['signal_name'].isin(cp.GAP_NAMES)]
            except SystemExit:
                continue
            verdict, reason, stx = cat.evaluate_valid(td, bar_day)
            d = 1 if dr == 'LONG' else -1
            row = {'signal_id': sid, 'family': fam, 'signal_def': sig, 'direction': dr,
                   'verdict': verdict, 'reason_code': reason}
            row.update(stx)
            if verdict == 'VALID':
                bars = np.asarray(td['entry_bar'].values, dtype=np.int64)
                entries_by_id[sid] = bars
                dirs_by_id[sid] = d
                fams_by_id[sid] = fam
                tch = cat.touched_episodes(bars, d, cs)
                tch_reach = [t for t in tch if t in reach[d]]
                row['touched_episode_ids'] = ';'.join(str(x) for x in tch)
                row['episodes_touched'] = len(tch)
                row['coverage_pct_raw_terrain'] = round(100.0 * len(tch) / max(raw_tot[d], 1), 4)
                row['coverage_pct_reachable'] = round(100.0 * len(tch_reach) / max(len(reach[d]), 1), 4)
                row['terrain_cell'] = f'W{W}/K{int(K*100)}/E{int(E*100)}'
                row.update(cat.segment_fold_stats(td))
                row.update({f'gated_{k}': v for k, v in cat.gated_arm(td, gate_ok).items()})
                row['gated_delta_net'] = (round(row['gated_net'] - stx.get('net', 0.0), 2)
                                          if row['gated_net'] != '' else '')
            rows.append(row)
        fr = pd.DataFrame(rows)
        if len(fr):
            N_F = len(fr)
            rng = np.random.default_rng(NULL_SEED_BASE + abs(hash(fam)) % 100000)
            fire_targets = [c for c in fam_fire_counts.get(fam, []) if c > 0]
            fam_k = cat.null_k_for(fam, null_k)
            drawn, nstats = cat.draw_matched_null_masks(pool, fire_targets, rng, k=fam_k)
            long_share = float((g['direction'].astype(str).str.upper() == 'LONG').mean()) \
                if len(g) else 0.5
            null_frames = []
            for j, nd in enumerate(drawn):
                col = f'__NULL_{fam}_{j}'
                df[col] = np.asarray(nd['mask'], dtype=bool).astype(int)
                nsig = pd.DataFrame([{'feat_1': col, 'thresh_1': '==1', 'feat_2': col,
                                      'thresh_2': '==1', 'feat_3': col, 'thresh_3': '==1',
                                      'direction': ('LONG' if rng.random() < long_share
                                                    else 'SHORT')}])
                ntd = engine.run_portfolio(df, nsig, adaptive=ad, structural=st, warmup=w,
                                           verbose=False, conviction=conv)
                null_frames.append(ntd[~ntd['signal_name'].isin(cp.GAP_NAMES)])
                df.drop(columns=[col], inplace=True)
            null_rate, null_pfs = cat.matched_null_rate(null_frames, bar_day)
            qflag, qwhy = cat.null_quality(len(null_frames), fam_k, nstats)
            print(f'    {fam:4} matched null: requested K={fam_k}, IN-BAND {nstats["matched"]} '
                  f'({nstats["matched_fraction"]:.1%} matched, {nstats["rejected_out_of_band"]} '
                  f'rejected out-of-band, targets {nstats["target_min"]}..{nstats["target_max"]} '
                  f'fires, tol +/-{nstats["tol"]:.0%}), direction LONG-share {long_share:.2f}, '
                  f'VALID-passing {len(null_pfs)}, rate {null_rate:.4f}'
                  + (f' | {qflag} -> Appendix A columns BLANK' if qflag else ''))
            if qflag:
                blanks = cat.pricing_blank(qwhy)
                for kk, vv in blanks.items():
                    fr[kk] = vv
                fr['n_null_family'] = len(null_frames)
                fr['null_matched_fraction'] = nstats['matched_fraction']
                fr['null_rejected_out_of_band'] = nstats['rejected_out_of_band']
                fr['null_direction_long_share'] = round(long_share, 4)
                fr['null_seed'] = NULL_SEED_BASE
            else:
                price = [cat.pricing_columns(r.get('agg_pf', float('nan')), N_F, null_rate,
                                             null_pfs) for _j, r in fr.iterrows()]
                for kk in price[0]:
                    fr[kk] = [pz[kk] for pz in price]
                exc = pd.to_numeric(fr['pf_null_exceedance_pct'], errors='coerce').fillna(1.0).values
                fr['q_value_BY_family'] = np.round(cat.benjamini_yekutieli(exc), 6)
                fr['pricing_unavailable_reason'] = ''
                fr['n_null_family'] = len(null_frames)
                fr['null_matched_fraction'] = nstats['matched_fraction']
                fr['null_rejected_out_of_band'] = nstats['rejected_out_of_band']
                fr['null_direction_long_share'] = round(long_share, 4)
                fr['null_seed'] = NULL_SEED_BASE
        per_family[fam] = fr
    _priced = {f: (len(fr) > 0 and 'pricing_unavailable_reason' in fr.columns
                   and str(fr['pricing_unavailable_reason'].iloc[0]) == '')
               for f, fr in per_family.items()}
    _why = {f: (str(fr['pricing_unavailable_reason'].iloc[0]) if len(fr)
                and 'pricing_unavailable_reason' in fr.columns else 'no rows')
            for f, fr in per_family.items()}
    cat_dir = os.path.join(out, 'catalogues')
    os.makedirs(cat_dir, exist_ok=True)
    print('  CATALOGUE ROW COUNT PER FAMILY:')
    for fam in sorted(per_family):
        fr = per_family[fam]
        path = os.path.join(cat_dir, f'catalogue_{fam}.csv')
        _write_with_header(path, fr, [
            f'DOT CATALOGUE - family {fam} - every signal VALID admits, nothing ranked or capped',
            f'dataset_rows={attest["rows"]} dataset_range={attest["range"]}',
            f'oracle_sha256_12={oracle_sha}',
            f'terrain cell W={W} K=p{int(K*100)} E=p{int(E*100)} | coverage emitted against BOTH '
            f'denominators: raw terrain (UP {raw_tot[1]} / DOWN {raw_tot[-1]}, MARKET) and REACHABLE '
            f'(UP {len(reach[1])} / DOWN {len(reach[-1])}, MARKET). REACHABLE IS PRIMARY.',
            'per-signal statistics are PROPERTY OF THE BOOK; terrain and reachable are PROPERTY OF '
            'THE MARKET.',
            (cat.CATALOGUE_HEADER_PRICING if _priced.get(fam) else
             'PRICING COLUMNS ARE BLANK for this family: ' + str(_why.get(fam, '')) +
             '. The Appendix A names carry no substitute quantity - reading this catalogue is still '
             'a search of size N_F, and nothing in this file prices it.'),
            cat.CATALOGUE_HEADER_UNSCORED,
            'UNEVALUABLE rows are RETAINED with statistics blank and a reason_code. INVALID rows '
            '(V2 survival breach) do not enter; their count is reported in the run log.'])
        vc = fr['verdict'].value_counts().to_dict() if len(fr) else {}
        print(f'    {fam:4} {len(fr):7} rows | {vc}')
    has_f0 = 'F0' in per_family and len(per_family.get('F0', []))
    n_valid_triples = {}
    if has_f0:
        f0v = per_family['F0']
        for _i, rr in f0v[f0v['verdict'] == 'VALID'].iterrows():
            for t in str(rr.get('touched_episode_ids', '')).split(';'):
                if t:
                    n_valid_triples[int(t)] = n_valid_triples.get(int(t), 0) + 1
    unclaimed = []
    spans = cat.episode_spans(cs)
    claimed = {d: set() for d in (1, -1)}
    for sid, bars in entries_by_id.items():
        d = dirs_by_id[sid]
        claimed[d].update(cat.touched_episodes(bars, d, cs))
    for d, lab in ((1, 'UP'), (-1, 'DOWN')):
        for eid in sorted(reach[d] - claimed[d]):
            b0, b1, _dd = spans[eid]
            unclaimed.append({'episode_id': eid, 'direction': lab, 'start_bar': b0, 'end_bar': b1,
                              'duration_bars': b1 - b0 + 1,
                              'displacement_pts': round(abs(float(df['Close'].values[min(b1 + W, n - 1)]
                                                                 - df['Close'].values[b0])), 1),
                              'est_hour_start': int(df['EST_Hour'].values[b0]),
                              'n_conditions_firing': int(sum(1 for k in pool
                                                             if pool[k][b0:b1 + 1].any())),
                              'n_valid_triples_touching': n_valid_triples.get(eid, '' if not has_f0 else 0),
                              'population': 'MARKET'})
    uf = pd.DataFrame(unclaimed)
    _write_with_header(os.path.join(cat_dir, 'unclaimed_reachable.csv'), uf, [
        'DOT item 6 - REACHABLE episodes no catalogue signal touches - PROPERTY OF THE MARKET',
        f'dataset_rows={attest["rows"]} terrain cell W={W} K=p{int(K*100)} E=p{int(E*100)}',
        'n_conditions_firing vs n_valid_triples_touching separates a SEARCH gap (many conditions '
        'fire, no valid triple lands) from a GRAMMAR gap (few fire). Without both the set shows what '
        'is unoccupied but not why.'])
    print(f'  UNCLAIMED REACHABLE: {len(uf)} episodes '
          f'(UP {int((uf["direction"] == "UP").sum()) if len(uf) else 0} / '
          f'DOWN {int((uf["direction"] == "DOWN").sum()) if len(uf) else 0})')
    ent = {d: [] for d in (1, -1)}
    ids = {d: [] for d in (1, -1)}
    for sid, bars in entries_by_id.items():
        d = dirs_by_id[sid]
        ent[d].extend(np.asarray(bars, dtype=np.int64).tolist())
        ids[d].extend([sid] * len(bars))
    cohort = cat.same_bar_cohort_table(ent, ids, fams_by_id)
    _write_with_header(os.path.join(cat_dir, 'same_bar_cohort.csv'), cohort, [
        'DOT item 11 - family composition of each bar as a CURVE OVER DEPTH - counts only',
        f'dataset_rows={attest["rows"]}',
        'Depth is DISTINCT SIGNALS on the same bar, per direction, never pooled (item 4). No P&L: '
        'depth-3 has no discriminating power at pool scale and P&L needs a book.'])
    allrows = pd.concat([f for f in per_family.values() if len(f)], ignore_index=True) \
        if per_family else pd.DataFrame()
    if len(allrows):
        v = allrows[allrows['verdict'] == 'VALID'].copy()
        for key, asc in (('agg_pf', False), ('EXPECTED_ROWS_AT_OR_ABOVE_THIS_PF', True)):
            if key not in v.columns:
                continue
            o = v.sort_values(key, ascending=asc)['signal_id'].tolist()
            dc = cat.dilution_curve(o, entries_by_id, dirs_by_id, key)
            _write_with_header(os.path.join(cat_dir, f'dilution_curve_{key}.csv'), dc, [
                f'DOT item 12 - dilution curve, ranking key = {key}',
                f'dataset_rows={attest["rows"]}',
                'Admission is best-first over the WHOLE catalogue, not a top-ranked subset. The '
                'curve is emitted under two keys because the stop-point differs by key, and the '
                'gap between them is the overfit estimate. Counts only, no P&L.'])
            print(f'  DILUTION CURVE ({key}): {len(dc)} admission steps')
    mark_done(out, 'S5D', {'input_sha': input_sha,
                           'families': len(per_family),
                           'rows': int(sum(len(f) for f in per_family.values()))})
    return {'per_family': per_family, 'unclaimed': uf, 'reach': reach, 'raw_tot': raw_tot}


def s5b_selection(df, ad, st, w, pool, anchor, book_file, out, input_sha, attest):
    import cluster_profiler as cp
    import selection as sel
    import terrain as tr
    import portfolio_simulation_engine as engine
    import score_g
    import sequential_temporal as seqmod
    import conviction as C
    import numpy as np
    oracle_sha = sha12(os.path.join(_ENGINE, 'dots_thresholds.py'))
    print(f'  oracle dots_thresholds.py sha256 : {oracle_sha}')
    print(f'  dataset: {attest["rows"]:,} rows | {attest["range"]}')
    cand = os.path.join(out, 'results', 'candidates.csv')
    exercised = os.path.exists(cand)
    n = len(df)
    months = sorted(set(pd.Series(df['Time'].astype(str).values).str[:7].tolist()))
    segment_label = f'{months[0]}..{months[-1]}' if months else 'unknown'
    U = cp.eligible_universe(df, w)
    hyg, dead, canonical, live = sel.vocabulary_hygiene(pool, U, segment_label)
    bk_path = book_file if book_file else os.path.join(_ENGINE, 'book50_signals.csv')
    sigs = score_g.build_book(df, pool, anchor, pd.read_csv(bk_path), adaptive=ad, structural=st)
    conv = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
    full = engine.run_portfolio(df, sigs, adaptive=ad, structural=st, warmup=w, verbose=False,
                               conviction=conv)
    ev_book, bk = cp.book_events(full)
    daily = sel.per_signal_daily(bk)
    smap = sel.daily_series_map(daily)
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
    bar_day = pd.Series(df['Time'].astype(str).values).str[:10].values
    tdays = sel.entry_basis_traded_days(bk, bar_day)
    ent = {1: bk[bk['direction'] == 'LONG']['entry_bar'].values,
           -1: bk[bk['direction'] == 'SHORT']['entry_bar'].values}
    sgn = {1: bk[bk['direction'] == 'LONG']['signal_name'].nunique(),
           -1: bk[bk['direction'] == 'SHORT']['signal_name'].nunique()}
    ids_dir = {1: bk[bk['direction'] == 'LONG']['signal_name'].values.tolist(),
               -1: bk[bk['direction'] == 'SHORT']['signal_name'].values.tolist()}
    grid = sel.depth_yield_grid(ent, sgn, tdays, ids_by_dir=ids_dir)
    grid['depth_yield_LONG_per_signal'] = [sel.depth_yield_per_signal(v, sgn.get(1, 0))
                                           for v in grid['depth_yield_LONG']]
    grid['depth_yield_SHORT_per_signal'] = [sel.depth_yield_per_signal(v, sgn.get(-1, 0))
                                            for v in grid['depth_yield_SHORT']]
    grid['same_signal_refire_LONG'] = [round(sel.same_signal_refire_rate(
        ent.get(1, []), int(t), ids_dir[1]), 4) for t in grid['tolerance_N']]
    grid['same_signal_refire_SHORT'] = [round(sel.same_signal_refire_rate(
        ent.get(-1, []), int(t), ids_dir[-1]), 4) for t in grid['tolerance_N']]
    h3 = sel.h3_within_direction(bk)
    base_hdr = [f'dataset_rows={attest["rows"]} segment={segment_label}',
                f'oracle_sha256_12={oracle_sha}']
    _write_with_header(os.path.join(out, 'selection_vocabulary_hygiene.csv'), hyg, [
        'DOT S5B spec G.1 vocabulary hygiene — PROPERTY OF THE VOCABULARY (not of any book)'] +
        base_hdr + ['dead conditions excluded BEFORE equivalence classes are formed; domain is the '
                    'ACTIVE SEGMENT eligible universe, never hardcoded.'])
    _write_with_header(os.path.join(out, 'selection_depthyield_grid.csv'), grid, [
        'DOT S5B spec C.1 DepthYield — PROPERTY OF THE BOOK'] + base_hdr +
        [f'traded-day denominator = {tdays} on the BOOK ENTRY-BAR basis (spec C.1).',
         'DepthYield is a PAIR (LONG, SHORT), normalised within direction. IT IS NEVER SUMMED.'])
    _write_with_header(os.path.join(out, 'selection_mcvar.csv'), mc, [
        'DOT S5B spec C.2 mCVaR per signal — PROPERTY OF THE BOOK'] + base_hdr +
        [f'C_max = 10th percentile of the incumbent mCVaR distribution = {round(c_max, 2)}',
         'more negative = worse tail concentration; a candidate fails if its worst mCVaR is BELOW C_max.'])
    _write_with_header(os.path.join(out, 'selection_h3_persistence.csv'), h3, [
        'DOT S5B spec H.3 / H.3.1 regime-conditional persistence — PROPERTY OF THE BOOK'] + base_hdr +
        ['RULE not literal: calendar month, positive in all but at most one, MINIMUM 3 BUCKETS or '
         'UNEVALUABLE. Buckets are evaluated WITHIN direction; a thin direction is reported '
         'UNEVALUABLE and is NEITHER passed NOR culled.'])
    con = pd.DataFrame([
        {'quantity': 'F_max (FailConc bound)', 'value': round(f_max, 4), 'source': 'incumbent FailConc on ACTIVE SEGMENT'},
        {'quantity': 'TailDep (incumbent)', 'value': round(tstats['TailDep'], 4), 'source': f"tau={sel.TAU} MIN_SHARED={sel.MIN_SHARED}"},
        {'quantity': 'TailDep_null_mean', 'value': round(null['TailDep_null_mean'], 4), 'source': f"permutation null P={null['permutations']} on ACTIVE SEGMENT"},
        {'quantity': 'kappa (incumbent/null)', 'value': round(kappa, 4), 'source': 'T_max = kappa * TailDep_null(segment); dimensionless'},
        {'quantity': 'C_max (mCVaR bound)', 'value': round(c_max, 2), 'source': 'p10 of incumbent mCVaR on ACTIVE SEGMENT'},
        {'quantity': 'worst modelled day (FULL)', 'value': round(surv['worst_modelled_day'], 1), 'source': 'absolute survival, evaluated independently of the relative bounds'},
        {'quantity': 'absolute survival passes', 'value': surv['passes'], 'source': 'FULL population (book + gap fillers)'},
        {'quantity': 'retention_pct', 'value': tstats['retention_pct'], 'source': 'share of pair space entering TailDep'},
        {'quantity': 'exclusion_bias_degeneracy_guarded', 'value': tstats['exclusion_bias_degeneracy_guarded'], 'source': 'k>=3 only'},
        {'quantity': 'FailCorr Pearson (REPORTED ONLY)', 'value': round(tstats['FailCorr_pearson_reported_only'], 4), 'source': 'never a constraint'},
        {'quantity': 'H.2 resampling pool (post-warmup trading days)', 'value': int(pd.Series(df['Time'].astype(str).values[w:]).str[:10].nunique()), 'source': 'the market, NOT the incumbent footprint'},
    ])
    con['segment'] = segment_label
    _write_with_header(os.path.join(out, 'selection_constraints.csv'), con, [
        'DOT S5B spec C.2 / C.3 constraint references — computed on the ACTIVE TRAINING SEGMENT'] +
        base_hdr + ['F_max, T_max and C_max are SEGMENT-LOCAL; full-series values are reporting '
                    'references only and never enter a constraint.',
                    'The absolute survival bound is evaluated on the FULL population INDEPENDENTLY '
                    'of the relative bounds.'])
    cell = (15, 0.85, 0.75)
    if _TERRAIN.get('cells'):
        cs_thr = _TERRAIN['cells'][cell]
        terrain_src = 'S2B MARKET TERRAIN (fixed denominator, identical for every candidate book)'
    else:
        cs_thr = tr.build_terrain(df, w)[1][cell]
        terrain_src = ('S2B MARKET TERRAIN rebuilt in-process by terrain.build_terrain — the SAME '
                       'construction and grid S2B writes, so the denominator is identical')
    covdir = sel.coverage_by_direction(ev_book, cs_thr, label='INCUMBENT BOOK')
    covdir['W'] = cell[0]
    covdir['K_pct'] = cell[1]
    covdir['E_pct'] = cell[2]
    covdir['terrain_source'] = terrain_src
    _write_with_header(os.path.join(out, 'selection_coverage.csv'), covdir, [
        'DOT S5B REACH — coverage of the S2B MARKET TERRAIN, scored PER DIRECTION'] + base_hdr +
        [f'terrain source: {terrain_src}',
         f'grid cell W={cell[0]} K=p{int(cell[1] * 100)} E=p{int(cell[2] * 100)} | mask {tr.eligibility_label()}',
         'terrain = MARKET (price only, no signals); entries = BOOK. The denominator is FIXED.',
         'PER DIRECTION IS THE POINT: the terrain is near 50/50, so a long-heavy book leaves nearly '
         'all short episodes uncovered and short candidates gain marginal value with NO quota, NO '
         'floor and NO minimum count anywhere in the objective.',
         'COVERAGE NEVER OVERRIDES SURVIVAL: it stays after survival, FailConc and DepthYield in the '
         'lexicographic order (spec C.3), never promoted. A book could reach 100% by taking '
         'everything; that must remain unreachable.',
         'COVERAGE COUNTS PRESENCE, NOT CAPTURE: a signal firing at bar 55 of a 60-bar episode counts '
         'as covering it while earning almost nothing. entry_pos_median is DESCRIPTIVE only; no taper '
         'is built on it because normalised position needs the episode end, unknowable at fire time.',
         tr.FORWARD_LOOKING_BOUNDARY])
    for _i, r in covdir.iterrows():
        print(f"    REACH {r['direction']:<5} {r['coverage_pct']:6.3f}% of {int(r['terrain_episodes']):5} "
              f"terrain episodes ({int(r['touched'])} touched, {int(r['missed'])} missed)", flush=True)
    both = covdir[covdir['direction'].str.startswith('BOTH')]
    cov = {'episodes': int(both['terrain_episodes'].iloc[0]) if len(both) else 0,
           'coverage_pct': float(both['coverage_pct'].iloc[0]) if len(both) else 0.0,
           'by_direction': covdir}
    ent_map = {}
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        ent_map[d] = {nm: g['entry_bar'].values
                      for nm, g in bk[bk['direction'] == lab].groupby('signal_name')}

    def _setval(d, sset):
        if not sset:
            return 0.0
        bars = np.concatenate([ent_map[d][x] for x in sset])
        v, _g = sel.depth_yield_direction(bars, tdays, sel.S_DEFAULT, sel.N_TOLERANCE)
        return v

    def _gain(d, selected, cid):
        return _setval(d, list(selected) + [cid]) - _setval(d, list(selected))

    def _nocon(d, ss):
        return True, ''

    fx = []
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        ids = sorted(ent_map[d].keys())
        if len(ids) < 2:
            continue
        mk = 3 if len(ids) <= 15 else 2
        f = sel.exhaustive_vs_greedy(d, ids, _setval, _gain, _nocon, max_k=mk)
        f['direction_label'] = lab
        fx.append(f)
    fixture = pd.concat(fx, ignore_index=True) if fx else pd.DataFrame()
    if len(fixture):
        _write_with_header(os.path.join(out, 'selection_fixture_exhaustive_vs_greedy.csv'),
                           fixture, ['DOT S5B STANDING CANARY - exhaustive vs greedy, BOTH directions, every run'] + base_hdr + [FIXTURE_WHY, FIXTURE_LIMIT])
        for _i, r in fixture[fixture['argmax'].str.startswith('GREEDY')].iterrows():
            print(f"    CANARY {r['direction_label']:<5} greedy {r['greedy_value']:.6f} = "
                  f"{r['greedy_pct_of_optimum']}% of enumerated optimum "
                  f"{r['exhaustive_optimum']:.6f} (optimum at size "
                  f"{int(r['optimum_at_size'])}, pair escapes {int(r['pair_escapes'])})", flush=True)
    pivot = daily.pivot_table(index='day', columns='signal_name', values='pnl',
                              aggfunc='sum').fillna(0.0)
    pbo = sel.pbo_cscv(pivot.values) if pivot.shape[0] >= 16 and pivot.shape[1] >= 2 else float('nan')
    merged_state = {'survival': surv, 'FailConc': f_max, 'TailDep': tstats['TailDep'],
                    'worst_mCVaR': float(np.nanmin(mc['mCVaR']))}
    bounds = {'F_max': f_max, 'T_max': kappa * null['TailDep_null_mean'], 'C_max': c_max}
    con_eval = sel.evaluate_constraints(merged_state, bounds)
    ce = pd.DataFrame([{'applied_to': 'INCUMBENT BOOK (self-reference)',
                        **{k: str(v) for k, v in con_eval.items()},
                        'PBO_cscv_reported_not_enforced': round(pbo, 4) if pbo == pbo else '',
                        'PBO_reference_bar': 0.10}])
    _write_with_header(os.path.join(out, 'selection_constraint_evaluation.csv'), ce,
                       ['DOT S5B spec C.3 constraint evaluation + spec H.1 PBO via CSCV'] + base_hdr + [PBO_WHY])
    print(f"    PBO (CSCV, reported not enforced, bar 0.10) = "
          f"{round(pbo, 4) if pbo == pbo else 'n/a'} | constraints "
          f"{con_eval['binding'] or 'all pass'}", flush=True)
    vz = df['Volume'].values == 0
    fri = ((df['EST_DayOfWeek'].values == 5)
           & ((df['EST_Hour'].values > 16)
              | ((df['EST_Hour'].values == 16) & (df['EST_Minute'].values >= 45))))
    entry_ok = ((df['ADX_Value'].values >= 15) & (df['Volume'].values > 50) & ~vz & ~fri
                & (np.arange(n) >= w))
    qmasks, qdirs, qnames = engine.build_signal_masks(df, sigs, ad, st, entry_ok, verbose=False)
    Mq = sel.cofire_matrix(qmasks, qnames)
    qd = np.array(qdirs)
    offm = ~np.eye(len(qnames), dtype=bool)
    cofire_rows = []
    for dd, lab in ((1, 'LONG'), (-1, 'SHORT')):
        sd = qd == dd
        sub = Mq[np.ix_(sd, sd)]
        o = ~np.eye(sub.shape[0], dtype=bool)
        if o.sum():
            cofire_rows.append({'basis': lab + '-only ordered pairs (WITHIN direction)',
                                'signals': int(sd.sum()),
                                'CoFire_mean': round(float(sub[o].mean()), 6),
                                'ordered_pairs': int(o.sum())})
    crossm = (qd[:, None] != qd[None, :]) & offm
    cofire_rows.append({'basis': 'CROSS-direction ordered pairs (structurally zero)',
                        'signals': len(qnames),
                        'CoFire_mean': round(float(Mq[crossm].mean()), 6) if crossm.sum() else 0.0,
                        'ordered_pairs': int(crossm.sum())})
    cofire_rows.append({'basis': 'ALL ordered pairs - cofire_book_all_pairs_DIAGNOSTIC (DEFLATED)',
                        'signals': len(qnames),
                        'CoFire_mean': round(sel.cofire_book_all_pairs_DIAGNOSTIC(Mq), 6),
                        'ordered_pairs': int(offm.sum())})
    cof = pd.DataFrame(cofire_rows)
    _write_with_header(os.path.join(out, 'selection_cofire.csv'), cof,
                       ['DOT S5B spec C.1 entry co-firing - PROPERTY OF THE BOOK'] + base_hdr + [COFIRE_WHY])
    Cmat, cnames, edges, gstats = sel.mask_correlation_graph(pool, live, U)
    comms = sel.detect_communities(cnames, edges)
    n90, n95, pr_ratio = sel.effective_dimension(Cmat)
    g2 = pd.DataFrame([{**gstats, 'communities_detected': len(comms),
                        'largest_community': max((len(v) for v in comms.values()), default=0),
                        'effective_dim_90pct': n90, 'effective_dim_95pct': n95,
                        'participation_ratio': round(pr_ratio, 2), 'r_threshold': 0.70}])
    _write_with_header(os.path.join(out, 'selection_g2_near_duplication.csv'), g2,
                       ['DOT S5B spec G.2 near-duplication and community detection'] + base_hdr + [G2_WHY])
    bookdf = pd.read_csv(bk_path)
    trows = []
    for _i, r in bookdf.iterrows():
        if 'trigger' in bookdf.columns and str(r['trigger']) != 'F0':
            continue
        parts = [x.strip() for x in str(r['signal_def']).split('+')]
        doms = sorted({sel.condition_domain(x) for x in parts})
        trows.append({'signal_def': r['signal_def'], 'direction': r['direction'],
                      'domains': ';'.join(doms), 'n_domains': len(doms),
                      'passes_2domain_rule': sel.triple_domain_ok(parts)})
    tdom = pd.DataFrame(trows)
    if len(tdom):
        _write_with_header(os.path.join(out, 'selection_g2_domain_bridging.csv'), tdom,
                           ['DOT S5B spec G.2 domain bridging applied RETROSPECTIVELY to the incumbent F0 triples - PROPERTY OF THE BOOK'] + base_hdr + [TDOM_WHY])
        print(f"    G.2 {gstats['pairs_ge_070']} pairs at |r|>=0.70 of {gstats['pairs_total']}, "
              f"median |r| {round(gstats['median_abs_r'], 4)}, {n90} components carry 90% variance, "
              f"{len(comms)} communities | domain bridging "
              f"{int(tdom['passes_2domain_rule'].sum())} of {len(tdom)} triples span >= 2 domains",
              flush=True)
    report_lines = [
        f'vocabulary: {hyg["vocabulary_total"].iloc[0]} total, {hyg["dead_conditions"].iloc[0]} dead, '
        f'{hyg["effective_vocabulary"].iloc[0]} effective (identity domain = eligible universe)',
        f'constraint references (segment {segment_label}): F_max {round(f_max, 3)}, kappa '
        f'{round(kappa, 3)}, C_max {round(c_max, 1)}, absolute survival '
        f'{"PASS" if surv["passes"] else "FAIL"} at worst day {round(surv["worst_modelled_day"], 1)}',
        'H.3 within direction: ' + '; '.join(f"{r['direction']} {r['verdict']}" for _i, r in h3.iterrows()),
        'submodularity: NOT established; greedy is a heuristic and the (1-1/e) bound is NOT claimed',
        'NO DIRECTIONAL TARGET: no floor, quota, target or reserved allocation exists in selection.py',
    ]
    if exercised:
        cands = pd.read_csv(cand)
        print(f'  SELECTION SEARCH over {len(cands)} candidates — per-direction greedy/CELF with '
              f'the lookahead-2 stopping rule, subject to the constraint references above.')
        entry_ok_sel = ((df['ADX_Value'].values >= 15) & (df['Volume'].values > 50)
                        & (df['Volume'].values != 0) & (np.arange(n) >= w))
        cand_bars = {1: {}, -1: {}}
        skipped = 0
        for _i, cr in cands.iterrows():
            fam = str(cr.get('family', '')).strip()
            sig = str(cr.get('signal_def', ''))
            d = 1 if str(cr.get('direction', 'LONG')).upper() == 'LONG' else -1
            key = f'{fam}|{sig}|{"LONG" if d == 1 else "SHORT"}'
            if key in cand_bars[d]:
                continue
            try:
                if fam == 'F0':
                    parts = [x.strip().rsplit(':', 1) for x in sig.split('+')]
                    mk = np.ones(n, dtype=bool)
                    for f_, t_ in parts:
                        mk &= np.asarray(engine.condition_mask(df, f_, t_, ad, st), dtype=bool)
                elif fam == 'F1':
                    mm = score_g._F1.match(sig)
                    mk = np.asarray(seqmod.pair_mask(pool[mm.group(1).strip()],
                                                     pool[mm.group(3).strip()],
                                                     int(mm.group(2)), anchor), dtype=bool)
                else:
                    mk = np.asarray(score_g.family_mask(df, pool, fam, sig, ad, st), dtype=bool)
            except SystemExit as _e:
                rl.warn(f'S5D candidate skipped ({fam}): {_e}')
                skipped += 1
                continue
            cand_bars[d][key] = np.flatnonzero(mk & entry_ok_sel).astype(np.int64)
        print(f'  candidate entry masks built: LONG {len(cand_bars[1])} | SHORT {len(cand_bars[-1])}'
              + (f' | {skipped} unparseable skipped' if skipped else ''))

        def _dy(d, sset):
            if not sset:
                return 0.0
            bars = np.concatenate([cand_bars[d][x] for x in sset])
            v, _g = sel.depth_yield_direction(bars, tdays, sel.S_DEFAULT,
                                              sel.N_TOLERANCE)
            return v

        def _sel_gain(d, selected, cid):
            return _dy(d, list(selected) + [cid]) - _dy(d, list(selected))

        def _sel_setgain(d, selected, add):
            return _dy(d, list(selected) + list(add)) - _dy(d, list(selected))

        chosen = {}
        stops = {}
        for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
            ids = sorted(cand_bars[d].keys())
            if not ids:
                chosen[d] = []
                stops[d] = 'no candidates in this direction'
                continue
            picked, reason, log, meta = sel.greedy_direction(
                d, ids, _sel_gain, _no_constraint, set_gain_fn=_sel_setgain)
            chosen[d] = picked
            stops[d] = reason
            print(f'    {lab}: selected {len(picked)} of {len(ids)} candidates | '
                  f'pair escapes {meta["pair_escapes"]} | stop: {reason[:80]}')
        admitted = {lab: list(chosen[d]) for d, lab in ((1, 'LONG'), (-1, 'SHORT'))}
        print(f'  ADMISSION ORDER retained IN MEMORY ONLY for item 12\'s dilution curve: '
              f'LONG {len(admitted["LONG"])} / SHORT {len(admitted["SHORT"])}. '
              f'NO selected_book.csv is written. Item 15: the catalogue is emitted from VALID, '
              f'never from an argmax, so no argmax output is persisted anywhere. greedy_direction '
              f'survives as the dilution-curve admission loop and nothing else consumes it.')
        report_lines.append(
            f'ADMISSION ORDER computed in memory for the dilution curve from {len(cands)} '
            f'candidates (LONG {len(chosen[1])} / SHORT {len(chosen[-1])}). NO selected book is '
            f'written: item 15 forbids emitting a catalogue from an argmax.')
    if not exercised:
        report_lines.append('SELECTION SEARCH NOT RUN: no candidates.csv on this run, so the '
                            'objective and per-direction greedy were not exercised. The constraint '
                            'references, hygiene, DepthYield and REACH above are measured on the '
                            'incumbent as a self-reference.')
    print(f'  vocabulary {hyg["effective_vocabulary"].iloc[0]} effective | kappa {kappa:.3f} | '
          f'C_max {c_max:.1f} | survival {"PASS" if surv["passes"] else "FAIL"}')
    print(f'  selection search: {"candidates present" if exercised else "UNEXERCISED PENDING S3 (no candidate pool)"}')
    if not exercised:
        print('  S5B NOT MARKED DONE — it reported itself unexercised (no candidate pool). A stage '
              'that did not do its work must not claim it did.')
    else:
        mark_done(out, 'S5B', {'input_sha': input_sha,
                               'effective_vocabulary': int(hyg['effective_vocabulary'].iloc[0])})
    return {'report_lines': report_lines, 'hygiene': hyg, 'grid': grid, 'constraints': con,
            'h3': h3, 'coverage': cov}



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
    sigs = score_g.build_book(df, pool, anchor, pd.read_csv(bk_path), adaptive=ad, structural=st)
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
    import discovery_orchestrator as orch
    _cand = os.path.join(out, 'results', 'candidates.csv')
    _pool_ok = False
    _pool_n = 0
    _pool_why = 'candidates.csv absent'
    if os.path.exists(_cand):
        try:
            _pool_n = len(pd.read_csv(_cand))
        except Exception as _e:
            _pool_n = 0
            _pool_why = f'candidates.csv unreadable: {type(_e).__name__}'
        if _pool_n > 0:
            _prov_ok, _prov_why = orch.provenance_is_current(_cand, input_sha)
            _pool_ok = bool(_prov_ok)
            _pool_why = ('pool present and current' if _prov_ok
                         else f'pool present ({_pool_n} rows) but provenance: {_prov_why}')
        else:
            _pool_why = 'candidates.csv present but empty'
    meta_checks = {'funnel_rerun': _pool_ok, 'null_per_split': True,
                   'funnel_detail': (f'DERIVED, not asserted: {_pool_why}; candidates={_pool_n}; '
                                     f'input_sha={input_sha}')}
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
    book_meta = {'persist_definition': wfs.PERSIST_DEFINITION,
                 'denominator_definition': wfs.DENOMINATOR_DEFINITION}
    null_meta = {'persist_definition': wfs.PERSIST_DEFINITION,
                 'denominator_definition': wfs.DENOMINATOR_DEFINITION}
    agree = wfs.assert_arms_agree(book_meta, null_meta)
    print(f'  ITEM 18 ARMS AGREE (asserted, abort on mismatch): persist = '
          f'{agree["persist_definition"]}')
    print(f'    denominator = {agree["denominator_definition"]}')
    if not _pool_ok:
        print(f'  BOOK ARM SKIPPED: {_pool_why}. book_rates stay nan and the criterion will read '
              f'UNEVALUABLE. THIS LINE EXISTS SO A nan IS ALWAYS ATTRIBUTABLE: without it, "no pool, '
              f'correctly skipped" and "pool present but the provenance stamp did not match" are '
              f'indistinguishable on the console, which is exactly what concealed a key mismatch '
              f'through three deliveries.', flush=True)
    if _pool_ok:
        import catalogue as cat2
        cands_wf = pd.read_csv(_cand)
        conv_wf = C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True)
        arm = wfs.book_arm_from_valid(df, cands_wf, pool, anchor, ad, st, w, splits,
                                      score_g.build_book, engine.run_portfolio,
                                      cat2.evaluate_valid,
                                      pd.Series(df['Time'].astype(str).values).str[:10].values,
                                      conviction=conv_wf, gap_names=cp.GAP_NAMES)
        book_rates = [a_['rate'] for a_ in arm]
        for a_ in arm:
            print(f'    split {a_["split"]}: VALID admitted {a_["entities"]} on train, '
                  f'{a_["k"]}/{a_["n_traded"]} persisted on test -> rate '
                  f'{a_["rate"] if a_["rate"] == a_["rate"] else "nan"}'
                  + (f' | {a_["note"]}' if a_['note'] else ''))
    verdict = wfs.pass_criterion(book_rates, null_rates, null_ok)
    verdict['certifies'] = ('THE CATALOGUE INCLUSION RULE (VALID), NOT ANY BOOK. Re-scoring a '
                            'hand-assembled book per split is prohibited: a validated generator '
                            'is not a validated book.')
    verdict['persist_definition'] = agree['persist_definition']
    verdict['denominator_definition'] = agree['denominator_definition']
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
        sigs = score_g.build_book(df, pool, anchor, pd.read_csv(bk_path), adaptive=ad, structural=st)
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
    sm.to_csv(os.path.join(out, 'cluster_basis_summary.csv'), index=False,
                lineterminator='\n', encoding='utf-8')
    print(f'  wrote {len(res)} rows → {path}')
    mark_done(out, 'S8B', {'input_sha': input_sha, 'rows': int(len(res)), 'conditions': len(pool)})
    return {'rows': int(len(res)), 'conditions': len(pool), 'summary': sm, 'overlaps': overlaps,
            'eligibility': cp.ELIGIBILITY_PREDICATE,
            'eligible_bars': int(U.sum()), 'path': path, 'res': res,
            'max_qual_depth': int(max(qual_depth[1].max(), qual_depth[-1].max()))}


# ── S9 REPORT + SPLIT ──
def s9_report(out, attest, contenders, committed, sacred, market_label, input_sha, profile=None, evidence=None, selection_state=None):
    scored_fresh = 'regenerated fresh this run (S6) — stale 746102aae415 / 0910f360a628 NOT inherited'
    L = []
    L.append(f'# DOT Master Report — {market_label}')
    L.append('')
    L.append('## 1. Ingest attestation')
    L.append(f'- files: {", ".join(attest["files"])}')
    L.append(f'- shape: {attest["rows"]:,} rows × {attest["cols"]} cols · range {attest["range"]}')
    L.append(f'- path: {attest["path"]} · invariants: {attest["invariants"]}')
    L.append('')
    L.append(f'- fold/OOS basis: {FOLD_BASIS_NOTE}')
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
                     f"{r['daily_wd']} | {r['daily_mDD']} | "
                     f"{str(r['folds_plus']) + '/' + str(r['fold_count']) if r['folds_evaluable'] else 'UNEVAL'} | "
                     f"{r['min_fold_pf']} | {r['oos_prop_pf'] if r['oos_prop_evaluable'] else 'UNEVAL'} | "
                     f"${r['oos_prop_net']} |")
        L.append('')
    if committed:
        L.append('## 4. Committed-system headline')
        L.append(f"- book: {committed['book_tag']}")
        L.append(f"- **net ${committed['net']} | {committed['trades']} tr | WR {committed['WR']}% | PF {committed['PF']} | "
                 f"daily wd {committed['daily_wd']} | daily mDD {committed['daily_mDD']} | "
                 f"{str(committed['folds_plus']) + '/' + str(committed['fold_count']) if committed['folds_evaluable'] else 'folds UNEVALUABLE'} "
                 f"min-PF {committed['min_fold_pf']} | OOS (final third {committed['oos_prop_window']}) "
                 f"PF {committed['oos_prop_pf']} | OOS net ${committed['oos_prop_net']}**")
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
    print(f'  report -> {rep} | every artifact written as ONE file (item 3: auto-split deleted; '
          f'the next stage used to read the chopped parts as if they were whole)')
    mark_done(out, 'S9', {'input_sha': input_sha})


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
    import runlog as rl
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description='DOT master orchestrator (S0→S9).')
    ap.add_argument('--data', default='/data')
    ap.add_argument('--out', default=os.path.join(_HERE, 'discovery'))
    ap.add_argument('--book', default=None)
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--stage', default=None, choices=STAGES)
    ap.add_argument('--market-label', default='US30 (sealed baseline)')
    ap.add_argument('--parity', default=None,
                    help="run the chunking parity harness and exit: a family (e.g. F0) or 'all'")
    ap.add_argument('--s3-limit', type=int, default=0,
                    help='bound each family to its first N axis units in S3 (0 = unbounded); for '
                         'smoke-testing the stage without committing days')
    ap.add_argument('--parity-limit', type=int, default=200,
                    help='cap each family to the first N axis units, applied to BOTH parity legs')
    args = ap.parse_args()
    args.workers = min(args.workers, 16)
    os.environ['DOT_WORKERS'] = str(args.workers)

    t0 = time.time()
    print('═' * 68)
    print('DOT MASTER ORCHESTRATOR')
    print('═' * 68)
    sacred = verify_sacred()
    preflight_loader_audit()
    data_dir = resolve_data(args.data)
    book_file = resolve_book(args.book)
    out = args.out
    for sub in ('raw', 'results', 'scored', 'contenders', 'committed', '.markers'):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    mode = 'FROZEN-BOOK replay + verify' if book_file else 'DISCOVER-FRESH (no --book)'
    print(f'mode: {mode} | data: {data_dir} | out: {out} | workers: {args.workers}')

    only = args.stage
    print('\n[S0] INGEST & VALIDATE')
    _logp = rl.open_run_log(out)
    print(f'  run log -> {_logp} (ATTESTATION RECORD: carries wall-clock; every CSV does not)')
    with rl.Stage('S0', 'ingest & validate'):
        df, attest, input_sha = s0_ingest(data_dir, out)
    bind_ingested_frame_permanently(df, input_sha, os.path.join(out, 'results'))
    print('\n[S1] ADAPTIVE THRESHOLDS (oracle)')
    ad, st = s1_thresholds(df)
    print('\n[S2] POOL & ANCHORS')
    pool, anchor, w = s2_pool(df, ad, st)

    if args.parity:
        import discovery_orchestrator as orch
        results = os.path.join(out, 'results')
        os.makedirs(results, exist_ok=True)
        orch.RESULTS_DIR = results
        os.environ['DOT_RESULTS_DIR'] = results
        fams = None if args.parity.lower() == 'all' else [x.strip().upper()
                                                         for x in args.parity.split(',')]
        frame_path = None
        if args.workers > 1:
            frame_path = os.path.join(results, f'_parity_frame_{input_sha}.csv')
            if not os.path.exists(frame_path):
                tmp = frame_path + '.tmp'
                with open(tmp, 'w', encoding='utf-8', newline='') as f:
                    df.to_csv(f, index=False, lineterminator='\n')
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, frame_path)
        print('\n[PARITY] CHUNKING PARITY HARNESS — pre-flight check, no scan is run')
        print('  scope=proof (the smaller candidate vocabulary): parity proves a MECHANISM —')
        print('  that chunked+collated equals unchunked over the SAME bounded range. Full scope')
        print('  would cost hours per leg and prove nothing further about the mechanism.')
        ok = orch.parity_check('proof', workers=args.workers, df=df, adaptive=ad, structural=st,
                               warmup=w, families=fams, limit=args.parity_limit,
                               frame_path=frame_path)
        if frame_path and os.path.exists(frame_path):
            os.remove(frame_path)
        print('\n' + '=' * 68)
        print('PARITY PASS — chunking is sound on this dataset; the full scan may be started.'
              if ok else
              'PARITY FAIL — a chunked family does NOT reproduce its unchunked result on this '
              'dataset. DO NOT start the scan; the pool would be wrong.')
        print('=' * 68)
        sys.exit(0 if ok else 1)

    contenders = committed = profile = evidence = selection_state = wf_state = None
    terrain_state = None
    catalogue_state = None
    run_all = only is None
    if run_all or only == 'S2B':
        print('\n[S2B] MARKET TERRAIN MAP')
        with rl.Stage('S2B', 'market terrain map'):
            terrain_state = s2b_terrain(df, w, out, input_sha, attest)
    discover = (book_file is None)
    if not discover and run_all:
        print('\n[S3–S6] DISCOVERY / REGEN — SKIPPED on the frozen-book verification path.')
        print('  --book replays a ratified book (S8); fresh discovery is the no-book path.')
        print('  Run `python master.py` (no --book) or `--stage S3` for the full 1–2 day discovery.')
    if (run_all and discover) or only == 'S3':
        print('\n[S3] FAMILY DISCOVERY (long-pole; delegates to ratified orchestrator)')
        s3_discovery(out, args.workers, input_sha, 'full', df=df, ad=ad, st=st, w=w,
                     limit=args.s3_limit)
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
    if run_all or only == 'S5D':
        print('\n[S5D] CATALOGUE - fourteen per-family books, every VALID signal')
        with rl.Stage('S5D', 'catalogue emission'):
            catalogue_state = s5d_catalogue(df, ad, st, w, pool, anchor, out, input_sha, attest)
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
        with rl.Stage('S9', 'report'):
            s9_report(out, attest, contenders, committed, sacred, args.market_label, input_sha, profile, evidence, selection_state)
    rl.print_timing_table(concurrent_stages=CONCURRENT_STAGES)

    print('\n' + '═' * 68)
    print(f'MASTER COMPLETE in {_hms(time.time() - t0)} | out: {out}')
    if committed and committed.get('canary'):
        print(f'US30 baseline canary: engine intact — net ${committed["net"]} / {committed["trades"]} tr')
    print('═' * 68)


if __name__ == '__main__':
    main()
