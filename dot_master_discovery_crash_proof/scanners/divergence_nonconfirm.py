import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 4 — DIVERGENCE / NON-CONFIRMATION  (discovery scanner)
#  Relationship: price makes an extreme but a flow/momentum variable does
#  NOT confirm — the edge is the two FAILING to line up. Signal is a price-
#  extreme condition AND a non-confirming flow condition (the opposite
#  extreme on the flow leg):
#     price:hi & flow:lo  -> reversion down -> SHORT
#     price:lo & flow:hi  -> reversion up   -> LONG
#
#  Price legs: VWAP_Z, KAMA_Dist_ATR, session/OR distances (hi/lo, oracle).
#  Flow legs : Micro_OrderFlowDelta, Micro_VPIN, OBV_Macd, Momentum_Value.
#  All conditions via engine.condition_mask (oracle-only).
#
#  D2D gate = INVERT or EXEMPT (counter-continuation — this family CANNOT
#  fire under confirm). The engine's gate is `d2d_dir == direction` and
#  D2D_Trend_Dir is used by the engine ONLY in that gate (verified: engine
#  L79/L89 — not in TM/pnl). So the D2D mode is expressed by reconstructing
#  the input D2D_Trend_Dir column for the run, engine and TM untouched:
#     confirm : orig                (not used here)
#     invert  : -orig               (enter opposite to D2D)
#     exempt  : constant = direction (gate always true -> no D2D restriction)
#  TM polarity uses `direction` (economic reversion direction) and is
#  unaffected by the gate column.
#
#  Scoring: survival-first walk-forward via wf.py primitives.
#  F4 is no-new-input tier: AND of existing exported columns — no derived
#  quantity, no parity burden.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F4DIV'

PRICE_FEATS = ['VWAP_Z', 'KAMA_Dist_ATR', 'OR_High_Dist_ATR', 'OR_Low_Dist_ATR',
               'Session_High_Dist_ATR', 'Session_Low_Dist_ATR']
FLOW_FEATS = ['Micro_OrderFlowDelta', 'Micro_VPIN', 'OBV_Macd', 'Momentum_Value']


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def apply_d2d(df, mode, direction, orig):
    if mode == 'confirm':
        df['D2D_Trend_Dir'] = orig
    elif mode == 'invert':
        df['D2D_Trend_Dir'] = -orig
    elif mode == 'exempt':
        df['D2D_Trend_Dir'] = np.full(len(df), direction, dtype=orig.dtype)
    else:
        raise ValueError(f"unknown d2d mode '{mode}'")


def score_mask(df, mask, direction, d2d_mode, orig, month, adaptive, structural, warmup):
    df[SEQ_COL] = mask.astype(int)
    dir_int = 1 if direction == 'LONG' else -1
    apply_d2d(df, d2d_mode, dir_int, orig)
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


def run_search(df, price_feats, flow_feats, d2d_modes, orig, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    # divergence configs: (price_thr, flow_thr, reversion_direction)
    configs = [('hi', 'lo', 'SHORT'), ('lo', 'hi', 'LONG')]
    total = len(price_feats) * len(flow_feats) * len(configs) * len(d2d_modes)
    print(f"\nSearch: {len(price_feats)} price x {len(flow_feats)} flow x "
          f"{len(configs)} divergence-configs x {len(d2d_modes)} d2d-mode = {total} candidates")
    results = []
    tested = 0
    for pf in price_feats:
        for ff in flow_feats:
            for p_thr, f_thr, direction in configs:
                price_mask = engine.condition_mask(df, pf, p_thr, adaptive, structural)
                flow_mask = engine.condition_mask(df, ff, f_thr, adaptive, structural)
                mask = price_mask & flow_mask
                if mask.sum() < MIN_TRADES:
                    continue
                for mode in d2d_modes:
                    sc = score_mask(df, mask, direction, mode, orig, month,
                                    adaptive, structural, warmup)
                    tested += 1
                    if sc is None:
                        continue
                    sc.update({'price': f"{pf}:{p_thr}", 'nonconfirm_flow': f"{ff}:{f_thr}",
                               'direction': direction, 'd2d': mode})
                    results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo divergence candidate met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 84)
    print("  FAMILY 4 — divergence / non-confirmation candidates (survival-first ranked)")
    print("  PRICE-extreme not confirmed by FLOW; D2D = invert/exempt (never confirm)")
    print("=" * 84)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} d2d={r['d2d']:6} "
              f"PRICE {r['price']}  NOT-CONFIRMED-BY  FLOW {r['nonconfirm_flow']}")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_live(df, PRICE_FEATS + FLOW_FEATS + ['D2D_Trend_Dir'])
    print(f"Price legs live: {', '.join(PRICE_FEATS)}")
    print(f"Flow legs live : {', '.join(FLOW_FEATS)}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    orig = df['D2D_Trend_Dir'].values.copy()

    # ---- run-proof subset; d2d modes exercised are INVERT and EXEMPT only
    # (never confirm). Widen price_feats/flow_feats for the full scan. ----
    try:
        results = run_search(df, ['VWAP_Z', 'KAMA_Dist_ATR'],
                             ['Micro_OrderFlowDelta', 'OBV_Macd'],
                             d2d_modes=['invert', 'exempt'], orig=orig,
                             adaptive=adaptive, structural=structural, warmup=warmup)
        report(results)
    finally:
        df['D2D_Trend_Dir'] = orig


if __name__ == '__main__':
    main()
