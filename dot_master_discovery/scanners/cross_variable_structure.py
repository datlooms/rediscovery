import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 8 — RELATIVE / CROSS-VARIABLE STRUCTURE  (scanner)
#  Relationship: the RELATION between two existing columns — not either's
#  absolute level. Signals are structural (zero-level / equality), so NO
#  independently-computed percentile is introduced:
#     inequality / spread-sign : A > B  ,  A < B
#     ST-vs-LT disagreement     : state_ST != state_LT
#  Pairs (from the vocabulary): Slope_EMA_ST vs Slope_EMA_LT,
#  Slope_Accel_ST vs Slope_Accel_LT (fast-vs-slow slope), AT_Regime_ST vs
#  AT_Regime_LT (regime disagreement).
#
#  If a relation ever needed a percentile the oracle does not provide, the
#  correct action is STOP-and-report — never compute one here. All relations
#  below are structural and need no threshold.
#
#  Injected as a one-column '==1' signal, driven through
#  engine.run_portfolio; ZERO TM reconstruction. D2D gate = confirm,
#  engine-applied. Scoring: survival-first via wf.py primitives.
#  F8 is new-derived-input tier (the relation is derived): analysis-only
#  here; production parity is a Stage-9 concern.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F8REL'

# (A, B, kind): kind 'ineq' -> A>B and A<B ; 'disagree' -> A!=B
PAIRS = [
    ('Slope_EMA_ST', 'Slope_EMA_LT', 'ineq'),
    ('Slope_Accel_ST', 'Slope_Accel_LT', 'ineq'),
    ('AT_Regime_ST', 'AT_Regime_LT', 'disagree'),
]


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def relation_masks(df, a, b, kind):
    av = df[a].values
    bv = df[b].values
    if kind == 'ineq':
        return [(f"{a} > {b}", av > bv), (f"{a} < {b}", av < bv)]
    if kind == 'disagree':
        return [(f"{a} != {b}", av != bv)]
    raise ValueError(f"unknown relation kind '{kind}'")


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


def run_search(df, pairs, directions, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    relations = []
    for a, b, kind in pairs:
        relations.extend(relation_masks(df, a, b, kind))
    total = len(relations) * len(directions)
    print(f"\nSearch: {len(relations)} relations x {len(directions)} dir = {total} candidates")
    results = []
    tested = 0
    for rel_lbl, mask in relations:
        if mask.sum() < MIN_TRADES:
            continue
        for direction in directions:
            sc = score_mask(df, mask, direction, month, adaptive, structural, warmup)
            tested += 1
            if sc is None:
                continue
            sc.update({'relation': rel_lbl, 'direction': direction})
            results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo cross-variable relation met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 84)
    print("  FAMILY 8 — relative / cross-variable structure (survival-first ranked)")
    print("  signal is the RELATION between two variables, not either level")
    print("=" * 84)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} REL ({r['relation']})")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    cols = sorted({c for a, b, _ in PAIRS for c in (a, b)})
    verify_live(df, cols + ['D2D_Trend_Dir'])
    print(f"Relation columns live: {', '.join(cols)}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)

    # ---- run-proof subset (widen PAIRS / directions for the full scan) ----
    results = run_search(df, PAIRS, directions=['LONG', 'SHORT'],
                         adaptive=adaptive, structural=structural, warmup=warmup)
    report(results)


if __name__ == '__main__':
    main()
