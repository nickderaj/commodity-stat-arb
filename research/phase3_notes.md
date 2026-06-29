# Research Summary - Phase 1 to 3

_Period covered: 2018-01-02 to 2026-06-23_
_Spreads: wti_calendar (CL M1-M2), brent_calendar (BZ M1-M2), brent_wti (BZ-CL front-month)_

---

## Key Statistics

### Stationarity and Cointegration

| Spread         | ADF p  | KPSS p | Call  | Mean HL (days) | HL p25 | HL p75 |
| -------------- | ------ | ------ | ----- | -------------- | ------ | ------ |
| wti_calendar   | <0.001 | 0.010  | mixed | 24.6           | 15.5   | 31.3   |
| brent_calendar | <0.001 | 0.010  | mixed | 7.1            | 2.3    | 8.0    |
| brent_wti      | 0.007  | 0.010  | mixed | 4.9            | 2.9    | 5.8    |

"Mixed" = ADF rejects unit root (stationary in sub-periods) but KPSS also rejects (long-run mean not constant). Structural breaks cause the KPSS rejection - within any one regime, all three spreads are clearly stationary.

### Structural Breaks (Zivot-Andrews)

| Spread         | Break date | p-value | Context                                          |
| -------------- | ---------- | ------- | ------------------------------------------------ |
| wti_calendar   | 2020-04-27 | 0.020   | COVID demand collapse / WTI negative price event |
| brent_calendar | 2023-11-05 | 0.126   | Post-Ukraine energy normalization                |
| brent_wti      | 2019-05-31 | 0.002   | Iran sanctions / US export capacity shift        |

### Term Structure Regime (2018-2026)

| Spread         | Contango | Backwardation |
| -------------- | -------- | ------------- |
| wti_calendar   | 31%      | 69%           |
| brent_calendar | 17%      | 83%           |

Both crude benchmarks have spent most of 2018-2026 in backwardation (prompt premium), with contango periods mainly confined to COVID-era oversupply (2020) and occasional storage-driven episodes.

### Carry Fair-Value Model

Carry FV = -(storage + financing), where storage ~$0.45/bbl/month and financing ~5% × M2_price/12.

| Spread         | Mean carry FV | Raw spread HL | Excess spread HL | Excess ADF p |
| -------------- | ------------- | ------------- | ---------------- | ------------ |
| wti_calendar   | -$0.73/bbl    | 26.5d         | 27.9d            | <0.001       |
| brent_calendar | -$0.75/bbl    | 11.1d         | 12.0d            | <0.001       |

Finding: excess spread half-life is similar to raw spread half-life. The carry FV is a useful anchor for the "fair" level but the convenience yield fluctuations dominate the dynamics - stripping out the carry component doesn't make the spread more mean-reverting on a day-to-day basis.

### Roll-Window Microstructure

From Phase 2 analysis:

- Calendar spreads show ~25% larger daily moves in roll windows vs mid-cycle (statistically significant)
- Brent roll effect slightly larger than WTI despite WTI's physical delivery mechanism - suggests Goldman Roll index flow dominates
- brent_wti shows negligible roll effect (continuous contracts, no actual roll)

### Pair Screening Universe (Phase 2.5)

| Pair          | Score | Verdict | Note                                                      |
| ------------- | ----- | ------- | --------------------------------------------------------- |
| brent_wti     | 0.444 | PASS    | Best stability                                            |
| crack_321     | 0.259 | PASS    | Low stability due to 2022 energy crisis; needs vol filter |
| copper_silver | 0.036 | FAIL    | Control pair; no economic tether                          |

---

## Parameter Scan Results (Phase 3)

Signal: rolling z-score, entry |z| > threshold, exit |z| < exit threshold. No transaction costs.

| Spread         | Best lookback | Entry | Exit | Sharpe (no filter) | Sharpe (filtered) | Trades |
| -------------- | ------------- | ----- | ---- | ------------------ | ----------------- | ------ |
| wti_calendar   | 20d           | 1.5   | 0.50 | 0.071              | 0.216             | 125    |
| brent_calendar | 60d           | 2.0   | 0.75 | 0.351              | 0.229             | 46     |
| brent_wti      | 60d           | 1.5   | 0.50 | 0.452              | 0.894             | 80     |

