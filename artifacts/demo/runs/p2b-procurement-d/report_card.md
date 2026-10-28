# Report card: Procurement Categorizer

Run `p2b-procurement-d`

## Winning strategy

**H(A-07→K-11)** (family H): cheapest candidate that meets the macro_f1 target of 0.60 on validation (0.617); wrapped in a cascade that answers 65% A-07, 35% K-11 (+0.045 on the shared sample).

Planner (llm): Trying rules (J), TF‑IDF (A), local embeddings with linear heads (C), and embedding kNN/centroids (I) because short keyword‑heavy descriptions favor lexical and semantic matching with low latency.; prompted Nemotron (K) added so the cascade can be evaluated

Frontier alternatives:

- recommended: A-07 — macro_f1 0.617 on validation, $0.0002 per 1M predictions, p50 0.23 ms
- most_accurate: A-05 — macro_f1 0.631 on validation, $0.0015 per 1M predictions, p50 0.45 ms
- cheapest: J-01 — macro_f1 0.403 on validation, $0.0001 per 1M predictions, p50 0.01 ms

## Sealed test set (true labels)

- macro_f1: **0.647** on 3368 records
- macro precision 0.652, macro recall 0.649, macro F1 0.647
- validation 0.671 vs sealed 0.647 (sealed is lower, as expected: picking among many candidates inflates validation)

| Class | Precision | Recall | Support |
|---|---|---|---|
| Aircraft, Ships/Submarines & Land Vehicles | 0.364 | 0.267 | 15 |
| Clothing, Textiles & Subsistence S&E | 0.789 | 0.903 | 186 |
| Electronic & Communication Equipment | 0.529 | 0.696 | 181 |
| Electronic & Communication Services | 0.118 | 0.095 | 21 |
| Equipment Related Services | 0.420 | 0.628 | 164 |
| Facilities & Construction | 0.671 | 0.572 | 285 |
| Human Capital | 0.662 | 0.616 | 86 |
| IT | 0.815 | 0.786 | 285 |
| Industrial Products & Services | 0.498 | 0.530 | 285 |
| Medical | 0.797 | 0.862 | 159 |
| Miscellaneous S&E | 0.721 | 0.682 | 110 |
| Office Management | 0.806 | 0.764 | 250 |
| Professional Services | 0.634 | 0.621 | 285 |
| Research and Development | 0.813 | 0.836 | 146 |
| Security and Protection | 0.657 | 0.657 | 102 |
| Sustainment S&E | 0.762 | 0.628 | 285 |
| Transportation and Logistics Services | 0.818 | 0.632 | 285 |
| Travel & Lodging | 0.873 | 0.890 | 154 |
| Weapons & Ammunition | 0.644 | 0.667 | 84 |

## Nemotron Ultra zero-shot baseline

On the same 298 sealed records: Nemotron Ultra macro_f1 0.456 vs specialist 0.627.
Baseline p50 latency 1238 ms, $806.78 per 1M predictions.

Agreement with Nemotron Ultra (agreement, not accuracy): 51.3% on 298 records.

## Seed error bars (3 seeds, validation)

- A-07: 0.587 ± 0.006
- A-05: 0.603 ± 0.003

## Speed and cost

- latency p50 0.232 ms, p99 673.797 ms
- throughput n/a items/s; model size n/a MB
- $25.8745 per 1M predictions; formula: sum over stages of (share of items reaching the stage × its cost)
- at 2,000,000 records/month (task card): Nemotron Ultra $19,363/year vs specialist $620.99/year (cost per 1M predictions × monthly_volume × 12 / 1e6 (marginal cost; the Serverless endpoint is shared by all specialists))
- cascade A-07 → K-11: answered by A-07 65.2% / K-11 34.8% on validation (used)
- on the sealed test: A-07 64.1% / K-11 35.9%

## Would more data help?

- 10% of training data: 0.423
- 40% of training data: 0.552
- 100% of training data: 0.617

## Known weaknesses

- Professional Services confused with Facilities & Construction (32 validation errors): Service contracts with site-specific work keywords (exploration, survey, installation, field testing, bridge, dam, park) are misclassified as construction due to overlapping location and activity terminology.
- Facilities & Construction confused with Professional Services (27 validation errors): Facilities records using service-oriented language (management support, planning, technical data, restoration services, environmental support) are misclassified as professional services due to the prevalence of 'services' and 'support' terms.
- Sustainment S&E confused with Industrial Products & Services (26 validation errors): Sustainment spare parts and components (pumps, bearings, wheels, clamps) with NSNs, part numbers, and hardware-specific nomenclature resemble industrial product purchases.
- Industrial Products & Services confused with Sustainment S&E (21 validation errors): Industrial product procurements (gear assemblies, fuel systems, filters, manifolds, coolant drums) with assembly/part descriptors, NSNs, and quantities mimic sustainment spare-part orders.

## Data sources

- usaspending_contracts (https://api.usaspending.gov/api/v2/search/spending_by_award/): USAspending.gov data: free to copy, adapt, redistribute, commercial or non-commercial, subject to the Limitation on Permissible Use of Dun & Bradstreet data; 17,732 rows. Cite: USAspending.gov, U.S. Department of Treasury, Bureau of the Fiscal Service, https://www.usaspending.gov. Accessed 27 October 2026.
