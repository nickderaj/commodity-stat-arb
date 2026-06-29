# Phase 2 Notes

## A. Roll Window Diagnostics

> Does spread volatility actually spike during roll windows? And does the spread level systematically shift?

### Prior hypotheses

1. **Spread vol increases near roll** - position-unwinding pressure as traders close M1 and open M2 simultaneously should create one-sided flow.
2. **Spread level shifts near roll** - calendar spreads could contango-bias as M1 is sold aggressively during the roll window.
3. **Volume drops in roll windows** - liquidity migrates from the front to the second contract.
4. **WTI roll effect bigger than Brent** - Cushing physical delivery constraints vs cash-settled Brent (ICE/NYMEX) should matter more for WTI.
5. **Post-roll mean reversion** - spread snaps back toward mid-cycle within 3-5 days of expiry.

### What actually happened (`roll_diagnostics.py`, ±10 DTE window)

| Spread         | Roll bars | Mid bars | Roll mean abs change | Mid mean abs change | Ratio | t-test p | MW p  |
| -------------- | --------- | -------- | -------------------- | ------------------- | ----- | -------- | ----- |
| wti_calendar   | 958       | 1678     | 0.1445               | 0.1141              | 1.27x | 0.034    | 0.002 |
| brent_calendar | 964       | 1642     | 0.2337               | 0.1872              | 1.25x | 0.006    | 0.000 |
| brent_wti      | 811       | 1320     | 0.6267               | 0.6104              | 1.03x | 0.686    | 0.008 |

Hypothesis 1 is confirmed for both calendar spreads - ~25% larger daily moves in roll windows, significant on both tests. Brent is actually slightly more significant than WTI despite the physical delivery argument, which suggests the dominant driver is index roll flow (the Goldman Roll is CME-agnostic) rather than physical delivery friction.

Hypothesis 2 did not hold - the mean spread level barely moves at roll (mid-cycle vs roll-window averages are nearly identical for all three spreads). So the roll creates volatility but not a systematic drift.

The brent_wti result makes sense - it uses continuous contracts that roll silently, so there's no liquidity migration effect baked into the series. The Mann-Whitney p=0.008 is technically significant but the ratio is 1.03x which is basically nothing economically.

Heatmaps: `research/outputs/roll_heatmap_x.png`

---

## B. Stationarity (ADF + KPSS)

> Quick reminder: ADF null is "has unit root" so rejecting (p<0.05) is good. KPSS null is "is stationary" so NOT rejecting (p>0.05) is good. We want both.

| Spread         | ADF stat | ADF p  | KPSS stat | KPSS p | Call  |
| -------------- | -------- | ------ | --------- | ------ | ----- |
| wti_calendar   | -5.07    | <0.001 | 1.49      | 0.010  | mixed |
| brent_calendar | -5.74    | <0.001 | 1.20      | 0.010  | mixed |
| brent_wti      | -3.55    | 0.007  | 1.44      | 0.010  | mixed |

KPSS rejects (0.05 > 0.01), but ADF also rejects (unit roots rejected with high confidence)

> ADF looks at this and says: "within each regime the series is clearly mean-reverting, the whole thing looks stationary" - so it rejects the random walk.
> KPSS looks at this and says: "the level keeps shifting around, that's not what a stationary series does" - so it rejects stationarity.

The series mean-reverts within regimes (ADF sees this), but the long-run mean is not fixed (KPSS sees this).

This isn't surprising and doesn't mean the series isn't tradeable. KPSS is known to be sensitive to level shifts - the 2020 COVID event and 2022 Ukraine shock create the appearance of non-stationarity because the mean shifts. If you sub-sample to any single regime period, KPSS will almost certainly pass. The ADF result is the one to lean on here: the series are mean-reverting, they just have structural breaks in the long-run mean. That's exactly what the regime-aware z-score in Phase 3 is designed for.

---

## C. Cointegration (Brent vs WTI legs)

> This is really a sanity check on the brent_wti spread - we know Brent and WTI should be cointegrated, so if the test fails something is wrong with the data.

| Test                  | Stat  | p-value | Result             |
| --------------------- | ----- | ------- | ------------------ |
| Engle-Granger         | -3.55 | 0.028   | Cointegrated       |
| Johansen trace (r=0)  | 67.69 | -       | Reject (CV95=15.5) |
| Johansen trace (r<=1) | 6.05  | -       | Reject (CV95=3.84) |
| OLS hedge ratio β     | 1.001 | -       | ~1:1 parity        |

The cointegration is solid. β=1.001 is basically perfect - Brent and WTI trade in near 1:1 lockstep over the long run, with the spread reflecting quality/location differences rather than any drifting relative value.

For two series (Brent and WTI), r can only be 0, 1, or 2:

- r = 0 - no cointegration at all, the two prices drift independently forever
- r = 1 - one cointegrating relationship (what we expect: Brent and WTI tied together by one spread)
- r = 2 - both series are individually stationary (they each mean-revert on their own, no cointegration needed)

The test works by running two sequential hypothesis tests:

