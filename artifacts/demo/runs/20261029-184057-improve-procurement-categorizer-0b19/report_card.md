# Procurement Categorizer v3: improve run

**Gate: passed, deployed.** beats the live version (0.655 vs 0.647) and passes every threshold.

- Corrections added to the training set only: 95
- Retrained: A-07 (validation 0.617 → 0.624), A-05 (validation 0.631 → 0.632)
- Shipped as: H(A-05→K-11)
- Fixed benchmark: the sealed test set of run p2b-procurement-d (the one v2 was scored on); corrections never enter it.

## Sealed test set

| | v2 (live before) | v3 (this run) |
|---|---|---|
| macro_f1 | 0.647 | 0.655 |
| records | 3368 | 3368 |
| answered by |  | A-05 68% / K-11 32% |
| cost per 1M predictions | | $23.8538 |

## Per class (this run, sealed test set)

| class | precision | recall | n |
|---|---|---|---|
| Aircraft, Ships/Submarines & Land Vehicles | 0.36 | 0.27 | 15 |
| Clothing, Textiles & Subsistence S&E | 0.82 | 0.90 | 186 |
| Electronic & Communication Equipment | 0.56 | 0.67 | 181 |
| Electronic & Communication Services | 0.20 | 0.14 | 21 |
| Equipment Related Services | 0.42 | 0.62 | 164 |
| Facilities & Construction | 0.67 | 0.58 | 285 |
| Human Capital | 0.66 | 0.59 | 86 |
| IT | 0.81 | 0.76 | 285 |
| Industrial Products & Services | 0.49 | 0.56 | 285 |
| Medical | 0.83 | 0.86 | 159 |
| Miscellaneous S&E | 0.74 | 0.70 | 110 |
| Office Management | 0.81 | 0.76 | 250 |
| Professional Services | 0.61 | 0.63 | 285 |
| Research and Development | 0.83 | 0.84 | 146 |
| Security and Protection | 0.67 | 0.66 | 102 |
| Sustainment S&E | 0.75 | 0.64 | 285 |
| Transportation and Logistics Services | 0.82 | 0.66 | 285 |
| Travel & Lodging | 0.87 | 0.88 | 154 |
| Weapons & Ammunition | 0.68 | 0.69 | 84 |
