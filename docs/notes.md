# Brent-WTI Mean Reversion

## _ These are my rough notes _

> We are trading the statistical relative value (stat-arb): two (or more) instruments are tied together by an economic relationship, therefore their price difference (spread) is mean-reverting

---

## The Core Idea

The strategy rests on one statistical property: **the spread is stationary (mean-reverting) even though the individual legs are not** - this is what co-integration formalises.

Two random walks (oil prices) can be individually non-stationary, yet have a linear combination that is stationary. The stationary combination is our trade-able signal.

---

## Calendar Spreads

> We capture the calendar spreads by longing one contract month and shorting the other, e.g. WTI front-month (M1) minus second-month (M2)

### What causes the "fair spread"?

The main reason for this spread in commodities is the cost-of-carry. The relationship between two futures expiries of a storable commodity is pinned by the cost-of-carry / storage arbitrage.

The fair spread can be calculated by the following:

$$
F(T_2) ≈ F(T_1) × (1 + r·Δt) + storage·Δt − convenience_yield·Δt
$$

- _r (financing)_: carrying a long futures position has an implicit finaancing cost
- _storage_: physical storage costs money (tank, rent, insurance). For crude, this is roughly $0.30 - 0.60 /bbl/month
- _convenience yield_: the benefit of holding the physical commodity now (a refiner that can't run dry will pay up for prompt barrels). This is the unobservable, volatile term that makes the whole thing variable.

Or in simple english, the calendar spread is essentially:

$$
M_1 - M_2 ≈ ConvenienceYield - Storage - Financing
$$

And we have two scenarios: Contango (M1 < M2, upward curve) and Backwardation (M1 > M2, downward curve).

### What causes the mean reversion / what pushes it apart

The "tether" that keeps them apart is the cash-and-carry arbitrage - if the spread strays too wide relative to actual storage economics, people will buy prompt and sell forward, store the barrels and lock the carry. The physical arbitrage caps how far the spread can deviate, **as long as storage is available.**

The "shocks" that push them apart are:

1. Roll pressure (the "Goldman Roll"): Large passive long-only commodity index funds (e.g. S&P GSCI, BCOM trackers) hold front-month exposure and mechnically roll from M1 -> M2 on a fixed calendar (typically the 5th - 9th business day of the month). This predictable, price-insensitive flow depresses M1 and lifts M2 during the roll window.
2. Inventory Shocks: EIA crude inventory reports (especially Cushing stocks), refinery outages, hurricanes in the Gulf
3. Seasonal Demand: E.g. driving season in the summer, heating season in the winter
4. Producer/Refiner hedging flows

---

## Inter-Commodity / Quality-Location Spread

> We capture inter-commodity spreads by longing Brent front-month and shorting WTI front-month (or the reverse). They are both light sweet crude benchmarks, so they are strongly co-integrated.

### The Tether

Brent & WTI are close substitutes for refiners. Large differences between them would make one grade uneconomic vs the other, drawing them back together due to physical substitution and trade flows.

The spread reflects structural differentials:

- Quality: small API gravity / sulphur differences.
- Location & Logistics: WTI is priced at Cushing, Oklahoma (landlocked), Brent is waterborne (North sea) so it tracks global seaborne demand differently. Getting WTI to the coast depends on pipeline capacity (Cushing -> US Gulf).
- US Export Dynamics: The spread regime shifted structurally after the 2015 repeal of the US Crude Export Ban - WTI became globally deliverable, tightening the link.
- Geopolitical Risk Premium: Brent carries more of the world's supply-disruption premium (Meddle East, Russia), so it widens versus WTI during global supply scares.

### The Shocks

- Cushing pipeline bottlenecks (the spread blew out to ~$25 in 2011 when Cushing was glutted & landlocked).
- US Shale supply surges (local WTI glut -> WTI discount widens).
- Global supply shocks that hit seaborne Brent (2022 Russia - Ukraine war)

### Important Nuance

The Brent-WTI spread has regime shifts and structural breaks (2011 Cushing glut, 2015 export-ban repeal). Therefore, the mean is **not** constant. This is why the plan's structural-break testing (Zivot-Andrews) and rolling/regime-aware Z-Scores matter - a naive fixed-mean Z-score will fight a trending spread.

---

## Why these edges still exist

If this is a known, well traded strategy, why do the edges still exist today? Why is not arbitraged to zero?

1. Storage is finite and costly: the cash-and-carry that caps calendar spreads requires physical tanks. When Cushing fills up (April 2020, WTI went negative), the arbitrage cannot be executed & the cap breaks causing the spread to blow out far past the "fair" assumed value above. Limited storage = limited arbitrage.
2. Convenience yield is unobservable & stochastic: you can't directly hedge it, so the "fair" spread is a moving target.
3. Capital & Margin constraints: spread positions still consume margin. During stress, margins spike and forced deleveraging widens dislocations when the trade looks best (e.g. limits-to-arbitrage). _The market can stay irrational longer than you can stay solvent._
4. Flow is price-insensitive: index rolls happen regardless of value. That flow is a cost to the index funds and a recurring opportunity, but capturing it requires being on the right side of a crowded trade.

### So is it still tradeable?

1. The frictions above are permanent (storage limits, pipeline capacity, fianncing).
2. The roll flows are calendar-predictable.
3. The convenience yield genuinely fluctuates.

Therefore, it's still real & trade-able. However, the real edge in crude spreads lives at intraday/tick resolution and is contested by HFT and macro funds with superior data, execution and capital. Daily bar data will capture the shape of the inefficiency but the magic Sharpe requires a very quick trading algorithm with the most up to date information.

### Possible Pairs

| Pair / spread                         | Type         | Economic tether                                      | Free data?              |
| ------------------------------------- | ------------ | ---------------------------------------------------- | ----------------------- |
| **Brent–WTI**                         | Cross-market | Same product, two locations                          | ✅ `BZ=F`, `CL=F`       |
| **Gold–Silver** (ratio)               | Ratio        | Both monetary/precious; classic GS ratio reverts     | ✅ `GC=F`, `SI=F`       |
| **Crude–Gasoline–HeatingOil** (crack) | Crack spread | Refining economics: input vs outputs                 | ✅ `CL=F`,`RB=F`,`HO=F` |
| **Soybeans–Soymeal–Soyoil** (crush)   | Crush spread | Processing economics                                 | ✅ `ZS=F`,`ZM=F`,`ZL=F` |
| **Gold–Platinum**                     | Ratio        | Both precious; substitution                          | ✅ `GC=F`, `PL=F`       |
| **Platinum–Palladium**                | Ratio        | Both autocatalyst PGMs; substitution                 | ✅ `PL=F`, `PA=F`       |
| **Corn–Wheat**                        | Ratio        | Substitutable feed grains                            | ✅ `ZC=F`, `ZW=F`       |
| **NatGas calendar**                   | Calendar     | Storage + strong seasonality                         | ⚠️ needs monthlies      |
| **Copper–Silver**                     | Ratio        | _Weak:_ copper pure-industrial, silver half-monetary | ✅ `HG=F`, `SI=F`       |

Copper-Silver is likely to fail, but worth testing that the cointegration screening system flags it.

### The risks involved

| Trade           | Breaks when…                                               | Observable warning                                          |
| --------------- | ---------------------------------------------------------- | ----------------------------------------------------------- |
| Calendar spread | Storage fills (cap on arbitrage vanishes), demand collapse | Cushing inventory near capacity - extreme contango          |
| Calendar spread | Roll-window vol spike overwhelms the edge                  | Realised vol > 90th pct in roll window                      |
| Brent–WTI       | Structural regime shift (new pipeline, policy change)      | Zivot-Andrews break; rolling mean trending, not reverting   |
| Brent–WTI       | Global supply shock decouples seaborne Brent               | Geopolitical event; spread trends without reverting         |
| Any spread      | Cointegration silently dies                                | Rolling ADF p-value drifts up; half-life blows out > 30–60d |

The strategy filters (vol, liquidity, roll-window & cointegration-health) exist to protect from these risks.

### The screening pipeline

1. **Correlation pre-filter**: rolling correlation of returns. High correlation ≠ cointegration, but very low correlation rules a pair out fast.
2. **Cointegration test:** Engle-Granger (2-leg) and/or Johansen (n-leg, gives hedge ratio β). Record p-value and β.
3. **Stationarity of the spread:** ADF + KPSS on the β-weighted spread.
4. **Half-life of mean reversion:** AR(1) regression; keep pairs with half-life in a tradeable band (~3–30 days).
5. **Stability:** rolling ADF / rolling co-integration to confirm the relationship isn't a single-period artefact; flag structural breaks.
6. **Rank & report:** a scorecard table (one row per pair), sorted by a composite score (cointegration confidence × half-life suitability × stability). Top pairs run through the full engine.
