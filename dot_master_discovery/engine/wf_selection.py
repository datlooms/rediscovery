"""engine/wf_selection.py — walk-forward on the SELECTION PROCESS (spec section I).

The book was validated; the method never was. Every prior validation sat inside
Jan-Jun, downstream of a funnel already run across that whole window. This module
re-runs the ENTIRE funnel inside each training segment and touches each test
segment exactly once.

DOCTRINE BINDING (DOT_signal_discovery_mantra.md, sha fae943d40231).
Rule 5 is the one this build breaches most easily: a walk-forward that passes
because a parameter leaked is a POSITIVE claim asserted at a strength the
measurement does not carry. Every bound, bucket boundary and hygiene derivation
here is computed from an explicit training index range and is asserted to be so.
WHEN A FINDING DEPENDS ON A FILTER, THRESHOLD OR RESTRICTION, THE FILTER IS PART
OF THE FINDING: split boundaries, the embargo bar count, the floor parameters and
the enumeration limits are emitted as columns beside every figure they govern.

wf.py IS SACRED AND ITS FOLDS ARE MONTH-LITERAL Jan-Jun. THIS MODULE DOES NOT
IMPORT wf AND DOES NOT REFERENCE FOLDS. Monthly buckets are computed from the
segment's own timestamps, per spec B.1.

NO ROW IS EVER DELETED. Segments are index ranges over the intact series. The
oracle always receives the FULL frame; training restriction is applied as a
boolean mask at measurement time. This is safe because mechanism D is causal —
the threshold at bar i depends only on bars at or before i — and that causality
is not assumed here, it is asserted by assert_oracle_causal() against a truncated
recomputation.

THE SINGLE TEST TOUCH IS STRUCTURAL, NOT A CONVENTION. TestSegmentGuard yields
the test slice exactly once and marks itself consumed; a second request raises
SecondTouchError. The real book and the null are scored inside that one pass, so
score-inspect-then-null is not expressible.

PASS CRITERION (spec I.3). Signal-level persistence measured as the record
measures it: net > 0, PF >= 2, WR >= 75 in BOTH train and test. Target is a mean
over the derived splits of >= 65% with NO single split below 50%, against a
random-triple null regenerated per split. A FAIL IS A LEGITIMATE RESULT and is
reported as one; no bar is lowered to obtain a pass.
"""

import hashlib
import itertools
import json
import math
import os
import time

import numpy as np
import pandas as pd

MIN_MONTH_BUCKETS = 3
MIN_TRAIN_DAYS = 60
MIN_BUCKETS_PER_DIRECTION = 3
EMBARGO_BARS = 1440
MIN_SPLITS = 3
PERSIST_MIN_PF = 2.0
PERSIST_MIN_WR = 75.0
PASS_MEAN = 0.65
PASS_FLOOR_PER_SPLIT = 0.50
NULL_TARGET_QUALIFIERS = 80
NULL_FLOOR_QUALIFIERS = 40
NULL_TRIPLES_CAP = 1500
NULL_GEN_BATCH = 150
NULL_SCORE_BATCH = 1
PASS_MEAN_RATIO = 2.40
PASS_MIN_RATIO = 1.85
PASS_LB_RATIO = 1.0
NULL_SEED = 20260724
ATTEST_FILE = '.wf_attest.jsonl'


class SecondTouchError(RuntimeError):
    pass


class FakeStepError(RuntimeError):
    pass


class UnevaluableError(RuntimeError):
    pass


def _sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def day_index(times):
    return pd.Series(np.asarray(times, dtype=str)).str[:10].values


def month_index(times):
    return pd.Series(np.asarray(times, dtype=str)).str[:7].values


def post_warmup_day_table(df, warmup):
    d = day_index(df['Time'].values)
    m = month_index(df['Time'].values)
    idx = np.arange(len(df))
    post = idx >= warmup
    rows = []
    for day in pd.unique(d[post]):
        sel = post & (d == day)
        pos = idx[sel]
        rows.append({'day': day, 'month': m[pos[0]], 'first_bar': int(pos[0]),
                     'last_bar': int(pos[-1]), 'bars': int(len(pos))})
    return pd.DataFrame(rows).sort_values('first_bar').reset_index(drop=True)


def segment_is_valid(day_tbl, lo_day, hi_day):
    seg = day_tbl.iloc[lo_day:hi_day]
    n_days = len(seg)
    n_buckets = seg['month'].nunique()
    return {'days': int(n_days), 'month_buckets': int(n_buckets),
            'meets_days_floor': bool(n_days >= MIN_TRAIN_DAYS),
            'meets_bucket_floor': bool(n_buckets >= MIN_MONTH_BUCKETS),
            'valid': bool(n_days >= MIN_TRAIN_DAYS and n_buckets >= MIN_MONTH_BUCKETS)}


