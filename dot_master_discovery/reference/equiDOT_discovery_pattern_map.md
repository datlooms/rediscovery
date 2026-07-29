# equiDOT — Discovery Pattern Map (Stage 8 search space)

*v6 — 2026-07-02 (FINAL — Step 13 closed. All scanners BUILT + Auditor-RATIFIED; each family below names its project-file script. F0 = triple_convergence_and_d2ddir.py with F10 convergence-density fused as a `density` mode; standalone convergence_density.py retired). Purpose: the COMPLETE catalog of signal-pattern families Stage 8 may search, so nothing is missed. All families draw on the same 117-candidate vocabulary (90 FEAT_ hi/lo + 27 binary/state/side equality) and the same sealed baseline; what differs is the RELATIONSHIP being scanned. Family 0 is the currently implemented engine; Families 1–11 are additional relationships over the same variables. This is a search-space map, not a commitment to build every scanner — the Manager decides scope. Live status: equiDOT_progress_and_rd_plan.md; ordered path: equiDOT_execution_sequence.md; laws: non_negotiables_*.txt.*

## The frame — held CONSTANT vs SEARCHED

**Constant across all families (eligibility / risk / execution — not signal, not directional):**
- Eligibility gates: ADX_Value >= 15, Volume > 50; entry gates: solo Volume >= 300, or concurrent (>=2 qualifying) Volume >= 50 (engine L4835).
- Threshold source: oracle-only (dots_thresholds.py, mechanism D + structural). Zero independent computation.
- Trade management: the locked S.7 TM (SACRED) — every family is discovered under the SAME exits. A family cannot specify its own exit logic; any exit change is a separate human-authorized decision, out of scope here.
- Scoring: survival-first walk-forward (wf.py, locked step 12) — worst-day vs -$2,500 before PF; 6/6 persistence; spread-stress.

**Searched, NOT a fixed constant — the D2D directional gate.** D2D_Trend_Dir is a per-family search parameter with three settings: **confirm** (entry dir == D2D — continuation), **invert** (entry dir == -D2D — counter-trend), **exempt** (no D2D condition). Continuation families (0,1,2,3,6,10) default to confirm; counter-direction families (4 divergence, 7 mean-reversion) require invert or exempt or they cannot fire (Stage 5: the confirm gate exists specifically to block mean-reversion traps, so it must be inverted/dropped for the families that intend reversion). Making the gate a search dimension removes the directional bias of holding it constant and is the resolution to the Families 4/7 tension.

---

## Family 0 — Simultaneous convergence  [IMPLEMENTED]
- **Relationship:** 3 variables at distributional extremes (hi/lo) on the SAME bar, D2D-confirmed.
- **Ingredients:** any 3 of the 90 FEAT_ (hi/lo) + 27 equality conditions -> 249 scan conditions.
- **Scanner:** `triple_convergence_and_d2ddir.py` — the ratified engine, with F10 convergence-density FUSED as a `density` mode (sweeps co-firing count>=k over the SELECTED set). BUILT + RATIFIED. D2D: confirm.
- **Status:** live. Stage-8 primary run. The prior 76-set is a benchmark only.

## Family 1 — Sequential / temporal
- **Relationship:** ordered signature over time — A extreme, then ~N bars later B, then C — not same-bar.
- **Ingredients:** the 117 vocabulary + a lag window; Bars_Since_Flip, ST_Flip_Event, D2D_Signal anchor timing.
- **Why:** convergence LEADS D2D by 10–20 bars (Stage 5) — ordering carries information the same-bar gate discards.
- **Scanner:** `sequential_temporal.py` — lagged-condition scan. BUILT + RATIFIED. D2D: confirm.

## Family 2 — Transition / regime-change
- **Relationship:** the edge is in the SWITCH between states, not the state itself: value[t] != value[t-1].
- **Ingredients:** Sqz_State, RangeOsc_State, AT_Regime_ST/LT, ADX_Rising, ST_Flip_Event (all live, in the equality-27). DecayState_ST/LT STRUCK — both are constant 0 across all 152,983 bars (dead, verified nunique=1) and sit in the excluded-54; they carry no transition.
- **Why:** convergence-of-levels sees states, not transitions; a squeeze RELEASING differs from a squeeze being on.
- **Optional extension (backlog):** oscillator-state DWELL — bars-since-transition in Sqz_State / RangeOsc_State / AT_Regime (how long a state has held), distinct from the transition event itself. Thin; not a separate family.
- **Scanner:** `state_transition.py` — state-change detector (typed + generic, lag-1 head-padded). BUILT + RATIFIED. D2D: confirm.

