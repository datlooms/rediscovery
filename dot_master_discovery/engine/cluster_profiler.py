"""S8B — per-candidate cluster-participation profiler.

Measures, for every single condition in the discovery vocabulary, how that
condition participates in same-direction convergence clusters. It measures; it
does not select, rank into a book, or tune anything.

HARD BOUNDARY — BASIS 3 IS FORWARD-LOOKING BY CONSTRUCTION.
The basis-3 thrust label uses Close[t+W], i.e. information not available at bar
t. That is legitimate for a selection-side diagnostic, because the question
"does this condition fire at the start of moves that turn out big" is inherently
a forward question. It means BASIS 3 CAN NEVER BECOME A LIVE GATE OR AN ENTRY
CONDITION. Anyone trading "thrust" would be trading future information. The
oracle ring for the thrust magnitude/efficiency columns therefore also contains
forward-looking values; this is inherent to the basis and is a further reason it
is selection-side only. The ATR_1M normaliser is taken at bar t and is causal.

COUPLING MITIGATION IMPLEMENTED — mitigation 2 of quant_response_6 §3.
Running depth is both a selection metric here (metric e) and the intended
runtime sizing input; selecting on it and then sizing by it would fit the book
to its own sizing mechanism. Metric (e) is therefore computed and emitted for
BASIS 3 as well as for bases 1 and 2. Price-anchored episodes are defined
without reference to the book or the jar, so "fires early in a thrust" is
measured against market structure rather than against the sizing mechanism's own
object.

METRIC (g) IS SUPPRESSED ON BASIS 3 — EPISODE-STRENGTH SELECTION.
The reason is not that a same-direction trade inside a thrust span wins by
construction: both arms of the participated/non-participated contrast are
already restricted to trades inside basis-3 episodes, so the shared forward-move
conditioning largely cancels in the differential. The actual defect is
episode-strength selection. A condition that fires preferentially in larger or
longer episodes inherits bigger forward moves in its participating arm, so the
contrast can be driven by the magnitude of the forward label rather than by any
difference in entry quality. Every dollar-denominated and outcome-denominated
column on basis 3 is exposed to this, so part_net, non_net, part_pf, part_wr,
part_wd, non_pf, non_wr and non_wd are all emitted empty for cluster_basis = 3.
Only part_clusters is retained, because it is a genuine count and not an
outcome. Basis 3 is instead given COVERAGE ATTRIBUTION (cov_*), which is not
outcome-denominated: it counts the episodes a condition fires in and splits them
by whether the committed book traded that episode at all. The missed set —
episodes where the condition fires and the book is absent — is the population
the basis exists to surface. cov_episodes is an explicit alias of part_clusters,
retained so the cov_* family is self-contained and so the identity
cov_book_traded + cov_book_missed == cov_episodes serves as a consistency check.
The cov_* columns are emitted empty for bases 1 and 2, where they are
meaningless by construction. Bases 1 and 2 keep the full (g) metric, which is
sound there because their clusters are defined by executed or qualifying book
signals, not by a forward price label.

SCOPE LIMIT.
The vocabulary profiled here is SINGLE CONDITIONS; the book's signals are
TRIPLES. A single condition's profile cannot be read as a signal's value, and no
book should be selected directly from this output. It is an input to selection,
not a selection rule.

ELIGIBLE UNIVERSE.
(ADX_Value >= 15) & (Volume > 50) & post-warmup. The Volume == 0 and
Friday-close exclusions carried by run_portfolio's entry_ok are OUT of the
measurement universe: Volume == 0 is already subsumed by Volume > 50, and this
matches build_condition_pool's own scannable definition, which is what defines
the vocabulary being profiled. The identical universe is applied to condition
fires and to every base-rate denominator. Cluster objects keep their native
definitions (book entries require the engine's entry_ok; thrust episodes are
price-anchored), which is a property of the object, not of the measurement.

GATES ARE STATE, NEVER ROW FILTERS. No bar is deleted anywhere in this stage.
Eligibility, validity and warm-up are recorded as boolean state and applied as
masks at measurement time.

All thresholds, including the basis-3 K and E, come from dots_thresholds via its
own compute_adaptive_thresholds (mechanism D, rolling-2500, day-refreshed,
floor-index), including the basis-3 K and E and the ATR strata used for the
volatility-proxy control. No percentile that defines a measured object, event,
cluster, episode, stratum, threshold or entry is computed locally. The only
local percentile calls remaining are pure descriptive output statistics — the
timing quartiles (timing_q1, timing_q3) and depth_at_fire_p90 — which gate
nothing, define nothing, and merely summarise the distribution of fires already
selected by causal means. The oracle is left byte-identical: _D_SPEC is extended
at runtime and restored.
"""

