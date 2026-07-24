import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 11 — CROSS-VARIABLE x WINDOWED (rolling lead-lag / corr)  (scanner)
#  Relationship: a WINDOWED statistical relation between TWO series — does A
#  lead B by k bars, or does an A<->B rolling correlation strengthen / break
#  down. Fills the {cross-variable}x{windowed} taxonomy cell.
#
#  Pairs (all live): OBV_Line<->Close, Micro_OrderFlowDelta<->Micro_LogReturn,
#  OBV_Macd<->Momentum_Value.
#
#  CAUSAL WINDOW (Stage-9 parity spec): every derived series uses ONLY bars
#  [t-N+1 .. t]. pandas .rolling(N) is trailing; .shift(k) pulls PAST bars
#  only; NO centered window, NO future bars. Bars with insufficient history
#  (NaN) yield signal False. Lag-1 breakdown events are head-padded.
#
#  SIGNAL from the derived series is STRUCTURAL only (sign / zero-cross) — no
#  independent percentile on the derived series:
#     corr_pos / corr_neg : rolling corr(A,B,N) > 0 / < 0
#     corr_break          : corr[t-1] > 0 AND corr[t] <= 0  (coupling breaks)
#     beta_pos / beta_neg : rolling beta(A~B,N) > 0 / < 0
#     leadlag_pos/neg     : sign( corr(A.shift(k),B,N) - corr(A,B.shift(k),N) )
#                           > 0 -> A leads B ; < 0 -> B leads A
#  ORACLE conditions (none needed here) would route through engine only —
#  ZERO independent threshold computation on oracle conditions.
#
#  Injected as a one-column '==1' signal, driven through
#  engine.run_portfolio; ZERO TM reconstruction. D2D gate = confirm,
#  engine-applied. Scoring: survival-first via wf.py primitives.
#  F11 is new-derived-input tier (heaviest): the rolling two-series statistic
#  needs an oracle-consistent, history-independent live definition +
#  export==live parity before production — analysis-only here (Stage-9).
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F11LL'
WINDOWS = [30, 60, 120]
LEADLAG_K = 5

PAIRS = [
    ('OBV_Line', 'Close'),
    ('Micro_OrderFlowDelta', 'Micro_LogReturn'),
    ('OBV_Macd', 'Momentum_Value'),
]
RELATIONS = ['corr_pos', 'corr_neg', 'corr_break', 'beta_pos', 'beta_neg',
             'leadlag_pos', 'leadlag_neg']


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def rolling_corr(a, b, n):
    return a.rolling(n).corr(b)


def rolling_beta(a, b, n):
    cov = a.rolling(n).cov(b)
    var = b.rolling(n).var()
    return cov / var.replace(0.0, np.nan)


def relation_mask(df, A, B, n, relation, k=LEADLAG_K):
    a = pd.Series(df[A].values, dtype=float)
    b = pd.Series(df[B].values, dtype=float)
    if relation in ('corr_pos', 'corr_neg', 'corr_break'):
        c = rolling_corr(a, b, n).values
        if relation == 'corr_pos':
            m = c > 0
        elif relation == 'corr_neg':
            m = c < 0
        else:
            m = np.zeros(len(c), dtype=bool)
            prev = c[:-1]
            cur = c[1:]
            m[1:] = (prev > 0) & (cur <= 0) & ~np.isnan(prev) & ~np.isnan(cur)
            return m
        return m & ~np.isnan(c)
    if relation in ('beta_pos', 'beta_neg'):
        bt = rolling_beta(a, b, n).values
        m = bt > 0 if relation == 'beta_pos' else bt < 0
        return m & ~np.isnan(bt)
    if relation in ('leadlag_pos', 'leadlag_neg'):
        c_alead = rolling_corr(a.shift(k), b, n).values
        c_blead = rolling_corr(a, b.shift(k), n).values
        diff = c_alead - c_blead
        m = diff > 0 if relation == 'leadlag_pos' else diff < 0
        return m & ~np.isnan(diff)
    raise ValueError(f"unknown relation '{relation}'")


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


def run_search(df, pairs, windows, relations, directions, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    total = len(pairs) * len(windows) * len(relations) * len(directions)
    print(f"\nSearch: {len(pairs)} pairs x {len(windows)} windows x {len(relations)} relations x "
          f"{len(directions)} dir = {total} candidates | leadlag k={LEADLAG_K}")
    results = []
    tested = 0
    for A, B in pairs:
        for n in windows:
            for rel in relations:
                mask = relation_mask(df, A, B, n, rel)
                if mask.sum() < MIN_TRADES:
                    continue
                for direction in directions:
                    sc = score_mask(df, mask, direction, month, adaptive, structural, warmup)
                    tested += 1
                    if sc is None:
                        continue
                    sc.update({'A': A, 'B': B, 'N': n, 'relation': rel, 'direction': direction})
                    results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo rolling lead-lag candidate met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 88)
    print("  FAMILY 11 — rolling lead-lag / cross-correlation (survival-first ranked)")
    print("  windowed relation between TWO series; causal trailing window [t-N+1..t]")
    print("=" * 88)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} {r['A']}<->{r['B']} N={r['N']:<3} {r['relation']}")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    cols = sorted({c for pair in PAIRS for c in pair})
    verify_live(df, cols + ['D2D_Trend_Dir'])
    print(f"Pair series live: {', '.join(cols)}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)

    # ---- run-proof subset; widen windows/relations/pairs for the full scan ----
    results = run_search(df, PAIRS, windows=[60], relations=RELATIONS,
                         directions=['LONG', 'SHORT'],
                         adaptive=adaptive, structural=structural, warmup=warmup)
    report(results)


if __name__ == '__main__':
    main()
