"""engine/catalogue.py — items 5-12 and the APPENDIX C VALID predicate.

WHAT THIS IS. The measuring instrument. It emits one catalogue per family
holding EVERY signal the VALID predicate admits, with the measurements needed
to judge it. NOTHING HERE CHOOSES ANYTHING: no rank gates inclusion, no cap
truncates a family, no threshold nobody specified removes a row. UNEVALUABLE
rows stay in the catalogue with their statistics blank and a reason_code, so
"this family catalogues nothing" and "this family could not be measured" can
never look the same.

VALID is a MEASURABILITY-AND-SURVIVAL predicate, not a quality predicate.
There is no PF bar and no WR bar; those are columns. That is what stops the
catalogue being a chooser in disguise.

EVERY TABLE STATES ITS PARAMETERS AT THE POINT OF USE AND CARRIES A MARKET OR
BOOK LABEL. Terrain and reachable episodes are MARKET. Everything computed from
a signal's own trades is BOOK.

WHAT THE MATCHED NULL MATCHES, AND WHAT IT DOES NOT. Appendix A specifies three
things - the same post-hygiene vocabulary, fire-rate matching, and the identical
VALID predicate - and the null meets all three, plus the family's own direction
composition. It matches RARITY. It does NOT match TEMPORAL STRUCTURE: a null
conjunction fires same-bar, whereas F1's ordered pairs, F2's transitions and F6's
crossings are lagged constructions. Firing autocorrelation therefore differs for
those families, and with it the shape of the PF distribution the null produces.
This is a stated limitation of the null, not a departure from the specification,
and it bears most on the lagged families.

REACHABLE IS THE PRIMARY DENOMINATOR. Raw terrain counts episodes the book
could never have taken: the eligible mask and the D2D direction agreement are
deliberate, measured exclusions, so an episode failing them is not a miss. Both
denominators are emitted on every coverage column and both are named in the
header, because a coverage figure without its denominator is not a measurement.
"""

import math

import numpy as np
import pandas as pd

MIN_TRADES = 30
FTMO_DAILY_CEILING = 2500
MIN_ACTIVE_DAYS = 10
MIN_BUCKETS = 3
PINNED_CELL = (15, 0.85, 0.75)
REASON_INSUFFICIENT_TRADES = 'insufficient_trades'
REASON_PF_UNDEFINED = 'pf_undefined'
REASON_INSUFFICIENT_ACTIVE_DAYS = 'insufficient_active_days'
REASON_INSUFFICIENT_BUCKETS = 'insufficient_buckets_direction'
CATALOGUE_HEADER_PRICING = (
    'This catalogue contains N_F rows for this family. Reading it and selecting rows IS a search of '
    'size N_F. EXPECTED_ROWS_AT_OR_ABOVE_THIS_PF prices that search on every row. A row whose '
    'expected-count exceeds 1 is not evidence of an edge.')
CATALOGUE_HEADER_UNSCORED = (
    'ANY BOOK ASSEMBLED FROM THIS CATALOGUE IS UNSCORED until it has been run through score_book.py '
    '(item 16). The set properties that decide whether a book is survivable - TailDep, FailConc, '
    'mCVaR, absolute survival, union coverage - have no per-signal value and are not in this file.')


def signal_id(family, signal_def, direction):
    return f'{family}|{signal_def}|{direction}'


def _pf(pnl):
    p = np.asarray(pnl, dtype=float)
    if len(p) == 0:
        return 0.0, True
    loss = -p[p < 0].sum()
    if loss <= 0:
        return float('inf'), True
    return float(p[p > 0].sum() / loss), False


def _daily(trades):
    d = pd.Series(trades['exit_time'].astype(str).values).str[:10].values
    return pd.Series(trades['pnl'].values).groupby(d).sum()


def month_buckets(trades):
    m = pd.Series(trades['exit_time'].astype(str).values).str[:7].values
    out = {}
    for b in sorted(pd.unique(m).tolist()):
        out[b] = float(np.asarray(trades['pnl'].values)[m == b].sum())
    return out