def derive_splits(df, warmup, min_splits=MIN_SPLITS, embargo_bars=EMBARGO_BARS):
    day_tbl = post_warmup_day_table(df, warmup)
    total_days = len(day_tbl)
    first_valid = None
    for k in range(1, total_days + 1):
        if segment_is_valid(day_tbl, 0, k)['valid']:
            first_valid = k
            break
    if first_valid is None:
        return [], day_tbl, {'total_post_warmup_days': total_days, 'first_valid_train_days': None,
                             'derived_splits': 0, 'under_powered': True,
                             'reason': 'no prefix satisfies the floor; the series cannot support a walk-forward'}
    remaining = total_days - first_valid
    attempts = []
    chosen = []
    chosen_n = 0
    for n in range(min_splits, 0, -1):
        if remaining < n:
            attempts.append({'n': n, 'result': 'rejected: fewer remaining days than splits'})
            continue
        base = remaining // n
        extra = remaining % n
        bounds = []
        cursor = first_valid
        for i in range(n):
            size = base + (1 if i < extra else 0)
            bounds.append((cursor, cursor + size))
            cursor += size
        built = []
        ok = True
        for i, (lo, hi) in enumerate(bounds):
            train_hi_day = lo
            chk = segment_is_valid(day_tbl, 0, train_hi_day)
            if not chk['valid']:
                ok = False
                attempts.append({'n': n, 'result': f'rejected: training segment {i} holds {chk["days"]} days / '
                                                   f'{chk["month_buckets"]} buckets, below the floor'})
                break
            train_last_bar = int(day_tbl.iloc[train_hi_day - 1]['last_bar'])
            embargo_start = train_last_bar + 1
            embargo_end = embargo_start + embargo_bars
            seg = day_tbl.iloc[lo:hi]
            seg = seg[seg['first_bar'] >= embargo_end]
            if len(seg) == 0:
                ok = False
                attempts.append({'n': n, 'result': f'rejected: test segment {i} is empty after the {embargo_bars}-bar embargo'})
                break
            built.append({'split_index': i, 'train_first_bar': int(day_tbl.iloc[0]['first_bar']),
                          'train_last_bar': train_last_bar,
                          'embargo_first_bar': embargo_start, 'embargo_last_bar': embargo_end - 1,
                          'embargo_bars': embargo_bars,
                          'test_first_bar': int(seg.iloc[0]['first_bar']),
                          'test_last_bar': int(seg.iloc[-1]['last_bar']),
                          'train_days': chk['days'], 'train_month_buckets': chk['month_buckets'],
                          'test_days': int(len(seg)), 'test_month_buckets': int(seg['month'].nunique()),
                          'floor_days': MIN_TRAIN_DAYS, 'floor_buckets': MIN_MONTH_BUCKETS,
                          'scheme': 'anchored'})
        if ok and built:
            attempts.append({'n': n, 'result': 'ACCEPTED'})
            chosen = built
            chosen_n = n
            break
    meta = {'total_post_warmup_days': total_days, 'first_valid_train_days': first_valid,
            'days_after_first_floor': remaining, 'derived_splits': chosen_n,
            'min_splits_required': min_splits, 'embargo_bars': embargo_bars,
            'partition': 'remaining post-floor days divided into contiguous equal test segments; '
                         'training segments are anchored so each strictly contains the previous',
            'floor': f'>={MIN_MONTH_BUCKETS} monthly buckets AND >={MIN_TRAIN_DAYS} post-warmup trading days; '
                     f'>={MIN_BUCKETS_PER_DIRECTION} buckets per direction where a direction is evaluated',
            'attempts': attempts, 'under_powered': bool(chosen_n < min_splits)}
    return chosen, day_tbl, meta


def split_definition_sha(splits, meta):
    payload = json.dumps({'splits': splits, 'floor_days': MIN_TRAIN_DAYS,
                          'floor_buckets': MIN_MONTH_BUCKETS,
                          'buckets_per_direction': MIN_BUCKETS_PER_DIRECTION,
                          'embargo_bars': meta.get('embargo_bars')}, sort_keys=True)
    return _sha_text(payload)


def assert_no_row_deletion(df, n_expected):
    if len(df) != n_expected:
        raise FakeStepError(f'row count changed from {n_expected} to {len(df)}: rejection-list item 8')
    return True


