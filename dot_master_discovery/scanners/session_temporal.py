import sys
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import wf

# ═══════════════════════════════════════════════════════════════
#  FAMILY 9 — TEMPORAL / SESSION / CALENDAR  (conditioner scanner)
#  Relationship: an edge that holds only around a NAMED session event or on
#  a given weekday. F9 is a CONDITIONER, not a standalone directional family
#  — it layers a session-anchor / weekday gate onto a base condition and
#  INHERITS that base family's D2D setting (an F0 base inherits confirm).
#
#  Session anchors (named only — no 24/60-way sweep). EST_Minute is struck
#  as a free dimension and used ONLY to pin the two :30 events exactly:
#     08:00 -> EST_Hour==8            (pre-market pickup, hour block)
#     09:30 -> EST_Hour==9  & Min==30 (cash open, exact event)
#     10:00 -> EST_Hour==10           (first reversal window, hour block)
#     15:30 -> EST_Hour==15 & Min==30 (MOC ramp, exact event)
#     16:00 -> EST_Hour==16           (close, hour block)
#  Weekday gate: EST_DayOfWeek (observed values, generic DOW==k).
#
#  Base: an F0 oracle FEAT_ hi/lo via engine.condition_mask. Signal =
#  base & session[/weekday]. Injected as a one-column '==1' signal, driven
#  through engine.run_portfolio; ZERO TM reconstruction. D2D = inherited
#  (confirm for F0 base), engine-applied. Base-alone vs base+session is
#  reported so the session effect is visible (like F3).
#  F9 is no-new-input tier: EST_Hour/EST_DayOfWeek used as-is (+ exact :30
#  pin) — no derived quantity, no parity burden.
# ═══════════════════════════════════════════════════════════════

MIN_TRADES = 30
SEQ_COL = '__F9SESS'
BASE_D2D = 'confirm'  # inherited from the F0 base family


def verify_live(df, cols):
    dead = [c for c in cols if c not in df.columns or df[c].nunique() <= 1]
    if dead:
        raise ValueError(f"cited columns dead or missing: {dead}")
    return True


def session_masks(df):
    h = df['EST_Hour'].values
    m = df['EST_Minute'].values
    return {
        '08:00': h == 8,
        '09:30': (h == 9) & (m == 30),
        '10:00': h == 10,
        '15:30': (h == 15) & (m == 30),
        '16:00': h == 16,
    }


def weekday_masks(df):
    dow = df['EST_DayOfWeek'].values
    return {f"DOW=={k}": dow == k for k in sorted(set(int(x) for x in dow))}


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


def run_search(df, base_labels, sessions, weekdays, directions,
               adaptive, structural, warmup):
    month = pd.Series(df['Time'].values).str[:7].values
    if SEQ_COL not in df.columns:
        df[SEQ_COL] = 0
    base_alone = {}
    base_masks = {}
    for lbl in base_labels:
        feat, thr = lbl.split(':')
        base_masks[lbl] = engine.condition_mask(df, feat, thr, adaptive, structural)
        for direction in directions:
            base_alone[(lbl, direction)] = score_mask(
                df, base_masks[lbl], direction, month, adaptive, structural, warmup)
    # session gates, optionally crossed with weekday
    gates = dict(sessions)
    if weekdays:
        for s_lbl, s_mask in sessions.items():
            for w_lbl, w_mask in weekdays.items():
                gates[f"{s_lbl}&{w_lbl}"] = s_mask & w_mask
    total = len(base_labels) * len(gates) * len(directions)
    print(f"\nSearch: {len(base_labels)} base x {len(gates)} session/weekday gates x "
          f"{len(directions)} dir = {total} candidates | D2D inherited = {BASE_D2D}")
    results = []
    tested = 0
    for base_lbl in base_labels:
        for gate_lbl, gate_mask in gates.items():
            mask = base_masks[base_lbl] & gate_mask
            if mask.sum() < MIN_TRADES:
                continue
            for direction in directions:
                sc = score_mask(df, mask, direction, month, adaptive, structural, warmup)
                tested += 1
                if sc is None:
                    continue
                sc.update({'base': base_lbl, 'session': gate_lbl, 'direction': direction,
                           'base_alone': base_alone.get((base_lbl, direction))})
                results.append(sc)
    print(f"Scored {tested} session-gated candidates with >= {MIN_TRADES} completions.")
    return results


def report(results):
    if not results:
        print("\nNo session-gated candidate met the minimum-trade floor.")
        return
    results.sort(key=lambda r: (r['survival_pass'], r['profitable_folds'],
                                r['min_fold_pf'], r['agg_pf']), reverse=True)
    print("\n" + "=" * 84)
    print(f"  FAMILY 9 — temporal / session conditioner (survival-first ranked)")
    print(f"  base+SESSION vs base-ALONE (session lift is the point); D2D inherited={BASE_D2D}")
    print("=" * 84)
    for r in results[:25]:
        surv = 'PASS' if r['survival_pass'] else 'REJECT'
        print(f"  [{surv:6}] {r['direction']:5} {r['base']}  IN-SESSION  {r['session']}")
        print(f"           SESSION: trades {r['trades']:>4} | aggPF {r['agg_pf']:>5.2f} | "
              f"WR {r['agg_wr']:>4.1f}% | worst-day ${r['worst_day_usd']:>9,.0f} | "
              f"hard-stop {r['hard_stop_days']:>2} | folds+ {r['profitable_folds']}/6 | "
              f"minfoldPF {r['min_fold_pf']:>4.2f} | spread {r['pf_base']:.2f}->{r['pf_stress']:.2f}")
        ba = r['base_alone']
        if ba is None:
            print(f"           ALONE:   <{MIN_TRADES} trades base-alone")
        else:
            print(f"           ALONE:   trades {ba['trades']:>4} | aggPF {ba['agg_pf']:>5.2f} | "
                  f"WR {ba['agg_wr']:>4.1f}% | worst-day ${ba['worst_day_usd']:>9,.0f} | "
                  f"folds+ {ba['profitable_folds']}/6 | minfoldPF {ba['min_fold_pf']:>4.2f}")


def main():
    df = engine.load_sealed_baseline()
    warmup = engine.warmup_floor(df)
    verify_live(df, ['EST_Hour', 'EST_DayOfWeek', 'EST_Minute', 'D2D_Trend_Dir'])
    sessions = session_masks(df)
    weekdays = weekday_masks(df)
    print(f"Session anchors: {', '.join(sessions.keys())} | weekdays: {', '.join(weekdays.keys())}")
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)

    # ---- run-proof subset; widen base_labels / weekdays for the full scan.
    # weekdays=None here keeps the session sweep bounded; pass `weekdays` to
    # cross session x weekday. ----
    base_labels = ['ADX_Value:hi', 'Momentum_Value:hi', 'VWAP_Z:hi']
    results = run_search(df, base_labels, sessions, weekdays=None,
                         directions=['LONG', 'SHORT'],
                         adaptive=adaptive, structural=structural, warmup=warmup)
    report(results)


if __name__ == '__main__':
    main()
