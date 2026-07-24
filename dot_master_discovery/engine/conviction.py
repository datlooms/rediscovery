import numpy as np
import dots_thresholds as dt
import portfolio_simulation_engine as engine


def _swept(df, specs):
    saved = dict(dt._D_SPEC)
    try:
        dt._D_SPEC.clear()
        dt._D_SPEC.update(specs)
        out = dt.compute_adaptive_thresholds(df)
    finally:
        dt._D_SPEC.clear()
        dt._D_SPEC.update(saved)
    return out


def build_conviction(df, hurst_sizing=True, recentfb_sizing=True, gap_singles=True,
                     d2d_conviction=True, d2d_gap=True, window=5):
    thr = _swept(df, {('Micro_Hurst', 'p90'): ('Micro_Hurst', engine.HURST_SIZE_PCT),
                      ('Micro_Hurst', 'p97'): ('Micro_Hurst', engine.HURST_GAP_PCT),
                      ('Micro_Hurst', 'p30'): ('Micro_Hurst', engine.D2D_HURST_PCT),
                      ('Micro_FailedBreak', 'p90'): ('Micro_FailedBreak', engine.FB_PCT)})
    hurst = df['Micro_Hurst'].values
    fb = df['Micro_FailedBreak'].values
    d2d_dir = df['D2D_Trend_Dir'].values
    d2d_sig = df['D2D_Signal'].values
    adx = df['ADX_Value'].values
    vol = df['Volume'].values
    hurst_hi90 = hurst > thr[('Micro_Hurst', 'p90')]
    hurst_hi97 = hurst > thr[('Micro_Hurst', 'p97')]
    fb_hi90 = fb > thr[('Micro_FailedBreak', 'p90')]
    throne = (adx >= engine.D2D_ADX_MIN) & (hurst >= thr[('Micro_Hurst', 'p30')])
    d2d_agree_long = (d2d_sig == 1) & throne
    d2d_agree_short = (d2d_sig == -1) & throne
    n = len(df)
    recentfb = np.zeros(n, dtype=bool)
    for j in np.flatnonzero(fb_hi90):
        recentfb[j + 1:min(n, j + window + 1)] = True
    long_mult = np.ones(n, dtype=float)
    if recentfb_sizing:
        long_mult[recentfb] = engine.CONV_RECENTFB_MULT
    if hurst_sizing:
        long_mult[hurst_hi90] = engine.CONV_HURST_MULT
    if d2d_conviction:
        long_mult[d2d_agree_long] = engine.CONV_HURST_MULT
    short_mult = np.ones(n, dtype=float)
    if d2d_conviction:
        short_mult[d2d_agree_short] = engine.CONV_HURST_MULT
    gate = (adx >= 15.0) & (vol >= 300.0)
    conv = {'long_mult': long_mult, 'short_mult': short_mult}
    if gap_singles:
        conv['gap_hurst'] = hurst_hi97 & (d2d_dir == 1) & gate
        conv['gap_fb'] = fb_hi90 & (d2d_dir == -1) & gate
    if d2d_gap:
        conv['gap_d2d_dir'] = np.where((d2d_sig != 0) & throne & gate, d2d_sig, 0).astype(int)
    return conv
