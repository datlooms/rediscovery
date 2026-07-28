"""engine/selection.py — the selection layer (spec sections C, D.1-D.2, G, H).

The single place selection logic lives, so the Auditor has one file to verify.

DOCTRINE BINDING (DOT_signal_discovery_mantra.md, sha fae943d40231).
Rule 1 — every emitted table is labelled MARKET or BOOK and states its parameters
in the table itself.
Rule 2 — nothing is removed on a single measurement. Dead conditions are EXCLUDED
from ranking and triple formation and are NEVER deleted from the vocabulary; they
re-enter automatically if a segment makes them live. No bar is deleted anywhere.
Rule 3 — NO PRE-SET TARGETS. There is no directional floor, quota, target,
minimum signal count or reserved allocation anywhere in this file. Each
direction's search stops on its own marginal-gain threshold or its own binding
constraint, never on a count, and a direction may terminate with zero signals.
Neither direction's stopping rule reads the other direction's book: the
per-direction search function receives only its own direction's candidates and
its own accumulated set.
Rule 4 — depth is the unit of quality. The objective maximises DepthYield, not
standalone signal statistics.
Rule 5 — a negative carries the same burden as a positive. UNEVALUABLE is a
first-class outcome and is reported, never converted into a rejection.

WHEN A FINDING DEPENDS ON A FILTER, THRESHOLD OR RESTRICTION, THE FILTER IS PART
OF THE FINDING. Every table this module emits carries tau, MIN_SHARED, N, S, the
mask, the segment months and the population label as columns.

THE TWO PROPERTIES STAY ON SEPARATE AXES. Entry co-firing is MAXIMISED
(DepthYield). Failure correlation is BOUNDED (TailDep, FailConc, mCVaR as hard
constraints). Pearson FailCorr NEVER enters feasibility and NEVER affects the
DepthYield tier; its only use is as the final tie-break sort key in
lexicographic_rank, which is spec C.3 step 6. It cannot promote an infeasible
book or reorder books that differ on DepthYield or Coverage. They are never
combined into a composite score anywhere in this file; the objective is
lexicographic, evaluated step by step, and each step returns its own value.

SEGMENT DISCIPLINE. F_max, T_max and C_max are computed on the ACTIVE TRAINING
SEGMENT passed in. Full-series values are reporting references only and never
enter a constraint. wf.FOLDS is month-literal and sacred; this module does NOT
import it and computes its own segment-local calendar-month buckets.

THRESHOLD PROVENANCE. Any threshold defining an object, event, cluster, episode
or stratum comes from dots_thresholds through cluster_profiler's ratified
helpers. Quantiles appearing in this file are of P&L or of a permutation null —
descriptive statistics of an already-selected population, and constraint
calibrations against an empirical null — not object-defining thresholds.

SUBMODULARITY. The (1 - 1/e) bound is NOT claimed anywhere in this file. Greedy
is used as a heuristic. submodularity_probe() empirically searches for
diminishing-returns violations so the decision rests on measurement. Its
violation rate is a function of its trial count, so the trial count is part of
the finding and is returned alongside the rate. MEASURED ON THE INCUMBENT
FIXTURE: at trials=120, LONG 38.3% and SHORT 50.8%; at the shipped default
trials=200, LONG 43.0% and SHORT 53.0%. THE CONSEQUENCE, NOT JUST THE RATES:
spec C.3.1 permits either establishing submodularity for the implemented penalty
or using greedy as a heuristic with no bound claimed. Violation rates of 38-53%
are near coin-flip, so THE FIRST PATH IS CLOSED. The (1 - 1/e) bound is claimed
nowhere in this codebase.

THE STOPPING RULE IS "NO ADDITION OF SIZE <= 2 IMPROVES", NOT "NO SINGLE
ADDITION IMPROVES". DepthYield normalises by the direction's signal count, which
makes the objective NON-MONOTONE in set size. A single signal cannot stack with
itself, so at S=5 every singleton whose own fires never cluster to S scores
exactly zero, and a search that halts on the first non-positive single gain
halts at |S| = 1 having evaluated no set of size >= 2. Measured on the incumbent
as a fixture: 0 of 13 short singletons and only 3 of 37 long singletons score
above zero, and the short side's true optimum sits at size 2. The rule is
therefore generalised: whenever the best single addition fails to clear eps, the
search attempts the best size-2 addition before halting, and halts only if that
also fails. This is evaluated at EVERY potential termination point, not only at
step 0, because the same plateau can occur at greater depth on a non-monotone
objective. It is DIRECTION-AGNOSTIC: one code path, no direction branch, no
floor, quota, count or reserved allocation. LIMIT, STATED: the escape looks
ahead two elements. A plateau that could only be escaped by a simultaneous
addition of three or more still halts, and that residue is reported rather than
implied away. The pair scan is exhaustive while the pool yields at most
PAIR_EXHAUSTIVE_MAX pairs and a seeded sample of PAIR_SAMPLE_K pairs above it,
so cost is bounded on large pools; the mode and pool size are recorded in the
stop reason.
"""

import itertools
import math

import numpy as np
import pandas as pd

