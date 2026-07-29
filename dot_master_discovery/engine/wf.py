import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine

# ═══════════════════════════════════════════════════════════════
#  NAMED CONSTANTS (operator-tuned against the discovered set after Stage 8)
# ═══════════════════════════════════════════════════════════════

DAILY_LOSS_CEILING_USD = 2500.0    # EA hard stop (operator-set: half the FTMO
                                   # $5,000 daily limit). This is the survival gate.
USD_PER_POINT_PER_LOT  = 1.0       # US30.cash: $1/point per 1.0 lot
                                   # (FTMO spec, operator-confirmed 2026-07-11).
LOT_SIZE               = 1.0       # CONFIGURABLE. Production lot size decided AFTER
                                   # Stage 8 from the discovered set's statistics;
                                   # the survival gate must work at any value.
FTMO_DAILY_LIMIT_USD   = 5000.0    # context (100K Swing) — not the gate
FTMO_MAX_DRAWDOWN_USD  = 10000.0   # context (100K Swing) — not the gate

SPREAD_STRESS_USD      = 2.0       # extra points added to the spread for robustness

DEFAULT_SIGNALS_PATH = "recommended_set_76.csv"

# Monthly folds: [Jan 19-31], [Feb], [Mar], [Apr], [May], [Jun 1-25].
# A bar is folded by its Time year.month; the Jan 19 start / Jun 25 end bounds
# are already enforced by the sealed baseline's range.
FOLDS = [
    ("Jan(19-31)", "2026.01"),
    ("Feb",        "2026.02"),
    ("Mar",        "2026.03"),
    ("Apr",        "2026.04"),
    ("May",        "2026.05"),
    ("Jun(1-25)",  "2026.06"),
]

def points_to_usd(points):
    return points * LOT_SIZE * USD_PER_POINT_PER_LOT

def daily_pnl_points(trades_df):
    if len(trades_df) == 0:
        return pd.DataFrame(columns=['exit_date', 'pnl'])
    td = trades_df.copy()
    td['exit_date'] = td['exit_time'].str[:10]
    return td.groupby('exit_date', as_index=False).agg(pnl=('pnl', 'sum'))

def fold_metrics(trades_df, label):
    n = len(trades_df)
    if n == 0:
        return {'fold': label, 'trades': 0, 'pf': 0.0, 'wr': 0.0,
                'total_pnl': 0.0, 'worst_day_usd': 0.0, 'hard_stop_days': 0,
                'trading_days': 0}
    pnls = trades_df['pnl'].values
    gw = pnls[pnls > 0].sum()
    gl = abs(pnls[pnls <= 0].sum())
    pf = (999.0 if gw > 0 else 0.0) if gl == 0 else gw / gl
    wr = (pnls > 0).sum() / n * 100.0
    daily = daily_pnl_points(trades_df)
    daily_usd = points_to_usd(daily['pnl'].values)
    worst_day_usd = float(daily_usd.min()) if len(daily_usd) else 0.0
    hard_stop_days = int((daily_usd <= -DAILY_LOSS_CEILING_USD).sum())
    return {'fold': label, 'trades': n, 'pf': round(pf, 2), 'wr': round(wr, 1),
            'total_pnl': round(float(pnls.sum()), 1),
            'worst_day_usd': round(worst_day_usd, 1),
            'hard_stop_days': hard_stop_days,
            'trading_days': int(len(daily))}

def pf_from_pnls(pnls):
    if len(pnls) == 0:
        return 0.0
    gw = pnls[pnls > 0].sum()
    gl = abs(pnls[pnls <= 0].sum())
    return (999.0 if gw > 0 else 0.0) if gl == 0 else gw / gl

def spread_stress(all_trades_df):
    # Spread is a flat per-trade deduction in the engine and does not alter any
    # exit decision (SL/BE/LF/FC/tier logic is price-based), so PF at a stressed
    # spread is exact from the base trades: pnl(s) = pnl_base + SPREAD - s.
    if len(all_trades_df) == 0:
        return 0.0, 0.0
    base = all_trades_df['pnl'].values
    pf_base = pf_from_pnls(base)
    stressed = base + engine.SPREAD - (engine.SPREAD + SPREAD_STRESS_USD)
    pf_stress = pf_from_pnls(stressed)
    return round(pf_base, 2), round(pf_stress, 2)

