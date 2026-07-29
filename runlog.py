"""engine/runlog.py — items 20 and 21. Instrumentation, logging, progress, ETA.

ITEM 20 SHIPS AS THE AUTHORISED DEVIATION. The checklist says profile before
parallelising, and profiling needs a real run at real scale — taken literally
that costs the operator two full runs of a stage that takes a day. Instead every
stage is instrumented so the RUN ITSELF emits the timing table. The table is an
output of the run he is about to do, not a separate blocking pass. Speculative
parallelism on stages of unknown cost is still forbidden; the next turn
parallelises whatever the table exposes.

TIMINGS ARE NOT AN ARTIFACT. They go to the run log, which is an ATTESTATION
RECORD alongside book_scored.jsonl — exempt from the determinism rule and
REQUIRED to carry wall-clock. Every CSV this pipeline writes stays byte-identical
across runs and worker counts and carries no wall-clock. That is how item 20's
reinterpretation stays compatible with the determinism assertion: the log is
exempt, the artifacts are not.

ITEM 21: the console stays readable whether it is watched, piped or redirected;
warnings go to the log; errors go to stderr; and every long stage prints a
progress line, a heartbeat and an ETA. The operator has twice had to guess
whether a healthy run was stuck.
"""

import os
import sys
import threading
import time

_STAGES = []
_LOG_FH = None
_LOG_PATH = None


class Tee(object):
    """Console AND log, without the caller knowing. Item 21."""

    def __init__(self, stream, fh):
        self._stream = stream
        self._fh = fh

    def write(self, s):
        self._stream.write(s)
        try:
            self._fh.write(s)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass
        try:
            self._fh.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False


def open_run_log(out_dir):
    """Item 21: the run writes its own log into the output tree, automatically."""
    global _LOG_FH, _LOG_PATH
    os.makedirs(out_dir, exist_ok=True)
    _LOG_PATH = os.path.join(out_dir, 'run_log.txt')
    _LOG_FH = open(_LOG_PATH, 'a', encoding='utf-8', errors='replace')
    _LOG_FH.write(f'\n=== RUN START {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} '
                  f'(ATTESTATION RECORD: wall-clock REQUIRED here and forbidden in every CSV) ===\n')
    _LOG_FH.flush()
    sys.stdout = Tee(sys.stdout, _LOG_FH)
    sys.stderr = Tee(sys.stderr, _LOG_FH)
    return _LOG_PATH


def warn(msg):
    """Item 21: warnings to the log, errors only on stderr."""
    if _LOG_FH is not None:
        _LOG_FH.write(f'WARNING {msg}\n')
        _LOG_FH.flush()


class Stage(object):
    """Item 20: time every stage. Context manager so an exception still records."""

    def __init__(self, name, note=''):
        self.name = name
        self.note = note
        self.t0 = None

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        secs = time.time() - self.t0
        _STAGES.append({'stage': self.name, 'seconds': round(secs, 2),
                        'status': 'ERROR' if exc_type else 'ok', 'note': self.note})
        return False


def timing_table():
    total = sum(s['seconds'] for s in _STAGES) or 1.0
    rows = []
    for s in _STAGES:
        rows.append({**s, 'pct_of_total': round(100.0 * s['seconds'] / total, 2)})
    return rows, total


def print_timing_table(concurrent_stages=()):
    """Item 20's deliverable: the table, with the genuinely concurrent fraction stated."""
    rows, total = timing_table()
    if not rows:
        return
    print('')
    print('STAGE TIMING TABLE (run log only — never an artifact, never a CSV)')
    print(f'  {"stage":<10} {"seconds":>10} {"pct":>7}  status  note')
    for r in sorted(rows, key=lambda x: -x['seconds']):
        print(f'  {r["stage"]:<10} {r["seconds"]:>10.2f} {r["pct_of_total"]:>6.2f}%  '
              f'{r["status"]:<6}  {r["note"]}')
    conc = sum(r['seconds'] for r in rows if r['stage'] in set(concurrent_stages))
    print(f'  TOTAL {total:.2f}s')
    print(f'  GENUINELY CONCURRENT: {conc:.2f}s of {total:.2f}s = {100.0*conc/total:.1f}% of total '
          f'runtime runs on more than one core. The remainder is sequential and is where the next '
          f'parallelism pass should look — measured, not guessed.')


class Progress(object):
    """Item 21: progress line, heartbeat and ETA on every long stage."""

    def __init__(self, label, total, min_interval=5.0, heartbeat=60.0):
        self.label = label
        self.total = max(int(total), 1)
        self.done = 0
        self.t0 = time.time()
        self.last = 0.0
        self.min_interval = min_interval
        self._stop = threading.Event()
        self._hb = None
        self.heartbeat = heartbeat

    def __enter__(self):
        if self.heartbeat:
            self._hb = threading.Thread(target=self._beat, daemon=True)
            self._hb.start()
        return self

    def _beat(self):
        while not self._stop.wait(self.heartbeat):
            el = time.time() - self.t0
            print(f'  ... {self.label} still running ({el/60:.1f} min elapsed, '
                  f'{self.done}/{self.total} done)', flush=True)

    def step(self, n=1, extra=''):
        self.done += n
        now = time.time()
        if now - self.last < self.min_interval and self.done < self.total:
            return
        self.last = now
        el = now - self.t0
        rate = self.done / el if el > 0 else 0.0
        eta = (self.total - self.done) / rate if rate > 0 else float('nan')
        pct = 100.0 * self.done / self.total
        eta_s = _hms(eta) if eta == eta else 'forming'
        print(f'  [{self.done}/{self.total} {pct:5.1f}%] {self.label} | elapsed {_hms(el)} '
              f'| ETA {eta_s} | {rate*60:.1f}/min{(" | " + extra) if extra else ""}', flush=True)

    def __exit__(self, *exc):
        self._stop.set()
        el = time.time() - self.t0
        print(f'  {self.label} complete: {self.done}/{self.total} in {_hms(el)}', flush=True)
        return False


def _hms(secs):
    if secs != secs or secs < 0:
        return '?'
    secs = int(secs)
    return f'{secs//3600}:{(secs%3600)//60:02d}:{secs%60:02d}'