def evaluate_valid(trades, bar_day=None):
    """APPENDIX C. Returns (verdict, reason_code, stats).

    V1 SUFFICIENCY   trades >= 30
    V2 SURVIVAL      worst_day >= -2500, signal's OWN trades, gap fillers excluded
    V3 MEASURABILITY at least one loss, and >= 10 distinct entry-basis days
    V4 REGIME        >= 3 segment-local monthly buckets within direction

    V2 is the only INVALID path. V1, V3 and V4 return UNEVALUABLE and the row
    still enters the catalogue with statistics blank.
    """
    n = int(len(trades))
    stats = {'trades': n}
    if n == 0:
        return 'UNEVALUABLE', REASON_INSUFFICIENT_TRADES, stats
    pnl = np.asarray(trades['pnl'].values, dtype=float)
    daily = _daily(trades)
    worst = float(daily.min())
    stats['worst_day_usd'] = round(worst, 2)
    if worst < -float(FTMO_DAILY_CEILING):
        return 'INVALID', 'survival_breach', stats
    if n < MIN_TRADES:
        return 'UNEVALUABLE', REASON_INSUFFICIENT_TRADES, stats
    pf, undefined = _pf(pnl)
    stats['agg_pf'] = pf
    stats['pf_undefined'] = bool(undefined)
    if undefined:
        return 'UNEVALUABLE', REASON_PF_UNDEFINED, stats
    if bar_day is not None:
        days = int(pd.unique(np.asarray(bar_day)[np.asarray(trades['entry_bar'].values,
                                                            dtype=np.int64)]).shape[0])
    else:
        days = int(len(daily))
    stats['active_days'] = days
    if days < MIN_ACTIVE_DAYS:
        return 'UNEVALUABLE', REASON_INSUFFICIENT_ACTIVE_DAYS, stats
    buckets = month_buckets(trades)
    stats['regime_total_buckets'] = len(buckets)
    stats['regime_positive_buckets'] = sum(1 for v in buckets.values() if v > 0)
    if len(buckets) < MIN_BUCKETS:
        return 'UNEVALUABLE', REASON_INSUFFICIENT_BUCKETS, stats
    stats['WR'] = round(float((pnl > 0).mean() * 100), 2)
    stats['net'] = round(float(pnl.sum()), 2)
    return 'VALID', '', stats


def reachable_episodes(clusters, df, warmup, universe):
    """Item 5: episodes holding >= 1 ELIGIBLE bar where D2D AGREES with direction.

    PROPERTY OF THE MARKET. Computed PER GRID CELL, never once and reused: the
    episode set differs by cell, so a reachable count borrowed from another cell
    is a different denominator wearing the same name.
    """
    d2d = df['D2D_Trend_Dir'].values
    cl = clusters['clusters']
    out = {}
    for d in (1, -1):
        sub = cl[cl['dir'] == d] if len(cl) else cl
        ids = []
        for _i, r in sub.iterrows():
            b0, b1 = int(r['b0']), int(r['b1'])
            seg = slice(b0, b1 + 1)
            if bool(np.any(universe[seg] & (d2d[seg] == d))):
                ids.append(int(r['cluster_id']))
        out[d] = set(ids)
    return out


def episode_spans(clusters):
    cl = clusters['clusters']
    return {int(r['cluster_id']): (int(r['b0']), int(r['b1']), int(r['dir']))
            for _i, r in cl.iterrows()} if len(cl) else {}


def touched_episodes(entry_bars, direction, clusters):
    """Item 7: the episode IDs a signal touches, so coverage is re-derivable."""
    bars = np.asarray(entry_bars, dtype=np.int64)
    if len(bars) == 0:
        return []
    cid = clusters['cid'][direction][bars]
    return sorted({int(c) for c in cid if c >= 0})


def matched_null_rate(null_frames, bar_day):
    """Appendix A: fraction of matched-null signals passing the IDENTICAL VALID."""
    if not null_frames:
        return 0.0, []
    passed = []
    for t in null_frames:
        v, _r, _s = evaluate_valid(t, bar_day)
        if v == 'VALID':
            pf, und = _pf(t['pnl'].values)
            if not und:
                passed.append(pf)
    return len(passed) / float(len(null_frames)), sorted(passed)


def pricing_columns(pf_value, n_trials, null_rate, null_pfs):
    """Appendix A's eight columns. EXPECTED_ROWS_AT_OR_ABOVE_THIS_PF does the work."""
    arr = np.asarray(null_pfs, dtype=float)
    exceed = float((arr >= pf_value).mean()) if len(arr) else float('nan')
    return {
        'n_trials_family': int(n_trials),
        'null_valid_rate_family': round(float(null_rate), 6),
        'expected_valid_by_chance_family': round(n_trials * float(null_rate), 2),
        'pf_null_p50_family': round(float(np.percentile(arr, 50)), 4) if len(arr) else '',
        'pf_null_p90_family': round(float(np.percentile(arr, 90)), 4) if len(arr) else '',
        'pf_null_p99_family': round(float(np.percentile(arr, 99)), 4) if len(arr) else '',
        'pf_null_exceedance_pct': round(exceed, 6) if exceed == exceed else '',
        'EXPECTED_ROWS_AT_OR_ABOVE_THIS_PF': (round(n_trials * exceed, 3)
                                              if exceed == exceed else ''),
    }