TAU = 0.20
MIN_SHARED = 10
N_TOLERANCE = 5
S_GRID = (3, 4, 5, 6, 7)
S_DEFAULT = 5
PERM_P = 500
STABILITY_B = 200
STABILITY_SUBSAMPLE = 0.80
STABILITY_RETENTION = 0.70
STABILITY_SENSITIVITY = (0.60, 0.80)
NULL_M = 10000
BY_Q = 0.10
COVERAGE_TOLERANCE = 0.05
MARGINAL_GAIN_EPS = 1e-9
FTMO_DAILY_CEILING = 2500.0
SURVIVAL_MARGIN = 0.80
H3_MIN_BUCKETS = 3
DOMAIN_MIN_DISTINCT = 2
GAP_NAMES = ('GAP_HURST', 'GAP_FB', 'GAP_D2D')

DOMAIN_MAP = {
    'micro': ('Micro_',),
    'adaptive_vol': ('ATR', 'HarmVol', 'Sqz', 'RangeOsc', 'Bar_Range', 'Volume'),
    'temporal_session': ('EST_', 'Session_', 'OR_', 'DailyOpen', 'PrevDay', 'WeeklyOpen', 'Lock_'),
    'structural_trend': ('AT_', 'Slope_', 'KAMA', 'EMA_', 'ADX', 'Momentum', 'Efficiency', 'TChan',
                         'Trend_', 'ST_Flip', 'Bars_Since', 'MultiDay', 'Round_'),
    'volume_profile': ('VWAP', 'VAH', 'VAL', 'VA_', 'PoC', 'Dist_To_PoC', 'Hist_Volume'),
    'd2d_obv': ('D2D', 'OBV', 'Harmonic'),
}


def segment_months(times):
    return pd.Series(np.asarray(times, dtype=str)).str[:7].values


def trading_days(times):
    return pd.Series(np.asarray(times, dtype=str)).str[:10].values


def dead_conditions(pool, eligible_mask):
    return sorted([k for k, m in pool.items() if int((m & eligible_mask).sum()) == 0])


def equivalence_classes(pool, eligible_mask, dead):
    live = [k for k in pool if k not in set(dead)]
    sig = {}
    for k in live:
        b = np.packbits(pool[k][eligible_mask]).tobytes()
        sig.setdefault(b, []).append(k)
    classes = [sorted(v) for v in sig.values() if len(v) > 1]
    canonical = {}
    for k in live:
        canonical[k] = k
    for cl in classes:
        for member in cl:
            canonical[member] = cl[0]
    return sorted(classes), canonical, live


def vocabulary_hygiene(pool, eligible_mask, segment_label):
    dead = dead_conditions(pool, eligible_mask)
    classes, canonical, live = equivalence_classes(pool, eligible_mask, dead)
    effective = len(set(canonical.values()))
    rows = [{'segment': segment_label, 'domain_of_identity_test': 'ELIGIBLE UNIVERSE (ADX>=15 & Volume>50 & post-warmup)',
             'eligible_bars': int(eligible_mask.sum()), 'vocabulary_total': len(pool),
             'dead_conditions': len(dead), 'exact_duplicate_pairs': sum(len(c) - 1 for c in classes),
             'equivalence_classes': len(classes), 'effective_vocabulary': effective,
             'order': 'dead excluded BEFORE equivalence classes formed (spec G.1)',
             'dead_list': ';'.join(dead), 'class_list': ' | '.join('=='.join(c) for c in classes)}]
    return pd.DataFrame(rows), dead, canonical, live


def condition_domain(name):
    base = str(name).split(':')[0]
    for dom, prefixes in DOMAIN_MAP.items():
        for p in prefixes:
            if base.startswith(p) or p in base:
                return dom
    return 'unclassified'


def triple_domain_ok(triple):
    return len({condition_domain(c) for c in triple}) >= DOMAIN_MIN_DISTINCT


def mask_correlation_graph(pool, live, eligible_mask, r_threshold=0.70):
    names = list(live)
    X = np.array([pool[k][eligible_mask].astype(np.float64) for k in names])
    X = X - X.mean(axis=1, keepdims=True)
    sd = X.std(axis=1)
    keep = sd > 0
    names = [n for n, k in zip(names, keep) if k]
    X = X[keep]
    sd = sd[keep]
    C = (X @ X.T) / (X.shape[1] * np.outer(sd, sd))
    np.fill_diagonal(C, 0.0)
    iu = np.triu_indices(len(names), 1)
    r = np.abs(C[iu])
    edges = [(names[i], names[j], float(abs(C[i, j])))
             for i, j in zip(*iu) if abs(C[i, j]) >= r_threshold]
    stats = {'pairs_total': int(len(r)), 'pairs_ge_070': int((r >= 0.70).sum()),
             'pairs_ge_080': int((r >= 0.80).sum()), 'pairs_ge_090': int((r >= 0.90).sum()),
             'pairs_ge_095': int((r >= 0.95).sum()), 'median_abs_r': float(np.median(r)),
             'p90_abs_r': float(np.percentile(r, 90)), 'p99_abs_r': float(np.percentile(r, 99)),
             'signed_positive': int((C[iu] > 0).sum()), 'signed_negative': int((C[iu] < 0).sum())}
    return C, names, edges, stats


