Yes—there are reproducible strategy, calculation, and update-order defects. This
   is not simply a matter of tuning thresholds or choosing a better model.
 
   I checked the AMT documents against current production wiring and independently
   calculated counterexamples. I did not use existing passing tests as proof.
 
   1. The “value area” can stop being a valid value area

   Your current configuration correctly specifies 68.2%. However, the calculation
   can stop before reaching that coverage.

   Reproduced example
    Prices:   100, 101, 102, 103
    Volumes:  100,   0,   0,  99
 
    Required coverage: 68.2%
    Returned coverage: 50.25%
   The expansion stops at the empty buckets, ignoring substantial volume beyond
   them.
 
   Location: quant/amt/profile/volume_profile.py:136

   The analyzer then modifies the calculated boundaries again:      

   - Clips them to the recent trading range.                        
   - Widens them to contain the leg value area.
   - Counts recent closes inside that modified interval to calculate balance.
 
   The assumption that a session VA must contain its leg VA is mathematically false:
    containing the leg’s data does not mean containing its value area.
 
   Locations: quant/amt/analyzer.py:540, quant/amt/analyzer.py:611,
   quant/amt/analyzer.py:633
 
   Effect: balance can change because the reference boundaries were manipulated—not
   because the auction genuinely accepted new value. The published POC can also fall
    outside the modified VA.
 
   2. Balance/imbalance classification contradicts its own rejection rule
 
   The actual condition is effectively:
    IMBALANCED if:
        displacement
        OR price outside VA
        OR balance ratio < 55%
   Acceptance is only a confidence increment, not a mandatory confirmation.
 
   I reproduced a rejected probe closing inside VA [100,110] at 105. Because
   previous closes were mostly outside, the result remained:
    IMBALANCED
    Reason: low balance ratio, probe rejected (mean-reversion context)
   It identifies mean-reversion context while publishing the opposite auction
   classification.
 
   Location: quant/amt/market/state_engine.py:88
 
   There are competing overrides too:

   - A B-shaped profile unconditionally changes IMBALANCED to BALANCED.
   - A simple price move outside completed initial balance becomes INITIATIVE,
   overriding the more qualified candle detector.
 
   One reproduction changed:
    Candle detector: RESPONSIVE DOWN
    Final output:   INITIATIVE UP
    Model router:   TREND
   Locations: quant/amt/analyzer.py:723, quant/amt/session/structure.py:78
 
   3. “Complete evidence” bypasses the actual strategy requirements 

   This is the clearest entry-enforcement defect.

   The documented requirements include:

   - Trend: valid location, breakout/retest, confirmation.
   - Fade: failed outside probe followed by a close back inside value.

   But SetupEvidence.is_complete() does not verify several of these conditions. Gate
    3 immediately approves that evidence before reaching its stricter location
   checks.
 
   Locations: quant/decision/setup_state.py:43, quant/decision/gates_edge.py:217
 
   Using the actual decision functions, I reproduced:
   ┌───────────────────────────────────────────┬─────────────────────────────────┐
   │ Controlled input                          │ Actual result                   │
   ├───────────────────────────────────────────┼─────────────────────────────────┤
   │ BALANCED auction; price 100 ticks away    │ Selects TREND and approves LVN  │
   │ from the LVN                              │ entry                           │
   ├───────────────────────────────────────────┼─────────────────────────────────┤
   │ Triple-A LONG below VWAP and still inside │ Approves                        │
   │ the compression box                       │                                 │
   ├───────────────────────────────────────────┼─────────────────────────────────┤
   │ Genuine earlier rejection below VAL,      │ Approves a fade; the standalone │
   │ followed by a micro candle closing        │ fade detector correctly rejects │
   │ outside value again                       │ it                              │
   └───────────────────────────────────────────┴─────────────────────────────────┘
   The documented evidence override is not inherently wrong. The evidence being 
   allowed to override the market state is insufficiently validated.
 
   That explains how the system can display one market condition while trading
   another playbook.
 
   4. History, current bars, and session state are inconsistent

   History seeding does not warm the whole strategy

   For 20 historical candles, each with volume 100 and delta +10:
   ┌──────────────────┬───────────────────────────────────────────────────┐
   │ Component        │ Observed state                                    │
   ├──────────────────┼───────────────────────────────────────────────────┤
   │ Profile volume   │ Correctly contains 2,000                          │
   ├──────────────────┼───────────────────────────────────────────────────┤
   │ CVD              │ Contains only 10—not 200                          │
   ├──────────────────┼───────────────────────────────────────────────────┤
   │ CVD history      │ One observation                                   │
   ├──────────────────┼───────────────────────────────────────────────────┤
   │ Session VWAP/ATR │ One candle                                        │
   │ buffer           │                                                   │
   ├──────────────────┼───────────────────────────────────────────────────┤
   │ Initial balance  │ Already complete, using only the final historical │
   │                  │ candle                                            │
   └──────────────────┴───────────────────────────────────────────────────┘
   The profile receives every historical candle, but the stateful analyzer runs only
    once.
 
   Location: quant/amt_engine.py:365
 
   Consequently, “warmup complete” can mean warm profile, cold order flow, incorrect
    initial balance.
 
   Duplicate bars affect components differently

   Refeeding the final historical timestamp changed:
    Profile volume: 2,000 → 2,100
    CVD:               10 → 20
    VWAP samples:       1 → 1
   There is no consistent timestamp reconciliation.
 
   Location: quant/amt_engine.py:467
 
   Rollover retains yesterday’s profile

   For an engine surviving into the next session, the candle ring and incremental
   profile remain populated while other trackers reset. I reproduced an initial
   balance immediately marked complete using yesterday’s session-open anchor.
 
   Location: quant/amt_engine.py:432

   5. Closed-candle confirmation uses mismatched timing

   At a simultaneous 1-minute/5-minute boundary, the code:

   1. Evaluates the closed micro candle using the previous macro snapshot.
   2. Starts the next footprint.
   3. Analyzes the newly closed macro candle.
 
   Thus the newly available macro information misses that micro decision.

   Location: quant/engine/tick_handler.py:222

   More importantly, the decision builder selects the newest footprint, including
   the forming candle.

   I reproduced: 
    Closed candle:       BUY stack, 3 levels
    First next-bar tick: new one-price footprint
    Selected stack:      none
   Locations: quant/amt/orderflow/footprint.py:271,
   quant/decision/context_builder.py:88
 
   There is also a timestamp mismatch: footprint keys are epoch strings, while leg
   candles use ISO timestamps. The exact-key lookup misses available tick footprints
    and falls back to candle-distributed profiles.
 
   Location: quant/amt/profile/displacement.py:92

   Effect: the system can lose the confirmation and precise leg profile that the
   strategy depends on.
 
   6. Several individual calculations are demonstrably wrong or mislabeled
   ┌─────────────┬───────────────────┬─────────────────────────────────────────┐
   │ Finding     │ Independently     │ Location                                │
   │             │ reproduced result │                                         │
   ├─────────────┼───────────────────┼─────────────────────────────────────────┤
   │ Flat-price  │ Five bars trading │ quant/amt/profile/volume_profile.py:384 │
   │ profile     │ only at 100       │                                         │
   │ corruption  │ produce an        │                                         │
   │ corruption  │ 100 produce an   │                                         │
   │             │ incremental      │                                         │
   │             │ profile at       │                                         │
   │             │ 100.5; expected  │                                         │
   │             │ buys/sells       │                                         │
   │             │ 400/100 become   │                                         │
   │             │ 370/130          │                                         │
   ├───────────────┼─────────────────┼─────────────────────────────────────────┤
   │ LVN ranking   │ Clustering      │ quant/amt/profile/lvn.py:205,           │
   │ reversed      │ discards the    │ quant/amt/profile/lvn.py:221            │
   │               │ stronger        │                                         │
   │               │ zero-volume     │                                         │
   │ reversed      │ discards the      │ quant/amt/profile/lvn.py:221            │
   │               │ stronger          │                                         │
   │               │ zero-volume       │                                         │
   │               │ trough and keeps  │                                         │
   │               │ the weaker nearby │                                         │
   │               │ trough            │                                         │
   ├───────────────┼───────────────────┼─────────────────────────────────────────┤
   │ Reading CVD   │ Identical candles │ quant/amt/orderflow/cvd.py:123,         │
   │ changes its   │ produce slope +10 │ quant/amt/orderflow/cvd.py:163          │
   │ persistence   │ or −14.88,        │                                         │
   │               │ depending on      │                                         │
   │               │ snapshot reads    │                                         │
   ├───────────────┼───────────────────┼─────────────────────────────────────────┤
   │ Published σ   │ Prices 90/110     │ quant/amt/profile/vwap.py:145           │
   │ is clamped,   │ give true VWAP    │                                         │
   │ not           │ 100 and σ10;      │                                         │
   │ statistical σ │ published recent  │                                         │
   │               │ σ becomes 3       │                                         │
   ├───────────────┼───────────────────┼─────────────────────────────────────────┤
   │ Reconstructed │ Volume100/delta20 │ quant/amt/orderflow/footprint.py:75     │
   │ footprint     │ becomes summed    │                                         │
   │ violates      │ level             │                                         │
   │ conservation  │ volume105/delta21 │                                         │
   └───────────────┴───────────────────┴─────────────────────────────────────────┘
   The σ clamp is intentional policy, but presenting it as statistical standard
   deviation makes “2σ overextension” misleading. The last finding concerns
   reconstructed analysis footprints, not proof of equivalent loss in the live tick
   accumulator.
 
   Two additional state-machine defects:
 
   - Acceptance can remain true above and below VA simultaneously.
   quant/amt/market/acceptance_rejection.py:106
   - Staying near a level becomes D2 and then D3 without requiring departure and
   re-approach.
   quant/amt/orderflow/drive.py:137

   7. Model names do not reliably describe behavior                 

   A complete-evidence VA_FADE is labeled Triple-A.

   That is not merely cosmetic: full exit at POC is selected using the VA_FADE
   label. Mislabeling sends the trade into different target-management behavior.

   Locations: quant/decision/decision_service.py:49,
   quant/execution/exit_checks.py:70
 
   Separately, TimesFM is not the default entry authority; the deterministic AMT
   strategy is. Yet the UI can synthesize a TIMESFM_3.0_NATIVE decision, forecast
   and confidence without an advisor decision.
 
   Locations: quant/strategies/selection.py:12, quant/multi_engine.py:830

   What is correct

   Not every formula is broken. Raw weighted VWAP/variance, ordinary non-flat volume
    accumulation, basic CVD summation/regression, and OFI arithmetic checked out.
   The current VA percentage is already 68.2%.
 
   The larger failure is that correct calculations are mixed with altered 
   boundaries, inconsistent history, stale snapshots, and entry shortcuts.
 
   Recommended repair order

   1. Remove the setup-certification bypasses and preserve the correct playbook
   identity.
   2. Fix historical warmup, duplicate handling, session reset, and closed-bar
   ordering.
   3. Restore profile/VA invariants and correct LVN/CVD defects.
   4. Establish one coherent auction-state and acceptance model.
   5. Validate candle-by-candle against independently specified AMT scenarios, then
   evaluate trading economics.
 
   No source changes were made. These defects establish incorrect strategy behavior;
    attributing a specific amount of historical loss to each would require a
   separate replay analysis.
 
                                      