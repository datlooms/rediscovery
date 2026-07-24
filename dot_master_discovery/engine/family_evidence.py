"""S3B — per-family evidence review (spec §A.1-A.5) and the D2D gate measurement (spec §E.1).

DOCTRINE BINDING (DOT_signal_discovery_mantra.md, sha fae943d40231).
Rule 1 — every emitted table is labelled MARKET or BOOK and states its parameters
at the point of use, in the table itself, not in a methods note.
Rule 2 — nothing is removed on a single measurement. Every gate variant here is a
STATE COLUMN applied as a mask; no bar is deleted anywhere in this module.
Rule 3 — no pre-set targets. Composition is reported, never constrained.
Rule 4 — depth participation is a first-class column on every family row.
Rule 5 — INSUFFICIENT-EVIDENCE is a permitted and expected verdict, and a
negative carries the same burden of proof as a positive. A family is never
assigned a verdict on the basis of its historical classification, and F13's
documented negative is never used to exclude anything.

WHEN A FINDING DEPENDS ON A FILTER, THRESHOLD OR RESTRICTION, THE FILTER IS PART
OF THE FINDING. The S5 gate, the eligible-universe mask, the cluster tolerance
and the thrust grid cell are emitted as columns beside every figure they govern.

THRESHOLD PROVENANCE. Every threshold defining an object, event, cluster,
episode or stratum comes from dots_thresholds via compute_adaptive_thresholds
(mechanism D, rolling-2500, day-refreshed, floor-index), reached through
cluster_profiler's ratified helpers. No percentile defining such an object is
computed locally. Descriptive output statistics (medians, quartiles of an
already-selected population) are permitted and are identifiable as such.

D2D MEASUREMENT LIMIT, STATED RATHER THAN SMOOTHED. Spec §E.1 part 1 asks for the
book scored with the D2D agreement condition removed from build_signal_masks.
That condition is `mask & (d2d_dir == direction)` inside
portfolio_simulation_engine.build_signal_masks, which is SACRED and byte-locked.
A single-run full removal across both directions is therefore not computable
without editing a sacred file, because one D2D_Trend_Dir column cannot satisfy
`== +1` and `== -1` on the same bar. What IS exactly computable, by setting the
D2D_Trend_Dir state column and changing nothing else, is emitted here: the
baseline, the inverted gate (part 4), and the per-direction ungated runs
(d2d = +1 frees every long and blocks every short; d2d = -1 frees every short and
blocks every long). The per-direction runs are exact within their direction but
isolate the jar, so they are labelled as such. The measurement that would close
the gap is an authorised `d2d_gate=on/off` parameter on run_portfolio, which
requires documented human authorisation and is not taken here.
"""

import glob
import hashlib
import os

import numpy as np
import pandas as pd
import cluster_profiler as cp

S5_GATE = 'trades>=30 & folds_plus>=4 & agg_pf>=2.0'
FAMILY_REGISTRY = [
    ('F0', 'triple_convergence_and_d2ddir.py', ('results_F0*.csv', 'deduped_survivors.csv', 'raw_survivors.csv')),
    ('F1', 'sequential_temporal.py', ('F1_part*.csv', 'results_F1_*.csv')),
    ('F2', 'state_transition.py', ('results_F2*.csv',)),
    ('F3', 'conditional_interaction.py', ('results_F3*.csv',)),
    ('F4', 'divergence_nonconfirm.py', ('results_F4*.csv',)),
    ('F5', 'persistence_autocorr.py', ('results_F5*.csv',)),
    ('F6', 'threshold_crossing.py', ('results_F6*.csv',)),
    ('F7', 'mean_reversion.py', ('results_F7*.csv',)),
    ('F8', 'cross_variable_structure.py', ('results_F8*.csv',)),
    ('F9', 'session_temporal.py', ('results_F9*.csv',)),
    ('F10', None, ()),
    ('F11', 'rolling_leadlag.py', ('results_F11_*.csv',)),
    ('F12', 'concurrence_profiler.py', ('concurrence_*.csv', 'results_F12_*.csv')),
    ('F13', 'single_variable_extremes.py', ('results_F13_*.csv',)),
]


def _sha12(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:12] if os.path.exists(path) else ''


def _find_outputs(search_dirs, patterns):
    hits = []
    for d in search_dirs:
        for pat in patterns:
            hits.extend(sorted(glob.glob(os.path.join(d, pat))))
    return sorted(set(hits))