import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine

GAP_NAMES = ('GAP_HURST', 'GAP_FB', 'GAP_D2D')
N_VALUES = (5, 10)
SIZE_BANDS = (3, 5, 8)
MIN_FIRE_FLOOR = 200
THRUST_W = (15, 30)
THRUST_K_PCTS = (0.85, 0.90)
THRUST_E_PCTS = (0.75,)
TIMING_MIN_SIZE = 3
VOL_PROXY_COLLAPSE = 0.70
ATR_BUCKETS = 5
ELIGIBILITY_PREDICATE = '(ADX_Value >= 15) & (Volume > 50) & post-warmup; Volume==0 and Friday-close exclusions OUT'


def eligible_universe(df, warmup):
    n = len(df)
    return (df['ADX_Value'].values >= 15.0) & (df['Volume'].values > 50.0) & (np.arange(n) >= warmup)


def _chain(bars, n_tol):
    out = []
    if len(bars) == 0:
        return out
    start = 0
    for i in range(1, len(bars) + 1):
        if i == len(bars) or (bars[i] - bars[i - 1]) > n_tol:
            out.append((start, i))
            start = i
    return out


def build_cluster_set(n_bars, events_by_dir, n_tol):
    cid = {1: np.full(n_bars, -1, np.int32), -1: np.full(n_bars, -1, np.int32)}
    depth = {1: np.zeros(n_bars, np.int32), -1: np.zeros(n_bars, np.int32)}
    fsize = {1: np.zeros(n_bars, np.int32), -1: np.zeros(n_bars, np.int32)}
    pos = {1: np.full(n_bars, np.nan), -1: np.full(n_bars, np.nan)}
    rows = []
    k = 0
    for d in (1, -1):
        ev = np.sort(np.asarray(events_by_dir.get(d, []), dtype=np.int64))
        for (i0, i1) in _chain(ev, n_tol):
            b0 = int(ev[i0])
            b1 = int(ev[i1 - 1])
            size = int(i1 - i0)
            seg = np.arange(b0, b1 + 1)
            cid[d][seg] = k
            depth[d][seg] = np.searchsorted(ev[i0:i1], seg, side='right')
            fsize[d][seg] = size
            if b1 > b0:
                pos[d][seg] = (seg - b0) / float(b1 - b0)
            rows.append({'cluster_id': k, 'dir': d, 'size': size, 'b0': b0, 'b1': b1, 'span': b1 - b0})
            k += 1
    clusters = pd.DataFrame(rows) if rows else pd.DataFrame(columns=['cluster_id', 'dir', 'size', 'b0', 'b1', 'span'])
    return {'cid': cid, 'depth': depth, 'fsize': fsize, 'pos': pos, 'clusters': clusters}


def book_events(td):
    bk = td[~td['signal_name'].isin(GAP_NAMES)]
    out = {}
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        out[d] = np.sort(bk[bk['direction'] == lab]['entry_bar'].values.astype(np.int64))
    return out, bk


def qualifying_events(df, sigs, ad, st, warmup):
    n = len(df)
    warm = np.arange(n) < warmup
    eligible = (df['ADX_Value'].values >= 15) & (df['Volume'].values > 50)
    vol_zero = df['Volume'].values == 0
    fri_block = (df['EST_DayOfWeek'].values == 5) & ((df['EST_Hour'].values > 16) | ((df['EST_Hour'].values == 16) & (df['EST_Minute'].values >= 45)))
    entry_ok = eligible & ~vol_zero & ~fri_block & ~warm
    masks, dirs, _names = engine.build_signal_masks(df, sigs, ad, st, entry_ok, verbose=False)
    out = {}
    depth_per_bar = {}
    for d in (1, -1):
        cnt = np.zeros(n, np.int32)
        for m, sd in zip(masks, dirs):
            if sd == d:
                cnt += m.astype(np.int32)
        depth_per_bar[d] = cnt
        out[d] = np.repeat(np.flatnonzero(cnt), cnt[cnt > 0])
    return out, depth_per_bar


