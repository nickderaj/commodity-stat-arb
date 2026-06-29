# Phase 7 Notes - Robustness Testing

## _ Notes after running sub-period analysis, walk-forward, parameter sensitivity, and stress tests _

> See `scripts/run_phase7_robustness.py` for all runs. All analyses reuse the existing engine and cost model from Phase 5 -- no new infrastructure, just different date slices and parameter grids. The baseline signal throughout is entry=2.0, exit=0.75, lookback=60, filters=True on a $100k book with 1% risk per trade.

---

## A. Sub-Period Analysis

Three intended periods: pre-2015, 2015-2019, 2020-present. The DB only has data from mid-2018 onwards for most contracts, so pre-2015 returned no data for any spread. Two periods ran.

| Period    | brent_calendar | brent_wti | wti_calendar |
| --------- | -------------- | --------- | ------------ |
| 2015-2019 | 0.076          | 0.841     | -0.054       |
| 2020+     | 0.276          | 0.363     | -0.152       |

The pre-2015 gap is a data limitation, not a code issue. The Databento subscription covers roughly 2018 onwards at the contract-level monthly resolution needed for calendar spreads.

**brent_wti** is the only spread with clearly positive Sharpe in both periods. It also shows the largest degradation from 2015-2019 to 2020+ (0.841 to 0.363). That's partly a regime shift -- the 2019 Zivot-Andrews break identified in Phase 2 changed the spread dynamics, and the 2020-2026 window includes both the COVID dislocation and the Ukraine energy crisis. That the spread held up at all (Sharpe 0.363 with 35 trades) is more encouraging than the raw number suggests.

**wti_calendar** is negative in both periods. This is consistent with the Phase 3 and Phase 5 findings. The spread spends 69% of the time in backwardation, and the z-score signal without a contango gate loses money in that regime. The 2020+ period has particularly large drawdown (-56% in the COVID window, see stress tests). This spread should not be traded with this signal configuration on daily bars.

**brent_calendar** improves from 2015-2019 to 2020+ (0.076 to 0.276). Unusual -- most strategies deteriorate post-COVID. Looking at the trade count: 13 trades in 2015-2019 vs 33 in 2020+. The vol spikes from 2020 and 2022 created larger z-score dislocations that the entry=2.0 threshold could catch, and those dislocations reverted cleanly once the acute episode passed. Not a durable edge, but the regime filter did its job of suppressing the ugly ones.

---

## B. Walk-Forward

Setup: 2-year IS window, 6-month OOS, sliding forward by one OOS period at a time. Parameters are fixed -- no re-optimisation on each IS window. This tests whether the Phase 5 parameters hold on unseen data without the additional question of whether they're the right parameters per window.

| Spread         | Avg efficiency ratio | Result |
| -------------- | -------------------- | ------ |
| brent_calendar | 0.923                | PASS   |
| brent_wti      | 1.368                | PASS   |
| wti_calendar   | 1861 (unstable)      | --     |

brent_wti and brent_calendar both pass the efficiency > 0.5 target. The brent_wti windows:

```
IS 2018-2019 (Sharpe 0.841) -> OOS 2020 H1 (Sharpe 1.087) - efficiency 1.29
IS 2020-2021 (Sharpe 0.351) -> OOS 2022 H1 (Sharpe 0.718) - efficiency 2.05
IS 2022-2023 (Sharpe 0.977) -> OOS 2024 H1 (Sharpe 0.746) - efficiency 0.76
```

The OOS Sharpe exceeds IS Sharpe in two of three windows for brent_wti. That's either good luck or the parameters genuinely generalize -- probably a bit of both. The H1 2022 OOS window was during the Ukraine crisis, which produced large z-score entries that reverted quickly. The H1 2020 OOS window was COVID, same story.

wti_calendar's "efficiency ratio" is numerically meaningless for several windows because the IS Sharpe is near zero. When the denominator approaches zero, the ratio goes to infinity. It's better to just say the IS runs have near-zero Sharpe and the OOS runs are noisy, both consistent with a weak signal.