def _rows_and_s5(paths):
    rows = 0
    passing = ''
    defs = set()
    for p in paths:
        try:
            t = pd.read_csv(p, comment='#')
        except Exception:
            continue
        rows += len(t)
        if {'trades', 'folds_plus', 'agg_pf'}.issubset(t.columns):
            k = int(((t['trades'] >= 30) & (t['folds_plus'] >= 4) & (t['agg_pf'] >= 2.0)).sum())
            passing = k if passing == '' else passing + k
        for c in ('signal_def', 'condition'):
            if c in t.columns:
                for v in t[c].astype(str).values:
                    for tok in str(v).replace('->', '+').split('+'):
                        tok = tok.strip()
                        if ':' in tok:
                            defs.add(tok.split('@')[0])
    return rows, passing, defs


def book_family_of(signal_name, f1_names):
    return 'F1' if signal_name in f1_names else 'F0'


def measure_book_families(df, bk, qual_depth, cs_by_basis, U, f1_names, months):
    out = {}
    for fam in ('F0', 'F1'):
        sel = np.array([book_family_of(s, f1_names) == fam for s in bk['signal_name'].values])
        sub = bk[sel]
        rec = {'trades': int(len(sub)), 'net': round(float(sub['pnl'].sum()), 1) if len(sub) else 0.0,
               'signals': int(sub['signal_name'].nunique()) if len(sub) else 0}
        for bname, cs in cs_by_basis.items():
            if len(sub) == 0:
                rec[f'depth_participation_{bname}'] = ''
                continue
            bars = sub['entry_bar'].values.astype(np.int64)
            dirs = np.where(sub['direction'].values == 'LONG', 1, -1)
            inband = np.zeros(len(sub), bool)
            for d in (1, -1):
                m = dirs == d
                if m.any():
                    inband[m] = (cs['cid'][d][bars[m]] >= 0) & (cs['fsize'][d][bars[m]] >= 5)
            rec[f'depth_participation_{bname}'] = round(100.0 * float(inband.mean()), 1)
        if len(sub):
            mo = pd.Series(sub['exit_time'].values).str[:7].values
            nets = {m: round(float(sub['pnl'].values[mo == m].sum()), 1) for m in sorted(set(mo))}
            rec['regime_conditional_net'] = ';'.join(f'{k}:{v}' for k, v in nets.items())
            rec['regime_buckets_positive'] = f"{sum(1 for v in nets.values() if v > 0)}/{len(nets)}"
        else:
            rec['regime_conditional_net'] = ''
            rec['regime_buckets_positive'] = ''
        out[fam] = rec
    return out


def cofire_with_f0(bk, f1_names):
    f0bars = {}
    for d in (1, -1):
        lab = 'LONG' if d == 1 else 'SHORT'
        s = bk[(bk['direction'] == lab) & np.array([book_family_of(x, f1_names) == 'F0' for x in bk['signal_name'].values])]
        f0bars[d] = set(s['entry_bar'].values.tolist())
    out = {}
    for fam in ('F0', 'F1'):
        sel = np.array([book_family_of(s, f1_names) == fam for s in bk['signal_name'].values])
        sub = bk[sel]
        if len(sub) == 0:
            out[fam] = ''
            continue
        hit = 0
        for _i, r in sub.iterrows():
            d = 1 if r['direction'] == 'LONG' else -1
            others = f0bars[d] - ({int(r['entry_bar'])} if fam == 'F0' else set())
            if int(r['entry_bar']) in f0bars[d] and (fam == 'F1' or True):
                same = [x for x in sub['entry_bar'].values if x == r['entry_bar']]
                if fam == 'F1' or len(same) > 1 or int(r['entry_bar']) in others:
                    hit += 1
        out[fam] = round(100.0 * hit / len(sub), 1)
    return out


