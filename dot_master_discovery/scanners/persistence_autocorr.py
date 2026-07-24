import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 5 — PERSISTENCE / AUTOCORRELATION  (discovery scanner)
#  Relationship: when a conditioning state HOLDS, the next N bars are
#  statistically biased — a mild, frequent edge. The conditioning state is
#  the signal; the forward-return bias is the DISCOVERY TARGET (for ranking
#  / reporting only) and NEVER a live input or a TM change.
#
#  Conditioning states (live): Micro_AutoCorr, Micro_Hurst,
#  Efficiency_Ratio, KAMA_Slope — hi/lo via engine.condition_mask (oracle).
#
#  Entries go through engine.run_portfolio under the locked S.7 TM (no
#  custom exits). D2D gate = confirm, engine-applied. The forward-return
#  measurement below is a descriptive statistic on entry-eligible bars; it
#  does not gate entry, size, or exit.
#  Scoring: survival-first walk-forward via wf.py primitives.
#  F5 is no-new-input tier: existing exported columns; forward-return is a
#  discovery-only target -> no parity burden.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
FWD_N = 10
SEQ_COL = '__F5PERS'

STATE_FEATS = ['Micro_AutoCorr', 'Micro_Hurst', 'Efficiency_Ratio', 'KAMA_Slope']


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def forward_bias(df, mask, direction, warmup, n=FWD_N):
    # DISCOVERY-ONLY descriptive target: mean N-bar forward point move in the
    # trade direction, on post-warmup bars where the condition holds and D2D
    # confirms. Not an input to entry/size/exit.
    closes = df['Close'].values
    d2d = df['D2D_Trend_Dir'].values
    dir_int = 1 if direction == 'LONG' else -1
    nonwarm = np.arange(len(df)) >= warmup
    idx = np.where(mask & nonwarm & (d2d == dir_int))[0]
    idx = idx[idx + n < len(df)]
    if len(idx) == 0:
        return 0.0, 0.0, 0
    fwd = (closes[idx + n] - closes[idx]) * dir_int
    return round(float(fwd.mean()), 2), round(float((fwd > 0).mean() * 100.0), 1), len(idx)


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
    fwd_pts, fwd_hit, fwd_n = forward_bias(df, mask, direction, warmup)
    return {
        'trades': n_total, 'agg_pf': agg_pf, 'agg_wr': agg_wr,
        'worst_day_usd': round(worst_day_usd, 1), 'hard_stop_days': hard_stop,
        'survival_pass': survival_pass, 'profitable_folds': profitable_folds,
        'min_fold_pf': min_fold_pf, 'pf_base': pf_base, 'pf_stress': pf_stress,
        'fwd_pts': fwd_pts, 'fwd_hit': fwd_hit, 'fwd_n': fwd_n,
    }


def run_search(df, cond_labels, directions, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    total = len(cond_labels) * len(directions)
    print(f"\nSearch: {len(cond_labels)} persistence conditions x {len(directions)} dir "
          f"= {total} candidates | forward-bias target N={FWD_N} (discovery-only)")
    results = []
    tested = 0
    for lbl in cond_labels:
        feat, thr = lbl.split(':')
        mask = engine.condition_mask(df, feat, thr, adaptive, structural)
        if mask.sum() < MIN_TRADES:
            continue
        for direction in directions:
            sc = score_mask(df, mask, direction, month, adaptive, structural, warmup)
            tested += 1
            if sc is None:
                continue
            sc.update({'condition': lbl, 'direction': direction})
            results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo persistence candidate met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 84)
    print("  FAMILY 5 — persistence / autocorrelation candidates (survival-first ranked)")
    print("  fwd = discovery-only forward-bias target (not a live input)")
    print("=" * 84)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} PERSIST {r['condition']}")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")
        print(f"           fwd(N={FWD_N}): mean {r['fwd_pts']:>7.2f} pts | hit {r['fwd_hit']:>4.1f}% | "
              f"n {r['fwd_n']}  [discovery target]")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_live(df, STATE_FEATS + ['D2D_Trend_Dir', 'Close'])
    print(f"Persistence states live: {', '.join(STATE_FEATS)}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)

    # ---- run-proof subset; widen cond_labels / directions for the full scan ----
    cond_labels = [f"{s}:{t}" for s in ['Micro_AutoCorr', 'Efficiency_Ratio', 'KAMA_Slope']
                   for t in ('hi', 'lo')]
    results = run_search(df, cond_labels, directions=['LONG', 'SHORT'],
                         adaptive=adaptive, structural=structural, warmup=warmup)
    report(results)


if __name__ == '__main__':
    main()
