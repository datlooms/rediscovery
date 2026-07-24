import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 2 — TRANSITION / REGIME-CHANGE  (discovery scanner)
#  Relationship: the edge is in the SWITCH between states, not the state
#  itself — value[t] != value[t-1] (onset / release / flip). A candidate is
#  a typed transition (state[t-1]==a & state[t]==b) or a generic change
#  (state[t] != state[t-1]); head-padded, no wraparound.
#
#  States (all live, in the equality-27): Sqz_State, RangeOsc_State,
#  AT_Regime_ST, AT_Regime_LT, ADX_Rising, ST_Flip_Event.
#  DecayState_ST/LT are STRUCK (constant 0, dead) — never used.
#
#  Thresholds: oracle-only (dots_thresholds via engine). The transition
#  boolean is injected as a one-column '==1' signal and driven through
#  engine.run_portfolio; ZERO TM reconstruction.
#  D2D gate: confirm (entry dir == D2D_Trend_Dir) — applied by the engine.
#  Scoring: survival-first walk-forward via wf.py primitives.
#  F2 is new-derived-input tier: the lag-1 transition boolean is computed
#  here in Python on the sealed baseline — analysis-only; production parity
#  is a Stage-9 concern, not a discovery blocker.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F2TRANS'

STATE_CANDIDATES = ['Sqz_State', 'RangeOsc_State', 'AT_Regime_ST', 'AT_Regime_LT',
                    'ADX_Rising', 'ST_Flip_Event']
STRUCK = ['DecayState_ST', 'DecayState_LT']


def verify_states(df, states):
    if any(s in states for s in STRUCK):
        raise ValueError(f"struck dead columns present in candidate list: {STRUCK}")
    dead = [s for s in states + ['D2D_Trend_Dir'] if s not in df.columns or df[s].nunique() <= 1]
    if dead:
        raise ValueError(f"cited state/gate columns dead or missing: {dead}")
    for s in STRUCK:
        if s in df.columns and df[s].nunique() > 1:
            raise ValueError(f"{s} is not dead as documented (nunique>1)")
    return True


def scannable_values(df, state, warmup):
    nonwarm = np.arange(len(df)) >= warmup
    eligible = (df['ADX_Value'].values >= 15) & (df['Volume'].values > 50)
    scan = eligible & nonwarm
    return sorted(set(int(v) for v in df[state].values[scan]))


def typed_transition(vals, a, b):
    m = np.zeros(len(vals), dtype=bool)
    m[1:] = (vals[:-1] == a) & (vals[1:] == b)
    return m


def any_change(vals):
    m = np.zeros(len(vals), dtype=bool)
    m[1:] = vals[1:] != vals[:-1]
    return m


def build_transition_pool(df, states, warmup):
    pool = {}
    for state in states:
        vals = df[state].values
        sv = scannable_values(df, state, warmup)
        pool[f"{state}:any"] = any_change(vals)
        for a in sv:
            for b in sv:
                if a == b:
                    continue
                m = typed_transition(vals, a, b)
                if m.sum() >= MIN_TRADES:
                    pool[f"{state}:{a}->{b}"] = m
    print(f"Transition pool: {len(states)} states -> {len(pool)} transition conditions "
          f"(typed with >= {MIN_TRADES} occurrences + generic any-change)")
    return pool


def score_candidate(df, mask, direction, month, adaptive, structural, warmup):
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


def run_search(df, pool, cond_labels, directions, adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    total = len(cond_labels) * len(directions)
    print(f"\nSearch: {len(cond_labels)} transitions x {len(directions)} dir = {total} candidates")
    results = []
    tested = 0
    for lbl in cond_labels:
        mask = pool[lbl]
        for direction in directions:
            sc = score_candidate(df, mask, direction, month, adaptive, structural, warmup)
            tested += 1
            if sc is None:
                continue
            sc.update({'transition': lbl, 'direction': direction})
            results.append(sc)
    print(f"Scored {tested} candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo candidate transition met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 78)
    print("  FAMILY 2 — transition candidates (survival-first ranked)")
    print("=" * 78)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} {r['transition']}")
        print(f"           trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_states(df, STATE_CANDIDATES)
    print(f"State columns live: {', '.join(STATE_CANDIDATES)} | "
          f"DecayState_ST/LT struck (dead)")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    pool = build_transition_pool(df, STATE_CANDIDATES, warmup)

    # ---- run-proof subset (the full state list + full pool is available by
    # widening states / cond_labels / directions; nothing here caps the core) ----
    subset_states = ['Sqz_State', 'ADX_Rising', 'RangeOsc_State']
    subset_pool = build_transition_pool(df, subset_states, warmup)
    results = run_search(df, subset_pool, list(subset_pool.keys()),
                         directions=['LONG', 'SHORT'],
                         adaptive=adaptive, structural=structural, warmup=warmup)
    report(results)


if __name__ == '__main__':
    main()
