import hashlib
import os
import re


def sha12(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:12]


def _natkey(path):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', os.path.basename(path))]


def split_output(path, chunk_mb):
    limit = chunk_mb * 1024 * 1024
    if not os.path.exists(path) or os.path.getsize(path) <= limit:
        return [path]
    base, ext = os.path.splitext(path)
    parts = []
    if ext.lower() == '.jsonl':
        lines = open(path, 'r', encoding='utf-8').read().splitlines(keepends=True)
        cur, sz, idx = [], 0, 1
        for ln in lines:
            b = len(ln.encode())
            if sz + b > limit and cur:
                pp = f'{base}_part{idx:02d}.jsonl'
                open(pp, 'w', encoding='utf-8').write(''.join(cur))
                parts.append(pp)
                cur, sz, idx = [], 0, idx + 1
            cur.append(ln)
            sz += b
        if cur:
            pp = f'{base}_part{idx:02d}.jsonl'
            open(pp, 'w', encoding='utf-8').write(''.join(cur))
            parts.append(pp)
    else:
        with open(path, 'r', encoding='utf-8') as f:
            header = f.readline()
            body = f.readlines()
        cur, sz, idx = [], len(header.encode()), 1
        for ln in body:
            b = len(ln.encode())
            if sz + b > limit and cur:
                pp = f'{base}_part{idx:02d}.csv'
                open(pp, 'w', encoding='utf-8').write(header + ''.join(cur) if idx == 1 else ''.join(cur))
                parts.append(pp)
                cur, sz, idx = [], 0, idx + 1
            cur.append(ln)
            sz += b
        if cur:
            pp = f'{base}_part{idx:02d}.csv'
            open(pp, 'w', encoding='utf-8').write(header + ''.join(cur) if idx == 1 else ''.join(cur))
            parts.append(pp)
    man = f'{base}_manifest.txt'
    with open(man, 'w', encoding='utf-8') as f:
        f.write(f'# split of {os.path.basename(path)} — header in part1 only, continuation parts headerless\n')
        for pp in parts:
            f.write(f'{sha12(pp)}  {os.path.basename(pp)}\n')
    os.remove(path)
    return parts
