import argparse
import glob
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.join(_HERE, 'engine')
for _d in (_HERE, _ENGINE):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import numpy as np
import pandas as pd
from _packutil import _natkey, split_output


def _load_core_functions():
    src_path = os.path.join(_ENGINE, 'core.py')
    with open(src_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    cut = next((i for i, ln in enumerate(lines) if ln.startswith('print("Loading')), len(lines))
    ns = {}
    exec(''.join(lines[:cut]), ns)
    return ns


def _canonical_schema():
    for cand in sorted(glob.glob(os.path.join(_HERE, 'data', '*.csv'))):
        head = open(cand, 'r', encoding='utf-8').readline().strip()
        if head.split(',')[0] == 'Time':
            return head.split(',')
    return None


def _read_raw(path):
    first = open(path, 'r', encoding='utf-8').readline().strip()
    hdr = 0 if first.split(',')[0] == 'Time' else None
    df = pd.read_csv(path, header=hdr)
    return df


def reconstruct(df):
    ncols = df.shape[1]
    if 'Time' in df.columns and ncols == 172:
        return df, 'export=live 172-col (Time+171) consumed as-is'
    if 'Time' in df.columns and ncols > 172:
        schema = _canonical_schema()
        if schema is not None and all(c in df.columns for c in schema):
            return df[schema].copy(), f'wide export reduced to canonical 172-col ({ncols}→172)'
        keep = list(df.columns[:172])
        return df[keep].copy(), f'wide export reduced to first 172 cols ({ncols}→172)'
    core = _load_core_functions()
    need = {'Open', 'High', 'Low', 'Close', 'Volume', 'Time'}
    if not need.issubset(set(df.columns)):
        print(f'ABORT — raw export has {ncols} cols and lacks OHLCV+Time; cannot reconstruct.')
        sys.exit(2)
    fam = core['families'](df)
    atr = fam['ATR_1M'].values if 'ATR_1M' in fam else df.get('ATR_1M')
    new45 = core['compute_new45'](df, atr)
    out = pd.DataFrame({'Time': df['Time'].values})
    for k, v in {**fam, **new45}.items():
        out[k] = v
    return out, f'core.py reconstruction (families + compute_new45) from OHLCV ({ncols}→{out.shape[1]})'


def validate(df):
    if 'Time' not in df.columns or df.shape[1] != 172:
        return False, f'column contract: {df.shape[1]} cols (need Time + 171)'
    t = df['Time'].astype(str).values
    if not (t[1:] > t[:-1]).all():
        return False, 'time not strictly increasing'
    if df.duplicated().any():
        return False, 'duplicate rows present'
    if df.isna().any().any():
        return False, 'NaN cells present'
    return True, 'PASS'


def clear_data(data_dir):
    old = sorted(glob.glob(os.path.join(data_dir, '*.csv')), key=_natkey)
    if old:
        print(f'  clearing {len(old)} old CSV(s) from data/:')
        for f in old:
            print(f'    - {os.path.basename(f)}')
            os.remove(f)
    for m in glob.glob(os.path.join(data_dir, '*_manifest.txt')):
        os.remove(m)


def main():
    ap = argparse.ArgumentParser(description='DOT Master Discovery — data-prep: raw EA export → validated 171-col baseline → data/.')
    ap.add_argument('--in', dest='inp', default=None, help='raw EA export CSV (default: newest CSV in raw/)')
    ap.add_argument('--raw', default=os.path.join(_HERE, 'raw'), help='raw-export folder')
    ap.add_argument('--data', default=os.path.join(_HERE, 'data'), help='output data folder')
    ap.add_argument('--chunk-mb', type=int, default=9)
    args = ap.parse_args()

    print('═' * 68)
    print('DOT MASTER DISCOVERY — rebuild (data-prep)')
    print('═' * 68)
    raw = args.inp
    if raw is None:
        cands = sorted(glob.glob(os.path.join(args.raw, '*.csv')), key=os.path.getmtime)
        if not cands:
            print(f'ABORT — no CSV in {args.raw}. Drop the raw EA export (<ASSET>_AUTO_EXPORT.csv) there, then re-run.')
            sys.exit(2)
        raw = cands[-1]
    if not os.path.exists(raw):
        print(f'ABORT — raw export not found: {raw}')
        sys.exit(2)
    print(f'raw export : {raw}')

    df = _read_raw(raw)
    print(f'read       : {len(df):,} rows × {df.shape[1]} cols')
    out, how = reconstruct(df)
    print(f'reconstruct: {how}')
    print('             (delta state-column shift is a one-time original-build fix vs the 64_256 reference;')
    print("              a fixed-EA export is already export=live in correct order — no shift applied.)")

    ok, msg = validate(out)
    t = out['Time'].astype(str).values if 'Time' in out.columns else ['?', '?']
    print(f'rows       : {len(out):,}')
    print(f'cols       : {out.shape[1]} (Time + {out.shape[1] - 1} features)')
    print(f'range      : {t[0]} → {t[-1]}')
    print(f'invariants : {"PASS" if ok else "FAIL — " + msg}')
    if not ok:
        print('ABORT — invariant failure; nothing written to data/.')
        sys.exit(2)

    os.makedirs(args.data, exist_ok=True)
    clear_data(args.data)
    asset = os.path.basename(raw).replace('_AUTO_EXPORT', '').replace('.csv', '')
    stem = os.path.join(args.data, f'{asset}_baseline.csv')
    out.to_csv(stem, index=False, lineterminator='\n')
    parts = split_output(stem, args.chunk_mb)
    print(f'wrote      : {len(parts)} part(s) to data/ (≤{args.chunk_mb}MB, header in part1 only):')
    for p in parts:
        print(f'    - {os.path.basename(p)}  ({os.path.getsize(p) // 1024} KB)')
    print('═' * 68)
    print('READY — run:  python master.py            (discover fresh)')
    print('        or :  python master.py --book engine/book50_signals.csv   (score the ratified book)')
    print('═' * 68)


if __name__ == '__main__':
    main()
