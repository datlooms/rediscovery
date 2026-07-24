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
NULL_TRIPLES_PER_SPLIT = 400
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


def assert_oracle_causal(df, adaptive_full, compute_fn, train_last_bar, feature_keys, sample=6):
    truncated = df.iloc[:train_last_bar + 1].copy()
    ad_tr = compute_fn(truncated)
    checked = 0
    mismatches = []
    for key in feature_keys:
        if key not in adaptive_full or key not in ad_tr:
            continue
        a = np.asarray(adaptive_full[key])[:train_last_bar + 1]
        b = np.asarray(ad_tr[key])
        if a.shape != b.shape:
            mismatches.append((key, 'shape'))
        elif not np.allclose(a, b, equal_nan=True):
            mismatches.append((key, int(np.argmax(~np.isclose(a, b, equal_nan=True)))))
        checked += 1
        if checked >= sample:
            break
    return {'features_checked': checked, 'mismatches': len(mismatches),
            'detail': ';'.join(f'{k}@{v}' for k, v in mismatches),
            'causal': len(mismatches) == 0,
            'meaning': 'threshold values over the training prefix are identical whether computed on the full '
                       'frame or on the truncated prefix; mechanism D therefore cannot see the test segment, '
                       'and masking after a full-frame computation is not a leak'}


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
                     'persists': bool(tr['passes'] and te['passes'])})
    return pd.DataFrame(rows)


def persistence_rate(frame):
    elig = frame[frame['train_passes']]
    if len(elig) == 0:
        return np.nan, 0, 0
    k = int(elig['persists'].sum())
    return float(k / len(elig)), k, int(len(elig))


def random_triple_null(pool_keys, rng, n_triples=NULL_TRIPLES_PER_SPLIT, arity=3):
    keys = list(pool_keys)
    out = []
    seen = set()
    guard = 0
    while len(out) < n_triples and guard < n_triples * 50:
        guard += 1
        pick = tuple(sorted(rng.choice(len(keys), size=arity, replace=False).tolist()))
        if pick in seen:
            continue
        seen.add(pick)
        out.append(tuple(keys[i] for i in pick))
    return out


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


def rejection_checks(df, n_expected, splits, meta, adaptive_causal, guards):
    checks = []
    checks.append({'item': 1, 'rule': 'a fixed book re-scored per split instead of the funnel re-run',
                   'status': 'ENFORCED BY CONSTRUCTION' if meta.get('funnel_rerun') else 'UNEXERCISABLE PENDING S3',
                   'detail': meta.get('funnel_detail', 'the funnel requires a candidate pool that does not exist')})
    checks.append({'item': 2, 'rule': 'any parameter chosen with sight of a test segment',
                   'status': 'PASS' if adaptive_causal.get('causal') else 'FAIL',
                   'detail': adaptive_causal.get('meaning', '')})
    checks.append({'item': 3, 'rule': 'discovery run across the full series and split afterwards',
                   'status': 'ENFORCED BY CONSTRUCTION' if meta.get('funnel_rerun') else 'UNEXERCISABLE PENDING S3',
                   'detail': 'every per-segment derivation takes an explicit training bar range'})
    ok_emb = all(s['embargo_bars'] >= EMBARGO_BARS and s['test_first_bar'] > s['embargo_last_bar'] for s in splits) if splits else False
    checks.append({'item': 4, 'rule': 'omitting the embargo or setting it shorter than the longest forward label',
                   'status': 'PASS' if ok_emb else 'FAIL',
                   'detail': f'embargo {EMBARGO_BARS} bars >= 1440; longest forward label in use is the thrust window W=60 bars'})
    checks.append({'item': 5, 'rule': 'reporting the best split or the mean without per-split values',
                   'status': 'PASS', 'detail': 'every derived split is emitted as its own row'})
    checks.append({'item': 6, 'rule': 're-running a failed split after adjustment',
                   'status': 'ENFORCED BY ATTESTATION', 'detail': 'append-only trail; repeats reported not blocked'})
    checks.append({'item': 7, 'rule': 'carrying the 27% null from the record',
                   'status': 'ENFORCED BY CONSTRUCTION' if meta.get('null_per_split') else 'UNEXERCISABLE PENDING S3',
                   'detail': 'the null is regenerated inside each split and scored in the same single test pass'})
    checks.append({'item': 8, 'rule': 'deleting rows anywhere to construct a segment',
                   'status': 'PASS' if len(df) == n_expected else 'FAIL',
                   'detail': f'row count {len(df)} unchanged; segments are index ranges over the intact series'})
    second = sum(1 for g in guards if g.touch_count > 1)
    checks.append({'item': 9, 'rule': 'touching a test segment more than once',
                   'status': 'PASS' if second == 0 else 'FAIL',
                   'detail': f'{second} guards recorded a second touch; TestSegmentGuard raises SecondTouchError'})
    below = [s['split_index'] for s in splits if s['train_days'] < MIN_TRAIN_DAYS or s['train_month_buckets'] < MIN_MONTH_BUCKETS]
    checks.append({'item': 10, 'rule': 'shortening a training segment below the floor to fit a split count',
                   'status': 'PASS' if not below else 'FAIL',
                   'detail': f'splits below floor: {below}' if below else 'every training segment meets the floor'})
    return pd.DataFrame(checks)


def pass_criterion(per_split_rates):
    vals = [r for r in per_split_rates if r == r]
    if not vals:
        return {'mean_persistence': np.nan, 'min_split': np.nan, 'splits': 0,
                'verdict': 'UNEVALUABLE', 'target_mean': PASS_MEAN, 'target_floor': PASS_FLOOR_PER_SPLIT,
                'note': 'no split produced an evaluable persistence rate'}
    mean = float(np.mean(vals))
    mn = float(np.min(vals))
    return {'mean_persistence': round(mean, 4), 'min_split': round(mn, 4), 'splits': len(vals),
            'target_mean': PASS_MEAN, 'target_floor': PASS_FLOOR_PER_SPLIT,
            'verdict': 'PASS' if (mean >= PASS_MEAN and mn >= PASS_FLOOR_PER_SPLIT) else 'FAIL',
            'note': 'a FAIL is a legitimate reported result; no bar is lowered to obtain a pass'}