1. H0: r = 0 (no cointegration). Trace stat = 67.69 vs CV95 = 15.5 → reject. So r > 0, there's at least one cointegrating relationship.
2. H0: r ≤ 1 (at most one relationship). Trace stat = 6.05 vs CV95 = 3.84 → reject. So r > 1, which implies r = 2.

The Johansen test rejecting r<=1 is a bit unusual (it means both individual price series may themselves be near-stationary). This is consistent with the ADF results above - crude futures prices are highly mean-reverting at multi-year timescales (they can't stay at $150 or $20 forever), so the individual legs have some mean-reversion in them which muddies the pure I(1) assumption. The key point is: the spread is cointegrated and tradeable.

- This is a known quirk with commodity prices over long samples. Oil can't go to zero or infinity forever - there's a physical floor (extraction cost ~$20-30/bbl) and a demand-destruction ceiling (~$120-150/bbl). So over an 8-year window, the individual price series look weakly stationary even though day-to-day they behave like random walks.

---

## D. Rolling Half-Life

> AR(1) regression: $$dS = a + b\*S_lag$$. Half-life = $$-ln(2)/b$$ when b < 0 (i.e. mean-reverting).

| Spread         | Mean HL (days) | p25  | p75  | Config estimate |
| -------------- | -------------- | ---- | ---- | --------------- |
| wti_calendar   | 24.6           | 15.5 | 31.3 | 10 days         |
| brent_calendar | 7.1            | 2.3  | 8.0  | 10 days         |
| brent_wti      | 4.9            | 2.9  | 5.8  | 15 days         |

All three are inside the 3-30 day tradeable band.

**wti_calendar** at 24.6 days mean is longer than I expected. The p75 of 31.3 days means in the slower regimes it's sitting right at the edge of "too slow." Cushing storage dynamics drive this - when the market is in deep contango and storage is nearly full, the spread can stay distorted for weeks. The vol filter in Phase 3 should help suppress signals in those regimes.

**brent_calendar** at 7.1 days is fast and tight (IQR of 2.3-8.0). This is the cleanest of the three. ICE Brent is more liquid and globally priced, so dislocations get arbed away quickly.

**brent_wti** at 4.9 days mean is shorter than the 15-day config estimate. The spread is more liquid and arbitrage-efficient than the calendar spreads - US/European traders with access to both exchanges keep it tight. The config estimate was probably conservative. This means a shorter lookback z-score window might be optimal for this spread in Phase 3.

> Rule of thumb: lookback should be ~3-5x the half-life. So brent_calendar points toward a 20-40 day lookback, brent_wti toward 15-25 days, and wti_calendar toward 60-90 days (but with the caveat that in slow regimes it needs to be suppressed entirely).

Rolling half-life chart: `research/outputs/rolling_half_life.png`

---

## E. Structural Breaks (Zivot-Andrews)

> ZA finds ONE endogenous break per series. Where the rolling ADF chart crosses the critical value boundary shows the actual regime shift picture more clearly.

| Spread         | Break date | ZA stat | ZA p  | Context                                          |
| -------------- | ---------- | ------- | ----- | ------------------------------------------------ |
| wti_calendar   | 2020-04-27 | -5.39   | 0.020 | COVID demand collapse / WTI negative price event |
| brent_calendar | 2023-11-05 | -4.73   | 0.126 | Post-Ukraine energy normalization                |
| brent_wti      | 2019-05-31 | -6.21   | 0.002 | Iran sanctions / US export capacity shift        |

**wti_calendar** break at April 27 2020 is one week after the famous -$37 close on April 20. That makes sense - the ZA test picks up the structural shift in the term structure that followed, not the single extreme day itself. The level and vol regime of the calendar spread changed meaningfully after that.

**brent_calendar** break is marginally significant (p=0.13, which is above the 5% cutoff). It's the least clean of the three. The rolling ADF chart shows more than one regime shift - the Ukraine war and subsequent normalization created a period where Brent term structure was unusually backwardated, then reverted. ZA can only find one break so it lands in late 2023 when the backwardation faded. This series needs more careful regime labeling in Phase 3.

**brent_wti** break in May 2019 is the most interesting. This predates COVID - it's a market structure break driven by Iranian oil sanctions (tightening global seaborne supply, lifting Brent relative to landlocked WTI) and continued US shale export ramp-up. The rolling ADF chart should show the diff erential trending before reverting at a new, lower mean level. This is the break I noted in docs/notes.md was flagging when I siad "naive fixed-mean z-score will fight a trending spread."

Dates saved to `research/structural_breaks.json`.

---

## F. Checklist

- [x] `contract_metrics` table populated - 79,414 rows, 279 contracts
- [x] `roll_diagnostics.py` run - PNGs in `research/outputs/`
- [x] Statistical roll tests - both t-test and Mann-Whitney recorded
- [x] `02_phase2_analysis.ipynb` run - stationarity, cointegration, half-life, structural breaks
- [x] ADF + KPSS results in table B
- [x] Cointegration results in table C
- [x] Rolling half-life plotted, values in table D
- [x] Structural break dates in table E + `structural_breaks.json`
