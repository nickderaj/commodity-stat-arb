# Hypothesis Cards - Top Signal Candidates

_Selected from Phase 3 parameter scan (2018-2026, no transaction costs)._
_Full scan results: `research/outputs/param_scan_results.csv`_

## Comparison Table

|                       | Card 1 - Brent-WTI   | Card 2 - Brent Calendar     | Card 3 - WTI Calendar         |
| --------------------- | -------------------- | --------------------------- | ----------------------------- |
| **Lookback**          | 60d                  | 60d                         | 20d                           |
| **Entry / Exit**      | \|z\|>1.5 / 0.5      | \|z\|>2.0 / 0.75            | \|z\|>1.5 / 0.5               |
| **Sharpe (filtered)** | 0.894                | 0.229                       | 0.216                         |
| **Trades (8.5yr)**    | 80                   | 46                          | 125                           |
| **Win rate**          | 52%                  | 51%                         | 51%                           |
| **Mean HL**           | 4.9-10.7d            | 7.1d                        | 24.6d                         |
| **Best regime**       | Any (cross-market)   | Backwardation (0.322)       | Contango (0.484)              |
| **Worst regime**      | High vol             | Contango (0.008)            | Backwardation (-0.080)        |
| **Filter benefit**    | +0.452 → 0.894       | +0.351 → 0.229 (hurts)      | +0.071 → 0.216                |
| **Economic tether**   | Refiner substitution | Cost-of-carry arb           | Cash-and-carry arb            |
| **Key failure mode**  | Structural break lag | 2022 trending backwardation | Storage fill / vol spike      |
| **For backtesting**   | Primary candidate    | Secondary (add regime gate) | Tertiary (contango-only gate) |

Filters hurt brent_calendar because the vol filter is too aggressive - it blocks valid entries during high-vol backwardation episodes, which is actually when the signal works best. The other two benefit from filtering.

---

## Card 1 - Brent-WTI Location Spread Mean Reversion

**Signal params**: lookback=60d, entry=|z|>1.5, exit=|z|<0.5, filters=ON
**Scan Sharpe**: 0.894 | **Trades**: 80 | **Win rate**: 52%

### Inefficiency being exploited

Brent and WTI are close substitutes. Refiners worldwide can switch between them when the differential strays too far. The spread reflects structural quality/logistics differentials (North Sea waterborne vs Cushing landlocked), but temporary dislocations happen from:

- Geopolitical events hitting Brent disproportionately (Middle East, Russia)
- Cushing inventory accumulation depressing WTI relative to Brent
- Short-term demand shocks hitting one benchmark faster than the other

When the differential overshoots, physical traders and refiners arbitrage it back. That's the edge.

### Signal logic and parameter choice

60-day rolling z-score. Enter when |z| > 1.5 (spread meaningfully extended from 60-day mean/std). Exit when |z| < 0.5 (back near mean). The 60d window captures the medium-term mean without being too sensitive to recent regime shifts. Shorter lookbacks (20d) produced lower Sharpe because the mean itself shifts faster than we can trade it.

Filters ON: vol regime filter blocks entries when 20-day spread vol is above 90th percentile (captures 2020 COVID and 2022 Ukraine events where the spread trended rather than reverted). Entry block during these periods raised Sharpe from 0.452 → 0.894.

### Expected half-life range

4.9-10.7 days (from Phase 2 rolling AR(1) analysis). The fast mean reversion is why the 60d z-score still catches entries: the spread returns to the rolling mean faster than the lookback window, so entries at |z|>1.5 are reliably mean-reverting.

### Regime conditions required

- Vol regime filter: vol must be below 90th percentile
- No specific contango/backwardation requirement (cross-market spread, not term structure)
- 2015 post-export-ban regime: rolling mean adjusts; z-score is robust to level shifts as long as the rolling window eventually catches up

### Failure modes and where it breaks down

1. Structural regime shift: new pipeline capacity, refinery openings/closings, trade policy change. The spread settles at a new mean that the 60d window hasn't learned yet → false entries.
2. COVID-style demand collapse (March-April 2020): both spreads behaved non-stationary for 6-8 weeks. Vol filter caught most of this.
3. Rolling mean lag: after a big shock, the 60d mean is "stale" for ~60 days. The z-score inflates, creating phantom entries.
4. Capacity constraint from brent_wti's structural break (2019-05-31 per Phase 2 ZA test): post-break mean is meaningfully different from pre-break.

---

## Card 2 - Brent Calendar Spread at Extreme Z-score

**Signal params**: lookback=60d, entry=|z|>2.0, exit=|z|<0.75, filters=ON
**Scan Sharpe**: 0.229 | **Trades**: 46 | **Win rate**: 51%
**Regime split**: backwardation Sharpe=0.322 vs contango Sharpe=0.008

### Inefficiency being exploited

