# Support Ticket Router v2: improve run

**Gate: passed, deployed.** beats the live version (0.935 vs 0.933) and passes every threshold.

- Corrections added to the training set only: 18 (plus 54 targeted variants written by Nemotron Ultra)
- Retrained: A-11 (validation 0.877 → 0.876), A-09 (validation 0.896 → 0.898)
- Shipped as: H(A-09→B-02)
- Fixed benchmark: the sealed test set of run p2b-support-c (the one v1 was scored on); corrections never enter it.

## Sealed test set

| | v1 (live before) | v2 (this run) |
|---|---|---|
| macro_f1 | 0.933 | 0.935 |
| records | 2474 | 2474 |
| answered by |  | A-09 80% / B-02 20% |
| cost per 1M predictions | | $0.0943 |

## Per class (this run, sealed test set)

| class | precision | recall | n |
|---|---|---|---|
| Refund_not_showing_up | 1.00 | 1.00 | 38 |
| activate_my_card | 0.97 | 1.00 | 38 |
| age_limit | 1.00 | 1.00 | 28 |
| apple_pay_or_google_pay | 1.00 | 1.00 | 31 |
| atm_support | 1.00 | 1.00 | 24 |
| automatic_top_up | 1.00 | 0.90 | 31 |
| balance_not_updated_after_bank_transfer | 0.82 | 0.70 | 40 |
| balance_not_updated_after_cheque_or_cash_deposit | 0.93 | 0.95 | 42 |
| beneficiary_not_allowed | 0.83 | 0.95 | 37 |
| cancel_transfer | 1.00 | 1.00 | 37 |
| card_about_to_expire | 1.00 | 0.94 | 32 |
| card_acceptance | 0.95 | 1.00 | 18 |
| card_arrival | 0.97 | 0.95 | 37 |
| card_delivery_estimate | 0.96 | 0.93 | 29 |
| card_linking | 0.97 | 0.97 | 34 |
| card_not_working | 0.96 | 0.90 | 29 |
| card_payment_fee_charged | 1.00 | 0.91 | 43 |
| card_payment_not_recognised | 0.95 | 0.95 | 40 |
| card_payment_wrong_exchange_rate | 0.97 | 0.97 | 39 |
| card_swallowed | 1.00 | 0.95 | 19 |
| cash_withdrawal_charge | 0.98 | 0.98 | 41 |
| cash_withdrawal_not_recognised | 0.95 | 0.92 | 38 |
| change_pin | 0.97 | 0.93 | 30 |
| compromised_card | 0.92 | 0.96 | 24 |
| contactless_not_working | 0.88 | 1.00 | 14 |
| country_support | 1.00 | 1.00 | 32 |
| declined_card_payment | 0.88 | 0.81 | 36 |
| declined_cash_withdrawal | 0.93 | 0.97 | 40 |
| declined_transfer | 0.87 | 0.79 | 33 |
| direct_debit_payment_not_recognised | 0.95 | 0.88 | 42 |
| disposable_card_limits | 0.94 | 1.00 | 31 |
| edit_personal_details | 1.00 | 1.00 | 30 |
| exchange_charge | 1.00 | 0.97 | 31 |
| exchange_rate | 0.96 | 0.93 | 29 |
| exchange_via_app | 0.87 | 0.90 | 30 |
| extra_charge_on_statement | 0.86 | 0.95 | 39 |
| failed_transfer | 0.89 | 0.94 | 33 |
| fiat_currency_support | 0.94 | 0.91 | 32 |
| get_disposable_virtual_card | 1.00 | 0.88 | 26 |
| get_physical_card | 0.97 | 1.00 | 28 |
| getting_spare_card | 0.97 | 0.97 | 32 |
| getting_virtual_card | 0.93 | 1.00 | 26 |
| lost_or_stolen_card | 0.82 | 1.00 | 23 |
| lost_or_stolen_phone | 1.00 | 0.94 | 31 |
| order_physical_card | 0.90 | 0.93 | 30 |
| passcode_forgotten | 1.00 | 0.96 | 27 |
| pending_card_payment | 0.88 | 0.97 | 38 |
| pending_cash_withdrawal | 0.97 | 0.94 | 35 |
| pending_top_up | 0.94 | 0.83 | 35 |
| pending_transfer | 0.78 | 0.78 | 36 |
| pin_blocked | 0.91 | 1.00 | 29 |
| receiving_money | 0.92 | 0.92 | 26 |
| request_refund | 0.98 | 1.00 | 40 |
| reverted_card_payment? | 0.80 | 0.95 | 38 |
| supported_cards_and_currencies | 1.00 | 0.94 | 32 |
| terminate_account | 1.00 | 1.00 | 28 |
| top_up_by_bank_transfer_charge | 0.93 | 0.90 | 29 |
| top_up_by_card_charge | 0.96 | 0.86 | 29 |
| top_up_by_cash_or_cheque | 1.00 | 1.00 | 29 |
| top_up_failed | 0.75 | 0.88 | 34 |
| top_up_limits | 0.89 | 0.96 | 25 |
| top_up_reverted | 0.96 | 0.79 | 34 |
| topping_up_by_card | 0.83 | 0.93 | 27 |
| transaction_charged_twice | 1.00 | 0.98 | 41 |
| transfer_fee_charged | 0.95 | 0.93 | 40 |
| transfer_into_account | 0.87 | 0.93 | 29 |
| transfer_not_received_by_recipient | 0.76 | 0.88 | 40 |
| transfer_timing | 0.80 | 0.75 | 32 |
| unable_to_verify_identity | 0.86 | 0.93 | 27 |
| verify_my_identity | 0.89 | 0.89 | 27 |
| verify_source_of_funds | 1.00 | 1.00 | 29 |
| verify_top_up | 1.00 | 1.00 | 31 |
| virtual_card_not_working | 1.00 | 0.93 | 15 |
| visa_or_mastercard | 0.97 | 1.00 | 33 |
| why_verify_identity | 0.97 | 0.90 | 31 |
| wrong_amount_of_cash_received | 1.00 | 0.93 | 42 |
| wrong_exchange_rate_for_cash_withdrawal | 0.95 | 0.92 | 39 |
