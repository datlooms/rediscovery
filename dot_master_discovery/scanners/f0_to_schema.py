import sys
import os
import numpy as np
import pandas as pd
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  f0_to_schema.py — convert F0 survivors to the common 14-column schema.
#
#  *** NOT A PURE FORMATTER — FLAGGED FOR FULL AUDIT ***
#  F0's deduped_survivors.csv carries only its fast single-pass scorer
#  metrics (trades/pf/wr); it does NOT carry the wf survival fields
#  (folds_plus, min_fold_pf, worst_day_usd, hard_stop_days, spread_pf,
#  survival). To place F0 on the SAME survival-first basis as F1-F11, each
#  survivor is RE-SCORED here through the ratified engine.run_portfolio + wf
#  6-fold primitives — identical to every family scanner's score path. This
#  adds re-scoring logic (no new TM, no new threshold), so it is flagged for
#  a full audit rather than a formatter sign-off.
#
#  Schema: family,script,signal_def,direction,d2d_mode,trades,WR,agg_pf,
#          worst_day_usd,hard_stop_days,folds_plus,min_fold_pf,spread_pf,survival
#  Reads : F0 survivors CSV (default dots_results/deduped_survivors.csv)
#  Writes: discovery_results/results_F0_triple_convergence_and_d2ddir.csv
# ═══════════════════════════════════════════════════════════════

SCHEMA = ['family', 'script', 'signal_def', 'direction', 'd2d_mode', 'trades', 'WR',
          'agg_pf', 'worst_day_usd', 'hard_stop_days', 'folds_plus', 'min_fold_pf',
          'spread_pf', 'survival']
SCRIPT = 'triple_convergence_and_d2ddir'
OUT = os.path.join('discovery_results', 'results_F0_triple_convergence_and_d2ddir.csv')


def score_survivor(df, row, month, adaptive, structural, warmup):
    sig = pd.DataFrame([{
        'feat_1': row['feat_1'], 'thresh_1': row['thresh_1'],
        'feat_2': row['feat_2'], 'thresh_2': row['thresh_2'],
        'feat_3': row['feat_3'], 'thresh_3': row['thresh_3'],
        'direction': row['direction'],
    }])
    fold_rows = []
    fold_trades = []
    for label, mkey in wf.FOLDS:
        td = engine.run_portfolio(df, sig, mask_window=(month == mkey), adaptive=adaptive,
                                  structural=structural, warmup=warmup, verbose=False)
        fold_rows.append(wf.fold_metrics(td, label))
        if len(td):
            fold_trades.append(td)
    all_trades = pd.concat(fold_trades, ignore_index=True) if fold_trades else pd.DataFrame(columns=['pnl', 'exit_time'])
    n = len(all_trades)
    pnls = all_trades['pnl'].values if n else np.array([])
    agg_pf = round(wf.pf_from_pnls(pnls), 2)
    wr = round((pnls > 0).sum() / n * 100.0, 1) if n else 0.0
    daily = wf.daily_pnl_points(all_trades)
    daily_usd = wf.points_to_usd(daily['pnl'].values) if len(daily) else np.array([])
    worst = round(float(daily_usd.min()), 1) if len(daily_usd) else 0.0
    hard = int((daily_usd <= -wf.DAILY_LOSS_CEILING_USD).sum())
    survive = worst > -wf.DAILY_LOSS_CEILING_USD
    folds_plus = sum(1 for r in fold_rows if r['total_pnl'] > 0)
    fold_pfs = [r['pf'] for r in fold_rows if r['trades'] > 0]
    min_fold_pf = min(fold_pfs) if fold_pfs else 0.0
    pf_base, pf_stress = wf.spread_stress(all_trades)
    signal_def = (f"{row['feat_1']}:{row['thresh_1']} + {row['feat_2']}:{row['thresh_2']} + "
                  f"{row['feat_3']}:{row['thresh_3']}")
    return {'family': 'F0', 'script': SCRIPT, 'signal_def': signal_def,
            'direction': row['direction'], 'd2d_mode': 'confirm', 'trades': n, 'WR': wr,
            'agg_pf': agg_pf, 'worst_day_usd': worst, 'hard_stop_days': hard,
            'folds_plus': folds_plus, 'min_fold_pf': min_fold_pf,
            'spread_pf': f"{pf_base}->{pf_stress}", 'survival': survive}


def main(path):
    surv = pd.read_csv(path)
    print(f"f0_to_schema — re-scoring {len(surv)} F0 survivors through wf 6-fold "
          f"(FLAGGED: re-scoring logic, not a pure formatter)")
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    adaptive = __import__('dots_thresholds').compute_adaptive_thresholds(df)
    structural = __import__('dots_thresholds').compute_structural_gates(df)
    month = pd.Series(df['Time'].values).str[:7].values
    rows = [score_survivor(df, r, month, adaptive, structural, warmup)
            for _, r in surv.iterrows()]
    os.makedirs('discovery_results', exist_ok=True)
    pd.DataFrame(rows, columns=SCHEMA).to_csv(OUT, index=False, lineterminator='\n')
    print(f"Wrote {len(rows)} F0 rows -> {OUT}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join('dots_results', 'deduped_survivors.csv'))