def run_walkforward(signals_path=DEFAULT_SIGNALS_PATH):
    print("equiDOT — Walk-Forward (survival-first)")
    df = engine.load_sealed_baseline()
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    warmup = engine.warmup_floor(df)
    signals_df = pd.read_csv(signals_path)
    print(f"\nSignal set: {signals_path} ({len(signals_df)} signals)")
    print(f"Survival gate: worst-day loss must not breach ${DAILY_LOSS_CEILING_USD:,.0f} "
          f"at LOT_SIZE={LOT_SIZE} (${USD_PER_POINT_PER_LOT:.0f}/pt/lot)")

    month = pd.Series(df['Time'].values).str[:7].values
    fold_rows = []
    all_fold_trades = []
    print("\nPer-fold (entries restricted to the fold; thresholds computed once on full series):")
    for label, mkey in FOLDS:
        mask_window = (month == mkey)
        td = engine.run_portfolio(df, signals_df, mask_window=mask_window,
                                  adaptive=adaptive, structural=structural,
                                  warmup=warmup, verbose=False)
        m = fold_metrics(td, label)
        fold_rows.append(m)
        if len(td):
            all_fold_trades.append(td)
        print(f"  {m['fold']:<11} | trades {m['trades']:>4} | PF {m['pf']:>6.2f} | "
              f"WR {m['wr']:>5.1f}% | days {m['trading_days']:>3} | "
              f"worst-day ${m['worst_day_usd']:>10,.0f} | hard-stop days {m['hard_stop_days']:>2}")

    all_trades = pd.concat(all_fold_trades, ignore_index=True) if all_fold_trades else pd.DataFrame(columns=['pnl', 'exit_time'])
    n_total = len(all_trades)
    agg_pnls = all_trades['pnl'].values if n_total else np.array([])
    agg_pf = round(pf_from_pnls(agg_pnls), 2)
    agg_wr = round((agg_pnls > 0).sum() / n_total * 100.0, 1) if n_total else 0.0
    agg_daily = daily_pnl_points(all_trades)
    agg_daily_usd = points_to_usd(agg_daily['pnl'].values) if len(agg_daily) else np.array([])
    worst_day_usd = float(agg_daily_usd.min()) if len(agg_daily_usd) else 0.0
    total_hard_stop = int((agg_daily_usd <= -DAILY_LOSS_CEILING_USD).sum())

    # 1. SURVIVAL (hard filter, before profitability)
    survival_pass = worst_day_usd > -DAILY_LOSS_CEILING_USD
    # 2. CROSS-FOLD PERSISTENCE
    fold_pfs = [r['pf'] for r in fold_rows if r['trades'] > 0]
    profitable_folds = sum(1 for r in fold_rows if r['total_pnl'] > 0)
    min_fold_pf = min(fold_pfs) if fold_pfs else 0.0
    # 3. SPREAD ROBUSTNESS
    pf_base, pf_stress = spread_stress(all_trades)

    print("\n" + "=" * 60)
    print("  AGGREGATE (survival-first scoring)")
    print("=" * 60)
    print(f"  1. SURVIVAL:  worst single day = ${worst_day_usd:,.0f} at LOT_SIZE={LOT_SIZE}")
    print(f"               ceiling = ${-DAILY_LOSS_CEILING_USD:,.0f}  ->  "
          f"{'PASS' if survival_pass else 'REJECT'}")
    print(f"               hard-stop days (would breach): {total_hard_stop}")
    per_fold_pf = ', '.join('{:.2f}'.format(r['pf']) for r in fold_rows)
    print(f"  2. PERSISTENCE: profitable folds {profitable_folds}/{len(FOLDS)} | "
          f"min fold PF {min_fold_pf:.2f} | per-fold PF [{per_fold_pf}]")
    print(f"  3. SPREAD ROBUSTNESS: PF @spread {engine.SPREAD:.1f} = {pf_base:.2f} -> "
          f"PF @spread {engine.SPREAD + SPREAD_STRESS_USD:.1f} = {pf_stress:.2f}")
    print(f"\n  Totals: trades {n_total} | PF {agg_pf:.2f} | WR {agg_wr:.1f}% | "
          f"trading days {len(agg_daily)}")
    verdict = "SURVIVAL PASS" if survival_pass else "SURVIVAL REJECT (worst-day breaches ceiling)"
    print(f"\n  VERDICT: {verdict}")
    return {'folds': fold_rows, 'survival_pass': survival_pass,
            'worst_day_usd': worst_day_usd, 'hard_stop_days': total_hard_stop,
            'agg_pf': agg_pf, 'agg_wr': agg_wr, 'min_fold_pf': min_fold_pf,
            'pf_base': pf_base, 'pf_stress': pf_stress}

if __name__ == '__main__':
    sp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SIGNALS_PATH
    run_walkforward(sp)
