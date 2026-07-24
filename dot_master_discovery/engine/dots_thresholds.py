"""equiDOT unified threshold replication.

Every Stage-8 candidate threshold is mechanism D (rolling-2500 floor-index percentile,
day-refreshed) for distributional features, or a structural constant for the natural-boundary
set (VWAP_Z, OR_Position). Mechanisms B (ATR-scaled fitted base), C (regression-EMA fitted
coefficients), the static-global percentile path, and the stale hardcoded constants are RETIRED
(threshold unification, locked). This module is the reference the EA's unified threshold
construction must match exactly (live==sim); discovery and wf trust it only after that match is
proven (the EA exports its live dots_threshold p80/p20 and we confirm bit-match).

Candidate population (83): the 62 existing FEAT_ features (col name == feature name) + 19 new D
candidates, all on D with both sides (hi=p80, lo=p20); plus VWAP_Z and OR_Position structural.
VWAP_Sigma_ATR is read from the exported column when present (faithful) else recomputed from
VWAP_Sigma / ATR_1M (pre-build). OR_Position carries an OR-set gate (compute_structural_gates)
the caller must AND into its mask."""
import numpy as np
from collections import deque

WARMUP_BARS = 4000
_ROLL_CAP = 2500

_EXISTING_D = [
    'ATR_1M', 'Bar_Range', 'D2D_ATR', 'D2D_ATR_MA', 'D2D_Dn_Count', 'D2D_Dynamic_Sensitivity',
    'D2D_Persist', 'D2D_Up_Count', 'AT_Lookback_LT', 'AT_Lookback_ST', 'AT_Score_LT', 'AT_Score_ST',
    'AT_Slope_LT', 'AT_Slope_ST', 'Bars_Since_Flip', 'Slope_EMA_LT', 'Slope_EMA_ST', 'Slope_Accel_LT',
    'Slope_Accel_ST', 'OBV_Macd', 'OBV_Velocity', 'OBVf_DirStepCount', 'KAMA_Dist', 'KAMA_Dist_ATR',
    'KAMA_Slope', 'EMA_Oscillator', 'Harmonic_LLEMA', 'Sqz_Val', 'RangeOsc_Val', 'Volume_Avg_10',
    'Volume_Ratio_10', 'Momentum_Value', 'Efficiency_Ratio', 'Dist_To_PoC_ATR',
    'Micro_Amihud', 'Micro_AutoCorr', 'Micro_BarEntropy', 'Micro_BarOverlap', 'Micro_CSSpread',
    'Micro_Entropy', 'Micro_FailedBreak', 'Micro_FractalDim', 'Micro_GarmanKlass', 'Micro_HLAsymmetry',
    'Micro_Hurst', 'Micro_IBSP', 'Micro_Lambda', 'Micro_LogReturn', 'Micro_MicroGap', 'Micro_MomoTransfer',
    'Micro_OrderFlowDelta', 'Micro_PriceAccel', 'Micro_RangeAccel', 'Micro_RangeVelocity', 'Micro_Rejection',
    'Micro_RollProxy', 'Micro_ThrustEff', 'Micro_TickIntensity', 'Micro_VPIN', 'Micro_VolAccel',
    'Micro_VolOfVol', 'Micro_WickImbalance',
]
_NEW_D = [
    'VWAP_Dist_ATR', 'VAH_Dist_ATR', 'VAL_Dist_ATR',
    'PrevDay_High_Dist_ATR', 'PrevDay_Low_Dist_ATR', 'PrevDay_Close_Dist_ATR',
    'DailyOpen_Dist_ATR', 'Round_100_Dist_ATR', 'Round_500_Dist_ATR', 'Round_1000_Dist_ATR',
    'OR_High_Dist_ATR', 'OR_Low_Dist_ATR', 'Session_High_Dist_ATR', 'Session_Low_Dist_ATR',
    'WeeklyOpen_Dist_ATR', 'MultiDay_Slope', 'MultiDay_Position', 'VWAP_Sigma_ATR', 'VA_Position',
    'ADX_Value', 'Body_Size', 'Upper_Wick', 'Lower_Wick', 'TChan_A15', 'VWAP_Sigma', 'Volume',
]
_D_COLS = _EXISTING_D + _NEW_D
_DERIVED_D_COLS = {'VWAP_Sigma_ATR'}
_D_SPEC = {}
for _c in _D_COLS:
    _D_SPEC[(_c, 'hi')] = (_c, 0.80)
    _D_SPEC[(_c, 'lo')] = (_c, 0.20)
_STRUCTURAL = {
    ('VWAP_Z', 'hi'): 2.0, ('VWAP_Z', 'lo'): -2.0,
    ('OR_Position', 'hi'): 0.80, ('OR_Position', 'lo'): 0.20,
}
def _floor_pct(sorted_vals, pct):
    count = len(sorted_vals)
    if count < 2:
        return 0.0
    idx = int(np.floor(count * pct))
    if idx < 0:
        idx = 0
    if idx > count - 1:
        idx = count - 1
    return sorted_vals[idx]
def is_adaptive(feature, side):
    return (feature, side) in _D_SPEC or (feature, side) in _STRUCTURAL
def _vwap_sigma_atr(df, atr):
    if 'VWAP_Sigma_ATR' in df.columns:
        return df['VWAP_Sigma_ATR'].values.astype(float)
    n = len(df)
    sig = df['VWAP_Sigma'].values.astype(float)
    out = np.zeros(n)
    nz = atr > 0.0
    out[nz] = sig[nz] / atr[nz]
    return out
def compute_structural_gates(df):
    orh = df['OR_High'].values.astype(float)
    orl = df['OR_Low'].values.astype(float)
    return {'OR_Position': (orh > 0.0) & (orl > 0.0) & (orh > orl)}
def compute_adaptive_thresholds(df):
    n = len(df)
    out = {}
    atr = df['ATR_1M'].values.astype(float)
    for (feat, side), const in _STRUCTURAL.items():
        out[(feat, side)] = np.full(n, const)
    adx = df['ADX_Value'].values.astype(float)
    vol = df['Volume'].values.astype(float)
    eligible = (adx >= 15.0) & (vol > 50.0)
    times = df['Time'].values
    derived = {}
    if any(col in _DERIVED_D_COLS for (col, _) in _D_SPEC.values()):
        derived['VWAP_Sigma_ATR'] = _vwap_sigma_atr(df, atr)
    roll_cols = {}
    for (feat, side), (col, pct) in _D_SPEC.items():
        if col not in roll_cols:
            roll_cols[col] = derived[col] if col in derived else df[col].values.astype(float)
    rings = {col: deque(maxlen=_ROLL_CAP) for col in roll_cols}
    snaps = {key: np.empty(n) for key in _D_SPEC}
    cur = {key: 0.0 for key in _D_SPEC}
    prev_day = None
    for i in range(n):
        if eligible[i]:
            for col in roll_cols:
                rings[col].append(roll_cols[col][i])
        day = int(str(times[i])[8:10])
        if day != prev_day:
            srt = {col: sorted(rings[col]) for col in roll_cols}
            for key, (col, pct) in _D_SPEC.items():
                cur[key] = _floor_pct(srt[col], pct)
            prev_day = day
        for key in _D_SPEC:
            snaps[key][i] = cur[key]
    for key in _D_SPEC:
        out[key] = snaps[key]
    return out