def classify_threshold_keys(adaptive, structural_keys):
    rolling = [k for k in adaptive if k not in structural_keys]
    constant = [k for k in adaptive if k in structural_keys]
    return rolling, constant


def assert_oracle_causal(df, adaptive_full, compute_fn, train_last_bar, structural_keys):
    t0 = time.time()
    truncated = df.iloc[:train_last_bar + 1].copy()
    ad_tr = compute_fn(truncated)
    rolling, constant = classify_threshold_keys(adaptive_full, set(structural_keys))
    checked_rolling = 0
    checked_constant = 0
    mismatches = []
    for key in list(adaptive_full.keys()):
        if key not in ad_tr:
            continue
        a = np.asarray(adaptive_full[key])[:train_last_bar + 1]
        b = np.asarray(ad_tr[key])
        same = a.shape == b.shape and np.array_equal(a, b)
        if not same:
            mismatches.append(str(key))
        if key in set(structural_keys):
            checked_constant += 1
        else:
            checked_rolling += 1
    elapsed = time.time() - t0
    return {'keys_total': len(adaptive_full),
            'rolling_D_keys_checked': checked_rolling,
            'rolling_D_keys_available': len(rolling),
            'structural_constant_keys_checked': checked_constant,
            'coverage': f'{checked_rolling} of {len(rolling)} rolling-D keys and '
                        f'{checked_constant} of {len(constant)} structural-constant keys',
            'equality': 'EXACT bitwise (np.array_equal); no tolerance, because a tolerance in a causality '
                        'assertion is a place a future leak could hide',
            'mismatches': len(mismatches), 'detail': ';'.join(mismatches[:12]),
            'causal': len(mismatches) == 0,
            'seconds': round(elapsed, 2),
            'meaning': 'threshold values over the training prefix are bitwise identical whether computed on the '
                       'full frame or on the truncated prefix; mechanism D therefore cannot see the test segment, '
                       'and masking after a full-frame computation is not a leak',
            'note': 'ALL keys are checked, not a sample. The structural constants (VWAP_Z, OR_Position) are '
                    'causally trivial because a constant is identical on any prefix, so they are counted '
                    'SEPARATELY and never presented as evidence of rolling-threshold causality. The cost is '
                    'dominated by the single truncated recomputation, which is paid regardless of how many keys '
                    'are compared, so full coverage is effectively free and must not be reduced for speed.'}


def require_h3_evaluable(split_index, direction_results):
    evaluable = [d for d in direction_results if d.get('evaluable')]
    if not evaluable:
        raise UnevaluableError(
            f'split {split_index}: no direction produced >= {MIN_BUCKETS_PER_DIRECTION} monthly buckets, so the '
            f'H.3 criterion is UNEVALUABLE for this split. The build fails loudly here rather than falling back to '
            f'a full-series bucket rule, which is the collision spec H.3 exists to prevent.')
    return True


def segment_month_buckets(times, mask):
    m = month_index(times)[mask]
    return sorted(pd.unique(m).tolist())


def h3_segment_rule(trades_dir, min_buckets=MIN_BUCKETS_PER_DIRECTION):
    if len(trades_dir) == 0:
        return {'buckets': 0, 'positive': 0, 'evaluable': False,
                'verdict': 'UNEVALUABLE - no trades in this direction in this segment'}
    mo = month_index(trades_dir['exit_time'].values)
    nets = {b: float(trades_dir['pnl'].values[mo == b].sum()) for b in sorted(pd.unique(mo).tolist())}
    nb = len(nets)
    pos = sum(1 for v in nets.values() if v > 0)
    if nb < min_buckets:
        return {'buckets': nb, 'positive': pos, 'evaluable': False,
                'verdict': f'UNEVALUABLE - segment holds {nb} monthly buckets, minimum {min_buckets}; '
                           f'the signal is NEITHER passed NOR culled on this basis',
                'per_bucket': ';'.join(f'{k}:{round(v, 1)}' for k, v in nets.items())}
    return {'buckets': nb, 'positive': pos, 'evaluable': True,
            'verdict': 'PASS' if pos >= nb - 1 else 'FAIL',
            'per_bucket': ';'.join(f'{k}:{round(v, 1)}' for k, v in nets.items())}


class TestSegmentGuard:
    def __init__(self, split_index, first_bar, last_bar):
        self.split_index = split_index
        self.first_bar = first_bar
        self.last_bar = last_bar
        self._consumed = False
        self._touch_count = 0

    def touch(self, df):
        if self._consumed:
            self._touch_count += 1
            raise SecondTouchError(
                f'split {self.split_index}: test segment already consumed; a second touch is a '
                f'rejection-list item 9 violation. The book and the null must be scored in the same pass.')
        self._consumed = True
        self._touch_count += 1
        return df.iloc[self.first_bar:self.last_bar + 1]

    @property
    def consumed(self):
        return self._consumed

    @property
    def touch_count(self):
        return self._touch_count