def _swept(df, specs):
    saved = dict(dt._D_SPEC)
    try:
        dt._D_SPEC.clear()
        dt._D_SPEC.update(specs)
        out = dt.compute_adaptive_thresholds(df)
    finally:
        dt._D_SPEC.clear()
        dt._D_SPEC.update(saved)
    return out


def thrust_state(df, W):
    c = df['Close'].values.astype(float)
    atr = df['ATR_1M'].values.astype(float)
    n = len(df)
    absd = np.abs(np.diff(c, prepend=c[0]))
    cs = np.cumsum(absd)
    fwd = np.zeros(n)
    path = np.zeros(n)
    valid = np.zeros(n, bool)
    fwd[:n - W] = c[W:] - c[:n - W]
    path[:n - W] = cs[W:] - cs[:n - W]
    valid[:n - W] = True
    mag = np.zeros(n)
    nz = atr > 0.0
    mag[nz] = np.abs(fwd[nz]) / atr[nz]
    eff = np.zeros(n)
    pz = path > 0.0
    eff[pz] = np.abs(fwd[pz]) / path[pz]
    return fwd, mag, eff, valid


def thrust_thresholds(df, W, k_pcts, e_pcts):
    fwd, mag, eff, valid = thrust_state(df, W)
    mcol = f'__THRUST_MAG_W{W}'
    ecol = f'__THRUST_EFF_W{W}'
    df[mcol] = mag
    df[ecol] = eff
    spec = {}
    for kp in k_pcts:
        spec[(mcol, f'k{int(round(kp * 100))}')] = (mcol, kp)
    for ep in e_pcts:
        spec[(ecol, f'e{int(round(ep * 100))}')] = (ecol, ep)
    try:
        thr = _swept(df, spec)
    finally:
        df.drop(columns=[mcol, ecol], inplace=True)
    return fwd, mag, eff, valid, thr, mcol, ecol


def thrust_events(fwd, mag, eff, valid, karr, earr, warmup):
    n = len(fwd)
    postwarm = np.arange(n) >= warmup
    qual = valid & postwarm & (fwd != 0.0) & (mag >= karr) & (eff >= earr)
    sgn = np.sign(fwd)
    return {1: np.flatnonzero(qual & (sgn > 0)).astype(np.int64),
            -1: np.flatnonzero(qual & (sgn < 0)).astype(np.int64)}


def map_trades_to_clusters(cs, bk):
    bars = bk['entry_bar'].values.astype(np.int64)
    dirs = np.where(bk['direction'].values == 'LONG', 1, -1)
    out = np.full(len(bk), -1, np.int32)
    for d in (1, -1):
        sel = dirs == d
        if sel.any():
            out[sel] = cs['cid'][d][bars[sel]]
    return out


def _pf(x):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return 0.0
    loss = -x[x < 0].sum()
    if loss <= 0:
        return 999.0 if x.sum() > 0 else 0.0
    return round(float(x[x > 0].sum() / loss), 3)


def _outcome(pnl, dates):
    if len(pnl) == 0:
        return 0.0, 0.0, 0.0, 0.0
    net = round(float(pnl.sum()), 1)
    pf = _pf(pnl)
    wr = round(float((pnl > 0).mean() * 100), 1)
    s = pd.Series(pnl).groupby(pd.Series(dates)).sum()
    wd = round(float(s.min()), 1)
    return net, pf, wr, wd


