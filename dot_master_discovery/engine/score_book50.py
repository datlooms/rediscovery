import os
import sys
import shutil
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
for _d in ('engine', 'scanners', 'orchestrator'):
    _p = os.path.join(_ROOT, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
def _baseline_dir():
    probe = 'equiDOT_recon171_step7_part1.csv'
    for cand in (_ROOT, os.path.join(_ROOT, 'data')):
        if os.path.exists(os.path.join(cand, probe)):
            return cand
    return _ROOT
os.chdir(_baseline_dir())
for _n in os.listdir(os.path.join(_ROOT, 'data')):
    if _n.endswith('.csv') and not os.path.exists(os.path.join(os.getcwd(), _n)):
        try:
            os.symlink(os.path.join(_ROOT, 'data', _n), os.path.join(os.getcwd(), _n))
        except (OSError, NotImplementedError):
            shutil.copy2(os.path.join(_ROOT, 'data', _n), os.path.join(os.getcwd(), _n))

import re
import numpy as np
import pandas as pd
import dots_thresholds as dt
import portfolio_simulation_engine as engine
import sequential_temporal as seq
import wf

F1_RE = re.compile(r'^(.*?)\s*->(\d+)->\s*(.*)$')


def build_signals(df, adaptive, structural, warmup, path=None):
    if path is None:
        path = os.path.join(_HERE, 'book50_signals.csv')
    book = pd.read_csv(path)
    pool = seq.build_condition_pool(df, adaptive, structural, warmup)
    anchor = seq.anchor_array(df, 'ST_Flip')
    rows = []
    fk = 0
    for _, b in book.iterrows():
        if b['trigger'] == 'F0':
            parts = [p.strip() for p in b['signal_def'].split('+')]
            ft = [p.rsplit(':', 1) for p in parts]
            rows.append({'feat_1': ft[0][0], 'thresh_1': ft[0][1], 'feat_2': ft[1][0],
                         'thresh_2': ft[1][1], 'feat_3': ft[2][0], 'thresh_3': ft[2][1],
                         'direction': b['direction']})
        else:
            m = F1_RE.match(b['signal_def'])
            a, k, bb = m.group(1).strip(), int(m.group(2)), m.group(3).strip()
            col = f'__F1_{fk}'
            fk += 1
            df[col] = seq.pair_mask(pool[a], pool[bb], k, anchor).astype(int)
            rows.append({'feat_1': col, 'thresh_1': '==1', 'feat_2': col, 'thresh_2': '==1',
                         'feat_3': col, 'thresh_3': '==1', 'direction': b['direction']})
    return pd.DataFrame(rows)


def main():
    df = engine.load_sealed_baseline(verbose=False)
    warmup = engine.warmup_floor(df, verbose=False)
    adaptive = dt.compute_adaptive_thresholds(df)
    structural = dt.compute_structural_gates(df)
    sigs = build_signals(df, adaptive, structural, warmup)
    td = engine.run_portfolio(df, sigs, adaptive=adaptive, structural=structural,
                              warmup=warmup, verbose=False)
    pnl = td['pnl'].values
    n = len(td)
    daily = wf.daily_pnl_points(td)
    mon = pd.Series(td['exit_time'].values).str[:7].values
    _oos_legacy = ['2026.05', '2026.06']
    _present = sorted(set(mon.tolist()))
    _oos_rel = _present[-2:] if len(_present) >= 2 else _present
    oos = td[np.isin(mon, _oos_legacy)]['pnl'].values
    oos_rel = td[np.isin(mon, _oos_rel)]['pnl'].values
    e = td['exit_type'].value_counts().to_dict()
    print(f"BOOK-50 in-book (merged ratified TM):")
    print(f"  trades={n}  net=${pnl.sum():.0f}  PF={pnl[pnl>0].sum()/-pnl[pnl<0].sum():.2f}  "
          f"WR={(pnl>0).sum()/n*100:.1f}%  worst-day=${daily['pnl'].min():.1f}")
    print(f"  exits SL={e.get('SL',0)} BE={e.get('BE',0)} LF={e.get('LF',0)} FC={e.get('FC',0)}  "
          f"OOS PF={oos[oos>0].sum()/-oos[oos<0].sum():.2f} [LEGACY {'+'.join(_oos_legacy)}, STALE: fixed months, not selection input]  "
          f"OOS_rel PF={oos_rel[oos_rel>0].sum()/-oos_rel[oos_rel<0].sum():.2f} [{'+'.join(_oos_rel)}]  "
          f"L/S={(td.direction=='LONG').sum()}/{(td.direction=='SHORT').sum()}")


if __name__ == '__main__':
    main()