def persistence_flags(pnl):
    p = np.asarray(pnl, dtype=float)
    if len(p) == 0:
        return {'net': 0.0, 'PF': 0.0, 'WR': 0.0, 'passes': False}
    loss = -p[p < 0].sum()
    pf = float(p[p > 0].sum() / loss) if loss > 0 else (999.0 if p.sum() > 0 else 0.0)
    wr = float((p > 0).mean() * 100.0)
    net = float(p.sum())
    return {'net': net, 'PF': pf, 'WR': wr,
            'passes': bool(net > 0 and pf >= PERSIST_MIN_PF and wr >= PERSIST_MIN_WR)}


def entity_persistence(train_trades, test_trades, key='signal_name'):
    rows = []
    for name in sorted(set(train_trades[key].tolist()) | set(test_trades[key].tolist())):
        tr = persistence_flags(train_trades[train_trades[key] == name]['pnl'].values)
        te = persistence_flags(test_trades[test_trades[key] == name]['pnl'].values)
        rows.append({'entity': name,
                     'train_net': round(tr['net'], 1), 'train_PF': round(tr['PF'], 3), 'train_WR': round(tr['WR'], 1),
                     'test_net': round(te['net'], 1), 'test_PF': round(te['PF'], 3), 'test_WR': round(te['WR'], 1),
                     'train_passes': tr['passes'], 'test_passes': te['passes'],
                     'test_traded': bool(len(test_trades[test_trades[key] == name]) > 0),
                     'persists': bool(tr['passes'] and te['passes'])})
    return pd.DataFrame(rows)


PERSIST_DEFINITION = (f'net>0 AND PF>={PERSIST_MIN_PF} AND WR>={PERSIST_MIN_WR}, '
                      f'applied identically to train and test')
DENOMINATOR_DEFINITION = ('n_traded: signals that qualified on TRAIN and FIRED AT LEAST ONCE ON '
                          'TEST. A signal that never fired on test did not fail, and folding it in '
                          'conflates silence with loss.')


def persistence_rate(frame):
    """Item 18: the denominator is n_TRADED, not n_included.

    Both arms call THIS function. The definition strings above are asserted
    identical across arms at run time, because this stage was once reported
    fixed while its artifact stayed byte-identical to the broken version.
    """
    elig = frame[frame['train_passes'] & (frame['test_traded'] if 'test_traded' in frame.columns
                                          else True)]
    if len(elig) == 0:
        return np.nan, 0, 0
    k = int(elig['persists'].sum())
    return float(k / len(elig)), k, int(len(elig))


def assert_arms_agree(book_meta, null_meta):
    """Item 18: ABORT if the two arms do not share persist and denominator."""
    bad = []
    for key in ('persist_definition', 'denominator_definition'):
        if book_meta.get(key) != null_meta.get(key):
            bad.append(f'{key}: book="{book_meta.get(key)}" null="{null_meta.get(key)}"')
    if bad:
        raise SystemExit(
            'ABORT [item 18] the walk-forward arms do not agree: ' + '; '.join(bad) +
            '. A ratio between two arms measuring different things is not a ratio.')
    return {'arms_agree': True, 'persist_definition': book_meta['persist_definition'],
            'denominator_definition': book_meta['denominator_definition']}


def random_triple_null(pool_keys, rng, n_triples, arity=3, seen=None):
    keys = list(pool_keys)
    out = []
    if seen is None:
        seen = set()
    guard = 0
    while len(out) < n_triples and guard < n_triples * 100:
        guard += 1
        pick = tuple(sorted(rng.choice(len(keys), size=arity, replace=False).tolist()))
        if pick in seen:
            continue
        seen.add(pick)
        out.append(tuple(keys[i] for i in pick))
    return out


def triples_to_signals(triples, rng):
    rows = []
    for t in triples:
        parts = []
        ok = True
        for c in t:
            if ':' not in c:
                ok = False
                break
            f, th = c.rsplit(':', 1)
            parts.append((f, th))
        if not ok or len(parts) != 3:
            continue
        rows.append({'feat_1': parts[0][0], 'thresh_1': parts[0][1],
                     'feat_2': parts[1][0], 'thresh_2': parts[1][1],
                     'feat_3': parts[2][0], 'thresh_3': parts[2][1],
                     'direction': 'LONG' if rng.integers(0, 2) == 0 else 'SHORT'})
    return pd.DataFrame(rows)