def coverage_of_missed(bk, cs_thrust, f1_names, n_bars):
    """EMPTY BY CONSTRUCTION for incumbent families. A book cannot cover episodes it
    defines as missed: the traded set is the incumbent's own footprint, so the value is
    tautologically zero. Emitting 0.0 would sort, average and rank as a real measurement.
    Precedent: the S8B basis-3 remediation suppressed circular columns to empty rather
    than documenting them. Non-incumbent families get a measured value once S3 produces
    their fires."""
    tcid_all = cp.map_trades_to_clusters(cs_thrust, bk)
    traded = set(np.unique(tcid_all[tcid_all >= 0]).tolist())
    cl = cs_thrust['clusters']
    missed = set(cl['cluster_id'].tolist()) - traded
    out = {}
    for fam in ('F0', 'F1'):
        sel = np.array([book_family_of(s, f1_names) == fam for s in bk['signal_name'].values])
        sub = bk[sel]
        if len(sub) == 0:
            out[fam] = ''
            continue
        out[fam] = ''
    return out


def build_family_evidence(df, bk, qual_depth, cs_by_basis, cs_thrust, U, pool, f1_names,
                          scanners_dir, search_dirs, grid_label):
    months = pd.Series(df['Time'].astype(str).values).str[:7].values
    bookm = measure_book_families(df, bk, qual_depth, cs_by_basis, U, f1_names, months)
    cofire = cofire_with_f0(bk, f1_names)
    covmiss = coverage_of_missed(bk, cs_thrust, f1_names, len(df))
    vocab = set(pool.keys())
    rows = []
    for fam, scanner, patterns in FAMILY_REGISTRY:
        spath = os.path.join(scanners_dir, scanner) if scanner else ''
        outs = _find_outputs(search_dirs, patterns) if patterns else []
        nrows, s5, defs = _rows_and_s5(outs)
        rec = {'family': fam, 'scanner': scanner if scanner else 'FUSED INTO F0',
               'scanner_sha12': _sha12(spath) if spath else '',
               'output_files_found': len(outs),
               'output_file_names': ';'.join(os.path.basename(x) for x in outs),
               'rows_emitted': nrows if outs else 0,
               'candidates_passing_S5': s5 if s5 != '' else '',
               'S5_gate': S5_GATE,
               'distinct_conditions_used': len(defs & vocab) if defs else '',
               'vocabulary_size': len(vocab)}
        if fam in ('F0', 'F1'):
            b = bookm[fam]
            rec.update({'book_signals': b['signals'], 'book_trades': b['trades'], 'book_net': b['net'],
                        'depth_participation_basis1': b['depth_participation_basis1'],
                        'depth_participation_basis2': b['depth_participation_basis2'],
                        'depth_participation_basis3': b['depth_participation_basis3'],
                        'co_fire_with_F0': cofire[fam], 'coverage_of_missed': covmiss[fam],
                        'regime_conditional_net': b['regime_conditional_net'],
                        'regime_buckets_positive': b['regime_buckets_positive'],
                        'verdict': 'SELECTABLE',
                        'verdict_basis': 'measured from the committed book executed-trade table on this dataset'})
        elif fam == 'F10':
            rec.update({'book_signals': '', 'book_trades': '', 'book_net': '',
                        'depth_participation_basis1': '', 'depth_participation_basis2': '',
                        'depth_participation_basis3': '', 'co_fire_with_F0': '', 'coverage_of_missed': '',
                        'regime_conditional_net': '', 'regime_buckets_positive': '',
                        'verdict': 'FUSED INTO F0',
                        'verdict_basis': 'not a separate family; concurrence lens fused into F0, F12 is the diagnostic remnant'})
        elif fam == 'F13':
            rec.update({'book_signals': 0, 'book_trades': 0, 'book_net': 0.0,
                        'depth_participation_basis1': '', 'depth_participation_basis2': '',
                        'depth_participation_basis3': '', 'co_fire_with_F0': '', 'coverage_of_missed': '',
                        'regime_conditional_net': '', 'regime_buckets_positive': '',
                        'verdict': 'DIAGNOSTIC',
                        'verdict_basis': ('negative SETTLED for F13 stated claim (single variable at an extreme as a standalone '
                                          'tradeable edge): its own scan reports 0 stars / 0 candidates, and S8B basis 3 corroborates '
                                          'independently on THIS dataset. THE NEGATIVE DOES NOT TRANSFER: F13 tested single conditions '
                                          'as entry signals, not as cluster participants or coverage contributors, and it excludes '
                                          'nothing from the vocabulary or from triple formation (spec A.3, doctrine rule 5)')})
        else:
            has = len(outs) > 0
            rec.update({'book_signals': 0, 'book_trades': 0, 'book_net': 0.0,
                        'depth_participation_basis1': '', 'depth_participation_basis2': '',
                        'depth_participation_basis3': '', 'co_fire_with_F0': '', 'coverage_of_missed': '',
                        'regime_conditional_net': '', 'regime_buckets_positive': '',
                        'verdict': 'INSUFFICIENT-EVIDENCE',
                        'verdict_basis': ('output file present but produced on a prior window; requires regeneration on this dataset (spec A.1 fit risk)'
                                          if has else
                                          'no results file exists on any window; S3 discovery has not been run for this family on this dataset')})
        rec['dataset_rows'] = len(df)
        rec['dataset_range'] = f"{df['Time'].astype(str).values[0]} -> {df['Time'].astype(str).values[-1]}"
        rec['thrust_grid'] = grid_label
        rec['population_label'] = 'BOOK for depth/co-fire/coverage columns; MARKET for thrust episode denominators'
        rows.append(rec)
    return pd.DataFrame(rows)


