import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 7 — MEAN-REVERSION-FROM-EXTREME  (discovery scanner)
#  Relationship: single-variable — "when X is this STRETCHED, it snaps
#  back." Reversion, not continuation. Entry AGAINST the stretch:
#     feat at hi extreme -> SHORT (fade the stretch up)
#     feat at lo extreme -> LONG  (fade the stretch down)
#  ONE stretched oracle condition per candidate (engine.condition_mask) —
#  NOT a 3-condition triple.
#
#  Stretched feats: VWAP_Z (±2 structural), KAMA_Dist_ATR, session / round-
#  level / OR distances.
#
#  D2D gate = INVERT or EXEMPT (against the stretch cannot fire under
#  confirm). Same sanctioned mechanism as F4: D2D_Trend_Dir is gate-only in
#  the engine (L79 read / L89 gate), so the D2D mode is expressed by
#  reconstructing the input column per run — engine and TM UNTOUCHED:
#     invert  : -orig               (fade against the D2D trend)
#     exempt  : constant = direction (gate always true -> no D2D restriction)
#  Confirm is never exercised; original column restored in finally.
#  Scoring: survival-first via wf.py primitives.
#  F7 is no-new-input tier: single existing oracle condition + polarity +
#  D2D-mode config — no derived quantity, no parity burden.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F7REV'

STRETCH_FEATS = ['VWAP_Z', 'KAMA_Dist_ATR', 'Session_High_Dist_ATR', 'Session_Low_Dist_ATR',
                 'Round_100_Dist_ATR', 'Round_500_Dist_ATR', 'Round_1000_Dist_ATR',
                 'OR_High_Dist_ATR', 'OR_Low_Dist_ATR']


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


def run_search(df, stretch_feats, d2d_modes, orig, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    # fade configs: stretched at hi -> SHORT, at lo -> LONG
    configs = [('hi', 'SHORT'), ('lo', 'LONG')]
    total = len(stretch_feats) * len(configs) * len(d2d_modes)
    print(f"\nSearch: {len(stretch_feats)} stretched feats x {len(configs)} fade-configs x "
          f"{len(d2d_modes)} d2d-mode = {total} candidates")
    results = []
    tested = 0
    for feat in stretch_feats:
        for thr, direction in configs:
            mask = engine.condition_mask(df, feat, thr, adaptive, structural)
            if mask.sum() < MIN_TRADES:
                continue
            for mode in d2d_modes:
                sc = score_mask(df, mask, direction, mode, orig, month,
                                adaptive, structural, warmup)
                tested += 1
                if sc is None:
                    continue
                sc.update({'stretched': f"{feat}:{thr}", 'direction': direction, 'd2d': mode})
                results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo mean-reversion candidate met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 84)
    print("  FAMILY 7 — mean-reversion-from-extreme candidates (survival-first ranked)")
    print("  entry AGAINST the stretch; D2D = invert/exempt (never confirm)")
    print("=" * 84)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} d2d={r['d2d']:6} FADE {r['stretched']}")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_live(df, STRETCH_FEATS + ['D2D_Trend_Dir'])
    print(f"Stretched feats live: {', '.join(STRETCH_FEATS)}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    orig = df['D2D_Trend_Dir'].values.copy()

    # ---- run-proof subset; d2d modes exercised are INVERT and EXEMPT only
    # (never confirm). Widen stretch_feats for the full scan. ----
    try:
        results = run_search(df, ['VWAP_Z', 'KAMA_Dist_ATR', 'Session_High_Dist_ATR'],
                             d2d_modes=['invert', 'exempt'], orig=orig,
                             adaptive=adaptive, structural=structural, warmup=warmup)
        report(results)
    finally:
        df['D2D_Trend_Dir'] = orig


if __name__ == '__main__':
    main()
