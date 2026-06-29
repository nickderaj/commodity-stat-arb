# Pair Screening Report

Period: 2015-01-01 to 2025-01-01  |  Min score for PASS: 0.25

Composite score = (1 - coint_p) x HL_suitability x stability

- coint_p: Engle-Granger p-value for 2-leg pairs; ADF p-value for n-leg
- HL suitability: 1.0 in 3-30d band, decays outside
- stability: fraction of rolling 252-day windows where ADF rejects unit root

## Results

| Pair | Type | Corr | EG p | beta | ADF p | KPSS p | Mean HL | HL p25 | HL p75 | Stab | Score | Verdict |
|------|------|------|------|------|-------|--------|---------|--------|--------|------|-------|---------|
| Brent-WTI Cross-Market | cross_market | +0.91 | 0.000 | 1.01 | 0.000 | 0.044 | 10.7d | 4.9d | 13.4d | 44% | 0.444 | **PASS** |
| 3-2-1 Crack Spread | crack | +0.74 | N/A | N/A | 0.035 | 0.010 | 28.1d | 10.0d | 31.9d | 27% | 0.259 | **PASS** |
| Platinum-Palladium (PGMs) | ratio | +0.52 | 0.007 | 0.02 | 0.001 | 0.014 | 30.7d | 15.8d | 36.9d | 9% | 0.090 | **FAIL** |
| Corn-Wheat Feed Grains | ratio | +0.58 | 0.002 | 0.74 | 0.000 | 0.086 | 42.6d | 15.9d | 32.6d | 15% | 0.086 | **FAIL** |
| Copper-Silver (control) | ratio | +0.36 | 0.149 | 0.13 | 0.051 | 0.010 | 44.6d | 16.0d | 48.3d | 8% | 0.036 | **FAIL** |
| Gold-Silver Ratio | ratio | +0.79 | 0.172 | 75.72 | 0.061 | 0.010 | 57.2d | 19.9d | 42.5d | 4% | 0.003 | **FAIL** |
| Soybean Crush Spread | crush | +0.75 | N/A | N/A | 0.069 | 0.010 | 59.0d | 19.3d | 52.6d | 9% | 0.003 | **FAIL** |
| Gold-Platinum | ratio | +0.57 | 1.000 | 0.41 | 0.994 | 0.010 | 88.5d | 28.7d | 78.4d | 2% | 0.000 | **FAIL** |

## Promoted Pairs

Pairs with score >= 0.25 promoted to SpreadDefinition configs:

- `brent_wti` (Brent-WTI Cross-Market) - score 0.444, mean HL 10.7d
- `crack_321` (3-2-1 Crack Spread) - score 0.259, mean HL 28.1d

## Economic Notes

- 2-leg pairs: EG test fits OLS hedge ratio. Spread = leg1 - beta * leg2.
- Crack spread: 3-2-1 ratio (2x RBOB + 1x HO - 3x CL), gasoline/heating oil converted from $/gal to $/bbl (*42).
- Crush spread: per-bushel gross processing margin. ZM converted by 0.02375 short tons/bushel, ZL by 10.7 lbs/bushel.
- Copper-silver is the control pair - no strong economic tether expected.