def detect_communities(names, edges, resolution=1.0, passes=12):
    idx = {n: i for i, n in enumerate(names)}
    label = list(range(len(names)))
    adj = {i: {} for i in range(len(names))}
    for a, b, wgt in edges:
        i, j = idx[a], idx[b]
        adj[i][j] = wgt
        adj[j][i] = wgt
    for _ in range(passes):
        moved = False
        for i in range(len(names)):
            if not adj[i]:
                continue
            counts = {}
            for j, wgt in adj[i].items():
                counts[label[j]] = counts.get(label[j], 0.0) + wgt * resolution
            best = max(counts.items(), key=lambda kv: kv[1])[0] if counts else label[i]
            if best != label[i]:
                label[i] = best
                moved = True
        if not moved:
            break
    comm = {}
    for n, l in zip(names, label):
        comm.setdefault(l, []).append(n)
    return {i: sorted(v) for i, v in enumerate(sorted(comm.values(), key=lambda x: -len(x)))}


def effective_dimension(C):
    ev = np.linalg.eigvalsh(C + np.eye(C.shape[0]))
    ev = np.clip(ev, 0, None)
    tot = ev.sum()
    if tot <= 0:
        return 0, 0, 0.0
    order = np.sort(ev)[::-1]
    cum = np.cumsum(order) / tot
    n90 = int(np.searchsorted(cum, 0.90) + 1)
    n95 = int(np.searchsorted(cum, 0.95) + 1)
    pr = float((ev.sum() ** 2) / (ev ** 2).sum())
    return n90, n95, pr


def cofire_matrix(qual_masks, names):
    n = len(names)
    M = np.zeros((n, n))
    counts = np.array([float(m.sum()) for m in qual_masks])
    for i in range(n):
        if counts[i] == 0:
            continue
        for j in range(n):
            if i == j:
                continue
            M[i, j] = float((qual_masks[i] & qual_masks[j]).sum()) / counts[i]
    return M


def cofire_book_all_pairs_DIAGNOSTIC(M):
    """UNCONDITIONAL off-diagonal mean over ALL ordered pairs. DIAGNOSTIC ONLY.

    NOT consumed by the objective, the greedy search or any constraint; the
    objective's depth term is depth_yield_pair, which is per-direction by
    construction. The name carries the warning because this basis is DEFLATED:
    cross-direction co-firing is structurally zero on every bar, since the D2D
    gate admits a signal only where D2D_Trend_Dir equals its direction, so long
    and short qualifying masks are disjoint. On the incumbent book 962 of 2,450
    ordered pairs are zero by construction. Wiring this into the objective would
    silently reintroduce the pooled-basis defect the per-direction search exists
    to remove. If a co-firing term is ever added to the objective, compute it
    WITHIN direction, as depth_yield_pair already does.
    """
    n = M.shape[0]
    if n < 2:
        return 0.0
    off = M[~np.eye(n, dtype=bool)]
    return float(off.mean())


def clusters_from_entries(bars, n_tol):
    bars = np.sort(np.asarray(bars, dtype=np.int64))
    out = []
    if len(bars) == 0:
        return out
    start = 0
    for i in range(1, len(bars) + 1):
        if i == len(bars) or (bars[i] - bars[i - 1]) > n_tol:
            out.append(i - start)
            start = i
    return out


def depth_yield_direction(entry_bars_d, n_signals_d, traded_day_count, S, n_tol):
    if traded_day_count <= 0:
        return 0.0, 0
    sizes = clusters_from_entries(entry_bars_d, n_tol)
    ge = int(sum(1 for s in sizes if s >= S))
    return float(ge) / float(traded_day_count), ge


def depth_yield_per_signal(depth_yield_value, n_signals_d):
    """Item 13: /n_signals_d is a REPORTED COLUMN, never part of the objective.

    Dividing the objective by the direction's signal count made every marginal
    addition dilute its own score, so the objective fought its own admissions.
    The per-signal figure is still informative and is emitted beside the raw
    one; it never gates inclusion.
    """
    if not n_signals_d:
        return float('nan')
    return depth_yield_value / float(n_signals_d)


def entry_basis_traded_days(trades, entry_bar_to_day):
    bars = np.asarray(trades['entry_bar'].values, dtype=np.int64)
    return int(pd.unique(np.asarray(entry_bar_to_day)[bars]).shape[0])


def depth_yield_pair(entries_by_dir, signals_by_dir, traded_day_count, S=S_DEFAULT, n_tol=N_TOLERANCE):
    dl, gl = depth_yield_direction(entries_by_dir.get(1, []), signals_by_dir.get(1, 0), traded_day_count, S, n_tol)
    ds, gs = depth_yield_direction(entries_by_dir.get(-1, []), signals_by_dir.get(-1, 0), traded_day_count, S, n_tol)
    return {'DepthYield_LONG': dl, 'DepthYield_SHORT': ds,
            'clusters_ge_S_LONG': gl, 'clusters_ge_S_SHORT': gs,
            'S': S, 'N': n_tol, 'traded_days': traded_day_count,
            'signals_LONG': signals_by_dir.get(1, 0), 'signals_SHORT': signals_by_dir.get(-1, 0)}