def profile_conditions(pool, cs, U, df, bk, trade_cid, basis, n_tol, grid, hours, atr_bucket):
    n = len(U)
    n_elig = int(U.sum())
    dirs = (1, -1)
    in_band = {}
    for k in SIZE_BANDS:
        per_dir = {d: (cs['cid'][d] >= 0) & (cs['fsize'][d] >= k) for d in dirs}
        per_dir['any'] = per_dir[1] | per_dir[-1]
        in_band[k] = per_dir
    base_rate = {k: float((in_band[k]['any'] & U).sum()) / n_elig if n_elig else 0.0 for k in SIZE_BANDS}
    timing_ok = {d: (cs['cid'][d] >= 0) & (cs['fsize'][d] >= TIMING_MIN_SIZE) & np.isfinite(cs['pos'][d]) for d in dirs}
    timing_zero = {d: (cs['cid'][d] >= 0) & (cs['fsize'][d] >= TIMING_MIN_SIZE) & ~np.isfinite(cs['pos'][d]) for d in dirs}
    shallow_m = {d: (cs['cid'][d] >= 0) & (cs['depth'][d] >= 1) & (cs['depth'][d] <= 2) & (cs['fsize'][d] >= 5) for d in dirs}
    pile_m = {d: (cs['cid'][d] >= 0) & (cs['depth'][d] >= 5) for d in dirs}
    incl = {d: cs['cid'][d] >= 0 for d in dirs}
    pnl = bk['pnl'].values.astype(float)
    dates = pd.Series(bk['exit_time'].values).str[:10].values
    band_cluster_ids = {}
    for k in SIZE_BANDS:
        cl = cs['clusters']
        band_cluster_ids[k] = set(cl[cl['size'] >= k]['cluster_id'].tolist()) if len(cl) else set()
    traded_ids = set(np.unique(trade_cid[trade_cid >= 0]).tolist())
    nb = ATR_BUCKETS
    rows = []
    for name, mask in pool.items():
        fm = mask & U
        fires = int(fm.sum())
        rec = {'condition': name, 'cluster_basis': basis, 'N': n_tol,
               'W': grid[0], 'K_pct': grid[1], 'E_pct': grid[2],
               'eligible_bars': n_elig, 'fires': fires,
               'fire_share_pct': round(100.0 * fires / n_elig, 4) if n_elig else 0.0,
               'min_fire_ok': bool(fires >= MIN_FIRE_FLOOR)}
        for k in SIZE_BANDS:
            pa = int((fm & in_band[k]['any']).sum())
            pl = int((fm & in_band[k][1]).sum())
            ps = int((fm & in_band[k][-1]).sum())
            rate = pa / fires if fires else 0.0
            rec[f'part_count_{k}'] = pa
            rec[f'part_rate_{k}'] = round(100.0 * rate, 4)
            rec[f'lift_{k}'] = round(rate / base_rate[k], 3) if base_rate[k] > 0 else 0.0
            rec[f'part_long_{k}'] = pl
            rec[f'part_short_{k}'] = ps
            rec[f'base_rate_{k}'] = round(100.0 * base_rate[k], 4)
        tvals = np.concatenate([cs['pos'][d][fm & timing_ok[d]] for d in dirs]) if fires else np.array([])
        rec['timing_n'] = int(len(tvals))
        rec['timing_excluded_zero_span'] = int(sum(int((fm & timing_zero[d]).sum()) for d in dirs))
        if len(tvals):
            rec['timing_median'] = round(float(np.median(tvals)), 4)
            rec['timing_q1'] = round(float(np.percentile(tvals, 25)), 4)
            rec['timing_q3'] = round(float(np.percentile(tvals, 75)), 4)
        else:
            rec['timing_median'] = ''
            rec['timing_q1'] = ''
            rec['timing_q3'] = ''
        shallow = int(sum(int((fm & shallow_m[d]).sum()) for d in dirs))
        pile = int(sum(int((fm & pile_m[d]).sum()) for d in dirs))
        rec['shallow_edge_count'] = shallow
        rec['pile_on_count'] = pile
        rec['shallow_pile_ratio'] = round(shallow / pile, 3) if pile else ''
        dvals = np.concatenate([cs['depth'][d][fm & incl[d]] for d in dirs]) if fires else np.array([])
        rec['depth_at_fire_median'] = round(float(np.median(dvals)), 2) if len(dvals) else ''
        rec['depth_at_fire_p90'] = round(float(np.percentile(dvals, 90)), 2) if len(dvals) else ''
        h5 = hours[fm & in_band[5]['any']]
        if len(h5):
            hc = np.bincount(h5.astype(int), minlength=24)
            rec['peak_hour_size5'] = int(np.argmax(hc))
            rec['share_1100_1300_size5'] = round(100.0 * hc[11:14].sum() / hc.sum(), 2)
            rec['hour_hist_size5'] = ';'.join(str(int(x)) for x in hc)
        else:
            rec['peak_hour_size5'] = ''
            rec['share_1100_1300_size5'] = ''
            rec['hour_hist_size5'] = ''
        for k in (3, 5):
            ids = np.concatenate([cs['cid'][d][fm & in_band[k][d]] for d in dirs]) if fires else np.array([], dtype=np.int32)
            part_ids = set(np.unique(ids).tolist())
            allowed = band_cluster_ids[k]
            in_part = np.isin(trade_cid, list(part_ids)) if part_ids else np.zeros(len(trade_cid), bool)
            in_band_tr = np.isin(trade_cid, list(allowed)) if allowed else np.zeros(len(trade_cid), bool)
            pnet, ppf, pwr, pwd = _outcome(pnl[in_part & in_band_tr], dates[in_part & in_band_tr])
            nnet, npf, nwr, nwd = _outcome(pnl[~in_part & in_band_tr], dates[~in_part & in_band_tr])
            if basis == 3:
                pnet = ''
                nnet = ''
                ppf = ''
                pwr = ''
                pwd = ''
                npf = ''
                nwr = ''
                nwd = ''
            rec[f'part_clusters_{k}'] = len(part_ids)
            rec[f'part_net_{k}'] = pnet
            rec[f'part_pf_{k}'] = ppf
            rec[f'part_wr_{k}'] = pwr
            rec[f'part_wd_{k}'] = pwd
            rec[f'non_net_{k}'] = nnet
            rec[f'non_pf_{k}'] = npf
            rec[f'non_wr_{k}'] = nwr
            rec[f'non_wd_{k}'] = nwd
            if basis == 3:
                traded = part_ids & traded_ids
                missed = len(part_ids) - len(traded)
                rec[f'cov_episodes_{k}'] = len(part_ids)
                rec[f'cov_book_traded_{k}'] = len(traded)
                rec[f'cov_book_missed_{k}'] = missed
                rec[f'cov_missed_share_{k}'] = round(missed / len(part_ids), 4) if part_ids else ''
            else:
                rec[f'cov_episodes_{k}'] = ''
                rec[f'cov_book_traded_{k}'] = ''
                rec[f'cov_book_missed_{k}'] = ''
                rec[f'cov_missed_share_{k}'] = ''
        num = 0.0
        den = 0
        for b in range(nb):
            bm = atr_bucket == b
            ub = U & bm
            nub = int(ub.sum())
            if nub == 0:
                continue
            fb = int((fm & bm).sum())
            if fb == 0:
                continue
            br = float((in_band[5]['any'] & ub).sum()) / nub
            if br <= 0:
                continue
            num += fb * ((int((fm & bm & in_band[5]['any']).sum()) / fb) / br)
            den += fb
        lift_ctrl = round(num / den, 3) if den else 0.0
        rec['lift_5_atr_controlled'] = lift_ctrl
        rec['vol_proxy_flag'] = bool(rec['lift_5'] > 1.0 and lift_ctrl < VOL_PROXY_COLLAPSE * rec['lift_5'])
        rows.append(rec)
    return rows


