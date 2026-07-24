import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 1 — SEQUENTIAL / TEMPORAL  (discovery scanner)
#  Relationship: an ordered PAIR over time — condition A leads condition B by
#  k bars: signal[t] = A@(t-k) AND B@t. NOT same-bar (that is F0's domain);
#  the 3-leg triple is intractable at full scope AND re-searches F0 with lags
#  bolted on, so F1's unique job (ordering / lead-lag) is expressed by the
#  ordered pair. Order matters: A->B != B->A. Anchored to a timing event on
#  leg A's bar (ST_Flip_Event / D2D_Signal), shifted by k, per the map.
#
#  Thresholds: oracle-only, via engine.condition_mask (dots_thresholds).
#  Trade management: the locked S.7 engine — the completed signature is
#  injected as a one-column '==1' signal and driven through
#  engine.run_portfolio; ZERO TM reconstruction.
#  D2D gate: confirm (entry dir == D2D_Trend_Dir) — applied by the engine.
#  Scoring: survival-first walk-forward via wf.py primitives.
#  F1 is new-derived-input tier: the lag/sequence latch is computed here in
#  Python on the sealed baseline — analysis-only; production parity is a
#  Stage-9 concern, not a discovery blocker.
# ═══════════════════════════════════════════════════════════════

LAGS = list(range(1, 16))
MIN_TRADES = 30
SEQ_COL = '__F1SEQ'

EQUALITY_CANDIDATES = [
    'D2D_Signal', 'D2D_DirStep', 'OBVf_Signal', 'OBVf_Trend_Dir',
    'Harmonic_OBVf_Concordance', 'Harmonic_D2D_Concordance', 'ADX_Rising',
    'Sqz_State', 'RangeOsc_State', 'PoC_Side', 'ST_Flip_Event',
    'Trend_Concordance', 'Trend_Conflict', 'AT_Regime_ST', 'AT_Regime_LT',
    'VWAP_Side', 'VAH_Side', 'VAL_Side', 'PrevDay_High_Side', 'PrevDay_Low_Side',
    'PrevDay_Close_Side', 'DailyOpen_Side', 'OR_High_Side', 'OR_Low_Side',
    'Session_High_Side', 'Session_Low_Side', 'WeeklyOpen_Side',
]


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited timing/gate columns dead or missing: {dead}")
    return True


def build_condition_pool(df, adaptive, structural, warmup):
    feat_candidates = list(dt._D_COLS) + ['VWAP_Z', 'OR_Position']
    assert len(feat_candidates) == 90, f"FEAT count {len(feat_candidates)} != 90"
    pool = {}
    for feat in feat_candidates:
        pool[f"{feat}:hi"] = engine.condition_mask(df, feat, 'hi', adaptive, structural)
        pool[f"{feat}:lo"] = engine.condition_mask(df, feat, 'lo', adaptive, structural)
    nonwarm = np.arange(len(df)) >= warmup
    eligible = (df['ADX_Value'].values >= 15) & (df['Volume'].values > 50)
    scannable = eligible & nonwarm
    n_eq = 0
    for feat in EQUALITY_CANDIDATES:
        for v in sorted(set(int(x) for x in df[feat].values[scannable])):
            pool[f"{feat}:=={v}"] = engine.condition_mask(df, feat, f"=={v}", adaptive, structural)
            n_eq += 1
    print(f"Condition pool: {len(feat_candidates)}x2 FEAT_ (hi/lo) + {n_eq} equality "
          f"= {len(pool)} conditions")
    return pool


def lag_shift(mask, k):
    if k == 0:
        return mask.copy()
    out = np.zeros_like(mask)
    out[k:] = mask[:-k]
    return out


def pair_mask(a_mask, b_mask, k, anchor_event):
    seq = lag_shift(a_mask, k) & b_mask
    if anchor_event is not None:
        seq = seq & lag_shift(anchor_event, k)
    return seq


def anchor_array(df, anchor):
    if anchor == 'none':
        return None
    if anchor == 'ST_Flip':
        return df['ST_Flip_Event'].values != 0
    if anchor == 'D2D_Signal':
        return df['D2D_Signal'].values != 0
    raise ValueError(f"unknown anchor '{anchor}'")


