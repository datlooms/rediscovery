import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 6 — THRESHOLD-CROSSING / MOMENTUM-IGNITION  (scanner)
#  Relationship: a variable CROSSING the oracle level — the bar the
#  condition FIRST becomes true — not being at an extreme (F0).
#     up-cross   = cond(feat,'hi')[t] AND NOT cond(feat,'hi')[t-1]  -> LONG
#     down-cross = cond(feat,'lo')[t] AND NOT cond(feat,'lo')[t-1]  -> SHORT
#  The LEVEL is the oracle hi/lo threshold via engine.condition_mask; no new
#  level is invented or computed. Lag-1 (t-1) head-padded, no wraparound.
#  Optional ROC filter is a second oracle condition at the cross bar (an
#  existing column / oracle mask) — not a new derived quantity beyond the
#  cross boolean.
#
#  Feats: Slope_Accel_ST/LT, Momentum_Value, KAMA_Slope, OBV_Velocity.
#  Injected as a one-column '==1' signal, driven through
#  engine.run_portfolio; ZERO TM reconstruction. D2D gate = confirm,
#  engine-applied. Scoring: survival-first via wf.py primitives.
#  F6 is new-derived-input tier (lag-1 crossing boolean, same class as F2):
#  analysis-only here; production parity is a Stage-9 concern.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F6CROSS'

CROSS_FEATS = ['Slope_Accel_ST', 'Slope_Accel_LT', 'Momentum_Value', 'KAMA_Slope', 'OBV_Velocity']


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def crossing_mask(df, feat, thr, adaptive, structural):
    m = engine.condition_mask(df, feat, thr, adaptive, structural)
    out = np.zeros(len(m), dtype=bool)
    out[1:] = m[1:] & ~m[:-1]
    return out


def score_mask(df, mask, direction, month, adaptive, structural, warmup):
    df[SEQ_COL] = mask.astype(int)
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


def run_search(df, cross_feats, roc_filter, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    # crossing configs: (cross_thr, reversion? no — ignition direction)
    configs = [('hi', 'LONG'), ('lo', 'SHORT')]
    roc_mask = None
    roc_lbl = 'none'
    if roc_filter is not None:
        rf, rt = roc_filter
        roc_mask = engine.condition_mask(df, rf, rt, adaptive, structural)
        roc_lbl = f"{rf}:{rt}"
    total = len(cross_feats) * len(configs)
    print(f"\nSearch: {len(cross_feats)} feats x {len(configs)} cross-dir = {total} candidates "
          f"| ROC filter={roc_lbl}")
    results = []
    tested = 0
    for feat in cross_feats:
        for thr, direction in configs:
            mask = crossing_mask(df, feat, thr, adaptive, structural)
            if roc_mask is not None:
                mask = mask & roc_mask
            if mask.sum() < MIN_TRADES:
                continue
            sc = score_mask(df, mask, direction, month, adaptive, structural, warmup)
            tested += 1
            if sc is None:
                continue
            cross_type = 'up-cross' if thr == 'hi' else 'down-cross'
            sc.update({'feat': feat, 'cross': cross_type, 'level': thr,
                       'direction': direction, 'roc': roc_lbl})
            results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo crossing candidate met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 84)
    print("  FAMILY 6 — threshold-crossing / momentum-ignition (survival-first ranked)")
    print("  cross = first bar the oracle level is breached (not being at extreme)")
    print("=" * 84)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} {r['feat']} {r['cross']} (level={r['level']}) "
              f"ROC={r['roc']}")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_live(df, CROSS_FEATS + ['D2D_Trend_Dir'])
    print(f"Crossing feats live: {', '.join(CROSS_FEATS)}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)

    # ---- run-proof subset; widen cross_feats / add roc_filter for full scan ----
    print("\n[cross-only]")
    r1 = run_search(df, ['Slope_Accel_ST', 'Momentum_Value', 'OBV_Velocity'],
                    roc_filter=None, adaptive=adaptive, structural=structural, warmup=warmup)
    report(r1)
    print("\n[cross + ROC filter Momentum_Value:hi]")
    r2 = run_search(df, ['Slope_Accel_ST', 'KAMA_Slope'],
                    roc_filter=('Momentum_Value', 'hi'),
                    adaptive=adaptive, structural=structural, warmup=warmup)
    report(r2)


if __name__ == '__main__':
    main()
