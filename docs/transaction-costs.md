# Transaction Costs

Costs are never hidden in a single haircut. Every simulated entry and exit
records commission, bid/ask spread, slippage, FX conversion, optional tax, and
minimum commission separately. Rates and basis-point assumptions are immutable
experiment parameters.

The predefined `SMALL_ACCOUNT_NIS_2000` research profile demonstrates minimum
fee, FX, and whole-share constraints around a NIS 2,000 notional. It is not a
broker tariff and must not be presented as one. Its defaults are generic,
replaceable experimental assumptions:

- 0.1% commission with a NIS 10 minimum;
- 10 bps spread and 5 bps slippage;
- 50 bps FX conversion when required;
- no assumed tax;
- no fractional shares.

The simulator rejects negative costs and margin-like negative cash. Tax remains
a reporting-layer input because actual liability depends on jurisdiction,
account, loss offsets, and operator-specific facts.
