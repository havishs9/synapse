# Report card: Support Ticket Router

Run `p2b-support-c`

## Winning strategy

**H(A-11→B-02)** (family H): cheapest candidate that meets the macro_f1 target of 0.85 on validation (0.877); wrapped in a cascade that answers 75% A-11, 25% B-02 (+0.060 on the shared sample).

Planner (llm): Trying keyword rules (J), TF‑IDF linear models (A), LightGBM (E), embedding kNN/centroids (I), and Qwen3 embeddings (B) because they cover keyword, linear, tree, embedding, and LLM‑embedding approaches within the 500 ms latency budget.; prompted Nemotron (K) added so the cascade can be evaluated

Frontier alternatives:

- recommended: A-11 — macro_f1 0.877 on validation, $0.0004 per 1M predictions, p50 0.30 ms
- most_accurate: B-02 — macro_f1 0.936 on validation, $0.4703 per 1M predictions, p50 281.21 ms
- cheapest: J-06 — macro_f1 0.269 on validation, $0.0001 per 1M predictions, p50 0.01 ms

## Sealed test set (true labels)

- macro_f1: **0.933** on 2474 records
- macro precision 0.935, macro recall 0.933, macro F1 0.933
- validation 0.930 vs sealed 0.933 (sealed is not lower here; with one config per family there was little selection to inflate validation)

| Class | Precision | Recall | Support |
|---|---|---|---|
| Refund_not_showing_up | 1.000 | 1.000 | 38 |
| activate_my_card | 0.974 | 1.000 | 38 |
| age_limit | 1.000 | 1.000 | 28 |
| apple_pay_or_google_pay | 1.000 | 1.000 | 31 |
| atm_support | 1.000 | 1.000 | 24 |
| automatic_top_up | 1.000 | 0.871 | 31 |
| balance_not_updated_after_bank_transfer | 0.818 | 0.675 | 40 |
| balance_not_updated_after_cheque_or_cash_deposit | 0.930 | 0.952 | 42 |
| beneficiary_not_allowed | 0.875 | 0.946 | 37 |
| cancel_transfer | 1.000 | 1.000 | 37 |
| card_about_to_expire | 1.000 | 0.938 | 32 |
| card_acceptance | 0.947 | 1.000 | 18 |
| card_arrival | 0.973 | 0.973 | 37 |
| card_delivery_estimate | 0.964 | 0.931 | 29 |
| card_linking | 0.971 | 0.971 | 34 |
| card_not_working | 0.963 | 0.897 | 29 |
| card_payment_fee_charged | 1.000 | 0.884 | 43 |
| card_payment_not_recognised | 0.927 | 0.950 | 40 |
| card_payment_wrong_exchange_rate | 0.974 | 0.974 | 39 |
| card_swallowed | 1.000 | 0.947 | 19 |
| cash_withdrawal_charge | 0.976 | 0.976 | 41 |
| cash_withdrawal_not_recognised | 0.946 | 0.921 | 38 |
| change_pin | 0.966 | 0.933 | 30 |
| compromised_card | 0.885 | 0.958 | 24 |
| contactless_not_working | 0.933 | 1.000 | 14 |
| country_support | 1.000 | 1.000 | 32 |
| declined_card_payment | 0.879 | 0.806 | 36 |
| declined_cash_withdrawal | 0.929 | 0.975 | 40 |
| declined_transfer | 0.867 | 0.788 | 33 |
| direct_debit_payment_not_recognised | 0.949 | 0.881 | 42 |
| disposable_card_limits | 0.861 | 1.000 | 31 |
| edit_personal_details | 1.000 | 1.000 | 30 |
| exchange_charge | 1.000 | 0.968 | 31 |
| exchange_rate | 0.931 | 0.931 | 29 |
| exchange_via_app | 0.900 | 0.900 | 30 |
| extra_charge_on_statement | 0.860 | 0.949 | 39 |
| failed_transfer | 0.886 | 0.939 | 33 |
| fiat_currency_support | 0.935 | 0.906 | 32 |
| get_disposable_virtual_card | 1.000 | 0.769 | 26 |
| get_physical_card | 0.966 | 1.000 | 28 |
| getting_spare_card | 0.939 | 0.969 | 32 |
| getting_virtual_card | 0.929 | 1.000 | 26 |
| lost_or_stolen_card | 0.821 | 1.000 | 23 |
| lost_or_stolen_phone | 1.000 | 0.935 | 31 |
| order_physical_card | 0.903 | 0.933 | 30 |
| passcode_forgotten | 1.000 | 0.963 | 27 |
| pending_card_payment | 0.878 | 0.947 | 38 |
| pending_cash_withdrawal | 0.971 | 0.943 | 35 |
| pending_top_up | 0.903 | 0.800 | 35 |
| pending_transfer | 0.778 | 0.778 | 36 |
| pin_blocked | 0.906 | 1.000 | 29 |
| receiving_money | 0.923 | 0.923 | 26 |
| request_refund | 1.000 | 1.000 | 40 |
| reverted_card_payment? | 0.804 | 0.974 | 38 |
| supported_cards_and_currencies | 1.000 | 0.906 | 32 |
| terminate_account | 1.000 | 1.000 | 28 |
| top_up_by_bank_transfer_charge | 0.931 | 0.931 | 29 |
| top_up_by_card_charge | 0.962 | 0.862 | 29 |
| top_up_by_cash_or_cheque | 1.000 | 1.000 | 29 |
| top_up_failed | 0.725 | 0.853 | 34 |
| top_up_limits | 0.857 | 0.960 | 25 |
| top_up_reverted | 0.963 | 0.765 | 34 |
| topping_up_by_card | 0.806 | 0.926 | 27 |
| transaction_charged_twice | 1.000 | 0.976 | 41 |
| transfer_fee_charged | 0.949 | 0.925 | 40 |
| transfer_into_account | 0.875 | 0.966 | 29 |
| transfer_not_received_by_recipient | 0.745 | 0.875 | 40 |
| transfer_timing | 0.800 | 0.750 | 32 |
| unable_to_verify_identity | 0.862 | 0.926 | 27 |
| verify_my_identity | 0.889 | 0.889 | 27 |
| verify_source_of_funds | 1.000 | 1.000 | 29 |
| verify_top_up | 1.000 | 1.000 | 31 |
| virtual_card_not_working | 1.000 | 0.933 | 15 |
| visa_or_mastercard | 0.971 | 1.000 | 33 |
| why_verify_identity | 0.966 | 0.903 | 31 |
| wrong_amount_of_cash_received | 1.000 | 0.929 | 42 |
| wrong_exchange_rate_for_cash_withdrawal | 0.947 | 0.923 | 39 |

