# Trends Intelligence Lab

Raw macro observations and derived signals are separate immutable records.
Version `deterministic-macro/1` exposes latest value, rolling mean, linear
endpoint slope, z-score anomaly, and a simple rising/falling/stable classifier.
Short, medium, and long horizons use separate input windows, so their states may
legitimately disagree.

Trend families include inflation, interest rates, FX, housing/construction,
tourism, credit, consumer demand, government spending, energy cost, and a
technology-capex placeholder. Mechanism mappings are candidates such as
`financing_cost`, `credit_demand`, `import_cost`, and `consumer_demand`; they do
not encode BUY/SELL direction or a causal conclusion.

Divergences preserve two source trend IDs, an explicit description, observation
time, and provenance. The system does not collapse CPI/wage, rates/FX, or
housing-volume/price disagreement into one score.

Eight structural-trend names are defined: AI infrastructure, cybersecurity,
defense spending, energy transition, demographic changes, housing supply,
cloud capex, and the semiconductor cycle. A structural candidate can be stored
only as curated and with evidence links. v0.11 makes no automatic structural
trend detection claim.

Replay snapshots include only macro releases, calculated trends, and curated
structural candidates visible at the historical cutoff. Research contexts carry
the same item-level provenance. Deterministic baselines are comparison tools,
not forecasts or recommendations.