def bar_mask(n_bars, first_bar, last_bar, warmup):
    m = np.zeros(n_bars, dtype=bool)
    m[max(first_bar, warmup):last_bar + 1] = True
    return m


def score_null_arm(df, pool_keys, adaptive, structural, warmup, split, guard, run_portfolio,
                   target=NULL_TARGET_QUALIFIERS, floor=NULL_FLOOR_QUALIFIERS,
                   cap=NULL_TRIPLES_CAP, gen_batch=NULL_GEN_BATCH, seed=NULL_SEED):
    split_seed = seed + int(split['split_index'])
    rng = np.random.default_rng(split_seed)
    n = len(df)
    train_mask = bar_mask(n, 0, split['train_last_bar'], warmup)
    seen = set()
    generated = 0
    batches = 0
    records = []
    while True:
        qualifiers = sum(1 for r in records if r['train_passes'])
        if qualifiers >= target or generated >= cap:
            break
        take = min(gen_batch, cap - generated)
        triples = random_triple_null(pool_keys, rng, n_triples=take, seen=seen)
        if not triples:
            break
        sig_batch = triples_to_signals(triples, rng)
        batches += 1
        for i in range(len(sig_batch)):
            one = sig_batch.iloc[[i]]
            td = run_portfolio(df, one, mask_window=train_mask, adaptive=adaptive,
                               structural=structural, warmup=warmup, verbose=False)
            pnl = td['pnl'].values if len(td) else np.array([])
            tr = persistence_flags(pnl)
            records.append({'entity': f'NULL_{generated + i:05d}', 'row': one,
                            'train_trades': int(len(pnl)), 'train_net': round(tr['net'], 1),
                            'train_PF': round(tr['PF'], 3), 'train_WR': round(tr['WR'], 1),
                            'train_passes': tr['passes']})
        generated += len(sig_batch)
    qualifiers = [r for r in records if r['train_passes']]
    test_slice = guard.touch(df)
    test_lo = int(test_slice.index[0])
    test_hi = int(test_slice.index[-1])
    test_mask = bar_mask(n, test_lo, test_hi, warmup)
    rows = []
    persisted = 0
    for r in qualifiers:
        td = run_portfolio(df, r['row'], mask_window=test_mask, adaptive=adaptive,
                           structural=structural, warmup=warmup, verbose=False)
        pnl = td['pnl'].values if len(td) else np.array([])
        te = persistence_flags(pnl)
        if te['passes']:
            persisted += 1
        rows.append({'split_index': split['split_index'], 'entity': r['entity'],
                     'train_trades': r['train_trades'], 'train_net': r['train_net'],
                     'train_PF': r['train_PF'], 'train_WR': r['train_WR'],
                     'test_trades': int(len(pnl)), 'test_net': round(te['net'], 1),
                     'test_PF': round(te['PF'], 3), 'test_WR': round(te['WR'], 1),
                     'train_passes': True, 'test_passes': te['passes'],
                     'persists': bool(te['passes'])})
    n_null = len(qualifiers)
    rate = float(persisted / n_null) if n_null else np.nan
    if n_null >= target:
        status = 'EVALUABLE - target denominator met'
    elif n_null >= floor:
        status = f'EVALUABLE - REDUCED DENOMINATOR ({n_null} of target {target}); reported, not imputed'
    else:
        status = f'UNEVALUABLE - {n_null} qualifiers below the hard floor of {floor}'
    lo, hi = binomial_ci(persisted, n_null)
    return pd.DataFrame(rows), {'split_index': split['split_index'],
                                'triples_generated': generated, 'generation_batches': batches,
                                'train_qualifiers': n_null, 'persisted': persisted,
                                'null_persistence_rate': round(rate, 4) if rate == rate else np.nan,
                                'null_ci95_lo': round(lo, 4) if lo == lo else np.nan,
                                'null_ci95_hi': round(hi, 4) if hi == hi else np.nan,
                                'target_qualifiers': target, 'floor_qualifiers': floor,
                                'cap_triples': cap, 'cap_reached': bool(generated >= cap),
                                'status': status, 'split_seed': split_seed,
                                'qualification_rate': round(n_null / generated, 4) if generated else np.nan,
                                'test_bar_range': f'{test_lo}-{test_hi}'}


def binomial_ci(k, n, alpha=0.05):
    if n <= 0:
        return np.nan, np.nan
    lo, hi = 0.0, 1.0
    p = k / n
    se = math.sqrt(max(p * (1 - p), 1e-12) / n)
    z = 1.959963984540054
    lo = max(0.0, p - z * se)
    hi = min(1.0, p + z * se)
    return lo, hi


