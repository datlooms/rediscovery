import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 3 — CONDITIONAL / INTERACTION (context-gating)  (scanner)
#  Relationship: "X matters ONLY when Y is in regime Z" — a FEAT_ condition
#  that is noise globally but strong inside a state sub-population. The
#  signal is a base FEAT_ hi/lo condition AND a conditioning state held at a
#  value:  base_mask & (state == value).  NOT a same-bar triple (F0), NOT a
#  transition (F2).
#
#  Base: any of the 90 FEAT_ (hi/lo) via engine.condition_mask (oracle).
#  Conditioning gate (state/regime, live, in the equality-27): AT_Regime_ST,
#  AT_Regime_LT, Sqz_State, Trend_Concordance, Trend_Conflict,
#  Harmonic_D2D_Concordance.
#
#  Thresholds: oracle-only. The AND mask is injected as a one-column '==1'
#  signal and driven through engine.run_portfolio; ZERO TM reconstruction.
#  D2D gate: confirm (entry dir == D2D_Trend_Dir) — applied by the engine.
#  Scoring: survival-first walk-forward via wf.py primitives. Each candidate
#  reports BASE-ALONE vs BASE-GATED so the sub-population effect is visible.
#  F3 is no-new-input tier: AND of existing exported columns — no derived
#  quantity, no parity burden.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F3COND'

GATE_STATES = ['AT_Regime_ST', 'AT_Regime_LT', 'Sqz_State',
               'Trend_Concordance', 'Trend_Conflict', 'Harmonic_D2D_Concordance']


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def scannable(df, warmup):
    nonwarm = np.arange(len(df)) >= warmup
    eligible = (df['ADX_Value'].values >= 15) & (df['Volume'].values > 50)
    return eligible & nonwarm


def build_base_pool(df, feat_labels, adaptive, structural):
    pool = {}
    for lbl in feat_labels:
        feat, thr = lbl.split(':')
        pool[lbl] = engine.condition_mask(df, feat, thr, adaptive, structural)
    return pool


def build_gate_masks(df, states, warmup):
    scan = scannable(df, warmup)
    gates = {}
    for state in states:
        for v in sorted(set(int(x) for x in df[state].values[scan])):
            gates[f"{state}=={v}"] = df[state].values == v
    print(f"Conditioning gates: {len(states)} states -> {len(gates)} state==value gates")
    return gates


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


def run_search(df, base_pool, gate_masks, directions, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    base_alone = {}
    for base_lbl, base_mask in base_pool.items():
        for direction in directions:
            base_alone[(base_lbl, direction)] = score_mask(
                df, base_mask, direction, month, adaptive, structural, warmup)
    total = len(base_pool) * len(gate_masks) * len(directions)
    print(f"\nSearch: {len(base_pool)} base x {len(gate_masks)} gates x "
          f"{len(directions)} dir = {total} candidates")
    results = []
    tested = 0
    for base_lbl, base_mask in base_pool.items():
        for gate_lbl, gate_mask in gate_masks.items():
            mask = base_mask & gate_mask
            if mask.sum() < MIN_TRADES:
                continue
            for direction in directions:
                sc = score_mask(df, mask, direction, month, adaptive, structural, warmup)
                tested += 1
                if sc is None:
                    continue
                ba = base_alone.get((base_lbl, direction))
                sc.update({'base': base_lbl, 'gate': gate_lbl, 'direction': direction,
                           'base_alone': ba})
                results.append(sc)
    print(f"Scored {tested} gated candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo gated candidate met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 82)
    print("  FAMILY 3 — conditional/interaction candidates (survival-first ranked)")
    print("  base-GATED vs base-ALONE (sub-population lift is the point)")
    print("=" * 82)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} {r['base']}  GATED-BY  {r['gate']}")
        print(f"           GATED: trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")
        ba = r['base_alone']
        if ba is None:
            print(f"           ALONE: <{MIN_TRADES} trades base-alone")
        else:
            print(f"           ALONE: trades {ba['trades']:>4} | aggPF {ba['agg_pf']:>5.2f} | "
                  f"WR {ba['agg_wr']:>4.1f}% | worst-day ${ba['worst_day_usd']:>9,.0f} | "
                  f"folds+ {ba['profitable_folds']}/6 | minfoldPF {ba['min_fold_pf']:>4.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_live(df, GATE_STATES + ['D2D_Trend_Dir'])
    print(f"Gate states live: {', '.join(GATE_STATES)}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)

    # ---- run-proof subset (widen base_labels / states / directions for the
    # full scan; nothing here caps the core logic) ----
    base_labels = ['ADX_Value:hi', 'Momentum_Value:hi', 'KAMA_Dist_ATR:lo', 'VWAP_Z:hi']
    base_pool = build_base_pool(df, base_labels, adaptive, structural)
    gate_masks = build_gate_masks(df, ['AT_Regime_ST', 'Sqz_State'], warmup)
    results = run_search(df, base_pool, gate_masks, directions=['LONG', 'SHORT'],
                         adaptive=adaptive, structural=structural, warmup=warmup)
    report(results)


if __name__ == '__main__':
    main()
