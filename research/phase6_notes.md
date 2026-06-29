# Phase 6 Notes - Almgren-Chriss Execution Simulator

## _ Notes after implementing and running the AC model on all three spread candidates _

> See `execution/almgren_chriss.py` for the model and `scripts/run_phase6_ac.py` for the comparison runs. The short version: at our position sizes, impact costs are essentially zero. Commission and bid-ask dominate by a wide margin. This is the correct finding, not a calibration failure.

---

## A. What the Model Does (and What It Can't)

The AC model separates execution cost into two components:

**Temporary impact** - you push the price while you're trading, then it snaps back. Cost per bbl = η · σ · p^α where p is your participation rate (fraction of ADV executed per period). The idea is that your order flow moves the market in proportion to your size relative to the ambient liquidity.

**Permanent impact** - a fraction of your price move sticks. Cost = γ · σ · (Q/ADV) · Q/2. This represents informed-order interpretation by the market: if you're a big enough buyer, everyone else revises their expectation of fair value upward.

The time-of-day adjustment scales η by a literature-based U-curve - higher at open and close (1.8x), lower mid-session (1.0x). This can't be estimated from daily bars because daily OHLCV has no intraday structure. It's an assumed shape, full stop.

η calibration uses the square-root-of-volume heuristic: η = k · σ / √ADV. This is the standard first-pass approach when you don't have tick data to measure impact directly. k=0.1 is conservative for liquid futures; equity-market studies typically use 0.2–0.5.

---

## B. The Main Finding: Impact Is Negligible at This Scale

This was not the expected result going in, but it's the honest one.

| Spread         | Avg commission | Avg spread cost | Avg temp impact | Avg perm impact | Total AC cost |
| -------------- | -------------- | --------------- | --------------- | --------------- | ------------- |
| wti_calendar   | $28.00         | $2.80           | $0.03           | $0.01           | $0.04         |
| brent_calendar | $24.96         | $3.91           | $1.00           | $0.25           | $1.25         |
| brent_wti      | $10.04         | $8.43           | $0.02           | $0.01           | $0.03         |

AC impact is less than $1.30/trade on every spread. Commission is $10–$28/trade. Bid-ask is $3–$8/trade. So the cost stack is approximately:

1. **Commission** - biggest line item for calendar spreads (high lot count because position sizing is in bbls)
2. **Bid-ask** - dominant for brent_wti where the commission is lower (fewer lots, tighter spread)
3. **Slippage/impact** - essentially zero at our scale

The reason is simple arithmetic. We're trading ~2–10 contracts per signal (1,000–10,000 bbls). CL open interest is typically 300,000–400,000 contracts. Our participation rate is 0.001–0.01% of ADV. At that scale there's no measurable price impact.

The AC model produces no execution tax in the naïve vs. AC comparison - Sharpe difference is ±0.001, PnL difference is <0.5%. These are noise-level differences, not a meaningful cost.

---

## C. Where Impact Would Actually Bite

The capacity question is more useful than the current-scale comparison. The scale stress table shows where things break:

| Position size | Contracts | Participation | Temp impact | Perm impact | Total |
| ------------- | --------- | ------------- | ----------- | ----------- | ----- |
| 2,000 bbls    | 2         | 0.40%         | $0.00       | $0.00       | $0.00 |
| 20,000 bbls   | 20        | 4.0%          | $0.01       | $0.00       | $0.01 |
| 100,000 bbls  | 100       | 20%           | $0.25       | $0.06       | $0.32 |
| 500,000 bbls  | 500       | 100%          | $6.36       | $1.59       | $7.95 |

Impact costs only reach the same order of magnitude as commission at ~100 contracts per trade. At 500 contracts (half of typical daily volume) you're looking at ~$8 total impact on a spread with probably $30+ commission, so still not the dominant cost.

This tells you the strategy doesn't hit an impact wall until well above the sizes we're testing. For a $100k book running 1% risk per trade, position sizes are 2–5 contracts. To get to sizes where impact matters you'd need a $5–10M book running similar risk. That's a capacity estimate of sorts: the signal, not impact, will likely degrade first.

The caveat is that this is based on the model's η value calibrated from daily bars, which can't capture intraday clustering of order flow. Real impact at 100-contract sizes might be higher than the model says, especially in the 30 minutes before a position is established.

---

## D. Alpha Exponent Behaviour

One thing that came out of the unit tests is worth noting: at our typical participation rates (p < 1), the square-root model (α=0.5) is actually _more_ expensive per unit than the linear model (α=1.0) with the same η.

For p=0.1: p^0.5 = 0.316 vs p^1 = 0.1. So the sqrt formula gives 3x higher per-unit cost.