def atr_buckets(df, U, nb=ATR_BUCKETS):
    n = len(df)
    out = np.full(n, -1, np.int8)
    if nb < 2:
        return out
    pcts = [i / float(nb) for i in range(1, nb)]
    spec = {}
    for p in pcts:
        spec[('ATR_1M', f'q{int(round(p * 100))}')] = ('ATR_1M', p)
    thr = _swept(df, spec)
    atr = df['ATR_1M'].values.astype(float)
    b = np.zeros(n, np.int8)
    for p in pcts:
        b = b + (atr > thr[('ATR_1M', f'q{int(round(p * 100))}')]).astype(np.int8)
    out[U] = b[U]
    return out


def _cover_mask(cs, n_bars, min_size=5):
    cover = np.zeros(n_bars, bool)
    for d in (1, -1):
        cover |= (cs['cid'][d] >= 0) & (cs['fsize'][d] >= min_size)
    return cover


def overlap_validation(thrust_cs, cs_book, cs_qual, n_bars, U):
    cov_b1 = _cover_mask(cs_book, n_bars)
    cov_b2 = _cover_mask(cs_qual, n_bars)
    cov_any = cov_b1 | cov_b2
    cl = thrust_cs['clusters']
    ep_tot = len(cl)
    ep_hit = 0
    for _i, r in cl.iterrows():
        if cov_any[int(r['b0']):int(r['b1']) + 1].any():
            ep_hit += 1
    thrust_bars = np.zeros(n_bars, bool)
    for d in (1, -1):
        thrust_bars |= thrust_cs['cid'][d] >= 0
    tb = int((thrust_bars & U).sum())
    tb_hit = int((thrust_bars & cov_any & U).sum())
    cb = int((cov_any & U).sum())
    cb_hit = int((cov_any & thrust_bars & U).sum())
    return {'episodes': ep_tot, 'episodes_hit': ep_hit,
            'episode_pct': round(100.0 * ep_hit / ep_tot, 1) if ep_tot else 0.0,
            'thrust_bars': tb, 'thrust_bars_in_cluster_pct': round(100.0 * tb_hit / tb, 1) if tb else 0.0,
            'cluster_bars': cb, 'cluster_bars_in_thrust_pct': round(100.0 * cb_hit / cb, 1) if cb else 0.0,
            'b1_only_pct': round(100.0 * int((thrust_bars & cov_b1 & U).sum()) / tb, 1) if tb else 0.0,
            'b2_only_pct': round(100.0 * int((thrust_bars & cov_b2 & U).sum()) / tb, 1) if tb else 0.0}