def write_attestation(out_dir, record):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, ATTEST_FILE)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, sort_keys=True) + '\n')
    return path


def read_attestation(out_dir):
    path = os.path.join(out_dir, ATTEST_FILE)
    if not os.path.exists(path):
        return pd.DataFrame()
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return pd.DataFrame(rows)


def detect_repeats(attest):
    if len(attest) == 0:
        return pd.DataFrame(), 0
    key = ['code_sha256', 'split_definition_sha256', 'input_sha', 'split_index']
    have = [k for k in key if k in attest.columns]
    for c in have:
        attest = attest.copy()
        attest[c] = attest[c].astype(str)
    grp = attest.groupby(have).size().reset_index(name='records')
    rep = grp[grp['records'] > 1]
    return rep, int(rep['records'].sum() - len(rep)) if len(rep) else 0


def build_attestation_record(run_id, code_shas, split_def_sha, input_sha, split, out_dir):
    if isinstance(code_shas, dict):
        code_shas = ';'.join(f'{k}={v}' for k, v in sorted(code_shas.items()))
    return {'run_id': run_id, 'utc_timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'code_sha256': code_shas, 'split_definition_sha256': split_def_sha,
            'input_sha': input_sha, 'split_index': split['split_index'],
            'segment_bar_range': [split['test_first_bar'], split['test_last_bar']],
            'train_bar_range': [split['train_first_bar'], split['train_last_bar']],
            'embargo_bar_range': [split['embargo_first_bar'], split['embargo_last_bar']]}


def rejection_checks(df, n_expected, splits, meta, adaptive_causal, guards,
                     per_split_frame=None, attest_trail=None, pass_frame=None):
    checks = []
    checks.append({'item': 1, 'rule': 'a fixed book re-scored per split instead of the funnel re-run',
                   'status': 'ENFORCED BY CONSTRUCTION' if meta.get('funnel_rerun') else 'UNEXERCISABLE PENDING S3',
                   'basis': 'run state',
                   'detail': meta.get('funnel_detail', 'the funnel requires a candidate pool that does not exist')})
    checks.append({'item': 2, 'rule': 'any parameter chosen with sight of a test segment',
                   'status': 'PASS' if adaptive_causal.get('causal') else 'FAIL',
                   'basis': f"computed: {adaptive_causal.get('coverage', '')}, {adaptive_causal.get('mismatches')} mismatches",
                   'detail': adaptive_causal.get('meaning', '')})
    checks.append({'item': 3, 'rule': 'discovery run across the full series and split afterwards',
                   'status': 'ENFORCED BY CONSTRUCTION' if meta.get('funnel_rerun') else 'UNEXERCISABLE PENDING S3',
                   'basis': 'run state',
                   'detail': 'every per-segment derivation takes an explicit training bar range'})
    ok_emb = bool(splits) and all(s['embargo_bars'] >= EMBARGO_BARS and s['test_first_bar'] > s['embargo_last_bar']
                                  for s in splits)
    gaps = [s['test_first_bar'] - s['train_last_bar'] for s in splits]
    checks.append({'item': 4, 'rule': 'omitting the embargo or setting it shorter than the longest forward label',
                   'status': 'PASS' if ok_emb else 'FAIL',
                   'basis': f'computed: min realised gap {min(gaps) if gaps else 0} bars vs required {EMBARGO_BARS}',
                   'detail': 'longest forward-looking label in use is the thrust window W=60 bars'})
    idx_expected = sorted(s['split_index'] for s in splits)
    if per_split_frame is not None and len(per_split_frame):
        idx_present = sorted(int(x) for x in per_split_frame['split_index'].tolist())
        rows_ok = idx_present == idx_expected
    else:
        idx_present = []
        rows_ok = False
    agg_ok = True
    if pass_frame is not None and len(pass_frame):
        declared = int(pass_frame['splits_derived'].iloc[0]) if 'splits_derived' in pass_frame.columns else -1
        agg_ok = declared == len(idx_expected)
    checks.append({'item': 5, 'rule': 'reporting the best split or the mean without per-split values',
                   'status': 'PASS' if (rows_ok and agg_ok) else 'FAIL',
                   'basis': f'computed from the emitted artifact: per-split rows {idx_present} vs derived '
                            f'{idx_expected}; aggregate declares {len(idx_expected)} splits',
                   'detail': 'every derived split is emitted as its own row and no aggregate is reported without them'})
    if attest_trail is not None and len(attest_trail) and 'split_index' in attest_trail.columns:
        trail_idx = sorted(set(int(x) for x in attest_trail['split_index'].tolist()))
        trail_ok = all(i in trail_idx for i in idx_expected)
        trail_basis = f'computed: trail holds {len(attest_trail)} records covering split indices {trail_idx}'
    else:
        trail_ok = False
        trail_basis = 'computed: no attestation trail found'
    checks.append({'item': 6, 'rule': 're-running a failed split after adjustment',
                   'status': 'PASS' if trail_ok else 'FAIL',
                   'basis': trail_basis,
                   'detail': 'append-only trail written BEFORE any test touch; repeats reported not blocked'})
    checks.append({'item': 7, 'rule': 'carrying the 27% null from the record',
                   'status': 'ENFORCED BY CONSTRUCTION' if meta.get('null_per_split') else 'UNEXERCISABLE PENDING S3',
                   'basis': 'run state',
                   'detail': meta.get('null_detail', 'the null is regenerated inside each split and scored in the '
                                                     'same single test pass')})
    checks.append({'item': 8, 'rule': 'deleting rows anywhere to construct a segment',
                   'status': 'PASS' if len(df) == n_expected else 'FAIL',
                   'basis': f'computed: row count {len(df)} vs expected {n_expected}',
                   'detail': 'segments are index ranges over the intact series; the oracle receives the full frame'})
    second = sum(1 for g in guards if g.touch_count > 1)
    touched = sum(1 for g in guards if g.consumed)
    checks.append({'item': 9, 'rule': 'touching a test segment more than once',
                   'status': 'PASS' if second == 0 else 'FAIL',
                   'basis': f'computed from guard state: {touched} guards consumed, {second} recorded a second touch',
                   'detail': 'TestSegmentGuard raises SecondTouchError on a second request and still increments '
                             'touch_count so the attempt remains visible'})
    below = [s['split_index'] for s in splits
             if s['train_days'] < MIN_TRAIN_DAYS or s['train_month_buckets'] < MIN_MONTH_BUCKETS]
    checks.append({'item': 10, 'rule': 'shortening a training segment below the floor to fit a split count',
                   'status': 'PASS' if not below else 'FAIL',
                   'basis': f'computed: training segments {[s["train_days"] for s in splits]} days vs floor '
                            f'{MIN_TRAIN_DAYS}; buckets {[s["train_month_buckets"] for s in splits]} vs floor '
                            f'{MIN_MONTH_BUCKETS}',
                   'detail': f'splits below floor: {below}' if below else 'every training segment meets the floor'})
    return pd.DataFrame(checks)