One limitation of this walk-forward setup: it uses fixed parameters, so it's measuring signal stability rather than overfitting. A proper in-sample optimisation on each IS window followed by OOS test would give a truer read on whether the Phase 3 parameter scan overfit. That's more work and would require a nested grid search per IS window. The result would likely show more degradation. For daily-bar mean reversion with a relatively simple signal, the fixed-parameter approach is probably not far off.

---

## C. Parameter Sensitivity Grid

Grid on brent_wti: entry threshold in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0] x lookback in [10, 20, 30, 45, 60, 90]. Exit fixed at 0.75, filters on.

| entry | lb=10 | lb=20 | lb=30 | lb=45 | lb=60 | lb=90 |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| 0.5   | 0.156 | 0.330 | 0.168 | 0.359 | 0.503 | 0.406 |
| 1.0   | 0.208 | 0.357 | 0.446 | 0.379 | 0.413 | 0.469 |
| 1.5   | 0.350 | 0.690 | 0.347 | 0.392 | 0.490 | 0.498 |
| 2.0   | 0.241 | 0.463 | 0.251 | 0.364 | 0.412 | 0.441 |
| 2.5   | 0.407 | 0.503 | 0.280 | 0.255 | 0.391 | 0.471 |
| 3.0   | N/A   | 0.110 | 0.151 | 0.097 | 0.170 | 0.285 |

N/A at entry=3.0, lb=10 means no trades fired (not enough data to reach 3-sigma at 10-day lookback).

22 of 35 valid combinations (63%) are within 50% of the peak Sharpe (0.690). That's a broad plateau. The strategy is not a spike around one lucky parameter point.

A few observations:

**The peak is at entry=1.5, lookback=20 (Sharpe 0.690), not at the Phase 5 best (entry=2.0, lookback=60, Sharpe 0.412).** This is because the Phase 5 best was chosen over the full multi-spread sweep and also weighted by max drawdown and trade count. entry=1.5/lb=20 fires 156 trades vs 49 for entry=2.0/lb=60. More trades mean more commission drag, lower per-trade quality, but better Sharpe because the signal is more frequent and the holding periods are shorter (less overnight risk).

**lb=10 is consistently the worst lookback.** At 10 days, the rolling mean and std are too noisy to define meaningful z-scores. The vol filter helps but can't fully compensate. Lookbacks of 20-90 all produce similar Sharpe in the 0.3-0.7 range.

**entry=3.0 is consistently the weakest.** At 3-sigma you fire very few trades (often fewer than 10 over the full history), making the Sharpe estimate unreliable and the strategy too inactive to be useful.

The ridge runs roughly from entry 0.5-2.5 at lookbacks 20-90. That's a wide usable region. The Phase 5 parameter choice (entry=2.0, lb=60) sits in the middle of the plateau, which is probably the right choice for a live system: lower entry thresholds generate more trades and more commission, while longer lookbacks are more robust to structural regime shifts.

---

## D. Stress Tests

### 2020 COVID (Oct 2019 to Mar 2021)

| Spread         | Sharpe | Max DD  | Trades | Result      |
| -------------- | ------ | ------- | ------ | ----------- |
| wti_calendar   | -0.375 | -56.87% | 7      | WARN-HIGH-DD|
| brent_calendar | -0.372 | -7.98%  | 8      | PASS        |
| brent_wti      | 0.180  | -4.43%  | 11     | PASS        |

wti_calendar is the problem. The 56.87% drawdown is not a result of many bad trades -- it's 7 trades over 18 months. The drawdown probably comes from one or two positions held through the March-April 2020 WTI collapse. WTI M1 went briefly negative on April 20 2020; the M1-M2 spread blew out in ways that had no historical precedent. The vol filter was already suppressing new entries (correct behavior) but any position already open at that point would have been held until z-score reversion, which means riding through the worst of it.

The fundamental issue: the exit signal for this strategy is z-score crossing back below the exit threshold. In a trending dislocation like April 2020, the z-score can keep getting more extreme before reverting, and there's no stop loss in the current engine. Adding a time-based stop or a hard delta stop on position PnL would have bounded this.

