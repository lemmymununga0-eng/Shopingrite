# Collecting verified labels for a grocery fraud model

**Status: no grocery-specific labelled data exists yet.** The store has recorded zero verified outcomes, PaySim cannot be downloaded without a
Kaggle token (and is a mobile-money simulation whose fields do not match grocery orders anyway), and the public card dataset has anonymised
features. So a supervised grocery model has **not** been trained and the store is assessed by the rule engine `store_risk_v1`
(labelled "rules" everywhere). Nothing in this repository generates, infers or balances labels.

## What counts as a label
Recorded by an authorised reviewer (`fraud.review`) on the order page (`POST /staff/orders/{id}/outcome`, append-only, audited):

| Outcome | Becomes label | Condition |
|---|---|---|
| `confirmed_fraud` | 1 | `verified` ticked, with evidence in the note |
| `legitimate`, `false_positive` | 0 | `verified` ticked |
| `undetermined` | none | never used |
| anything unticked ("suspected") | none | never used |
| no outcome recorded | none | **not** assumed legitimate |

The newest outcome for an order wins, so a mistaken conclusion can be corrected by adding another row.
**Verified** means evidence outside the model and the rules: a chargeback or provider dispute, a confirmed customer contact, a verified delivery,
a returned-goods investigation. A high risk score, an open case, or a failed payment is never evidence.

## Avoiding biased labels
Reviewers mostly open orders the rules flagged, so labels over-represent rule-flagged orders and a model learns "what the rules already catch".
Mitigation (process, not yet automated): each week review a random sample of unflagged orders (at least 20) and record their outcomes too.
Report the sampled and flagged counts separately when evaluating.

## When training is allowed
`python -m app.ml.train_store --status` prints progress. Training is attempted only with at least **150 verified fraud, 1,000 verified legitimate and
50 distinct customers**; otherwise it exits with code 3 (BLOCKED). The validation gate then still requires ≥ 30 fraud rows in the held-out test set,
PR-AUC clearly above a do-nothing baseline, a customer-grouped split (no customer on both sides), and a fresh-process reload check.
A model trained on fewer than **1,000 verified fraud cases is EXPERIMENTAL**: its predictions are stored for comparison with the rules but never create alerts and the UI says so.

## Commands
```bash
cd backend
python -m app.ml.train_store --status                 # label counts, exclusions, what is missing
python -m app.ml.train_store --export labelled.csv    # labelled rows without customer ids, for offline review
python -m app.ml.train_store                          # train, validate, promote only if the gate passes
python -m app.ml.train --rollback store_grocery       # return to the previous promoted version
```
Retraining is always a person's decision. Nothing retrains automatically from feedback.

## Privacy
Notes must not contain card numbers, passwords or other secrets. The export drops customer ids; the schema contains no names, contacts or addresses.