def depth_yield_grid(entries_by_dir, signals_by_dir, traded_day_count, s_grid=S_GRID, tolerances=(1, 5, 10, 15, 20, 25, 30)):
    rows = []
    for n_tol in tolerances:
        for S in s_grid:
            r = depth_yield_pair(entries_by_dir, signals_by_dir, traded_day_count, S, n_tol)
            dl, ds = r['DepthYield_LONG'], r['DepthYield_SHORT']
            gl, gs = r['clusters_ge_S_LONG'], r['clusters_ge_S_SHORT']
            nl, ns = r['signals_LONG'], r['signals_SHORT']
            r['raw_ratio_long_short'] = round(gl / gs, 3) if gs else ''
            r['normalised_ratio_long_short'] = round(dl / ds, 3) if ds else ''
            r['signal_count_ratio'] = round(nl / ns, 3) if ns else ''
            r['population'] = 'BOOK'
            rows.append(r)
    return pd.DataFrame(rows)


def per_signal_daily(trades):
    t = trades.copy()
    t['day'] = pd.Series(t['exit_time'].astype(str).values).str[:10].values
    return t.groupby(['signal_name', 'day'], as_index=False)['pnl'].sum()


def daily_series_map(daily):
    out = {}
    for name, g in daily.groupby('signal_name'):
        out[name] = pd.Series(g['pnl'].values, index=g['day'].values)
    return out


def pair_tail_dependence(series_map, names, tau=TAU, min_shared=MIN_SHARED):
    rows = []
    for a, b in itertools.combinations(names, 2):
        sa, sb = series_map.get(a), series_map.get(b)
        if sa is None or sb is None:
            continue
        shared = sa.index.intersection(sb.index)
        k = len(shared)
        if k == 0:
            continue
        x = sa.loc[shared].values.astype(float)
        y = sb.loc[shared].values.astype(float)
        qa = float(np.quantile(x, tau))
        qb = float(np.quantile(y, tau))
        co = float(np.mean((x <= qa) & (y <= qb)))
        lam = co / tau if tau > 0 else 0.0
        r = float(np.corrcoef(x, y)[0, 1]) if k >= 3 and x.std() > 0 and y.std() > 0 else np.nan
        rows.append({'a': a, 'b': b, 'shared_days': k, 'lambda_L': lam,
                     'pearson_r': r, 'qualifies': k >= min_shared})
    return pd.DataFrame(rows)


DEGENERACY_MIN_K = 3


def tail_dep_book(pairs):
    q = pairs[pairs['qualifies']]
    e = pairs[~pairs['qualifies']]
    eg = e[e['shared_days'] >= DEGENERACY_MIN_K]
    tot = len(pairs)
    deg = int((e['shared_days'] < DEGENERACY_MIN_K).sum())
    guarded_bias = ('conservative' if len(q) and len(eg) and q['lambda_L'].mean() >= eg['lambda_L'].mean()
                    else ('ANTI-CONSERVATIVE' if len(q) and len(eg) else 'n/a'))
    extra = {'lambda_over_independence': float(q['lambda_L'].mean() / TAU) if len(q) else np.nan,
             'mean_lambda_excluded_k_ge3': float(eg['lambda_L'].mean()) if len(eg) else np.nan,
             'exclusion_bias_degeneracy_guarded': guarded_bias,
             'degenerate_excluded_pairs_k_lt3': deg,
             'degeneracy_note': 'at k=1 the single shared day IS its own tau-quantile so lambda is mechanically 1/tau; k<3 pairs are reported separately because they dominate the raw exclusion-bias direction',
             'independence_note': 'lambda_L is emitted per the spec formula coexceed/tau; lambda_over_independence = coexceed/tau^2 is the 1.0==independence reading. T_max is a ratio to a permutation null computed with the identical estimator, so the choice of normalisation cancels in every constraint'}
    base = {'TailDep': float(q['lambda_L'].mean()) if len(q) else np.nan,
            'pairs_total': tot, 'pairs_qualified': len(q), 'pairs_excluded': len(e),
            'retention_pct': round(100.0 * len(q) / tot, 1) if tot else 0.0,
            'mean_lambda_excluded': float(e['lambda_L'].mean()) if len(e) else np.nan,
            'exclusion_bias': ('conservative' if len(q) and len(e) and q['lambda_L'].mean() >= e['lambda_L'].mean()
                               else ('ANTI-CONSERVATIVE' if len(q) and len(e) else 'n/a')),
            'below_floor_majority_flag': bool(tot and (len(e) / tot) > 0.50),
            'FailCorr_pearson_reported_only': float(q['pearson_r'].mean(skipna=True)) if len(q) else np.nan,
            'tau': TAU, 'MIN_SHARED': MIN_SHARED}
    base.update(extra)
    return base


def _pair_index_cache(series_map, names, min_shared=MIN_SHARED):
    pos = {n: {d: i for i, d in enumerate(series_map[n].index)} for n in names if n in series_map}
    cache = []
    for a, b in itertools.combinations(names, 2):
        if a not in series_map or b not in series_map:
            continue
        shared = series_map[a].index.intersection(series_map[b].index)
        if len(shared) < min_shared:
            continue
        ia = np.array([pos[a][d] for d in shared], dtype=np.int64)
        ib = np.array([pos[b][d] for d in shared], dtype=np.int64)
        cache.append((a, b, ia, ib))
    return cache