brent_calendar and brent_wti both passed cleanly. Both held drawdowns under 8% and 5% respectively despite the same vol environment. The difference is that the Brent-WTI spread and the Brent calendar spread were less exposed to the Cushing storage-driven mechanics that caused the WTI outright and calendar to go haywire.

### 2022 Russia-Ukraine (Oct 2021 to Mar 2023)

| Spread         | Sharpe | Max DD  | Trades | Result |
| -------------- | ------ | ------- | ------ | ------ |
| wti_calendar   | -0.316 | -4.73%  | 7      | PASS   |
| brent_calendar | 0.023  | -20.83% | 6      | PASS   |
| brent_wti      | 0.686  | -3.46%  | 7      | PASS   |

All three pass on drawdown. The wti_calendar drawdown is much smaller (4.7%) than in COVID even though the strategy is still losing on a Sharpe basis. The Ukraine energy spike was an upward surge in prices rather than a collapse, and the calendar spreads were driven into steep backwardation -- which means high vol, but the spread values themselves stayed within ranges the vol filter could handle.

brent_wti produced Sharpe 0.686 during this window. That's the best stress period result across all spreads and crises. The Brent-WTI differential was volatile around the Ukraine invasion (European buyers shifting away from Russian supply, US Gulf exports surging) but these macro flows created temporary dislocations in the spread that reverted once the logistics adjusted.

brent_calendar had a 20.83% drawdown despite positive Sharpe. Only 6 trades in 18 months. One or two bad trades with small positions can produce large percentage drawdowns at this position count. The Calmar ratio would be weak, but the overall direction is right (positive Sharpe, bounded losses).

---

## E. Key Takeaways

**brent_wti is the only spread worth trading with this signal on daily bars.** The sub-period, walk-forward, and stress tests all point the same direction. It generates consistent alpha across time periods, parameters, and crisis windows.

**wti_calendar has a structural flaw for this signal: no contango gate.** The Phase 3 finding (Sharpe 0.484 in contango vs -0.080 in backwardation) predicted this. Adding a contango entry gate would probably fix the COVID drawdown issue too, since the spread collapsed into extreme backwardation during that period. This is a meaningful improvement to test in a follow-up.

**The parameter ridge is real.** 63% of parameter combinations on brent_wti are near the peak. You don't need to be precise about the exact lookback or entry threshold to get a viable strategy. This makes the Phase 5 parameter choice (entry=2.0, lb=60) defensible even though a slightly different choice (entry=1.5, lb=20) produces a higher Sharpe -- the higher-Sharpe config fires 3x as many trades and the commission drag would be larger if transaction costs were higher.

**The walk-forward result is better than expected.** OOS efficiency ratios above 1.0 are uncommon for mean-reversion strategies tested honestly. The caveat is that the OOS windows include crisis periods (COVID 2020, Ukraine 2022) which happened to be good for the strategy. A longer history would give a more balanced test.

**No stop loss is the main operational risk.** The wti_calendar COVID drawdown (56.87%) shows what happens when a position gets caught in a structural break with no stop. The vol filter suppresses new entries but doesn't exit open positions. For a live system, a time-based stop (e.g. exit after 30 days if z-score hasn't crossed exit threshold) or a drawdown stop at some fixed percentage would have bounded this.

---

## F. Checklist

- [x] `scripts/run_phase7_robustness.py` - sub-period, walk-forward, sensitivity grid, stress tests; runs in ~2-3 min
- [x] Sub-period table: 2 of 3 periods available; brent_wti positive in both (0.841 / 0.363)
- [x] Walk-forward: brent_wti avg efficiency 1.37 (PASS); brent_calendar 0.92 (PASS)
- [x] Parameter grid (36 combos): ridge confirmed -- 22/35 within 50% of peak Sharpe
- [x] 2020 COVID stress: wti_calendar WARN (56.87% DD); brent_wti and brent_calendar PASS
- [x] 2022 Russia-Ukraine stress: all three spreads PASS on drawdown; brent_wti Sharpe 0.686
- [x] `research/robustness_summary.md` written with all tables and pass/fail verdicts
- [x] wti_calendar flagged as not-recommended for live trading without a contango entry gate
