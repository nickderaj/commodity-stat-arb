# Phase 2.5 Notes - Pair Screening

## _ These are rough notes after running the pair screener over 2015-2025 data _

> See `research/pair_screener.py` for methodology. Short version: rolling correlation pre-filter, then Engle-Granger + Johansen for 2-leg pairs, ADF + KPSS on the spread, AR(1) half-life, rolling 252-day ADF stability. Composite score = (1 - coint_p) x HL_suitability x stability.

---

## A. What Passed (and Why)

| Pair | Score | Verdict | Key stats |
| ---- | ----- | ------- | --------- |
| Brent-WTI | 0.444 | PASS | EG p=0.000, HL 10.7d, stability 44% |
| 3-2-1 Crack | 0.259 | PASS | ADF p=0.035, HL 28.1d, stability 27% |

**Brent-WTI** is the cleanest result. EG p basically 0, beta=1.01 (near-perfect 1:1 parity as expected), mean HL of 10.7 days is right in the sweet spot. Stability at 44% is decent -- it means roughly half of rolling 1-year windows show stationary behavior, which is honest given the 2020 COVID crash and 2022 Ukraine regime shifts.

**Crack spread** is a borderline pass. The ADF rejects at 5% (p=0.035) and the mean HL of 28.1d is just inside the tradeable band. The drag is stability at 27% -- the 2022 European energy crisis blew refining margins to ~$50-60/bbl, way outside the normal $10-20/bbl range. That's 2 years of rolling windows failing the ADF. Remove 2022 from the sample and it would look a lot cleaner. The economic tether is real: refiners will shut if margins go below variable cost, and competition caps the upside. This needs the vol filter from Phase 3 to suppress signals during those extreme regimes.

---

## B. What Failed (and Why It Makes Sense)

### Gold-Silver
This is the surprising one. Classic "gold-silver ratio" trade, talked about in every commodities textbook, and it outright fails:
- EG p = 0.172 (not cointegrated over this 10-year window)
- Mean HL = 57.2d (way too slow)
- Stability = 4%

The ratio went from ~65 in 2015 to ~120 during COVID in 2020, then back to ~85. That's a multi-year trending move, not a 10-30 day reverting spread. The mean reversion for gold-silver operates on timescales of months to years, not days. Hedge funds running this trade are doing it on a quarterly horizon, not a daily bar strategy.

The textbook cointegration holds over 50+ year samples (both are monetary stores of value). Over 10 years with a structural regime shift (March 2020 when the ratio hit 120 -- unprecedented in modern history), the test doesn't see enough cycles to confirm the relationship.

Take-away: the pair is real but the frequency doesn't match our strategy. Worth revisiting if we extend the sample to 2000-2025.

### Gold-Platinum
EG p = 1.000 (basically the worst possible result). The spread isn't even close to stationary. Makes sense: gold is monetary/financial, platinum is industrial (auto catalysts, jewelry, green hydrogen). Their demand drivers have diverged structurally since 2015 -- platinum was at a premium to gold historically but has traded at a significant discount since palladium ate its catalysis market share. Not a stat-arb candidate.

### Platinum-Palladium
Interesting failure. ADF p = 0.001 on the spread (very stationary!) but stability = 9%. How?

The series-level test (full sample) shows cointegration, but the rolling windows don't. The 2018-2022 period saw palladium go from $800 to $3000+ (palladium supply squeeze: Russia is 40% of supply, plus ICE emissions regulations driving gasoline car catalysts). That price divergence from platinum was a structural shift, not noise. The pair looked cointegrated in 2015-2017 and in 2022-2024 but not in between. The instability score correctly captures this.

### Soybean Crush
Mean HL = 59d (too slow) and stability = 9%. The crush margin has strong seasonality (harvest vs non-harvest) and USDA crop report shock sensitivity. The processing margin mean-reverts but at a seasonal frequency, not a few days. For a daily bar strategy this is the wrong instrument -- the crush trade needs to be run seasonally.

### Corn-Wheat
EG p = 0.002 (actually cointegrated at 5%) but HL = 42.6d and stability = 15%. Close to borderline but the half-life is too slow and stability is low. Grain substitution at the feed-buying level happens quarterly, not weekly. ADF rejects on the full sample because they're broadly tethered over 10 years, but the spread can trend for months before reverting.

---

## C. The Control Worked

**Copper-Silver** scored 0.036 (FAIL). 

Correlation of 0.36 (low vs 0.91 for Brent-WTI). EG p = 0.149 (not cointegrated). HL = 44.6d (too slow). Stability = 8%. Nothing works.

Copper is pure industrial -- construction, EV motors, power grids. Silver is half-monetary (a risk asset that behaves like gold during panics) and half-industrial (solar panels, electronics). Their correlation comes from broad commodity risk-on/risk-off, not from any substitution or processing relationship. The screener correctly rejects it.

This is exactly what you want from a control: clear rejection, and the rejection is explainable. If the screener had passed copper-silver, it would mean the threshold is miscalibrated.

---

## D. Composite Score Formula -- Does It Work?

The formula: `(1 - coint_p) x HL_suitability x stability`

Overall it discriminates reasonably well. The separation between PASS and FAIL is about 2x (0.444/0.259 vs 0.090 or below). A few observations:

1. **Stability is the dominant kill factor.** Platinum-palladium has ADF p=0.001 but still fails because stability=9%. This is actually correct behavior -- a pair that looks cointegrated in aggregate but fails in most sub-periods is a data mining artifact, not a tradeable relationship.

2. **The HL suitability penalty is aggressive.** Gold-silver at 57d gets hl_score = max(0, 1 - (57-30)/30) = 0.10. Combined with low stability, the score collapses. If I wanted to include longer-horizon pairs, I'd need a separate strategy class with different entry/exit timescales.

3. **n-leg pairs use ADF p as coint_p proxy.** This is a weaker signal than EG for 2-leg pairs because ADF on the spread doesn't tell you if the weights are data-fit or economically imposed. For crack and crush, the economic weights are fixed, so the ADF result is more credible (not an in-sample fit).

---

## E. What Gets Promoted

Two pairs make the cut at score >= 0.25:
- `brent_wti` -- already in config, validated again here
- `crack_321` -- new config added

The crack spread needs:
1. RB=F and HO=F data ingested (currently not in DB -- need a yfinance ingest pass)
2. Vol filter in Phase 3 to suppress entries during extreme regimes
3. Separate note that the 2022 regime shift should be treated as a structural break

The other pairs aren't dead ends forever:
- **Gold-Silver**: reconsider on a 25+ year sample, or for a different (monthly/quarterly) strategy
- **Corn-Wheat**: might work seasonally adjusted; the ADF passes on the full sample
- **Platinum-Palladium**: might be tradeable in the 2022-present "normalized" sub-regime

---

## F. Checklist

- [x] `pair_screener.py` runs over all 8 candidate pairs
- [x] `research/stats.py` extracted with shared stat functions (ADF, KPSS, EG, Johansen, AR1 HL, ZA, rolling stability)
- [x] `screening_report.md` generated with ranked table
- [x] Brent-WTI confirmed PASS (was already in Phase 2)
- [x] Crack spread PASS (new, score 0.259)
- [x] Copper-silver correctly FAIL (control test works)
- [x] `config/crack_321.yaml` added with price_multiplier fields
- [x] `config/schema.py` updated with `price_multiplier: float = 1.0` on LegConfig
- [x] All 4 existing configs still load correctly after schema change