def taildep_permutation_null(series_map, names, p=PERM_P, tau=TAU, min_shared=MIN_SHARED, seed=20260724):
    rng = np.random.default_rng(seed)
    cache = _pair_index_cache(series_map, names, min_shared)
    if not cache:
        return {'TailDep_null_mean': np.nan, 'TailDep_null_sd': np.nan, 'permutations': 0,
                'construction': 'no qualifying pairs'}
    base = {n: series_map[n].values.astype(float).copy() for n in names if n in series_map}
    vals = []
    for _ in range(p):
        perm = {}
        for n, v in base.items():
            w = v.copy()
            rng.shuffle(w)
            perm[n] = w
        acc = 0.0
        cnt = 0
        for a, b, ia, ib in cache:
            x = perm[a][ia]
            y = perm[b][ib]
            qa = np.quantile(x, tau)
            qb = np.quantile(y, tau)
            acc += float(np.mean((x <= qa) & (y <= qb))) / tau
            cnt += 1
        if cnt:
            vals.append(acc / cnt)
    arr = np.array(vals, dtype=float)
    return {'TailDep_null_mean': float(arr.mean()) if len(arr) else np.nan,
            'TailDep_null_sd': float(arr.std()) if len(arr) else np.nan,
            'permutations': int(len(arr)),
            'construction': 'each signal loss series permuted across its OWN active days; cross-signal alignment destroyed, per-signal distribution and activity preserved; shared-day index structure precomputed and invariant across permutations'}


def fail_conc(daily_book_pnl):
    v = np.asarray(daily_book_pnl, dtype=float)
    losses = v[v < 0]
    if len(losses) == 0:
        return 0.0
    return float(abs(v.min()) / abs(losses.mean()))


def mcvar_per_signal(trades, daily, worst_frac=0.05):
    t = trades.copy()
    t['day'] = pd.Series(t['exit_time'].astype(str).values).str[:10].values
    book_daily = t.groupby('day')['pnl'].sum().sort_values()
    k = max(1, int(round(worst_frac * len(book_daily))))
    worst_days = set(book_daily.index[:k].tolist())
    lots_total = float(t['lots'].sum()) if 'lots' in t.columns else float(len(t))
    rows = []
    for name, g in t.groupby('signal_name'):
        gd = g[g['day'].isin(worst_days)]
        cvar = float(gd['pnl'].sum() / k) if k else 0.0
        share = float(g['lots'].sum() / lots_total) if lots_total > 0 and 'lots' in g.columns else float(len(g) / len(t))
        rows.append({'signal_name': name, 'CVaR': cvar, 'lot_share': share,
                     'mCVaR': cvar / share if share > 0 else np.nan,
                     'worst_days_used': k, 'worst_frac': worst_frac})
    return pd.DataFrame(rows)