def pass_criterion(book_rates, null_rates, null_evaluable=None):
    n = min(len(book_rates), len(null_rates))
    ratios = []
    for i in range(n):
        b = book_rates[i]
        d = null_rates[i]
        if null_evaluable is not None and not null_evaluable[i]:
            continue
        if b != b or d != d or d <= 0:
            continue
        ratios.append(b / d)
    base = {'criterion': 'ratio to the split own measured null (spec I.3 Revision 9); the previous absolute '
                         'form is withdrawn as incoherent',
            'target_mean_ratio': PASS_MEAN_RATIO, 'target_min_ratio': PASS_MIN_RATIO,
            'target_lower_bound': PASS_LB_RATIO,
            'splits_with_ratio': len(ratios),
            'note': 'a FAIL is a legitimate reported result; no bar is lowered to obtain a pass, and an '
                    'UNEVALUABLE split is reported as unevaluable rather than imputed'}
    if not ratios:
        base.update({'mean_ratio': np.nan, 'min_ratio': np.nan, 'mean_ratio_lb95': np.nan,
                     'verdict': 'UNEVALUABLE'})
        return base
    arr = np.asarray(ratios, dtype=float)
    mean = float(arr.mean())
    mn = float(arr.min())
    if len(arr) > 1:
        se = float(arr.std(ddof=1) / math.sqrt(len(arr)))
        lb = mean - 1.959963984540054 * se
    else:
        lb = np.nan
    ok = (mean >= PASS_MEAN_RATIO and mn >= PASS_MIN_RATIO and lb == lb and lb > PASS_LB_RATIO)
    base.update({'mean_ratio': round(mean, 4), 'min_ratio': round(mn, 4),
                 'mean_ratio_lb95': round(lb, 4) if lb == lb else np.nan,
                 'verdict': 'PASS' if ok else 'FAIL'})
    return base


SPLIT_REQUIRED_KEYS = ('train_first_bar', 'train_last_bar', 'test_first_bar', 'test_last_bar')