def directional_baseline(df, W, k_pct, e_pct, warmup, mask_name):
    fwd, mag, eff, valid, thr, mcol, ecol = thrust_thresholds(df, W, (k_pct,), (e_pct,))
    karr = thr[(mcol, f'k{int(round(k_pct * 100))}')]
    earr = thr[(ecol, f'e{int(round(e_pct * 100))}')]
    n = len(df)
    if mask_name == 'post-warmup':
        U = np.arange(n) >= warmup
    else:
        U = eligible_universe(df, warmup)
    qual = valid & U & (fwd != 0.0) & (mag >= karr) & (eff >= earr)
    up = qual & (fwd > 0)
    dn = qual & (fwd < 0)
    tot = int(up.sum() + dn.sum())
    rows = [{'scope': 'ALL', 'direction': 'UP', 'thrust_bars': int(up.sum()),
             'share_pct': round(100.0 * up.sum() / tot, 1) if tot else 0.0,
             'median_move_pts': round(float(np.median(np.abs(fwd[up]))), 1) if up.any() else 0.0},
            {'scope': 'ALL', 'direction': 'DOWN', 'thrust_bars': int(dn.sum()),
             'share_pct': round(100.0 * dn.sum() / tot, 1) if tot else 0.0,
             'median_move_pts': round(float(np.median(np.abs(fwd[dn]))), 1) if dn.any() else 0.0}]
    months = pd.Series(df['Time'].astype(str).values).str[:7].values
    closes = df['Close'].values.astype(float)
    for m in sorted(set(months)):
        mm = months == m
        u = int((up & mm).sum())
        d = int((dn & mm).sum())
        if u + d == 0:
            continue
        idx = np.flatnonzero(mm)
        rows.append({'scope': m, 'direction': 'DOWN_SHARE', 'thrust_bars': u + d,
                     'share_pct': round(100.0 * d / (u + d), 1),
                     'median_move_pts': round(float(closes[idx[-1]] - closes[idx[0]]), 0)})
    out = pd.DataFrame(rows)
    out['W'] = W
    out['K_pct'] = k_pct
    out['E_pct'] = e_pct
    out['mask'] = mask_name
    return out