Key observations:

1. **Filters help dramatically for brent_wti** (0.452 → 0.894): the vol filter prevented costly entries during COVID and Ukraine dislocations that trended rather than reverted.
2. **Filters hurt brent_calendar slightly** (0.351 → 0.229): the filter is too aggressive for this spread, suppressing profitable entries during high-vol backwardation episodes.
3. **wti_calendar is the weakest signal** overall - it compensates by being regime-selective (see below).

### Term Structure Regime Stratification

This is the most important Phase 3 finding:

| Spread         | Contango Sharpe | Backwardation Sharpe |
| -------------- | --------------- | -------------------- |
| wti_calendar   | +0.484          | -0.080               |
| brent_calendar | +0.008          | +0.322               |

**WTI calendar works in contango, fails in backwardation.** When M1 < M2 (storage economics dominant), deviations from the carry-implied level are anchored by physical arbitrage. In backwardation, convenience yield swings create trending behavior that the z-score signal fights.

**Brent calendar works in backwardation, is neutral in contango.** Brent spends 83% of the time in backwardation and the supply-premium dynamics mean-revert more cleanly than WTI's Cushing-driven dynamics.

Trading implication: WTI calendar entries should be gated on ts_regime == 'contango'. This converts the weak (0.216) all-regime signal into a cleaner trade.

---

## Top 2 Signal Candidates for Backtesting

### Candidate A - Brent-WTI with Vol Filter

**Why selected**: Highest Sharpe (0.894), clear ridge in parameter scan at lookback=60d (robust to entry threshold between 1.0-1.5), filters dramatically improve performance. 80 trades over 8.5 years is enough for meaningful statistics. The fastest half-life (4.9-10.7d) means capital is deployed efficiently.

**Config**: lookback=60d, entry=1.5, exit=0.5, vol regime filter ON, roll-window vol filter ON

**Outstanding risk**: structural break sensitivity (2019 shift). The 60d rolling mean catches up but there's a 2-month transition period after any structural shift where the z-score is unreliable.

### Candidate B - Brent Calendar (backwardation regime only)

**Why selected**: Second-highest Sharpe, very fast mean reversion (7.1d), clear regime-conditional behavior. The 0.229 all-regime Sharpe understates performance in its actual operating conditions (0.322 in backwardation, which accounts for 83% of the time).

**Config**: lookback=60d, entry=2.0, exit=0.75, vol filter ON, ts_regime gate = backwardation only

**Outstanding risk**: the convenience yield finding means the carry model can't predict when backwardation will persist vs revert. The 60d z-score is the best available proxy but has no forward-looking information.

---

## Outstanding Questions for Later Phases

1. **Transaction costs**: Phase 5 will apply commission + bid-ask spread costs. The crack spread (Phase 2.5 promoted) may become unviable at 28-day half-life with realistic transaction costs.

2. **Carry model vs raw spread**: the carry model doesn't improve the signal. But it might be useful as a regime indicator: when excess spread is very negative (spread much below carry FV), that's a strong entry signal for long spread. This should be tested separately.

3. **WTI calendar contango gate**: the regime-stratification result (Sharpe 0.484 vs -0.080) suggests gating entries on ts_regime. But this halves the number of available trading days (~31%). Need to check if the Sharpe improvement survives transaction costs and reduced opportunity.

4. **Parameter stability**: the lookback=60d result for brent_wti and brent_calendar looks robust (ridge visible in heatmap). The lookback=20d for wti_calendar is shakier (only marginally better than 30d or 60d). Phase 7 walk-forward will test this.

5. **Crack spread signals**: Phase 2.5 promoted crack_321 to a config. Its mean reversion (28.1d HL) is slower than the calendar spreads. Z-score signal needs testing but requires ingesting RB=F and HO=F data first.