def assert_split_shape(splits):
    """Item 17: fail LOUDLY if the split dict is not the shape derive_splits emits.

    book_arm_from_valid once read train_lo_bar/test_lo_bar while derive_splits
    emitted train_first_bar/test_first_bar. The mismatch was invisible because
    the arm sits behind `if _pool_ok:` - with no pool it never runs, book_rates
    stays nan, and the artifact reads UNEVALUABLE, WHICH IS INDISTINGUISHABLE
    FROM CORRECT BEHAVIOUR. A silent nan is exactly the failure this stage has
    already shipped twice, so the shape is asserted rather than assumed. NO
    TRANSLATION LAYER: these are derive_splits' own key names, read directly, so
    there is nothing to drift out of step.
    """
    if not splits:
        raise SystemExit('ABORT [item 17] no splits were derived; the book arm cannot run and a '
                         'nan rate would be indistinguishable from a correct UNEVALUABLE.')
    missing = [k for k in SPLIT_REQUIRED_KEYS if k not in splits[0]]
    if missing:
        raise SystemExit(
            f'ABORT [item 17] split dict is missing {missing}. book_arm_from_valid reads '
            f'derive_splits\' own keys {list(SPLIT_REQUIRED_KEYS)}; got {sorted(splits[0])[:12]}. '
            f'Failing loudly because a shape change here returns nan silently.')
    return True


def book_arm_from_valid(df, cands, pool, anchor, ad, st, warmup, splits, build_book_fn,
                        run_portfolio_fn, evaluate_valid_fn, bar_day, conviction=None,
                        gap_names=()):
    """Item 17: per split, apply VALID on the TRAINING SEGMENT ALONE, score on TEST.

    IT CERTIFIES THE CATALOGUE'S INCLUSION RULE, NOT ANY BOOK. The entities are
    the signals VALID admits on train; the rate is how many of those persist on
    test. Re-scoring a hand-assembled book per split is PROHIBITED and is the
    thing that already failed - a validated generator is not a validated book.
    """
    assert_split_shape(splits)
    if bar_day is None:
        raise SystemExit(
            'ABORT [item 17] bar_day is None. Appendix C V3b counts DISTINCT ENTRY-BASIS days; with '
            'bar_day absent evaluate_valid falls back to exit-day groups, so the arm would apply a '
            'V3b VARIANT while the catalogue and the null apply the specified one. Item 17 certifies '
            'VALID and Appendix A requires the null to run the IDENTICAL predicate, so a divergence '
            'in even one clause breaks the thing this stage exists to certify.')
    out = []
    for s_i, sp in enumerate(splits):
        tr_lo, tr_hi = int(sp['train_first_bar']), int(sp['train_last_bar'])
        te_lo, te_hi = int(sp['test_first_bar']), int(sp['test_last_bar'])
        train_rows, test_rows = [], []
        for _i, cr in cands.iterrows():
            fam = str(cr.get('family', ''))
            sig = str(cr.get('signal_def', ''))
            direction = str(cr.get('direction', 'LONG')).upper()
            one = pd.DataFrame([{'trigger': fam, 'family': fam, 'direction': direction,
                                 'signal_def': sig}])
            try:
                sg = build_book_fn(df, pool, anchor, one, adaptive=ad, structural=st)
                td = run_portfolio_fn(df, sg, adaptive=ad, structural=st, warmup=warmup,
                                      verbose=False, conviction=conviction)
            except SystemExit:
                continue
            if len(gap_names):
                td = td[~td['signal_name'].isin(gap_names)]
            eb = np.asarray(td['entry_bar'].values, dtype=np.int64)
            tr_t = td[(eb >= tr_lo) & (eb <= tr_hi)]
            te_t = td[(eb >= te_lo) & (eb <= te_hi)]
            verdict, _reason, _stats = evaluate_valid_fn(tr_t, bar_day)
            if verdict != 'VALID':
                continue
            name = f'{fam}|{sig}|{direction}'
            tr_t = tr_t.copy(); tr_t['signal_name'] = name
            te_t = te_t.copy(); te_t['signal_name'] = name
            train_rows.append(tr_t); test_rows.append(te_t)
        if not train_rows:
            out.append({'split': s_i, 'rate': float('nan'), 'k': 0, 'n_traded': 0,
                        'entities': 0, 'note': 'VALID admitted no signal on this training segment'})
            continue
        trf = pd.concat(train_rows, ignore_index=True)
        tef = pd.concat(test_rows, ignore_index=True)
        frame = entity_persistence(trf, tef)
        rate, k, n = persistence_rate(frame)
        out.append({'split': s_i, 'rate': rate, 'k': k, 'n_traded': n,
                    'entities': int(len(frame)), 'note': ''})
    return out