## Family 3 — Conditional / interaction (context-gating)
- **Relationship:** "X matters only when Y is in regime Z" — noise globally, strong inside a sub-population.
- **Ingredients:** any FEAT_ condition gated by a state/regime variable (AT_Regime_*, Sqz_State, Trend_Concordance, Trend_Conflict, Harmonic_D2D_Concordance).
- **Why:** regime non-stationarity — some behaviours are bull/bear/vol/flat-dependent (the adaptive-convergence thesis).
- **Scanner:** `conditional_interaction.py` — base FEAT_ AND state-gate, base-alone vs base-gated reported. BUILT + RATIFIED. D2D: confirm.

## Family 4 — Divergence (non-confirmation)
- **Relationship:** price makes an extreme but a flow/momentum variable does NOT confirm — edge from failing to line up.
- **Ingredients:** price-extreme (VWAP_Z, KAMA_Dist_ATR, session/OR distances) vs non-confirming flow (Micro_OrderFlowDelta, Micro_VPIN, OBV_Macd, Momentum_Value).
- **Why:** the structural opposite of convergence; classic order-flow divergence.
- **Scanner:** `divergence_nonconfirm.py` — price-extreme AND opposite-flow. BUILT + RATIFIED. **D2D: invert or exempt** (counter-continuation — cannot fire under confirm; via the sanctioned D2D-column reconstruction, engine/TM untouched).

## Family 5 — Persistence / autocorrelation
- **Relationship:** when a condition holds, the next N bars are statistically biased — a mild, frequent edge, not a rare sharp one.
- **Ingredients:** Micro_AutoCorr, Micro_Hurst, Efficiency_Ratio, KAMA_Slope as the conditioning state; forward-return bias as the DISCOVERY TARGET (not a production input).
- **Why:** not all edge is rare/extreme; a small persistent bias traded often can dominate on survival terms.
- **Scanner:** `persistence_autocorr.py` — state-hold entry; forward-return is a DISCOVERY-ONLY target (quarantined from mask/sig/direction/size/exit/ranking). Runs under the locked S.7 TM — no distinct exit logic. BUILT + RATIFIED. D2D: confirm.

## Family 6 — Threshold-crossing / momentum-ignition
- **Relationship:** a variable CROSSING a level with velocity — value[t] > level AND value[t-1] <= level — the crossing event, not being at an extreme.
- **Ingredients:** Slope_Accel_ST/LT, Momentum_Value, KAMA_Slope, OBV_Velocity — level-cross + rate-of-change filter.
- **Why:** ignition/breakout is a crossing, invisible to a static hi/lo extreme test.
- **Scanner:** `threshold_crossing.py` — first-breach of the oracle level (lag-1 head-padded) + optional oracle ROC filter. BUILT + RATIFIED (thinnest family — decomposes to F0-velocity + F2-cross; earns its own scanner at selection or folds into F0/F2). D2D: confirm.

## Family 7 — Mean-reversion-from-extreme
- **Relationship:** single-variable — "when X is this stretched, it snaps back." Reversion, not continuation.
- **Ingredients:** one stretched FEAT_ (VWAP_Z +/-2, KAMA_Dist_ATR, session/round-level distances); entry against the stretch.
- **Why:** the counter-aligned triples hinted at reversion in the Stage-5 gate study.
- **Scanner:** `mean_reversion.py` — single stretched oracle condition, faded (hi->SHORT, lo->LONG). BUILT + RATIFIED. **D2D: invert or exempt** — against-the-stretch is counter-continuation; via the sanctioned D2D-column reconstruction (shared with F4), engine/TM untouched.

## Family 8 — Relative / cross-variable structure
- **Relationship:** ratios, spreads, or rank-orderings BETWEEN variables — not each one's absolute level.
- **Ingredients:** pairwise relations among the 117 (fast-vs-slow slope spread, ST-vs-LT regime disagreement, Slope_EMA_ST vs Slope_EMA_LT).
- **Why:** relative structure can be stationary where absolute levels are not.
- **Scanner:** `cross_variable_structure.py` — structural relation between two columns (A>B, A<B, A!=B); zero smuggled percentile (condition_mask never called). BUILT + RATIFIED. D2D: confirm.

