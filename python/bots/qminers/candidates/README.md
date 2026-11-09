# Every candidate, by round

Each file is one self-contained bot for the organisers' `exchange-simulator` (their `BaseStrategy`), named
`r<round>_<ID>_<what>.py`; its docstring holds the notes of the bots it builds on. **Bold** marks the four finals. A
score is the server's for an upload (the public tape in round 1, the validation tape from round 2); every upload is in
[`RESULTS.md`](../../../../RESULTS.md) and each round's reasoning in `data/arena/round<N>/HANDOVER.md`.

## Round 0: the playground (7 Nov, morning)

| Candidate | What it is | Uploaded |
|---|---|---:|
| [`r0_A0_mm.py`](round0/r0_A0_mm.py) | Playground candidate A0 (7 Nov): the template as is with a conservative market-making setting, to check their pipeline end to end (static check, ... |  |
| [`r0_A1_strict.py`](round0/r0_A1_strict.py) | Playground candidate A1 (7 Nov): A0 with every construct their static analysis might reject taken out (A0 failed it with no detail): no statistics ... |  |
| [`r0_A2_compact.py`](round0/r0_A2_compact.py) | A1 failed their static analysis too, so A2 is A1 without a comment or docstring (arena.compact, then the template's own docstring, a plain string ... |  |
| [`r0_A3_plain.py`](round0/r0_A3_plain.py) | their trend follower passed their static analysis (+1,878, the same as their simulator locally), A0 and A1 didn't; A3 is A2 with the two constructs ... |  |
| [`r0_A4_classes.py`](round0/r0_A4_classes.py) | A3 failed their static analysis too; the user's guess, more classes than the one BaseStrategy subclass their README describes: A4 is A3 with Book, ... |  |
| [`r0_A5_oneclass.py`](round0/r0_A5_oneclass.py) | A4 failed their static analysis too, so A5 is A3 folded into one top-level class as their examples have it (imports, then ArenaBot(BaseStrategy) ... |  |
| [`r0_A6_noexec.py`](round0/r0_A6_noexec.py) | Playground candidate A6 and probes 4a/4b: probes 2 and 3 passed, so every syntax node, operator and builtin in A3 is allowed alone; what is left are ... |  |
| [`r0_F1_fallback.py`](round0/r0_F1_fallback.py) | Fallback candidate F1 (7 Nov): a small market maker written in the style of the starter's trend_follower.py, so it passes their static analysis where ... |  |
| [`r0_F2_maker_v2.py`](round0/r0_F2_maker_v2.py) | Playground candidate F2 (7 Nov): F1 gridded on the playground's second sample (sample_v2.csv: 2M rows over 5,750 s, a 1-2 tick spread, ~900 lots at ... |  |
| [`r0_F3_full_room.py`](round0/r0_F3_full_room.py) | Playground candidate F3 (7 Nov): the ladder maker (families/ladder_maker.py) at its best cell on the playground's second sample (sample_v2.csv, 5,750 ... |  |
| [`r0_F4_depletion_guard.py`](round0/r0_F4_depletion_guard.py) | Playground candidate F4 (7 Nov): the room maker (families/room_maker.py) at its best cell on sample_v2.csv: F3 plus the queue-depletion guard ... |  |
| [`r0_M1_runner.py`](round0/r0_M1_runner.py) | Playground candidate M1 (7 Nov): the families agent's momentum runner (python/bots/qminers/families/momentum_runner.py) with its best cell on the ... |  |
| [`r0_M2_runner_safe.py`](round0/r0_M2_runner_safe.py) | Playground candidate M2 (7 Nov): the momentum runner with two protections on: a 2 s flow window and no taking while the spread is wider than 2 ticks. ... |  |

## Round 1 (7 Nov, 13:00-18:00): a calm tape; market makers

| Candidate | What it is | Uploaded |
|---|---|---:|
| [`r1_C10_codex_v4_capped.py`](round1/r1_C10_codex_v4_capped.py) | Round-1 market maker with 23 causal microstructure features. |  |
| [`r1_C11_codex_v5_29feat.py`](round1/r1_C11_codex_v5_29feat.py) | Round-1 market maker with 29 causal microstructure features. | 619,282 |
| **[`r1_C12_codex_v6.py`](round1/r1_C12_codex_v6.py)** | Round-1 market maker with 29 causal microstructure features. | **622,921** |
| [`r1_C1_codex_ridge.py`](round1/r1_C1_codex_ridge.py) | Round-1 submission: online fair-price prediction and passive execution. | 554,347 |
| [`r1_C1b_codex_pipelined.py`](round1/r1_C1b_codex_pipelined.py) | Round-1 market maker with pipelined cancel/replace and charged risk. | 571,237 |
| [`r1_C2_ridge_dying.py`](round1/r1_C2_ridge_dying.py) | Round 1 candidate R1-C2 (7 Nov): R1-C1 (the online ridge maker) plus R1-F8's dying-touch guard and sweep hold. |  |
| [`r1_C3_ridge_blend.py`](round1/r1_C3_ridge_blend.py) | Round-1 submission: online fair-price prediction and passive execution. |  |
| [`r1_C4_pipelined_blend.py`](round1/r1_C4_pipelined_blend.py) | Round 1 candidate R1-C4 (7 Nov, 17:00): R1-C1b (the codex v2) plus R1-C3's second ridge at 500 ms blended in at 0.4: 586,109.13 (penalty 879). The ... |  |
| [`r1_C5_long_horizon.py`](round1/r1_C5_long_horizon.py) | Round 1 candidate R1-C5 (7 Nov, 17:05): R1-C1b (the codex v2) with HORIZON_US 400000, MODEL_MEMORY_US 1e11 and the dead zone 0.18, the centre of the ... | 595,442 |
| [`r1_C5t_long_horizon_top.py`](round1/r1_C5t_long_horizon_top.py) | Round 1 candidate R1-C5t (7 Nov, 17:05): R1-C1b (the codex v2) with HORIZON_US 500000, MODEL_MEMORY_US 1e11, the dead zone 0.22 and the inside ... |  |
| [`r1_C6_place_slow.py`](round1/r1_C6_place_slow.py) | Round 1 candidate R1-C6 (7 Nov, 17:20): R1-C5 with the Rust ridge_maker PLACE features (the share of new market orders at/inside the previous touch, ... |  |
| [`r1_C7_event_blend.py`](round1/r1_C7_event_blend.py) | Round 1 candidate R1-C7 (7 Nov, 17:20): R1-C5 with an event-time learner blended in. The first ridge's label is the mid's change at its LABEL_K-th ... |  |
| [`r1_C9_codex_v4_flow_groups.py`](round1/r1_C9_codex_v4_flow_groups.py) | Round-1 market maker with 23 causal public microstructure features. | 605,753 |
| [`r1_F3_full_room.py`](round1/r1_F3_full_room.py) | Round 1 candidate R1-F3 (7 Nov, 13:15): F3 (r0_F3_full_room.py) with SESSION_S 1e9, so it never winds down whatever the private tape's length: on ... | 425,553 |
| [`r1_F5_shrink_react.py`](round1/r1_F5_shrink_react.py) | Round 1 candidate R1-F5 (7 Nov, 13:35): the shrink maker with REACT_CANCEL 1, DEPLETE_LOTS 100, DEPL_FRAC 0.06 (cancel only on a touch that has ... |  |
| [`r1_F6_two_levels.py`](round1/r1_F6_two_levels.py) | Round 1 candidate R1-F6 (7 Nov, 14:00): R1-F5 with a second level (LEVELS 2, KEEP_DEPTH 2, SIZE_TOUCH 65, SIZE_DEEP 80, SIZE_NARROW 115, TOPUP 1), ... |  |
| [`r1_F6b_alloc.py`](round1/r1_F6b_alloc.py) | Round 1 candidate R1-F6b (7 Nov, 14:25): R1-F6 with ALLOC_K -0.5 (fewer lots at the back of a long queue, more on the short side's touch; nothing ... |  |
| [`r1_F7_signal.py`](round1/r1_F7_signal.py) | Round 1 candidate R1-F7 (7 Nov, 14:25): R1-F6 with a dying touch's room one tick back (DYING_DEEP 80, DEPL_FRAC 0.12) and, for 50 ms after a 400+ lot ... |  |
| [`r1_F8_take_join.py`](round1/r1_F8_take_join.py) | Round 1 candidate R1-F8 (7 Nov, 15:05): R1-F7 plus three additions chosen together on round1's first 75% (F7 368,589): 1. TAKE (TAKE_LOTS 60, ... |  |
| [`r1_F8b_combo.py`](round1/r1_F8b_combo.py) | Round 1 candidate R1-F8b (7 Nov, 16:10): R1-F8 plus the three small in-sample gains measured after it, each below the bar on its own: SIZE_NARROW 100 ... |  |
| [`r1_F9_ghost.py`](round1/r1_F9_ghost.py) | Round 1 candidate R1-F9 (7 Nov, 16:05): R1-F8 plus the GHOST harvest, a replay-exact family. The tape never reacts to us, so when a sweep would have ... |  |
| [`r1_G1_queue_depth.py`](round1/r1_G1_queue_depth.py) | Round 1 candidate R1-G1 (7 Nov, 16:10): R1-F8 plus four ways to a better queue place, built from the ceilings (experiments.maker.ceilings on R1-F8's ... |  |
| [`r1_G2_latent.py`](round1/r1_G2_latent.py) | Round 1 candidate R1-G2 (7 Nov, 16:00): R1-F8 plus the latent-price signal (LAT_*). The tape's new passive orders centre on a latent price the mid ... |  |
| [`r1_G2r_ridge_latent.py`](round1/r1_G2r_ridge_latent.py) | Round 1 candidate R1-G2r (7 Nov, 16:30): R1-C1 (the online ridge maker) plus the latent-price signal as LAT_FEAT more features ... |  |
| [`r1_G3_steer.py`](round1/r1_G3_steer.py) | Round 1 candidate R1-G3 (7 Nov, 16:00, the inventory-as-a-bet angle): R1-F8 plus an inventory target from an online forecast of the mid's move over ... |  |
| [`r1_G4_deep_queue.py`](round1/r1_G4_deep_queue.py) | Round 1 experiment R1-G4 (7 Nov, 16:15; DROPPED, kept as the record): R1-F8 plus the volume / queue-priority knobs, every default reproducing F8 ... |  |
| [`r1_H1_join_any.py`](round1/r1_H1_join_any.py) | Round 1 hypothesis H1 "JOIN_ANY" (7 Nov, 14:50): R1-F7 plus JOIN_ANY / JOIN_MS, MOM_JOIN generalised from sweeps to any touch clear. While JOIN_ANY ... |  |
| [`r1_H2_reduce_room.py`](round1/r1_H2_reduce_room.py) | Round 1 hypothesis H2 "REDUCE" (7 Nov, 14:50): R1-F7 (r1_F7_signal.py, its parent; REDUCE_POS 1000 reproduces it exactly) plus a bigger quote on the ... |  |
| [`r1_H3_imb_join.py`](round1/r1_H3_imb_join.py) | Round 1 hypothesis H3 "IMB_JOIN" (7 Nov, 14:50): R1-F7 (the parent, every default reproducing it) plus IMB_JOIN, a quote one tick inside a 2+ tick ... |  |
| [`r1_H4_take_dying.py`](round1/r1_H4_take_dying.py) | Round 1 candidate R1-H4 (7 Nov, hypothesis D, TAKE_DYING): R1-F7 plus a limit order that takes the last lots of the OTHER side's dying touch ... |  |
| [`r1_H5_alloc.py`](round1/r1_H5_alloc.py) | Round 1 candidate R1-H5 (7 Nov, 15:00): R1-F7 plus ALLOC_K from family 12's alloc maker (R1-F6b: ALLOC_K -0.5 gave +6,770 on R1-F6, 11 of 12 ... |  |
| [`r1_H6_combo.py`](round1/r1_H6_combo.py) | Round 1 candidate R1-H6 (7 Nov, 15:05): R1-H4 (R1-F7 plus TAKE_LOTS / TAKE_MAX / TAKE_MS, the take of the other side's dying touch) plus ALLOC_K from ... |  |
| [`r1_H7_gates.py`](round1/r1_H7_gates.py) | Round 1 hypothesis H7 (7 Nov, 15:10): R1-F8 plus DYING_OWN, the dying touch's room shift (DYING_DEEP) only while the OTHER side's touch holds at ... |  |
| [`r1_H8_take_thin.py`](round1/r1_H8_take_thin.py) | Round 1 hypothesis H8 (7 Nov, 15:25): R1-F8 plus TAKE_FRAC, the take's own peak fraction (the take fires on a touch under TAKE_DEPLETE lots and under ... |  |
| [`r1_H9_sweep_take.py`](round1/r1_H9_sweep_take.py) | Round 1 hypothesis H9 (7 Nov, 15:45): R1-F8 plus the SWEEP take: after an aggressive order of SWEEP_LOTS+ lots that left the touch it hit standing ... |  |
| [`r1_HA_codex_deep.py`](round1/r1_HA_codex_deep.py) | Round-1 submission: online fair-price prediction and passive execution. |  |
| [`r1_HB_codex_take.py`](round1/r1_HB_codex_take.py) | Round 1 candidate R1-HB (7 Nov, hybrid B, TAKE): strategy_codex_best.py (the online-ridge maker, +554,347 on round1) plus R1-F8's dying-touch take ... |  |
| [`r1_X1_codex.py`](round1/r1_X1_codex.py) | Round 1 candidate R1-X1 (7 Nov, 16:25): the user's strategy_codex_best.py (an online ridge model of 100-ms mid returns from 15 book and flow ... |  |

## Round 2 (7 Nov, 19:00-24:00): a volatile tape; the forecast taker

| Candidate | What it is | Uploaded |
|---|---|---:|
| [`r2_E1_low_exposure.py`](round2/r2_E1_low_exposure.py) | R2-FT1 (r2_FT1_forecast_take.py) at a low exposure, for round 2. |  |
| [`r2_E2_low_exposure_keep.py`](round2/r2_E2_low_exposure_keep.py) | R2-E1 (r2_E1_low_exposure.py) plus R2-Q1's queue keeping (r2_Q1_keep_slice.py), for round 2. | −41,499 |
| [`r2_E3_conf_exposure.py`](round2/r2_E3_conf_exposure.py) | R2-E1 (r2_E1_low_exposure.py) with a confidence-dependent exposure, for round 2. |  |
| [`r2_FH1_flow_stop.py`](round2/r2_FH1_flow_stop.py) | Round 2 candidate R2-FH1 (7 Nov, 20:15, the fable worktree): the flow holder (family 14) at GRACE_MS 0 (an IOC entry, which reproduces the board's ... |  |
| [`r2_FT1_forecast_take.py`](round2/r2_FT1_forecast_take.py) | R1-C12 (r1_C12_codex_v6.py) plus a forecast take. |  |
| [`r2_H1_flow_bias.py`](round2/r2_H1_flow_bias.py) | R2-T1 (r2_T1_take_only.py, the online ridge's forecast take) biased by R2-RA's big-flow signal (r2_RA_flow_window.py). RA's state is kept beside the ... | 567,740 |
| [`r2_H1b_flow_bias_t2.py`](round2/r2_H1b_flow_bias_t2.py) | R2-H1's bias on R2-T2's code (the hybrid agent's final, commit 6918af5) instead of R2-T1's; not uploaded. R2-H1 (r2_H1_flow_bias.py, the T1-based ... |  |
| [`r2_H2_take_bigflow.py`](round2/r2_H2_take_bigflow.py) | R2-T2 with the big-flow side of R2-M4 (the last 125-ms window of net market-taker lots of 575+) added to the forecast take's signal with weight ... |  |
| [`r2_H3_flow_bias_shock.py`](round2/r2_H3_flow_bias_shock.py) | R2-H1 (the uploaded +567,739.71 file) plus the shock follow-through term on the take's signal: SHOCK_W x the side of a 2+ tick mid jump in one book ... |  |
| [`r2_L1_taker_liquidity.py`](round2/r2_L1_taker_liquidity.py) | T2-derived structural taker hypothesis: t2_liquidity_features. Original source supplied by another session. No validation score for this alteration; ... | 771,770 |
| [`r2_L3_taker_pure.py`](round2/r2_L3_taker_pure.py) | Structural liquidity-taker followup: liquidity_no_probes. Fixed100-lot exposure and strict all-live reservations. Altered source has no server score. | 804,018 |
| [`r2_L4_taker_largeflow.py`](round2/r2_L4_taker_largeflow.py) | Structural liquidity-taker followup: liquidity_large_flow. Fixed100-lot exposure and strict all-live reservations. Altered source has no server score. |  |
| [`r2_L5_largeflow_pure.py`](round2/r2_L5_largeflow_pure.py) | Structural liquidity-taker followup: liquidity_large_flow. Fixed100-lot exposure and strict all-live reservations. Altered source has no server score. |  |
| [`r2_L6_pure_flowbias.py`](round2/r2_L6_pure_flowbias.py) | R2-L3 (the pure liquidity taker, +804,018 on validation) plus R2-H1's big-flow bias at BIAS_AGREE 0.15: R2-L2's file (R2-L1 + the bias) with ... | 798,269 |
| [`r2_L8_quote_switch.py`](round2/r2_L8_quote_switch.py) | R2-L1 (the liquidity taker with one-lot quotes) with the quotes switched by regime: one lot only while the 5-s decayed \|mid change\| rate is below ... | 826,778 |
| **[`r2_L9_taker_huber.py`](round2/r2_L9_taker_huber.py)** | T2-derived structural taker hypothesis: t2_liquidity_features. Original source supplied by another session. No validation score for this alteration; ... | **873,719** |
| [`r2_M1_tsmom.py`](round2/r2_M1_tsmom.py) | time-series momentum. Round 2's price wanders hundreds of ticks and a move over the last minute or two keeps going (round 2's public tape: after the ... |  |
| [`r2_M2_flow_trend.py`](round2/r2_M2_flow_trend.py) | follow the big aggressive orders and the minute-scale trend. On round 2's public tape an aggressive order of 500+ lots moves the mid on by +1.2 to +2 ... | 376,082 |
| [`r2_M3_flow_stop_gated.py`](round2/r2_M3_flow_stop_gated.py) | R2-M2 (r2_M2_flow_trend.py, below) plus R2-FH1's stop (r2_FH1_flow_stop.py). The stop (STOP > 0): once the mid has moved STOP ticks against the ... | 366,342 |
| [`r2_M4_flow_rev.py`](round2/r2_M4_flow_rev.py) | R2-RA (the flow-window signal on R2-M3: the net market-taker lots over FLOW_MS 250 ms, MIN_LOTS 500) plus R2-RC's stop-and-reverse (STOP_REVERSE 1: ... |  |
| [`r2_M4_flow_window.py`](round2/r2_M4_flow_window.py) | R2-M2 with the big signal taken from the net market-taker lots over the last FLOW_MS 125 ms (a deque of (time, net) summed over the window) instead ... | 441,088 |
| [`r2_Q1_keep_slice.py`](round2/r2_Q1_keep_slice.py) | R1-C12 (r1_C12_codex_v6.py) keeping its queue place on the dead-zone step-back. |  |
| [`r2_RA_flow_window.py`](round2/r2_RA_flow_window.py) | R2-M3 (r2_M3_flow_stop_gated.py, below) with the big signal's trigger generalised to a flow window. FLOW_MS > 0: the signal fires toward the side ... | 467,703 |
| [`r2_RB_entry.py`](round2/r2_RB_entry.py) | R2-M3 (r2_M3_flow_stop_gated.py, below) plus an entry confirmation. CONFIRM_TICKS > 0: after a fresh big signal (a side change, or the first big ... |  |
| [`r2_RC_exits.py`](round2/r2_RC_exits.py) | R2-M3 (r2_M3_flow_stop_gated.py, its docstring below) plus three exits behind knobs; with TRAIL 0, STOP_REVERSE 0, TIME_S 0 it is R2-M3 to the cent ... |  |
| [`r2_RD_sizing.py`](round2/r2_RD_sizing.py) | R2-M3 (r2_M3_flow_stop_gated.py, below) with the target sized by the signal. Three knobs, each off by default (the defaults reproduce R2-M3 to the ... |  |
| [`r2_RE_hysteresis.py`](round2/r2_RE_hysteresis.py) | R2-M3 plus a flip hysteresis, FLIP_LOTS: a big order AGAINST the side the bot holds sets the new signal only if it is at least FLIP_LOTS lots (a big ... |  |
| [`r2_RF_forecast_exit.py`](round2/r2_RF_forecast_exit.py) | R2-M3 plus R2-E2's online ridge forecast of the 400-ms mid move, used only to time exits and re-entries. The model is r2_E2_low_exposure_keep.py's ... |  |
| [`r2_RG_clear_signal.py`](round2/r2_RG_clear_signal.py) | R2-M3 plus a second trigger, the cascade: when the market's best ask rises (or the best bid falls) with no market trade in the event (a cancel-driven ... |  |
| [`r2_RH_vol_momentum.py`](round2/r2_RH_vol_momentum.py) | R2-M3 with the position scaled by the price's speed, the opposite of the maker's rule: fast = the mid's \|change\| in ticks a second decayed over ... |  |
| [`r2_T1_take_only.py`](round2/r2_T1_take_only.py) | the forecast take ALONE. R2-E2's file (R1-C12's online ridge of the 400-ms mid move on 29 features, a forecast take, queue keeping) with its quoting ... | 485,667 |
| [`r2_T2_take_only_safe.py`](round2/r2_T2_take_only_safe.py) | R2-T1 without its position breaches. T1 paid 21,956 of breach penalty on the server's validation tape (10,000 a second over \|100\|) and 8,829 on ... | 490,359 |
| [`r2_U1_unwind.py`](round2/r2_U1_unwind.py) | R1-C12 (r1_C12_codex_v6.py) with an IOC unwind when the forecast turns against the position. |  |
| [`r2_V1_vol_exposure.py`](round2/r2_V1_vol_exposure.py) | R2-E2 (r2_E2_low_exposure_keep.py) with an exposure that follows the tape's speed, and two trend features. |  |
| [`r2_V2_vol_exposure_dz18.py`](round2/r2_V2_vol_exposure_dz18.py) | R2-E2 (r2_E2_low_exposure_keep.py) with an exposure that follows the tape's speed: R2-V1 (r2_V1_vol_exposure.py) at R2-E2's DEAD_ZONE 0.18 and ... | 71,864 |
| [`r2_X2_codex_untested.py`](round2/r2_X2_codex_untested.py) | Round-2 inverse-absolute-variance development hypothesis: absolute_variance_tau3_risk200. Causal regular samples and original native rules. |  |
| [`r2_base_v5.py`](round2/r2_base_v5.py) | Round 2 base (R2-B5): R1-C11 (r1_C11_codex_v5_29feat.py, round 1's uploaded final) with its constants named at the top of the class; no behaviour ... |  |
| [`r2_learned_dz_v5.py`](round2/r2_learned_dz_v5.py) | Round 2 learned dead zone (R2-L5): r2_base_v5.py (R1-C11's model, constants named) + the dead zone learned online from our own fills, ported line for ... |  |
| [`r2_safe_v5.py`](round2/r2_safe_v5.py) | Round 2 safe (R2-S5): r2_base_v5.py (R1-C11's model) with CANCEL_FREE = 0.0 and HEDGE = False: every live order, being cancelled or not, counts ... |  |

## Round 3 (8 Nov, 01:00-06:00): the hidden-price filter

| Candidate | What it is | Uploaded |
|---|---|---:|
| [`r3_B1_huber_quote_switch.py`](round3/r3_B1_huber_quote_switch.py) | R2-L9 (the Huber-robust pure taker, +873,719 on validation) plus R2-L8's speed-switched one-lot quotes: QUOTE_SIZE 1, used only while the 5-s decayed ... | 733,790 |
| [`r3_F10_blend150.py`](round3/r3_F10_blend150.py) | R3-F5 plus Rust ridge_maker's multi-horizon options, ported line for line. BLEND_W (with H2_US): a second ridge on the same features at the H2_US ... | 818,039 |
| [`r3_F11_h250.py`](round3/r3_F11_h250.py) | R3-F5 with the forecast horizon HORIZON_US 250 ms instead of 400 ms; nothing else changed. Rust: F5's line and --set HORIZON_US=250000 (531,344 on ... |  |
| [`r3_F1_latent_filter.py`](round3/r3_F1_latent_filter.py) | R2-L9 (the Huber-ridge taker) plus a latent-price filter's features in the ridge. The filter is a hidden-Markov filter over the generator's latent ... | 862,764 |
| [`r3_F2_latent_filter_l8.py`](round3/r3_F2_latent_filter_l8.py) | R2-L8 (the liquidity taker, one-lot quotes below QS_RATE) plus R3-F1's latent-price filter: three ridge features from a hidden-Markov filter of the ... |  |
| [`r3_F3_latent_filter_b1.py`](round3/r3_F3_latent_filter_b1.py) | R3-B1 (R2-L9 plus R2-L8's speed-switched one-lot quotes) plus R3-F1's latent-price filter: three ridge features from a hidden-Markov filter of the ... | 883,559 |
| [`r3_F4_filter_bank.py`](round3/r3_F4_filter_bank.py) | R3-F3 with a bank of two latent-price filters, impact x3 (F3's) and x2 (FILTER_IMP2), fed the same events; each keeps its inserts' predictive ... | 839,401 |
| **[`r3_F5_jump_bar.py`](round3/r3_F5_jump_bar.py)** | R3-F3 with a state-dependent take bar: TAKE_EDGE 0.25 instead of 0.15, except for TAKE_JUMP_HOLD_MS after the mid moved TAKE_JUMP ticks or more ... | **888,195** |
| [`r3_F6_policy_s3.py`](round3/r3_F6_policy_s3.py) | R3-F5 with the policy search's search-3 final mean (R3-P1; IDEAS.md): TAKE_EDGE 0.228, a jump of 4.5 ticks within 191 ms lowers the bar to 0.123 for ... |  |
| [`r3_F6c_policy_s3_const.py`](round3/r3_F6c_policy_s3_const.py) | R3-F6 without the filter-sd rule (TAKE_SD off), so only F5's constants change. The notes of R3-F6 follow. | 868,327 |
| [`r3_P1_pretrained_mlp.py`](round3/r3_P1_pretrained_mlp.py) | R3-F1 plus a PRETRAINED forecast of the 400-ms mid move, a small tanh MLP fitted offline on real and tape_gen v2 tapes ... |  |
| [`r3_P2_pretrained_mlp_b1.py`](round3/r3_P2_pretrained_mlp_b1.py) | R3-P1's stacking on R3-F3 (R3-B1 + FILTER: R3-F1 plus R2-L8's speed-switched one-lot quotes, QUOTE_SIZE 1 only while the 5-s \|mid change\| rate is ... |  |
| [`r3_S1_gap_maker.py`](round3/r3_S1_gap_maker.py) | a passive maker on the latent filter's gap, the first non-taker of round 3. |  |
| [`r3_S2_quiet_maker.py`](round3/r3_S2_quiet_maker.py) | a two-sided touch maker that quotes only in quiet markets, with no forecast at all. |  |
| [`r3_S3_jump_catch.py`](round3/r3_S3_jump_catch.py) | a jump-catch taker, held for seconds, gated by the latent filter. |  |
| [`r3_S4_taker_gap_quote.py`](round3/r3_S4_taker_gap_quote.py) | R3-F1's taker (R2-L9 plus the latent filter's features) with R3-S1's quote in place of none: a QUOTE_SIZE-lot quote at the touch only on the side the ... |  |
| [`r3_S5_pre_entry.py`](round3/r3_S5_pre_entry.py) | R3-F5 plus a passive pre-entry. While (pred - skew) its way is at least PRE_TH + 0.5*spread but not past the take's bar, at a 1-tick spread, one ... |  |

## Round 4 (8 Nov, 07:00-12:00): the warm start

| Candidate | What it is | Uploaded |
|---|---|---:|
| [`r4_G1_gasym.py`](round4/r4_G1_gasym.py) | R3-F5 plus two ridge features at the end of the vector, after the filter's three (R4-S1). GASYM_US: the new market limit orders' mean distance behind ... |  |
| [`r4_MH1.py`](round4/r4_MH1.py) | R3-F5 plus two more ridges at 100 ms and 1 s whose forecasts enter the main ridge as two features (Rust: F5's line and --set MH=1 --set ... |  |
| [`r4_MH3.py`](round4/r4_MH3.py) | R4-MH1 with the second extra ridge at 600 ms instead of 1 s (Rust: F5's line and --set MH=1 --set MH_US1=100000 --set MH_US2=600000; round4_public ... | 1,736,913 |
| [`r4_W1_warm.py`](round4/r4_W1_warm.py) | R3-F5 with a warm start. With PRIOR_MASS > 0 the ridge starts from statistics saved on a public tape (WARM_XX, WARM_XY, WARM_MASS: Rust ridge_maker's ... | 1,752,785 |
| **[`r4_W2_warm10k.py`](round4/r4_W2_warm10k.py)** | R4-W1 with round 4's statistics embedded (F5's ridge on round4_public, RIDGE_DUMP data/arena/round4/r4_stats.txt) at PRIOR_MASS 10000: the ridge ... | **1,754,574** |
| [`r4_W3_flow_depth.py`](round4/r4_W3_flow_depth.py) | R4-W1 with round 4's statistics embedded (F5's ridge on round4_public, RIDGE_DUMP data/arena/round4/r4_stats.txt) at PRIOR_MASS 10000: the ridge ... | 1,732,375 |
| [`r4_X1R3.py`](round4/r4_X1R3.py) | R4-X1 (wide-spread takes on strong signals) plus the filter at FILTER_RATE 3, FILTER_EPS 0.02, FILTER_DEPTH 10. Rust: F5's line and --set ... | 1,724,973 |
| [`r4_X1_wide_take.py`](round4/r4_X1_wide_take.py) | R3-F5 plus takes at wide spreads on strong signals only. F5's take fires only at a 1-tick spread (TAKE_MAXSPREAD 1), and its forecast is clamped to ... |  |