def score_candidate(df, seq, direction, month, adaptive, structural, warmup):
    df[SEQ_COL] = seq.astype(int)
    sig = pd.DataFrame([{
        'feat_1': SEQ_COL, 'thresh_1': '==1',
        'feat_2': SEQ_COL, 'thresh_2': '==1',
        'feat_3': SEQ_COL, 'thresh_3': '==1',
        'direction': direction,
    }])
    full = engine.run_portfolio(df, sig, mask_window=None, adaptive=adaptive,
                                structural=structural, warmup=warmup, verbose=False)
    if len(full) < MIN_TRADES:
        return None
    fold_rows = []
    fold_trades = []
    for label, mkey in wf.FOLDS:
        td = engine.run_portfolio(df, sig, mask_window=(month == mkey), adaptive=adaptive,
                                  structural=structural, warmup=warmup, verbose=False)
        fold_rows.append(wf.fold_metrics(td, label))
        if len(td):
            fold_trades.append(td)
    all_trades = pd.concat(fold_trades, ignore_index=True) if fold_trades else pd.DataFrame(columns=['pnl', 'exit_time'])
    n_total = len(all_trades)
    agg_pnls = all_trades['pnl'].values if n_total else np.array([])
    agg_pf = round(wf.pf_from_pnls(agg_pnls), 2)
    agg_wr = round((agg_pnls > 0).sum() / n_total * 100.0, 1) if n_total else 0.0
    agg_daily = wf.daily_pnl_points(all_trades)
    agg_daily_usd = wf.points_to_usd(agg_daily['pnl'].values) if len(agg_daily) else np.array([])
    worst_day_usd = float(agg_daily_usd.min()) if len(agg_daily_usd) else 0.0
    hard_stop = int((agg_daily_usd <= -wf.DAILY_LOSS_CEILING_USD).sum())
    survival_pass = worst_day_usd > -wf.DAILY_LOSS_CEILING_USD
    profitable_folds = sum(1 for r in fold_rows if r['total_pnl'] > 0)
    fold_pfs = [r['pf'] for r in fold_rows if r['trades'] > 0]
    min_fold_pf = min(fold_pfs) if fold_pfs else 0.0
    pf_base, pf_stress = wf.spread_stress(all_trades)
    return {
        'trades': n_total, 'agg_pf': agg_pf, 'agg_wr': agg_wr,
        'worst_day_usd': round(worst_day_usd, 1), 'hard_stop_days': hard_stop,
        'survival_pass': survival_pass, 'profitable_folds': profitable_folds,
        'min_fold_pf': min_fold_pf, 'pf_base': pf_base, 'pf_stress': pf_stress,
    }


def scorable_pool(pool, warmup):
    nonwarm = None
    labels = []
    for lbl, m in pool.items():
        if nonwarm is None:
            nonwarm = np.arange(len(m)) >= warmup
        if int(m[nonwarm].sum()) >= MIN_TRADES:
            labels.append(lbl)
    print(f"Scorable pool: {len(labels)} of {len(pool)} conditions with "
          f">= {MIN_TRADES} post-warmup activations (rest fire too rarely to reach the floor)")
    return labels


def run_search(df, pool, cond_labels, lags, anchor, directions,
               adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    anchor_event = anchor_array(df, anchor)
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    results = []
    ordered_pairs = [(a, b) for a in cond_labels for b in cond_labels]
    total = len(ordered_pairs) * len(lags) * len(directions)
    print(f"\nSearch: {len(cond_labels)}^2 = {len(ordered_pairs)} ordered pairs (A->B) x "
          f"{len(lags)} lags x {len(directions)} dir = {total} candidates | anchor={anchor}")
    tested = 0
    for a_lbl, b_lbl in ordered_pairs:
        a_mask = pool[a_lbl]
        b_mask = pool[b_lbl]
        for k in lags:
            seq = pair_mask(a_mask, b_mask, k, anchor_event)
            if seq.sum() < MIN_TRADES:
                continue
            for direction in directions:
                sc = score_candidate(df, seq, direction, month, adaptive, structural, warmup)
                tested += 1
                if sc is None:
                    continue
                sc.update({'A': a_lbl, 'B': b_lbl, 'k': k, 'direction': direction})
                results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo candidate ordered-signature met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 78)
    print("  FAMILY 1 — ordered-signature candidates (survival-first ranked)")
    print("=" * 78)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} A={r['A']} ->{r['k']}-> B={r['B']}")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_live(df, ['ST_Flip_Event', 'D2D_Signal', 'Bars_Since_Flip', 'D2D_Trend_Dir'])
    print("Timing/gate columns live: ST_Flip_Event, D2D_Signal, Bars_Since_Flip, D2D_Trend_Dir")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    pool = build_condition_pool(df, adaptive, structural, warmup)
    labels = scorable_pool(pool, warmup)

    # ---- run-proof subset (proof scope). Full scope = the whole scorable pool
    # (len(labels)^2 x LAGS x 2 dirs); the orchestrator drives that. ----
    subset = [l for l in ['ADX_Value:hi', 'Momentum_Value:hi', 'Sqz_State:==1',
                          'RangeOsc_State:==1'] if l in labels]
    results = run_search(df, pool, subset, lags=[3, 5], anchor='ST_Flip',
                         directions=['LONG', 'SHORT'],
                         adaptive=adaptive, structural=structural, warmup=warmup)
    report(results)
    n_full = len(labels) ** 2 * len(LAGS) * 2
    print(f"\nFull-scope candidate count = {len(labels)}^2 x {len(LAGS)} lags x 2 dir "
          f"= {n_full:,}")


if __name__ == '__main__':
    main()