The Brent M1-M2 spread is tethered by cost-of-carry arbitrage. When the spread extends to more than 2 standard deviations from its 60-day mean, one of two things is happening: (a) a genuine supply shock is creating extreme backwardation/contango that will normalize, or (b) the market has temporarily mispriced the roll-implied storage cost. In either case, the spread reverts.

The signal only fires reliably in backwardation regime (Brent Sharpe 0.322 vs 0.008 in contango). In backwardation, excess prompt demand creates overshoot that normalizes as inventory replenishes. In contango, the moves are smaller and less predictable.

### Signal logic and parameter choice

60-day lookback (aligns with the ~7-day mean half-life × 5-10x heuristic = 35-70d). Entry threshold of 2.0 is more conservative than for brent_wti (1.5) because the calendar spread has a shorter half-life (7.1d vs 4.9-10.7d) and more false signals in roll windows. Higher threshold filters out the noisy roll-window moves.

Exit at |z| < 0.75 is looser than brent_wti (0.5), appropriate given the faster mean reversion - trades exit quickly anyway.

### Expected half-life range

7.1 days mean (Phase 2), IQR 2.3-8.0d. Fastest of the three spreads. ICE Brent is globally liquid and heavily arbitraged - dislocations get corrected within 1-2 weeks.

### Regime conditions required

- Backwardation regime preferred (Sharpe 4x higher than in contango)
- Vol filter blocks entries during Ukraine/COVID extreme vol spikes
- Roll-window vol filter: roll windows create vol but not directional signal

### Failure modes and where it breaks down

1. Energy supply shocks (2022 Ukraine): Brent term structure went into extreme backwardation for months, trending rather than reverting. The z-score couldn't anchor fast enough.
2. Short half-life risk: at 7.1 days mean, if holding costs (margin, roll cost) accumulate faster than the spread reverts, the trade is unprofitable before the exit signal triggers.
3. Carry model finding: the excess spread (raw minus carry FV) has the same half-life (12.0d) as the raw spread (11.1d). This means the convenience yield fluctuations dominate, not the storage/financing component. The fair-value model doesn't give us an edge in timing.

---

## Card 3 - WTI Calendar Spread Contango Mean Reversion

**Signal params**: lookback=20d, entry=|z|>1.5, exit=|z|<0.5, filters=ON
**Scan Sharpe (all regimes)**: 0.216 | **Trades**: 125 | **Win rate**: 51%
**Regime split**: contango Sharpe=0.484 vs backwardation Sharpe=-0.080

### Inefficiency being exploited

In contango (M1 < M2), the WTI calendar spread is anchored by the cash-and-carry arbitrage: traders buy prompt barrels, store them, and sell forward. This puts a ceiling on how negative the spread can get. Deviations below the storage cost floor are temporary - once tanks fill the arb closes. Recurring drivers of short-term deviation include the Goldman Roll (predictable flow pressure in the first 2 weeks of each month) and EIA inventory report surprises.

The key insight from regime stratification: this signal only works in contango (Sharpe 0.484). In backwardation, convenience yield swings dominate and the signal breaks down (Sharpe -0.080, slightly negative).

### Signal logic and parameter choice

20-day lookback (shorter than brent spread candidates) matches the ~24.6 day mean half-life for WTI. This is at the limit of the "3-5x half-life" rule of thumb. The Goldman Roll happens on a 5-9 business day window, so a 20d lookback captures roughly 1 roll cycle.

Entry at |z| > 1.5 catches meaningful dislocations without overfitting. Exit at |z| < 0.5.

### Expected half-life range

15.5-31.3 days (IQR, Phase 2). Longer-tailed than Brent. When WTI is in a slow Cushing storage-driven contango regime, the spread can stay distorted for weeks. The vol filter is essential to avoid entering during these slow-moving distortions when the spread may trend further before reverting.

### Regime conditions required

- Contango regime (M1 < M2): signal essentially doesn't work outside this
- Non-extreme vol (vol filter blocks 2020 COVID, 2022 Ukraine)
- Available storage capacity: when Cushing tanks are nearly full, the arbitrage breaks and the contango can become extreme/persistent (April 2020 being the extreme case)

### Failure modes and where it breaks down

1. Storage capacity exhaustion: April 2020 saw WTI go negative. The carry-arbitrage floor breaks entirely when there's nowhere to store oil. The vol filter would have caught most of this.
2. Regime misclassification: the signal is labeled by the spread sign (positive = backwardation), but the spread flips quickly at roll. A position entered in contango can find itself in a backwardation regime mid-hold.
3. Long half-life in slow regimes: when the market is stuck in deep contango for months, the 20d lookback produces a z-score that never reaches |z| > 1.5 anyway (spreads don't deviate enough within the mean window). In practice the 125 trades over 8.5 years means ~15 trades/year - many contango regimes produce no signal.