## Family 9 — Temporal / session / calendar  [CONFIRMED — session-anchored]
- **Relationship:** edge that holds only around a known session event or on a given weekday.
- **Ingredients:** EST_Hour restricted to NAMED session anchors — 08:00 (pre-market pickup), 09:30 (cash open), 10:00 (first reversal window), 15:30 (MOC ramp — operator-observed US30 volatility spike), 16:00 (close) — plus EST_DayOfWeek (0–5). EST_Minute STRUCK (noise-fishing at M1). All in the baseline, currently in the excluded-54.
- **Why:** US30 intraday structure is anchored to session events, not arbitrary clock values. Testing named events (not a blind 24/60-way sweep) removes the curve-fit risk by construction.
- **D2D gate:** F9 is a CONDITIONER, not a standalone directional family — it inherits the D2D setting of whatever base family it layers onto (a session window applied to an F0 pattern inherits F0's confirm; applied to F7 inherits F7's invert/exempt).
- **Scanner:** `session_temporal.py` — base FEAT_ conditioned on NAMED session anchors (08:00/09:30/10:00/15:30/16:00) + weekday only; EST_Minute pins the two :30 events, never a free sweep; base-alone vs base+session reported. BUILT + RATIFIED. D2D: inherited (confirm for an F0 base).

## Family 10 — Convergence density  [FOLDED INTO F0 — not a peer scanner]
- **Reclassified 2026-07-02.** Density is not a standalone signal — it is a tally of how many OTHER signals co-fire, so it is degenerate over the raw 249-condition pool (min count ~8; every band k=2..12 selects the same bars, identical trades/PF). It is meaningful only over the SELECTED signal set, which is F0's own output. Therefore co-firing density is a DISCOVERY DIMENSION of the F0 convergence engine (the role `Dots_MinConcurrent`/`SoloVolumeGate` already play), not a peer family.
- **Implementation:** fused into `triple_convergence_and_d2ddir.py` as a `density` mode — per-bar direction-aligned co-firing count over the candidate set's own conditions (via `engine.condition_mask`), swept as `count>=k`, scored through the ratified engine (S.7 TM, D2D=confirm). Discriminates over a selected set (degeneracy resolved); Auditor-RATIFIED. The standalone `convergence_density.py` is RETIRED.
- **In Stage 8:** density is one of the dimensions F0 searches over the selected signals — not a separate scanner run.

## Family 11 — Cross-variable × windowed (rolling lead-lag / cross-correlation)
- **Relationship:** a WINDOWED statistical relationship between TWO series — does A lead B by k bars; does an A<->B correlation strengthen or break down over the last N bars. Fills the empty {cross-variable}x{windowed} cell (F0 single/instant, F5 single/windowed, F4+F8 cross/instant).
- **Ingredients:** rolling correlation / beta over N bars on pairs — OBV_Line<->Close, Micro_OrderFlowDelta<->Micro_LogReturn, OBV_Macd<->Momentum_Value (all present and live).
- **Why:** flow-leads-price and correlation-breakdown are real microstructure edges; distinct from F1 (discrete ordered events) and F8 (instantaneous ratio/spread).
- **Scanner:** `rolling_leadlag.py` — causal trailing-window (bars [t-N+1..t] only; truncation-test clean, no look-ahead) rolling corr/beta/lead-lag; STRUCTURAL levels only (sign/zero-cross, no percentile); corr_pos===beta_pos is a documented harmless duplicate. BUILT + RATIFIED. D2D: confirm. New-derived-input tier — causal-window definition stated for the Stage-9 parity spec.
---

## Parity classification (matters only IF a pattern graduates to a production EA input)
- **For DISCOVERY:** no family carries a parity burden — all are computed in Python on the sealed baseline.
- **For PRODUCTION:** two tiers —
  - **No new-input burden (existing exported columns, used as-is / AND / inverted):** Families 0, 3, 4, 5, 7, 9, 10. (F9 conditions on EST_Hour/EST_DayOfWeek as-is — zero new derived input.) (F5's forward-return is a discovery-only target, never a live input.)
  - **New derived-input tier (lag-based or cross-variable quantities not currently exported -> need oracle-consistent, history-independent definition + export==live parity before entering the EA):** Families 1 (lag latch), 2 (lag-1 transition boolean), 6 (lag-1 crossing boolean), 8 (cross-variable ratio/spread), 11 (rolling cross-correlation/beta). F2 and F6 are the SAME class — computable from existing columns at adjacent bars, but still new derived inputs at production.

## Scope note (for sign-off)
- **Family 0 is Stage-8 primary and runs now** on the ratified engine.
- **Families 1–11 require net-new scan logic — ALL in active Stage-8 scope.** Discovery requires the full perspective together (fullest-market-perspective directive); no family is deferred or parked. Family 0 is live on the ratified engine; the scanners for 1–11 are built out so the definitive discovery searches the complete space at once. Build cost (heaviest: F1, F8, F11) is a reason to build them correctly, not to delay them.
- **This map is the completeness reference.** If a real pattern type is not here, it was missed — add it here first.
