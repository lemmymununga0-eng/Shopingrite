# Product and pricing sources

Catalogue data lives in `backend/app/db/catalogue_zm.py` (66 products). Run `python -m app.db.catalogue_zm` from `backend/` for a live audit report (counts and products still needing a photograph).

## Read this first

* **No price in this catalogue is "verified".** I could not confirm any price against a dated promotional catalogue or a current official price list. The database allows the status `verified`, but nothing uses it.
* **12 prices are `observed`**: seen on the Lusaka Grocery Delivery storefront (https://lusakadelivery.com/) on **2026-10-17**, as a single "regular price" with no promotion dates. They are not guaranteed to be current and not a statement about any other shop.
* **54 prices are `estimated`**: demonstration figures chosen to sit plausibly beside the observed ones. They are **not market prices**. The storefront shows a "Demo price" tag on them and the product page says "Demonstration estimate".
* The two mealie-meal estimates (K230 breakfast, K190 roller, assumed 25 kg bags) come from reports of **October 2023** government-backed Shoprite sales, so they are three years old and also marked `estimated`.
* **Offers are demonstration offers.** Six products carry an invented discount that ends 2026-11-30 and expires on its own. They are labelled "Demo offer" and are not retailer promotions. An offer past its end date is neither shown nor charged (backend rule, tested).

## Sources tried

| Source | Result (2026-10-17) |
|---|---|
| https://lusakadelivery.com/ | Loaded. Product names and kwacha prices were readable. `robots.txt` allows product pages. No promotion dates. Terms linked from it (Shopify) were **not read**. Used only to record 12 observed prices, with the product page URL on each row. Photos and descriptions were **not** copied. |
| https://www.shoprite.co.zm/ | HTTP 403. Not accessible; no data used. |
| https://specials.shoprite.co.zm/ | Loaded but empty (script-rendered). No data. |
| https://www.picknpayzambia.com/ and `/specials/` | Loaded; no product list or prices in the page text. No data. |
| https://pamarketonline.net/ | Fetch failed. No data. |
| News reports on mealie-meal prices (Millingmea, Zambia Monitor, Lusaka Times) | Used only for the 2022/2023 reference points described above. |

I did not scrape, bypass blocking, or hot-link any images.

## Observed prices (all from Lusaka Grocery Delivery, checked 2026-10-17)

| SKU | Product | Price (ZMW) | Page |
|---|---|---|---|
| ZM-FP-002 | Tomatoes per kg | 22 | /products/tomatoes-per-kg |
| ZM-DE-001 | Parmalat long life milk 1 L | 45 | /products/milk-1l-long-life-parmalat |
| ZM-DE-002 | Zammilk 2 L | 48 | /products/milk-2l-zammilk |
| ZM-DE-003 | Natural yoghurt 500 g | 27 | /products/natural-yoghurt-500g |
| ZM-BK-001 | Zambika white family bread 700 g | 28 | /products/zambika-white-family-bread-700g |
| ZM-ST-003 | Mongu rice 2.5 kg | 120 | /products/mongu-rice-2-5kg |
| ZM-ST-004 | NMC household flour 2.5 kg | 90 | /products/nmc-household-flour-2-5kg |
| ZM-PA-001 | Cooking oil 750 ml (brand not stated) | 68 | /products/cooking-oil-750ml |
| ZM-PA-002 | White spoon sugar 1 kg | 45 | /products/white-spoon-sugar |
| ZM-SN-001 | Jungle Oats 1 kg | 120 | /products/jungle-oats-1kg |
| ZM-SN-002 | Oreo original 152 g (listing says "14pack", URL says "16-pack") | 36 | /products/oreo-original-16-pack-152g |
| ZM-BV-001 | Coca-Cola 2 L | 32 | /products/coca-cola-2l |

Left out because the source was ambiguous: "Breakfast Mealie Meal K350" (no pack size stated), bananas "1S Pack" K48 (no weight), and alcoholic drinks.

## Stock

All stock quantities are invented demonstration inventory. Nothing is connected to a retailer's stock.

## Images

* Policy: only openly licensed photographs, shown with credit. Nine generic photographs from Wikimedia Commons are used (bananas, apples, tomatoes, eggs, butter, toilet paper, laundry powder, beef mince, whole chicken). They show the generic item, not a branded pack, and the product page says so.
* The other **57 products show a category illustration** and are flagged `image_status = placeholder`. The product page states that a correct photograph has not been added. They are listed by `python -m app.db.catalogue_zm`.
* No generated or invented packaging photographs are used.
* The old `DEMO-*` photographs were reviewed: several did not match their product (for example a cat-litter jug for "Bin Bags", an engraving for "Lamb Chops", a spinach dish for "Baby Spinach"). Those products are hidden, and only the nine good matches were kept (copied to `img-*.jpg`).
* `frontend/public/products/credits.json` was **truncated and invalid JSON** (the image-credits page could not load). It is now regenerated from the catalogue data.

## How to improve this

1. Replace estimates with a dated source (a shop's printed catalogue, or written permission to use a retailer's price list), then set `price_status = verified`.
2. Add photographs: your own photos, a supplier's media with permission, or openly licensed images that show the correct pack. Fill `image_source` and `image_license`.
3. Administrators will be able to edit prices and stock in the store management screens (Phase 6); each price edit is recorded in `price_history`.