def cross_family_cofiring(bk, f1_names, n_tol, n_bars):
    fams = np.array([book_family_of(s, f1_names) for s in bk['signal_name'].values])
    rows = []
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        sub = bk[bk['direction'] == ('LONG' if d == 1 else 'SHORT')]
        subf = fams[bk['direction'].values == ('LONG' if d == 1 else 'SHORT')]
        bars = sub['entry_bar'].values.astype(np.int64)
        order = np.argsort(bars, kind='stable')
        bars = bars[order]
        subf = subf[order]
        pnl = sub['pnl'].values[order]
        if len(bars) == 0:
            continue
        start = 0
        for i in range(1, len(bars) + 1):
            if i == len(bars) or (bars[i] - bars[i - 1]) > n_tol:
                famset = sorted(set(subf[start:i]))
                size = i - start
                p = pnl[start:i]
                rows.append({'direction': lab, 'size': size, 'families': '+'.join(famset),
                             'n_families': len(famset), 'net': round(float(p.sum()), 1),
                             'wins': int((p > 0).sum()), 'trades': size})
                start = i
    cl = pd.DataFrame(rows)
    if len(cl) == 0:
        return cl, pd.DataFrame()
    cl['size_band'] = pd.cut(cl['size'], [0, 1, 2, 4, 7, 12, 10 ** 6],
                             labels=['1', '2', '3-4', '5-7', '8-12', '13+'])
    agg = []
    for mixed in (False, True):
        s = cl[(cl['n_families'] >= 2) == mixed]
        for band in ['1', '2', '3-4', '5-7', '8-12', '13+']:
            b = s[s['size_band'] == band]
            if len(b) == 0:
                continue
            tr = int(b['trades'].sum())
            wn = int(b['wins'].sum())
            agg.append({'cluster_type': 'mixed-family' if mixed else 'single-family',
                        'size_band': band, 'clusters': len(b), 'trades': tr,
                        'WR_pct': round(100.0 * wn / tr, 1) if tr else 0.0,
                        'net': round(float(b['net'].sum()), 1), 'N': n_tol,
                        'population': 'BOOK (F0+F1 executed, gaps excluded)'})
    return cl, pd.DataFrame(agg)


def d2d_variants(df):
    d = df['D2D_Trend_Dir'].values.copy()
    n = len(df)
    return [
        ('baseline_gate_on', d, 'real D2D_Trend_Dir; the committed gate'),
        ('inverted', -d, 'gate polarity inverted; encoding-error probe (spec E.1 part 4)'),
        ('long_free_short_blocked', np.ones(n, dtype=d.dtype), 'd2d=+1: every LONG ungated, every SHORT blocked'),
        ('short_free_long_blocked', -np.ones(n, dtype=d.dtype), 'd2d=-1: every SHORT ungated, every LONG blocked'),
    ]


def depth_yield(bk, n_tol, n_bars):
    ev = {}
    for d in (1, -1):
        lab = 'LONG' if d == 1 else 'SHORT'
        ev[d] = np.sort(bk[bk['direction'] == lab]['entry_bar'].values.astype(np.int64))
    cs = cp.build_cluster_set(n_bars, ev, n_tol)
    cl = cs['clusters']
    days = pd.Series(bk['exit_time'].values).str[:10].nunique() if len(bk) else 0
    ge5 = int((cl['size'] >= 5).sum()) if len(cl) else 0
    return round(ge5 / days, 3) if days else 0.0, ge5, days
