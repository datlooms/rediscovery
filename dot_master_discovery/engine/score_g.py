import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
for _d in (_HERE, os.path.join(_ROOT, 'scanners')):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import sequential_temporal as seq
import wf
import conviction as C

_F1 = re.compile(r'^(.*?)\s*->(\d+)->\s*(.*)$')


def build_book(df, pool, anchor, book):
    rows = []
    fk = 0
    for _, b in book.iterrows():
        if b['trigger'] == 'F0':
            ft = [p.strip().rsplit(':', 1) for p in b['signal_def'].split('+')]
            rows.append({'feat_1': ft[0][0], 'thresh_1': ft[0][1], 'feat_2': ft[1][0],
                         'thresh_2': ft[1][1], 'feat_3': ft[2][0], 'thresh_3': ft[2][1],
                         'direction': b['direction']})
        else:
            m = _F1.match(b['signal_def'])
            a, k, bb = m.group(1).strip(), int(m.group(2)), m.group(3).strip()
            col = f'__F1_{fk}'
            fk += 1
            df[col] = seq.pair_mask(pool[a], pool[bb], k, anchor).astype(int)
            rows.append({'feat_1': col, 'thresh_1': '==1', 'feat_2': col, 'thresh_2': '==1',
                         'feat_3': col, 'thresh_3': '==1', 'direction': b['direction']})
    return pd.DataFrame(rows)


def population(td):
    lots = td['lots'].values
    names = td['signal_name'].values
    dirs = td['direction'].values
    gap = (names == 'GAP_HURST') | (names == 'GAP_FB') | (names == 'GAP_D2D')
    book2 = (lots == 2.0) & ~gap
    return {'x1': int(((lots == 1.0) & ~gap).sum()), 'x2': int(book2.sum()),
            'x2_short': int((book2 & (dirs == 'SHORT')).sum()), 'x1.25': int((lots == 1.25).sum()),
            'gapH': int((names == 'GAP_HURST').sum()), 'gapF': int((names == 'GAP_FB').sum()),
            'gapD2D': int((names == 'GAP_D2D').sum())}


def score(df, sigs, ad, st, w, conv, tag):
    td = engine.run_portfolio(df, sigs, adaptive=ad, structural=st, warmup=w,
                              verbose=False, conviction=conv)
    p = td['pnl'].values
    wd = wf.daily_pnl_points(td)['pnl'].min()
    pf = round(p[p > 0].sum() / -p[p < 0].sum(), 2) if (p < 0).any() else 999.0
    wr = round((p > 0).sum() / len(td) * 100, 1)
    pop = population(td)
    mdd = _daily_mdd(td)
    print(f"{tag:22} tr={len(td):5} net=${p.sum():8.0f} PF={pf:5} WR={wr:5} wd={wd:7.1f} mDD={mdd:7.1f} | "
          f"x2={pop['x2']}(sh{pop['x2_short']}) x1.25={pop['x1.25']} gapH={pop['gapH']} gapF={pop['gapF']} gapD2D={pop['gapD2D']}")
    return td, p.sum()


def _daily_mdd(td):
    d = wf.daily_pnl_points(td).sort_values('exit_date')
    eq = d['pnl'].cumsum().values
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min()) if len(eq) else 0.0


def _baseline_dir():
    probe = 'equiDOT_recon171_step7_part1.csv'
    for cand in (_ROOT, os.path.join(_ROOT, 'data'), _HERE):
        if os.path.exists(os.path.join(cand, probe)):
            return cand
    return _ROOT


def main():
    os.chdir(_baseline_dir())
    df = engine.load_sealed_baseline(verbose=False)
    w = engine.warmup_floor(df, verbose=False)
    ad = dt.compute_adaptive_thresholds(df)
    st = dt.compute_structural_gates(df)
    anchor = seq.anchor_array(df, 'ST_Flip')
    pool = seq.build_condition_pool(df, ad, st, w)
    book = pd.read_csv(os.path.join(_HERE, 'book50_signals.csv'))
    sigs = build_book(df, pool, anchor, book)
    print('=== D2D CROWN-JEWEL OPTION MAP (BOOK-50 + jar + runner + momentum-SL + S.20 + D2D roles) ===')
    print('  built-system canonical: WR 92.3 / PF 6.40 / net $92,347 / daily wd -104.4 / daily mDD -145.9 / OOS PF 6.96')
    print('  toggles: DOT-alone $89,432/-153.7 | +Role2 +$1,011 | +Role1 14 gaps ~+$1,900 wd -104.4')
    _, base = score(df, sigs, ad, st, w,
                    C.build_conviction(df, True, True, True, d2d_conviction=False, d2d_gap=False), 'DOT-alone (S.20+warmup)')
    _, r2 = score(df, sigs, ad, st, w,
                  C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=False), '+Role2 D2D-conviction')
    _, r1 = score(df, sigs, ad, st, w,
                  C.build_conviction(df, True, True, True, d2d_conviction=False, d2d_gap=True), '+Role1 D2D-gap')
    _, crown = score(df, sigs, ad, st, w,
                     C.build_conviction(df, True, True, True, d2d_conviction=True, d2d_gap=True), 'CROWN JEWEL (all)')
    print(f"\n  Role2 conviction delta: +${r2-base:.0f} (target +$1,011)")
    print(f"  Role1 gap delta:        +${r1-base:.0f} (built-system canonical ~+$1,900, 14 gaps)")
    print(f"  Crown jewel net:        ${crown:.0f} (built-system canonical $92,347)")


if __name__ == '__main__':
    main()