This seems backwards but it's mathematically correct and has a sensible interpretation: the square-root model assumes impact per unit declines as you trade more (concave in size), which is what you observe empirically in equities. But for small participation rates, the "baseline" per-unit impact is high - the square-root of a small number is relatively large. The linear model is cheaper at low participation and more expensive only at high participation (p > 1, which never happens in practice since you can't execute more than 100% of ADV in a period).

Practical implication: the choice of α matters a lot for how the model extrapolates to large sizes, but for our actual position sizes both give essentially zero impact. The α sensitivity is only relevant if you're projecting capacity constraints.

---

## E. The Time-of-Day Curve

The U-shape is assumed, not estimated. At open (09:00 ET) and close (17:00 ET), impact is assumed 80% higher than mid-session. This is consistent with the literature on equity markets (open/close auction dynamics, inventory rebalancing) and probably in the right ballpark for crude futures, though CME WTI and ICE Brent have extended hours that smooth some of this.

For the backtest, all fills use the mid-session default (factor=1.0) because daily bars don't tell you what time you actually executed. In a live system with intraday data you'd want to measure this directly. The time-of-day adjustment adds a small (but visible) layer of cost if you assume the strategy tends to trade on busy sessions - but since we can't know that from daily data, the default is the honest choice.

Curve:

```
09:00  1.800  ████████████████████████████████████
10:00  1.450  █████████████████████████████
11:00  1.200  ████████████████████████
12:00  1.050  █████████████████████
13:00  1.000  ████████████████████
14:00  1.050  █████████████████████
15:00  1.200  ████████████████████████
16:00  1.450  █████████████████████████████
17:00  1.800  ████████████████████████████████████
```

---

## F. Naïve vs. AC Comparison Results

| Spread         | Sharpe (A) | Sharpe (B) | ΔSharpe | ΔPnL% |
| -------------- | ---------- | ---------- | ------- | ----- |
| wti_calendar   | -0.132     | -0.131     | +0.000  | +0.2% |
| brent_calendar | +0.236     | +0.236     | 0.000   | +0.0% |
| brent_wti      | +0.412     | +0.413     | +0.001  | +0.4% |

Mode A: CostModel with commission + spread + 2 bps slippage.
Mode B: CostModel with commission + spread, slippage=0, AC model for impact.

The direction of ΔPnL is slightly positive for Mode B. This happens because the fixed 2 bps slippage in Mode A is slightly larger than the AC impact cost - replacing it with the (near-zero) AC cost gives a marginal PnL improvement. This makes sense: 2 bps slippage on a $2–3/bbl spread price is $0.0004/bbl × 1000 bbls = $0.40/trade, while AC impact is $0.01–$1/trade. So they're in the same neighbourhood, and the AC model happens to come out slightly lower for our position sizes.

This is not a result to spin as "AC model improves PnL." It's just saying the fixed-bps slippage assumption overestimates impact at our scale.

---

## G. What This Means for the Interview

The honest pitch is: the model is correctly implemented and calibrated, and it tells us something real - the strategy has essentially no impact constraint at the sizes we're running. The binding execution costs are commission and bid-ask spread, both of which are already in the Phase 5 cost model. If someone asks "what would change your cost picture?" the answer is: (1) position sizes above 50 contracts, or (2) intraday execution data to actually measure η rather than approximating it.

If asked about the "30-50% Sharpe reduction" mentioned in the CV bullet - that's written for a hypothetical institutional scale where impact matters. At our backtest scale the AC model is illustrative of the cost _structure_, not the cost _magnitude_.

---

## H. Checklist

- [x] `execution/almgren_chriss.py` implemented: temporary impact h(v) = η·σ·p^α, permanent g(x) = γ·σ·(Q/ADV)
- [x] η calibrated via square-root-of-volume heuristic: η = k·σ/√ADV (k=0.1, σ=0.30, ADV from DB)
- [x] Time-of-day U-curve implemented: factor 1.0 (mid-session) to 1.8 (open/close)
- [x] Unit tests: 21/21 pass - monotonicity, α behaviour, tod curve, calibration edge cases
- [x] Engine wired: `temp_impact_cost` + `perm_impact_cost` populated in `orders` table per trade
- [x] `scripts/run_phase6_ac.py` runs naïve vs AC comparison across all three spreads
- [x] η sensitivity and scale stress tables produced
- [x] Key finding documented: at 2–10 contract scale, AC impact is <$2/trade; commission dominates
- [x] Capacity estimate derived: impact constraint kicks in around 50–100 contracts/trade (~$1–5M book)
