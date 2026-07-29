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


_F1 = re.compile(r'^(.*?)\s*->(\d+)->\s*(.*)$')
_F2 = re.compile(r'^(.+?):(-?\d+)->(-?\d+)$')
_F3 = re.compile(r'^(.+?)\s+GATED-BY\s+(.+?)==(-?\d+)$')
_F7 = re.compile(r'^FADE\s+(.+)$')
_F9 = re.compile(r'^(.+?)\s+IN-SESSION\s+(\S+)$')

_F6 = re.compile(r'^(.+?)\s+(up|down)-cross\(level=(hi|lo)\)\s+ROC=(\S+)$')
_F8 = re.compile(r'^(.+?)\s+(>|<|!=)\s+(.+)$')
_F11 = re.compile(r'^(.+?)<->(.+?)\s+N=(\d+)\s+(\S+)$')
_F4 = re.compile(r'^(.+?):(\S+)\s+NOT-CONFIRMED-BY\s+(.+?):(\S+)$')

UNSCOREABLE_FAMILIES = {}


def _pool_mask(pool, label, fam, sig):
    if label not in pool:
        raise SystemExit(
            f'ABORT [{fam}] signal_def "{sig}" references condition "{label}", which is not in the '
            f'{len(pool)}-condition pool. The book cannot be scored; the candidate is NOT silently '
            f'dropped and NOT reparsed as another family.')
    return np.asarray(pool[label], dtype=bool)


def family_mask(df, pool, fam, sig, adaptive=None, structural=None):
    if fam == 'F6':
        m = _F6.match(sig)
        if m:
            import threshold_crossing as f6
            import portfolio_simulation_engine as _eng
            feat, level, roc = m.group(1).strip(), m.group(3), m.group(4)
            if adaptive is None or structural is None:
                raise SystemExit(
                    f'ABORT [F6] "{sig}" needs the oracle thresholds to rebuild its crossing mask, '
                    f'but build_book was called without adaptive/structural. Refusing to approximate.')
            out = np.asarray(f6.crossing_mask(df, feat, level, adaptive, structural), dtype=bool)
            if roc != 'none':
                if ':' not in roc:
                    raise SystemExit(f'ABORT [F6] unparseable ROC token "{roc}" in "{sig}".')
                rf, rt = roc.rsplit(':', 1)
                out = out & np.asarray(_eng.condition_mask(df, rf, rt, adaptive, structural),
                                       dtype=bool)
            return out
    if fam == 'F8':
        m = _F8.match(sig)
        if m:
            import cross_variable_structure as f8
            a, op, b = m.group(1).strip(), m.group(2), m.group(3).strip()
            kind = 'disagree' if op == '!=' else 'ineq'
            for lbl, msk in f8.relation_masks(df, a, b, kind):
                if lbl == sig.strip():
                    return np.asarray(msk, dtype=bool)
            raise SystemExit(
                f'ABORT [F8] "{sig}" did not match any label relation_masks emitted for '
                f'({a}, {b}, {kind}). Refusing to guess which relation was meant.')
    if fam == 'F11':
        m = _F11.match(sig)
        if m:
            import rolling_leadlag as f11
            A, B = m.group(1).strip(), m.group(2).strip()
            n, rel = int(m.group(3)), m.group(4).strip()
            return np.asarray(f11.relation_mask(df, A, B, n, rel), dtype=bool)

    if fam == 'F5':
        return _pool_mask(pool, sig.strip(), fam, sig)
    if fam == 'F7':
        m = _F7.match(sig)
        if m:
            return _pool_mask(pool, m.group(1).strip(), fam, sig)
    if fam == 'F3':
        m = _F3.match(sig)
        if m:
            base = _pool_mask(pool, m.group(1).strip(), fam, sig)
            col, val = m.group(2).strip(), int(m.group(3))
            if col not in df.columns:
                raise SystemExit(f'ABORT [{fam}] gate column "{col}" absent from the frame for "{sig}".')
            return base & (df[col].values == val)
    if fam == 'F2':
        import state_transition as f2
        col = sig.split(':', 1)[0].strip()
        if col not in df.columns:
            raise SystemExit(f'ABORT [F2] state column "{col}" absent from the frame for "{sig}".')
        vals = df[col].values
        rest = sig.split(':', 1)[1].strip() if ':' in sig else ''
        if rest == 'any':
            return np.asarray(f2.any_change(vals), dtype=bool)
        m = _F2.match(sig)
        if m:
            return np.asarray(f2.typed_transition(vals, int(m.group(2)), int(m.group(3))),
                              dtype=bool)
    if fam == 'F9':
        m = _F9.match(sig)
        if m:
            import session_temporal as f9
            base = _pool_mask(pool, m.group(1).strip(), fam, sig)
            gate_lbl = m.group(2).strip()
            sess = f9.session_masks(df)
            wds = f9.weekday_masks(df)
            if '&' in gate_lbl:
                s_lbl, w_lbl = gate_lbl.split('&', 1)
            else:
                s_lbl, w_lbl = gate_lbl, None
            if s_lbl not in sess:
                raise SystemExit(
                    f'ABORT [F9] session anchor "{s_lbl}" in "{sig}" is not one of '
                    f'{sorted(sess)}. Refusing to approximate the gate.')
            gate = np.asarray(sess[s_lbl], dtype=bool)
            if w_lbl is not None:
                if w_lbl not in wds:
                    raise SystemExit(
                        f'ABORT [F9] weekday gate "{w_lbl}" in "{sig}" is not one of '
                        f'{sorted(wds)} for this dataset.')
                gate = gate & np.asarray(wds[w_lbl], dtype=bool)
            return base & gate
    if fam == 'F4':
        m = _F4.match(sig)
        if m:
            import divergence_nonconfirm as f4
            if adaptive is None or structural is None:
                raise SystemExit(
                    f'ABORT [F4] "{sig}" needs the oracle thresholds to rebuild its divergence '
                    f'mask, but build_book was called without adaptive/structural.')
            return np.asarray(f4.divergence_mask(df, m.group(1).strip(), m.group(2).strip(),
                                                 m.group(3).strip(), m.group(4).strip(),
                                                 adaptive, structural), dtype=bool)
    if fam in UNSCOREABLE_FAMILIES:
        raise SystemExit(
            f'ABORT [{fam}] cannot be scored by build_book: {UNSCOREABLE_FAMILIES[fam]}. '
            f'signal_def "{sig}". S5 should have filtered this family out before S8; if it reached '
            f'here the filter and the scorer disagree.')
    raise SystemExit(
        f'ABORT [{fam}] unrecognised signal_def grammar: "{sig}". build_book will not guess and will '
        f'not fall through to another family parser — that silent fall-through is what crashed S8.')


