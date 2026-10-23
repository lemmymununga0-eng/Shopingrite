# Public datasets for this system

Download them with `python scripts/fetch_datasets.py` (from `backend/`). Nothing downloads until you read the dataset's terms
(`info <name>`) and pass `--accept-licence`. Files go to `backend/data/external/<name>/` (git-ignored) with a `MANIFEST.json`
(source, date, SHA-256) and an `ATTRIBUTION.txt`: keep both with the data and credit the source where its licence requires.

```
python scripts/fetch_datasets.py list
python scripts/fetch_datasets.py info phiusiil
python scripts/fetch_datasets.py get phiusiil --accept-licence
python scripts/fetch_datasets.py get off-zambia --accept-licence --max-products 500
python scripts/fetch_datasets.py get osm-lusaka --accept-licence
python scripts/fetch_datasets.py get paysim --accept-licence        # Kaggle: needs your own token and pip install kaggle
```

| Name | For | Licence status | Notes |
|---|---|---|---|
| `phiusiil` | ScamWatch experiments | confirmed, CC BY 4.0 | Use only features computable from the URL text: ScamWatch never opens a link. |
| `paysim` | mobile-money fraud experiments | unverified | Never use the balance columns as inputs (they leak the label). |
| `creditcard` | the PCA demo, rare-fraud practice | unverified | Anonymised features; cannot map to store orders. |
| `ieee-cis` | which device / email / address signals matter | unverified | Competition: join it and accept its rules on Kaggle first. |
| `instacart` | "bought together" / "buy again" prototypes | unverified | Likely non-commercial: read the rules. |
| `off-zambia` | catalogue names, brands, pack sizes, image links | confirmed: ODbL data, CC BY-SA images | Coverage of Zambia may be thin. Never prices. Credit Open Food Facts; share-alike applies to published derivatives. |
| `osm-lusaka` | starting list of delivery-area names | unverified | Volunteer-entered names: check by hand. Credit OpenStreetMap contributors. |

"Unverified" means the project did not confirm the licence: read the terms page yourself.

## What these cannot do
* A fraud model trained on public data does **not** know Zambian customers or prices. Use it to test the pipeline and to learn
  which signals matter; do not let it make real decisions. Real accuracy needs your own labelled orders (outcomes, chargebacks,
  analyst verdicts), and the store already saves each order's risk inputs for that.
* No dataset gives you your prices or your product photos. Enter those yourself in the Products screen.