## Nemotron Ultra zero-shot baseline

On the same 300 sealed records: Nemotron Ultra macro_f1 0.738 vs specialist 0.913.
Baseline p50 latency 1437 ms, $1029.14 per 1M predictions.

Agreement with Nemotron Ultra (agreement, not accuracy): 75.3% on 300 records.

## Seed error bars (3 seeds, validation)

- A-11: 0.858 ± 0.002
- B-02: 0.931 ± 0.003

## Speed and cost

- latency p50 0.298 ms, p99 1543.000 ms
- throughput n/a items/s; model size n/a MB
- $0.1193 per 1M predictions; formula: sum over stages of (share of items reaching the stage × its cost)
- at 500,000 records/month (task card): Nemotron Ultra $6,175/year vs specialist $0.72/year (cost per 1M predictions × monthly_volume × 12 / 1e6 (marginal cost; the Serverless endpoint is shared by all specialists))
- cascade A-11 → B-02: answered by A-11 74.7% / B-02 25.3% on validation (used)
- on the sealed test: A-11 75.6% / B-02 24.4%

## Would more data help?

- 10% of training data: 0.714
- 40% of training data: 0.841
- 100% of training data: 0.877

## Known weaknesses

- direct_debit_payment_not_recognised confused with card_payment_not_recognised (6 validation errors): Customers describe unrecognized payments without specifying payment method (debit vs card), using generic terms like 'payment', 'charge', 'money taken out', causing the classifier to default to the more common card payment class.
- card_payment_fee_charged confused with transfer_fee_charged (5 validation errors): Customers mention fees in the context of card purchases or transactions, but the classifier over-associates 'fee' with 'transfer' due to stronger lexical overlap in training data.
- verify_my_identity confused with why_verify_identity (5 validation errors): Customers ask procedural 'what/how' questions about verification requirements and methods, but the classifier misroutes them to the 'why' (reason/purpose) class due to shared verification vocabulary.
- unable_to_verify_identity confused with verify_my_identity (4 validation errors): Customers express inability, failure, or confusion completing verification ('can't verify', 'not working', 'stuck'), but the classifier maps them to the general verification process class instead of the failure-specific class.

## Data sources

- banking77 (https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/): CC-BY-4.0; 13,023 rows. Cite: Casanueva et al. Efficient Intent Detection with Dual Sentence Encoders. 2020. https://arxiv.org/abs/2003.04807