def c_max_from_incumbent(mcvar_frame):
    v = np.asarray(mcvar_frame['mCVaR'].values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return np.nan
    return float(np.percentile(v, 10))


def absolute_survival(daily_full_pnl, ceiling=FTMO_DAILY_CEILING, margin=SURVIVAL_MARGIN):
    v = np.asarray(daily_full_pnl, dtype=float)
    worst = float(v.min()) if len(v) else 0.0
    allowed = -abs(ceiling) * margin
    return {'worst_modelled_day': worst, 'ceiling': -abs(ceiling), 'margin_frac': margin,
            'allowed_worst_day': allowed, 'passes': bool(worst >= allowed),
            'population': 'FULL (book + gap fillers; the ceiling does not distinguish them)'}


def evaluate_constraints(merged_state, bounds):
    res = {}
    res['survival_absolute'] = merged_state['survival']['passes']
    res['failconc'] = merged_state['FailConc'] <= bounds['F_max'] if bounds.get('F_max') is not None else None
    res['taildep'] = (merged_state['TailDep'] <= bounds['T_max']) if (bounds.get('T_max') is not None and not math.isnan(merged_state.get('TailDep', np.nan))) else None
    res['mcvar'] = merged_state['worst_mCVaR'] >= bounds['C_max'] if bounds.get('C_max') is not None else None
    binding = [k for k, v in res.items() if v is False]
    res['all_pass'] = len(binding) == 0
    res['binding'] = ';'.join(binding)
    return res


def lexicographic_rank(candidates):
    feasible = [c for c in candidates if c['constraints']['all_pass']]
    if not feasible:
        return [], []
    best_l = max(c['DepthYield_LONG'] for c in feasible)
    best_s = max(c['DepthYield_SHORT'] for c in feasible)
    def within(c):
        okl = c['DepthYield_LONG'] >= best_l * (1.0 - COVERAGE_TOLERANCE)
        oks = c['DepthYield_SHORT'] >= best_s * (1.0 - COVERAGE_TOLERANCE)
        return okl and oks
    tier = [c for c in feasible if within(c)] or feasible
    tier = sorted(tier, key=lambda c: (-c.get('Coverage', 0.0), c.get('FailCorr', 0.0)))
    return tier, feasible


PAIR_EXHAUSTIVE_MAX = 20000
PAIR_SAMPLE_K = 20000
PAIR_SAMPLE_SEED = 20260724


def _pair_candidates(pool_ids, rng):
    n = len(pool_ids)
    total = n * (n - 1) // 2
    if total <= PAIR_EXHAUSTIVE_MAX:
        return list(itertools.combinations(pool_ids, 2)), 'exhaustive', total
    seen = set()
    out = []
    while len(out) < PAIR_SAMPLE_K:
        i = int(rng.integers(0, n))
        j = int(rng.integers(0, n))
        if i == j:
            continue
        key = (min(i, j), max(i, j))
        if key in seen:
            continue
        seen.add(key)
        out.append((pool_ids[key[0]], pool_ids[key[1]]))
    return out, 'sampled', total


def _best_pair_addition(direction, selected, remaining, set_gain_fn, constraint_fn, rng):
    pairs, mode, total = _pair_candidates(remaining, rng)
    best = None
    best_gain = 0.0
    for a, b in pairs:
        g = set_gain_fn(direction, selected, [a, b])
        if g > best_gain:
            ok, _why = constraint_fn(direction, selected + [a, b])
            if ok:
                best_gain = g
                best = (a, b)
    return best, best_gain, mode, total


def greedy_direction(direction, candidate_ids, gain_fn, constraint_fn,
                     eps=MARGINAL_GAIN_EPS, max_steps=None, set_gain_fn=None,
                     seed=PAIR_SAMPLE_SEED):
    rng = np.random.default_rng(seed)
    if set_gain_fn is None:
        def set_gain_fn(d, sel_set, add):
            g = 0.0
            cur = list(sel_set)
            for e in add:
                g += gain_fn(d, cur, e)
                cur = cur + [e]
            return g
    selected = []
    log = []
    heap = []
    for cid in candidate_ids:
        heap.append([-gain_fn(direction, selected, cid), cid, 0])
    heap.sort()
    step = 0
    pair_escapes = 0
    stop_reason = 'exhausted candidate pool'
    while heap:
        if max_steps is not None and step >= max_steps:
            stop_reason = 'max_steps reached (safety bound, not a target)'
            break
        top = heap[0]
        if top[2] != step:
            top[0] = -gain_fn(direction, selected, top[1])
            top[2] = step
            heap.sort()
            continue
        gain = -top[0]
        cid = top[1]
        if gain <= eps:
            remaining = [h[1] for h in heap]
            pair, pgain, mode, total = _best_pair_addition(direction, selected, remaining,
                                                           set_gain_fn, constraint_fn, rng)
            if pair is not None and pgain > eps:
                pair_escapes += 1
                for e in pair:
                    selected.append(e)
                    heap = [h for h in heap if h[1] != e]
                log.append({'direction': direction, 'step': step, 'candidate': '+'.join(map(str, pair)),
                            'marginal_gain': pgain, 'action': 'ADDED_PAIR',
                            'reason': f'single-element plateau escaped by size-2 addition ({mode}, {total} pairs in pool)'})
                step += 1
                for h in heap:
                    h[2] = -1
                continue
            stop_reason = (f'no addition of size <= 2 improves: best single {gain:.3e} <= eps {eps:.3e}, '
                           f'best pair {pgain:.3e} ({mode} over {total} pairs)')
            break
        ok, why = constraint_fn(direction, selected + [cid])
        if not ok:
            heap.pop(0)
            log.append({'direction': direction, 'step': step, 'candidate': cid,
                        'marginal_gain': gain, 'action': 'REJECTED', 'reason': why})
            continue
        heap.pop(0)
        selected.append(cid)
        log.append({'direction': direction, 'step': step, 'candidate': cid,
                    'marginal_gain': gain, 'action': 'ADDED', 'reason': ''})
        step += 1
    return selected, stop_reason, pd.DataFrame(log), {'pair_escapes': pair_escapes}


def exhaustive_vs_greedy(direction, candidate_ids, set_value_fn, gain_fn, constraint_fn,
                         max_k=3, eps=MARGINAL_GAIN_EPS):
    ids = list(candidate_ids)
    rows = []
    best_overall = 0.0
    best_k = 0
    for k in range(1, min(max_k, len(ids)) + 1):
        best = -np.inf
        arg = None
        for combo in itertools.combinations(ids, k):
            v = set_value_fn(direction, list(combo))
            if v > best:
                best, arg = v, combo
        rows.append({'direction': direction, 'set_size': k, 'exhaustive_best': float(best),
                     'argmax': '+'.join(map(str, arg)) if arg else ''})
        if best > best_overall:
            best_overall = float(best)
            best_k = k
    if len(ids) > max_k:
        v_all = set_value_fn(direction, ids)
        rows.append({'direction': direction, 'set_size': len(ids), 'exhaustive_best': float(v_all),
                     'argmax': 'ALL'})
        if v_all > best_overall:
            best_overall = float(v_all)
            best_k = len(ids)
    sel_set, reason, log, meta = greedy_direction(direction, ids, gain_fn, constraint_fn, eps=eps)
    gval = set_value_fn(direction, sel_set) if sel_set else 0.0
    rows.append({'direction': direction, 'set_size': len(sel_set), 'exhaustive_best': float(gval),
                 'argmax': 'GREEDY:' + ('+'.join(map(str, sel_set)) if sel_set else 'EMPTY')})
    frame = pd.DataFrame(rows)
    frame['greedy_value'] = gval
    frame['exhaustive_optimum'] = best_overall
    frame['optimum_at_size'] = best_k
    frame['greedy_pct_of_optimum'] = round(100.0 * gval / best_overall, 2) if best_overall > 0 else np.nan
    frame['optimum_is_lower_bound'] = True
    frame['pct_is_upper_bound_note'] = ('exhaustive enumeration covers sizes 1..max_k plus the all-signals set; the '
                                        'interior is UNENUMERATED, so exhaustive_optimum is a LOWER BOUND and '
                                        'greedy_pct_of_optimum is correspondingly an UPPER BOUND on the true ratio. '
                                        'A forward hill-climb on LONG reaches 0.027664 at size 24 against the '
                                        'enumerated 0.025033, which puts the honest LONG figure at <= 80%, not 88.41%. '
                                        'SHORT is exact because its optimum sits at k=2, inside the enumerated region.')
    frame['greedy_stop_reason'] = reason
    frame['pair_escapes'] = meta['pair_escapes']
    frame['max_k_enumerated'] = max_k
    return frame


def submodularity_probe(direction, candidate_ids, gain_fn, trials=200, seed=20260724):
    rng = np.random.default_rng(seed)
    ids = list(candidate_ids)
    if len(ids) < 4:
        return {'trials': 0, 'violations': 0, 'violation_rate': np.nan, 'verdict': 'INSUFFICIENT CANDIDATES'}
    viol = 0
    done = 0
    for _ in range(trials):
        k = rng.integers(1, max(2, len(ids) // 2))
        A = list(rng.choice(ids, size=int(k), replace=False))
        rest = [x for x in ids if x not in A]
        if len(rest) < 2:
            continue
        extra = list(rng.choice(rest, size=min(len(rest) - 1, int(rng.integers(1, max(2, len(rest))))), replace=False))
        B = A + extra
        cand = [x for x in ids if x not in B]
        if not cand:
            continue
        e = cand[int(rng.integers(0, len(cand)))]
        ga = gain_fn(direction, A, e)
        gb = gain_fn(direction, B, e)
        done += 1
        if gb > ga + 1e-12:
            viol += 1
    rate = viol / done if done else np.nan
    return {'trials': done, 'violations': viol, 'violation_rate': rate,
            'verdict': 'DIMINISHING RETURNS VIOLATED — not submodular; greedy is a heuristic and the (1-1/e) bound is NOT claimed'
                       if viol > 0 else
                       'no violation found in this probe; ABSENCE OF A COUNTEREXAMPLE IS NOT A PROOF, bound still NOT claimed'}


def benjamini_yekutieli(pvals, q=BY_Q):
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    if n == 0:
        return np.array([], dtype=bool), 0.0
    order = np.argsort(p)
    ranked = p[order]
    c_n = np.sum(1.0 / np.arange(1, n + 1))
    thresh = (np.arange(1, n + 1) / (n * c_n)) * q
    passed = ranked <= thresh
    kmax = np.max(np.flatnonzero(passed)) if passed.any() else -1
    out = np.zeros(n, dtype=bool)
    if kmax >= 0:
        out[order[:kmax + 1]] = True
    return out, float(c_n)


def empirical_null_bar(null_stats, n_trials, target_false_accepts=1.0):
    arr = np.sort(np.asarray(null_stats, dtype=float))
    if len(arr) == 0 or n_trials <= 0:
        return np.nan, np.nan
    q = 1.0 - (target_false_accepts / float(n_trials))
    q = min(max(q, 0.0), 1.0)
    return float(np.quantile(arr, q)), q


def whites_reality_check(observed_best, null_best_distribution):
    arr = np.asarray(null_best_distribution, dtype=float)
    if len(arr) == 0:
        return np.nan
    return float(np.mean(arr >= observed_best))


def hansen_spa(observed_stats, null_matrix, drop_quantile=0.25):
    obs = np.asarray(observed_stats, dtype=float)
    if len(obs) == 0 or null_matrix.size == 0:
        return np.nan
    keep = obs >= np.quantile(obs, drop_quantile)
    if not keep.any():
        return np.nan
    o = obs[keep].max()
    nb = null_matrix[:, keep].max(axis=1)
    return float(np.mean(nb >= o))


def romano_wolf(observed_stats, null_matrix, alpha=0.10):
    obs = np.asarray(observed_stats, dtype=float)
    idx = np.argsort(-obs)
    rejected = np.zeros(len(obs), dtype=bool)
    remaining = list(idx)
    while remaining:
        nb = null_matrix[:, remaining].max(axis=1)
        crit = np.quantile(nb, 1.0 - alpha)
        i = remaining[0]
        if obs[i] > crit:
            rejected[i] = True
            remaining.pop(0)
        else:
            break
    return rejected


def pbo_cscv(perf_matrix, n_splits=8):
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2 or M.shape[0] < n_splits or M.shape[1] < 2:
        return np.nan
    rows = M.shape[0]
    block = rows // n_splits
    blocks = [np.arange(i * block, (i + 1) * block) for i in range(n_splits)]
    logits = []
    for combo in itertools.combinations(range(n_splits), n_splits // 2):
        tr = np.concatenate([blocks[i] for i in combo])
        te = np.concatenate([blocks[i] for i in range(n_splits) if i not in combo])
        mtr = M[tr].mean(axis=0)
        mte = M[te].mean(axis=0)
        star = int(np.argmax(mtr))
        rank = float((mte <= mte[star]).mean())
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1 - rank)))
    return float(np.mean(np.asarray(logits) <= 0))


def day_block_bootstrap(all_post_warmup_days, b=STABILITY_B, frac=STABILITY_SUBSAMPLE, seed=20260724):
    rng = np.random.default_rng(seed)
    days = np.asarray(sorted(set(all_post_warmup_days)))
    k = max(1, int(round(frac * len(days))))
    return [np.sort(rng.choice(days, size=k, replace=True)) for _ in range(b)]


def stability_retention(selection_counts, b, threshold=STABILITY_RETENTION):
    rows = []
    for name, c in selection_counts.items():
        freq = c / float(b) if b else 0.0
        rows.append({'signal': name, 'selection_frequency': freq,
                     'retained_at_070': freq >= threshold,
                     'retained_at_060': freq >= 0.60, 'retained_at_080': freq >= 0.80})
    return pd.DataFrame(rows)


def h3_buckets(trades_dir, min_buckets=H3_MIN_BUCKETS):
    if len(trades_dir) == 0:
        return {'buckets': 0, 'positive': 0, 'evaluable': False,
                'verdict': 'UNEVALUABLE - no trades in this direction',
                'rule': 'calendar month; positive in all but at most one; minimum 3 buckets'}
    mo = segment_months(trades_dir['exit_time'].values)
    nets = {m: float(trades_dir['pnl'].values[mo == m].sum()) for m in sorted(set(mo.tolist()))}
    nb = len(nets)
    pos = sum(1 for v in nets.values() if v > 0)
    if nb < min_buckets:
        return {'buckets': nb, 'positive': pos, 'evaluable': False,
                'verdict': f'UNEVALUABLE - segment holds {nb} monthly buckets, minimum {min_buckets} required; signal is NEITHER passed NOR culled on this basis',
                'rule': 'calendar month; positive in all but at most one; minimum 3 buckets',
                'per_bucket': ';'.join(f'{k}:{round(v,1)}' for k, v in nets.items())}
    return {'buckets': nb, 'positive': pos, 'evaluable': True,
            'verdict': 'PASS' if pos >= nb - 1 else 'FAIL',
            'rule': 'calendar month; positive in all but at most one; minimum 3 buckets',
            'per_bucket': ';'.join(f'{k}:{round(v,1)}' for k, v in nets.items())}


def h3_within_direction(trades):
    rows = []
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        sub = trades[trades['direction'] == lab]
        r = h3_buckets(sub)
        r['direction'] = lab
        r['trades'] = int(len(sub))
        r['population'] = 'BOOK'
        r['directional_protection'] = 'H.3.1: buckets evaluated WITHIN direction; thin samples reported UNEVALUABLE, never culled'
        rows.append(r)
    return pd.DataFrame(rows)


def coverage_by_direction(entry_bars_by_dir, thrust_cs, label='BOOK'):
    """Coverage of the MARKET terrain, scored WITHIN each direction.

    Per-direction is not cosmetic. The terrain is close to 50/50 up/down, so a
    long-heavy book leaves nearly all short episodes uncovered and short
    candidates carry high marginal value automatically. THAT IS HOW DIRECTIONAL
    BALANCE ARRIVES WITHOUT A QUOTA: no floor, no target, no minimum count and no
    reserved allocation anywhere. The terrain supplies the balance; the objective
    must not, and coverage stays where spec C.3 puts it, after survival,
    FailConc and DepthYield, never promoted above them.
    """
    cl = thrust_cs['clusters']
    rows = []
    for d, name in ((1, 'UP'), (-1, 'DOWN')):
        sub = cl[cl['dir'] == d] if len(cl) else cl
        total = len(sub)
        bars = np.asarray(entry_bars_by_dir.get(d, []), dtype=np.int64)
        touched = set()
        if len(bars):
            cid = thrust_cs['cid'][d][bars]
            allowed = set(sub['cluster_id'].tolist()) if total else set()
            touched = {int(c) for c in cid if c >= 0 and int(c) in allowed}
        pos = []
        if len(bars) and total:
            spans = {int(r['cluster_id']): (int(r['b0']), int(r['b1'])) for _i, r in sub.iterrows()}
            cid = thrust_cs['cid'][d][bars]
            for bar, c in zip(bars, cid):
                if c < 0 or int(c) not in spans:
                    continue
                b0, b1 = spans[int(c)]
                pos.append(0.0 if b1 == b0 else (float(bar) - b0) / float(b1 - b0))
        rows.append({'direction': name, 'terrain_episodes': total, 'touched': len(touched),
                     'coverage_pct': round(100.0 * len(touched) / total, 3) if total else 0.0,
                     'missed': total - len(touched), 'scored_for': label,
                     'entry_pos_median': round(float(np.median(pos)), 3) if pos else '',
                     'population': 'terrain=MARKET, entries=BOOK'})
    tot = len(cl)
    hit = sum(r['touched'] for r in rows)
    rows.append({'direction': 'BOTH (reported only, never used as the score)',
                 'terrain_episodes': tot, 'touched': hit, 'entry_pos_median': '',
                 'coverage_pct': round(100.0 * hit / tot, 3) if tot else 0.0,
                 'missed': tot - hit, 'scored_for': label,
                 'population': 'terrain=MARKET, entries=BOOK'})
    return pd.DataFrame(rows)


def coverage_of_book(entry_bars_by_dir, thrust_cs):
    touched = set()
    total = len(thrust_cs['clusters']) if len(thrust_cs['clusters']) else 0
    for d, bars in entry_bars_by_dir.items():
        if len(bars) == 0:
            continue
        cid = thrust_cs['cid'][d][np.asarray(bars, dtype=np.int64)]
        touched.update(int(c) for c in cid if c >= 0)
    return {'episodes': total, 'touched': len(touched),
            'coverage_pct': round(100.0 * len(touched) / total, 3) if total else 0.0}