def build_book(df, pool, anchor, book, adaptive=None, structural=None):
    rows = []
    fk = 0
    for _, b in book.iterrows():
        fam = str(b['family']).strip() if 'family' in book.columns else str(b['trigger']).strip()
        sig = str(b['signal_def'])
        if fam == 'F0':
            ft = [p.strip().rsplit(':', 1) for p in sig.split('+')]
            rows.append({'feat_1': ft[0][0], 'thresh_1': ft[0][1], 'feat_2': ft[1][0],
                         'thresh_2': ft[1][1], 'feat_3': ft[2][0], 'thresh_3': ft[2][1],
                         'direction': b['direction']})
            continue
        col = f'__BOOK_{fk}'
        fk += 1
        if fam == 'F1':
            m = _F1.match(sig)
            if m is None:
                raise SystemExit(
                    f'ABORT [F1] signal_def "{sig}" does not match the sequential-pair grammar '
                    f'A ->k-> B. Refusing to guess.')
            a, k, bb = m.group(1).strip(), int(m.group(2)), m.group(3).strip()
            for lbl in (a, bb):
                if lbl not in pool:
                    raise SystemExit(f'ABORT [F1] "{lbl}" is not in the condition pool for "{sig}".')
            df[col] = seq.pair_mask(pool[a], pool[bb], k, anchor).astype(int)
        else:
            df[col] = family_mask(df, pool, fam, sig, adaptive, structural).astype(int)
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

_SHAPE_ID = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
_SHAPE_NUM = re.compile(r'-?\d+(?:\.\d+)?')
_SHAPE_KEEP = {'IN', 'SESSION', 'GATED', 'BY', 'NOT', 'CONFIRMED', 'FADE', 'DOW', 'ROC',
               'up', 'down', 'cross', 'level', 'none', 'any', 'N'}


def grammar_shape(sig):
    out = _SHAPE_NUM.sub('N', str(sig))
    def _r(m):
        t = m.group(0)
        return t if t in _SHAPE_KEEP else 'V'
    return _SHAPE_ID.sub(_r, out)


def can_parse(fam, sig):
    sig = str(sig)
    if fam == 'F0':
        return len([p for p in sig.split('+') if ':' in p]) == 3
    if fam == 'F1':
        return _F1.match(sig) is not None
    if fam == 'F2':
        return sig.split(':', 1)[-1].strip() == 'any' or _F2.match(sig) is not None
    if fam == 'F3':
        return _F3.match(sig) is not None
    if fam == 'F5':
        return ':' in sig and ' ' not in sig.strip()
    if fam == 'F6':
        return _F6.match(sig) is not None
    if fam == 'F7':
        return _F7.match(sig) is not None
    if fam == 'F8':
        return _F8.match(sig) is not None
    if fam == 'F9':
        return _F9.match(sig) is not None
    if fam == 'F11':
        return _F11.match(sig) is not None
    if fam == 'F4':
        return _F4.match(sig) is not None
    return False


def grammar_coverage(pool_df):
    rows = []
    for fam, g in pool_df.groupby('family'):
        shapes = {}
        for sig in g['signal_def'].astype(str):
            shapes.setdefault(grammar_shape(sig), []).append(sig)
        for shape, sigs in sorted(shapes.items(), key=lambda kv: -len(kv[1])):
            ok = can_parse(fam, sigs[0])
            rows.append({'family': fam, 'grammar_shape': shape, 'rows': len(sigs),
                         'example': sigs[0], 'handled': bool(ok),
                         'reason': '' if ok else (UNSCOREABLE_FAMILIES.get(fam)
                                                  or 'no parser branch matches this form')})
    return pd.DataFrame(rows)