def benjamini_yekutieli(pvals, q=0.10):
    """BY, not BH: measured signed dependence is 49.6/50.4 so PRDS fails."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    out = np.full(n, float('nan'))
    if n == 0:
        return out
    c_n = float(np.sum(1.0 / np.arange(1, n + 1)))
    order = np.argsort(p)
    ranked = p[order]
    qv = ranked * n * c_n / np.arange(1, n + 1)
    qv = np.minimum.accumulate(qv[::-1])[::-1]
    out[order] = np.clip(qv, 0.0, 1.0)
    return out


def segment_fold_stats(trades):
    """Item 9: SEGMENT-LOCAL monthly buckets. wf.FOLDS is month-literal and sacred."""
    b = month_buckets(trades)
    if not b:
        return {'folds_plus': 0, 'min_fold_pf': '', 'fold_buckets': 0}
    months = sorted(b)
    m = pd.Series(trades['exit_time'].astype(str).values).str[:7].values
    pnl = np.asarray(trades['pnl'].values, dtype=float)
    pfs = []
    for mo in months:
        pf, und = _pf(pnl[m == mo])
        if not und:
            pfs.append(pf)
    return {'folds_plus': int(sum(1 for v in b.values() if v > 0)),
            'min_fold_pf': round(min(pfs), 4) if pfs else '',
            'fold_buckets': len(months)}


def gated_arm(trades, gate_ok_bars):
    """Item 10: the conviction arm. Both arms emitted, plus the delta."""
    if len(trades) == 0:
        return {'trades': 0, 'WR': '', 'PF': '', 'worst_day_usd': '', 'net': 0.0}
    keep = trades[np.isin(np.asarray(trades['entry_bar'].values, dtype=np.int64), gate_ok_bars)]
    if len(keep) == 0:
        return {'trades': 0, 'WR': '', 'PF': '', 'worst_day_usd': '', 'net': 0.0}
    p = np.asarray(keep['pnl'].values, dtype=float)
    pf, und = _pf(p)
    return {'trades': int(len(keep)), 'WR': round(float((p > 0).mean() * 100), 2),
            'PF': ('inf' if und else round(pf, 4)),
            'worst_day_usd': round(float(_daily(keep).min()), 2),
            'net': round(float(p.sum()), 2)}


def same_bar_cohort_table(entries_by_dir, ids_by_dir, families_by_id, max_depth=12):
    """Item 11: family composition of each bar as a CURVE OVER DEPTH, counts only.

    PROPERTY OF THE BOOK/POOL. No P&L: depth-3 has no discriminating power at
    pool scale and P&L needs a book. Depth is DISTINCT SIGNALS on the bar,
    per direction, never pooled.
    """
    rows = []
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        bars = np.asarray(entries_by_dir.get(d, []), dtype=np.int64)
        ids = np.asarray(ids_by_dir.get(d, []), dtype=object)
        if len(bars) == 0:
            continue
        by_bar = {}
        for b, i in zip(bars, ids):
            by_bar.setdefault(int(b), set()).add(i)
        for depth in range(1, max_depth + 1):
            sel_bars = [b for b, s in by_bar.items() if len(s) == depth] if depth < max_depth \
                else [b for b, s in by_bar.items() if len(s) >= depth]
            if not sel_bars:
                continue
            fam_counts = {}
            for b in sel_bars:
                for i in by_bar[b]:
                    f = families_by_id.get(i, '?')
                    fam_counts[f] = fam_counts.get(f, 0) + 1
            rows.append({'direction': lab,
                         'depth': depth if depth < max_depth else f'{max_depth}+',
                         'bars': len(sel_bars),
                         'distinct_signal_slots': sum(fam_counts.values()),
                         'family_composition': ';'.join(f'{k}:{v}' for k, v in sorted(fam_counts.items())),
                         'population': 'POOL', 'basis': 'distinct signals on the SAME BAR, per direction'})
    return pd.DataFrame(rows)


def dilution_curve(order_keys, entries_by_id, dirs_by_id, ranking_key_name, n_tol=1, depth=3):
    """Item 12: admit best-first over the WHOLE catalogue, re-scoring same-bar 3+.

    Emitted under at least two ranking keys because the stop-point differs by
    key, and the gap between the curves is the overfit estimate. Counts only.
    """
    rows = []
    acc_bars = {1: [], -1: []}
    acc_ids = {1: [], -1: []}
    for k, sid in enumerate(order_keys, start=1):
        d = dirs_by_id.get(sid, 1)
        bars = np.asarray(entries_by_id.get(sid, []), dtype=np.int64)
        if len(bars):
            acc_bars[d].extend(bars.tolist())
            acc_ids[d].extend([sid] * len(bars))
        tot = 0
        for dd in (1, -1):
            if not acc_bars[dd]:
                continue
            by_bar = {}
            for b, i in zip(acc_bars[dd], acc_ids[dd]):
                by_bar.setdefault(int(b), set()).add(i)
            tot += sum(1 for s in by_bar.values() if len(s) >= depth)
        rows.append({'admitted': k, 'signal_id': sid, 'ranking_key': ranking_key_name,
                     'same_bar_ge3_bars': tot, 'tolerance_N': n_tol, 'depth': depth,
                     'population': 'POOL', 'basis': 'distinct signals per bar, per direction'})
    return pd.DataFrame(rows)


NULL_K_DEFAULT = 200
NULL_K_MIN_MEANINGFUL = 50
NULL_FIRE_TOL = 0.35
NULL_MAX_ARITY = 3


def _fire_count(mask):
    return int(np.asarray(mask, dtype=bool).sum())


def draw_matched_null_masks(pool, target_fire_counts, rng, k=NULL_K_DEFAULT,
                            tol=NULL_FIRE_TOL, max_arity=NULL_MAX_ARITY, max_tries_per=60):
    """APPENDIX A's matched null: same vocabulary, FIRE-RATE MATCHED.

    Random conjunctions of 1..max_arity conditions drawn from the SAME
    post-hygiene vocabulary the family's candidates come from, accepted ONLY
    when the conjunction's fire count lands within tol of a target sampled from
    THAT FAMILY'S OWN fire-count distribution.

    THE BAND IS A FILTER, NOT A PREFERENCE. An out-of-band draw is DISCARDED,
    never kept as a closest miss. Keeping misses made n_null a count of masks
    rather than a count of MATCHED masks, so the K-floor in null_quality tested
    the wrong quantity and a null of the wrong rarity was published under a
    header asserting the search had been priced. Discarding is chosen over a
    separate matched-fraction gate because it makes the existing K-floor do
    double duty: after this change n_null IS the matched count, so one threshold
    guards both quantities and there is no second number to keep in step.

    Fire-rate matching is not decoration. A triple fires far more rarely than any
    single condition, so a null drawn without matching would be a null for a
    different rarity than the population it prices - easier or harder, and in
    either direction the exceedance it produces is not the exceedance Appendix A
    asks for. Arity varies precisely so the fire rate can be matched, and F0 is
    the most exposed family because its candidates are triples, the rarest
    population in the build.

    Returns (matched_masks, attempts_stats). attempts_stats carries the matched
    fraction so the console line and the catalogue can both report how well the
    null matched without re-deriving it.
    """
    labels = sorted(pool.keys())
    stats = {'requested_k': int(k), 'draws_attempted': 0, 'matched': 0,
             'rejected_out_of_band': 0, 'tol': tol,
             'target_min': '', 'target_max': ''}
    if not labels or len(target_fire_counts) == 0:
        stats['matched_fraction'] = 0.0
        return [], stats
    targets = np.asarray(target_fire_counts, dtype=float)
    stats['target_min'] = int(targets.min())
    stats['target_max'] = int(targets.max())
    out = []
    for _i in range(k):
        want = float(rng.choice(targets))
        lo, hi = want * (1.0 - tol), want * (1.0 + tol)
        hit = None
        for _t in range(max_tries_per):
            stats['draws_attempted'] += 1
            arity = int(rng.integers(1, max_arity + 1))
            picks = [labels[int(rng.integers(0, len(labels)))] for _a in range(arity)]
            m = np.asarray(pool[picks[0]], dtype=bool).copy()
            for lb in picks[1:]:
                m &= np.asarray(pool[lb], dtype=bool)
            fc = _fire_count(m)
            if fc == 0:
                continue
            if lo <= fc <= hi:
                hit = {'mask': m, 'conditions': picks, 'fire_count': fc,
                       'target_fire_count': int(want)}
                break
            stats['rejected_out_of_band'] += 1
        if hit is not None:
            out.append(hit)
            stats['matched'] += 1
    stats['matched_fraction'] = round(stats['matched'] / float(k), 4) if k else 0.0
    return out, stats


def null_quality(n_matched, k_requested, stats=None):
    """n_matched is now a count of MATCHED draws, so the K-floor does double duty.

    Before the band became a filter this tested a count of masks, and 141 of 200
    unmatched draws could pass it. A null too small to price a tail must say so
    rather than emit a confident number - that is the whole argument for
    pricing_blank, and a wrong number in the pricing column is worse than a
    blank one.
    """
    frac = (stats or {}).get('matched_fraction', None)
    if n_matched < NULL_K_MIN_MEANINGFUL:
        why = (f'matched null holds {n_matched} IN-BAND signals (< {NULL_K_MIN_MEANINGFUL}) '
               f'against a request of {k_requested}')
        if frac is not None:
            why += (f'; matched fraction {frac:.1%} at tol +/-{(stats or {}).get("tol", 0):.0%} '
                    f'for targets {(stats or {}).get("target_min", "?")}..'
                    f'{(stats or {}).get("target_max", "?")} fires')
        why += (f'. The exceedance floor is 1/{max(n_matched, 1)} and cannot resolve a tail, so the '
                f'Appendix A columns are BLANK rather than confidently wrong.')
        return ('null_too_small', why)
    return ('', '')


def pricing_blank(reason):
    """Item 8 fallback: the mandated names stay EMPTY rather than carry another quantity."""
    return {'n_trials_family': '', 'null_valid_rate_family': '',
            'expected_valid_by_chance_family': '', 'pf_null_p50_family': '',
            'pf_null_p90_family': '', 'pf_null_p99_family': '',
            'pf_null_exceedance_pct': '', 'EXPECTED_ROWS_AT_OR_ABOVE_THIS_PF': '',
            'q_value_BY_family': '', 'pricing_unavailable_reason': reason}


MECHANISM_D_LOCKS = {
    'engine/dots_thresholds.py': '518862bf19fb',
    'engine/terrain.py': 'dcaecaf7e8e1',
    'engine/cluster_profiler.py': '070bb2aa7aaa',
    'scanners/concurrence_profiler.py': '554019e93069',
}


def assert_episode_thresholds_mechanism_d(root, thr, mcol, ecol, k_tag, e_tag):
    """Item 5's IN-RUN half. Appendix D: the lock is pre-run, this is in-run.

    Two checks. First, the four modules that may legitimately define episodes,
    clusters or strata are byte-verified against the shas Appendix D fixes as
    constants of that document - the Developer verifies, he does not record his
    own baseline. Second, the K and E arrays actually used to build this run's
    episodes must be per-bar arrays from the oracle sweep, not scalars: a
    constant broadcast over the span is exactly the local-percentile shape the
    prohibition targets, and it is invisible to a file lock.
    """
    import hashlib
    import os as _os
    import numpy as _np
    drift = []
    for rel, want in MECHANISM_D_LOCKS.items():
        p_ = _os.path.join(root, rel)
        if not _os.path.exists(p_):
            drift.append(f'{rel} MISSING')
            continue
        got = hashlib.sha256(open(p_, 'rb').read()).hexdigest()[:12]
        if got != want:
            drift.append(f'{rel} {got} != {want}')
    if drift:
        raise SystemExit(
            'ABORT [item 5] market-object module drift: ' + '; '.join(drift) +
            '. These four modules are the only ones that may define episodes, clusters or strata. '
            'Any change requires explicit re-blessing regardless of how the cut is written.')
    for col, tag, name in ((mcol, k_tag, 'K magnitude'), (ecol, e_tag, 'E efficiency')):
        arr = thr.get((col, tag))
        if arr is None:
            raise SystemExit(f'ABORT [item 5] episode threshold {name} ({col}, {tag}) absent from '
                             f'the oracle sweep - it did not route through dots_thresholds.')
        a = _np.asarray(arr)
        if a.ndim == 0 or a.size <= 1:
            raise SystemExit(
                f'ABORT [item 5] episode threshold {name} is a SCALAR. Episode thresholds must be '
                f'per-bar arrays from mechanism D (rolling, day-refreshed, causal). A constant '
                f'broadcast over the span is a span-wide cut and the file lock cannot see it.')
    return {'modules_verified': len(MECHANISM_D_LOCKS), 'k_col': mcol, 'e_col': ecol,
            'basis': 'mechanism D, rolling-2500, day-refreshed, per-bar arrays'}