def episode_traded_split(df, W, k_pct, e_pct, n_tol, warmup, bk):
    fwd, mag, eff, valid, thr, mcol, ecol = thrust_thresholds(df, W, (k_pct,), (e_pct,))
    karr = thr[(mcol, f'k{int(round(k_pct * 100))}')]
    earr = thr[(ecol, f'e{int(round(e_pct * 100))}')]
    ev = thrust_events(fwd, mag, eff, valid, karr, earr, warmup)
    n = len(df)
    cs = build_cluster_set(n, ev, n_tol)
    tcid = map_trades_to_clusters(cs, bk)
    traded = set(np.unique(tcid[tcid >= 0]).tolist())
    cl = cs['clusters']
    closes = df['Close'].values.astype(float)
    rows = []
    strata = [('<50', 0.0, 50.0), ('50-100', 50.0, 100.0), ('100-200', 100.0, 200.0), ('>200', 200.0, 1e12)]
    for d, lab in ((1, 'UP'), (-1, 'DOWN')):
        sub = cl[cl['dir'] == d]
        tot = len(sub)
        tr = len(set(sub['cluster_id'].tolist()) & traded)
        rows.append({'stratum': 'ALL', 'direction': lab, 'episodes': tot, 'traded': tr,
                     'traded_pct': round(100.0 * tr / tot, 1) if tot else 0.0,
                     'missed_pct': round(100.0 * (tot - tr) / tot, 1) if tot else 0.0})
        for slab, lo, hi in strata:
            mv = np.abs(closes[np.minimum(sub['b1'].values + W, n - 1)] - closes[sub['b0'].values])
            sel = (mv >= lo) & (mv < hi)
            ssub = sub[sel]
            st = len(ssub)
            str_tr = len(set(ssub['cluster_id'].tolist()) & traded)
            rows.append({'stratum': slab, 'direction': lab, 'episodes': st, 'traded': str_tr,
                         'traded_pct': round(100.0 * str_tr / st, 1) if st else 0.0,
                         'missed_pct': round(100.0 * (st - str_tr) / st, 1) if st else 0.0})
    out = pd.DataFrame(rows)
    out['W'] = W
    out['K_pct'] = k_pct
    out['E_pct'] = e_pct
    out['N'] = n_tol
    return out


def missed_reason_decomposition(df, W, k_pct, e_pct, n_tol, warmup, bk, qual_depth):
    fwd, mag, eff, valid, thr, mcol, ecol = thrust_thresholds(df, W, (k_pct,), (e_pct,))
    karr = thr[(mcol, f'k{int(round(k_pct * 100))}')]
    earr = thr[(ecol, f'e{int(round(e_pct * 100))}')]
    ev = thrust_events(fwd, mag, eff, valid, karr, earr, warmup)
    n = len(df)
    cs = build_cluster_set(n, ev, n_tol)
    tcid = map_trades_to_clusters(cs, bk)
    traded = set(np.unique(tcid[tcid >= 0]).tolist())
    cl = cs['clusters']
    closes = df['Close'].values.astype(float)
    a = 0
    b = 0
    a_mv = []
    b_mv = []
    for _i, r in cl.iterrows():
        cid = int(r['cluster_id'])
        if cid in traded:
            continue
        d = int(r['dir'])
        b0 = int(r['b0'])
        b1 = int(r['b1'])
        mv = abs(float(closes[min(b1 + W, n - 1)] - closes[b0]))
        if qual_depth[d][b0:b1 + 1].sum() == 0:
            a += 1
            a_mv.append(mv)
        else:
            b += 1
            b_mv.append(mv)
    tot = a + b
    return pd.DataFrame([
        {'reason': 'A - no book signal ever qualified in span', 'count': a,
         'share_pct': round(100.0 * a / tot, 1) if tot else 0.0,
         'median_move_pts': round(float(np.median(a_mv)), 1) if a_mv else 0.0},
        {'reason': 'B - a signal qualified but no entry resulted', 'count': b,
         'share_pct': round(100.0 * b / tot, 1) if tot else 0.0,
         'median_move_pts': round(float(np.median(b_mv)), 1) if b_mv else 0.0},
    ]).assign(W=W, K_pct=k_pct, E_pct=e_pct, N=n_tol, total_missed=tot)


def book_depth_structure(bk, n_tol, n_bars):
    rows = []
    for d, lab in ((1, 'LONG'), (-1, 'SHORT')):
        sub = bk[bk['direction'] == ('LONG' if d == 1 else 'SHORT')]
        ev = {d: np.sort(sub['entry_bar'].values.astype(np.int64)), -d: np.array([], dtype=np.int64)}
        cs = build_cluster_set(n_bars, ev, n_tol)
        cl = cs['clusters']
        cl = cl[cl['dir'] == d]
        sizes = cl['size'].values if len(cl) else np.array([0])
        rows.append({'direction': lab, 'signals': int(sub['signal_name'].nunique()),
                     'clusters': int(len(cl)), 'mean_depth': round(float(sizes.mean()), 2),
                     'max_depth': int(sizes.max()),
                     'reach_ge5_pct': round(100.0 * float((sizes >= 5).mean()), 1),
                     'solo_pct': round(100.0 * float((sizes == 1).mean()), 1)})
    return pd.DataFrame(rows).assign(N=n_tol)
