"""Zambian grocery catalogue for the demonstration store. READ docs/product-pricing-sources.md BEFORE TRUSTING A PRICE.

Every row says how far its price can be trusted:
  observed  : seen on a retailer web page on `checked` (see source URL). Not guaranteed to be today's price.
  estimated : a demonstration figure chosen to be plausible next to the observed ones. NOT a market price.
Nothing here is "verified": no price could be confirmed against a dated promotional catalogue (see the sources doc).
Stock quantities are invented demonstration inventory, not any retailer's stock.
Images: `licensed` rows use an openly licensed photograph (credit in IMAGES); every other product uses its category
placeholder and is listed by `python -m app.db.catalogue_zm` as still needing a correct photograph.
"""
from datetime import date

CHECKED = date(2026, 10, 17)
LD = "Lusaka Grocery Delivery"
LD_BASE = "https://lusakadelivery.com/products/"

CATEGORIES = [   # slug, name   (existing demo slugs are kept so nothing already seeded changes)
    ("fresh-produce", "Fresh Produce"), ("meat-poultry", "Meat, Fish & Poultry"), ("dairy-eggs", "Dairy & Eggs"),
    ("bakery", "Bakery"), ("staples", "Mealie Meal, Rice & Flour"), ("pantry", "Cooking Essentials"),
    ("snacks", "Snacks & Breakfast"), ("beverages", "Beverages"), ("household", "Household & Cleaning"),
    ("personal-care", "Personal Care & Baby"), ("frozen", "Frozen Foods"),
]

# Openly licensed photographs (Wikimedia Commons). key -> (file, licence, author, page)
IMAGES = {
    "bananas": ("Bunch of bananas on sale.jpg", "CC0", "Wilfredor"),
    "apples": ("Red Apple.jpg", "CC BY 2.0", "Abhijit Tembhekar from Mumbai, India"),
    "tomatoes": ("Fresh red tomatoes.jpg", "CC BY-SA 4.0", "Selimee"),
    "eggs": ("Egg cartons with chicken eggs 03.jpg", "CC BY-SA 4.0", "Krzysztof Golik"),
    "butter": ("Block of butter in butter dish.jpg", "CC BY 4.0", "Qwertyxp2000"),
    "toilet-paper": ("Stacked rolls of toilet paper, Tunnicliff's Tavern.jpg", "CC BY-SA 4.0", "Ser Amantio di Nicolao"),
    "laundry-powder": ("Laundry detergent 1.jpg", "CC BY-SA 4.0", "MartinMerinsky"),
    "beef-mince": ("Hackfleisch-1.jpg", "CC BY-SA 3.0", "Rainer Zenz (assumed, per Wikimedia Commons)"),
    "whole-chicken": ("Whole raw chicken - Japan Dec 22 2019.jpeg", "CC BY 4.0", "Nesnad"),
}
IMAGE_NOTE = {   # what the photo really shows, so the alt text does not over-claim
    "bananas": "Bunch of bananas", "apples": "Red apple", "tomatoes": "Fresh red tomatoes",
    "eggs": "Cartons of chicken eggs", "butter": "Block of butter in a dish", "toilet-paper": "Stacked toilet paper rolls",
    "laundry-powder": "Laundry detergent", "beef-mince": "Minced beef", "whole-chicken": "Whole raw chicken",
}

# sku, name, brand, pack, unit, category, price ZMW, status, observed-source slug|None, stock, reorder, featured, image key|None, description
P = [
 # --- fresh produce
 ("ZM-FP-001", "Bananas", "", "per kg", "per kg", "fresh-produce", 24.00, "estimated", None, 80, 15, True, "bananas", "Sweet yellow bananas, sold by weight."),
 ("ZM-FP-002", "Tomatoes", "", "per kg", "per kg", "fresh-produce", 22.00, "observed", "tomatoes-per-kg", 90, 15, True, "tomatoes", "Firm salad tomatoes, sold by weight."),
 ("ZM-FP-003", "Red Apples", "", "1 kg", "1 kg", "fresh-produce", 55.00, "estimated", None, 50, 10, False, "apples", "Crisp red apples."),
 ("ZM-FP-004", "Onions", "", "per kg", "per kg", "fresh-produce", 18.00, "estimated", None, 100, 20, False, None, "Brown cooking onions."),
 ("ZM-FP-005", "Irish Potatoes", "", "2 kg bag", "2 kg", "fresh-produce", 40.00, "estimated", None, 70, 15, False, None, "General-purpose potatoes."),
 ("ZM-FP-006", "Rape (Leafy Greens)", "", "bunch", "bunch", "fresh-produce", 8.00, "estimated", None, 60, 10, False, None, "Fresh rape leaves, a Zambian staple relish."),
 ("ZM-FP-007", "Cabbage", "", "each", "each", "fresh-produce", 20.00, "estimated", None, 45, 10, False, None, "Firm green cabbage."),
 ("ZM-FP-008", "Carrots", "", "1 kg", "1 kg", "fresh-produce", 20.00, "estimated", None, 55, 10, False, None, "Fresh carrots."),
 ("ZM-FP-009", "Green Peppers", "", "3 pack", "3 pack", "fresh-produce", 18.00, "estimated", None, 0, 10, False, None, "Green bell peppers."),
 ("ZM-FP-010", "Oranges", "", "1 kg", "1 kg", "fresh-produce", 30.00, "estimated", None, 40, 10, False, None, "Juicy oranges."),
 # --- meat, fish, poultry
 ("ZM-MP-001", "Whole Chicken", "", "approx. 1.5 kg", "each", "meat-poultry", 135.00, "estimated", None, 35, 8, True, "whole-chicken", "Whole fresh chicken, approximate weight."),
 ("ZM-MP-002", "Beef Mince", "", "500 g", "500 g", "meat-poultry", 75.00, "estimated", None, 30, 8, False, "beef-mince", "Beef mince."),
 ("ZM-MP-003", "Beef Stewing Cuts", "", "1 kg", "1 kg", "meat-poultry", 120.00, "estimated", None, 25, 8, False, None, "Bone-in beef pieces for stewing."),
 ("ZM-MP-004", "Boerewors", "", "500 g", "500 g", "meat-poultry", 70.00, "estimated", None, 22, 6, False, None, "Coiled beef sausage."),
 ("ZM-MP-005", "Dried Kapenta (Matemba)", "", "250 g", "250 g", "meat-poultry", 65.00, "estimated", None, 40, 8, True, None, "Sun-dried small fish, a Zambian favourite."),
 ("ZM-MP-006", "Frozen Bream (Tilapia)", "", "1 kg", "1 kg", "meat-poultry", 95.00, "estimated", None, 18, 6, False, None, "Whole frozen bream."),
 ("ZM-MP-007", "Chicken Drumsticks", "", "1 kg", "1 kg", "meat-poultry", 85.00, "estimated", None, 0, 8, False, None, "Chicken drumsticks."),
 # --- dairy and eggs
 ("ZM-DE-001", "Long Life Milk", "Parmalat", "1 L", "1 L", "dairy-eggs", 45.00, "observed", "milk-1l-long-life-parmalat", 120, 25, True, None, "UHT long life full cream milk."),
 ("ZM-DE-002", "Fresh Milk", "Zammilk", "2 L", "2 L", "dairy-eggs", 48.00, "observed", "milk-2l-zammilk", 90, 20, True, None, "Fresh milk."),
 ("ZM-DE-003", "Natural Yoghurt", "", "500 g", "500 g", "dairy-eggs", 27.00, "observed", "natural-yoghurt-500g", 45, 10, False, None, "Natural yoghurt."),
 ("ZM-DE-004", "Eggs", "", "tray of 30", "tray of 30", "dairy-eggs", 85.00, "estimated", None, 60, 12, True, "eggs", "Tray of 30 table eggs."),
 ("ZM-DE-005", "Margarine", "", "500 g", "500 g", "dairy-eggs", 42.00, "estimated", None, 50, 10, False, None, "Spreadable margarine tub."),
 ("ZM-DE-006", "Butter", "", "250 g", "250 g", "dairy-eggs", 55.00, "estimated", None, 20, 6, False, "butter", "Salted butter."),
 ("ZM-DE-007", "Cheddar Cheese", "", "400 g", "400 g", "dairy-eggs", 95.00, "estimated", None, 4, 8, False, None, "Mature cheddar block."),
 # --- bakery
 ("ZM-BK-001", "White Family Bread", "Zambika", "700 g", "700 g", "bakery", 28.00, "observed", "zambika-white-family-bread-700g", 100, 20, True, None, "Sliced white family loaf."),
 ("ZM-BK-002", "Brown Bread", "", "700 g", "700 g", "bakery", 30.00, "estimated", None, 70, 15, False, None, "Sliced brown loaf."),
 ("ZM-BK-003", "Bread Rolls", "", "6 pack", "6 pack", "bakery", 24.00, "estimated", None, 50, 12, False, None, "Soft bread rolls."),
 ("ZM-BK-004", "Scones", "", "4 pack", "4 pack", "bakery", 32.00, "estimated", None, 25, 8, False, None, "Freshly baked scones."),
 # --- staples
 ("ZM-ST-001", "Breakfast Mealie Meal", "", "25 kg (assumed)", "25 kg", "staples", 230.00, "estimated", None, 60, 12, True, None, "Refined maize meal for nshima. Pack size assumed 25 kg; estimate based on 2023 government-backed retail prices (K230)."),
 ("ZM-ST-002", "Roller Mealie Meal", "", "25 kg (assumed)", "25 kg", "staples", 190.00, "estimated", None, 45, 10, False, None, "Roller maize meal for nshima. Pack size assumed 25 kg; estimate based on 2023 government-backed retail prices (K190)."),
 ("ZM-ST-003", "Mongu Rice", "Mongu", "2.5 kg", "2.5 kg", "staples", 120.00, "observed", "mongu-rice-2-5kg", 55, 10, True, None, "Locally grown long grain rice."),
 ("ZM-ST-004", "Household Flour", "NMC", "2.5 kg", "2.5 kg", "staples", 90.00, "observed", "nmc-household-flour-2-5kg", 50, 10, False, None, "General purpose flour."),
 ("ZM-ST-005", "Spaghetti", "", "500 g", "500 g", "staples", 24.00, "estimated", None, 70, 12, False, None, "Dried durum wheat spaghetti."),
 ("ZM-ST-006", "Sugar Beans", "", "1 kg", "1 kg", "staples", 48.00, "estimated", None, 40, 10, False, None, "Dried sugar beans."),
 ("ZM-ST-007", "Kidney Beans", "", "1 kg", "1 kg", "staples", 45.00, "estimated", None, 0, 10, False, None, "Dried red kidney beans."),
 ("ZM-ST-008", "Groundnuts (Raw)", "", "1 kg", "1 kg", "staples", 60.00, "estimated", None, 30, 8, False, None, "Raw shelled groundnuts."),
 # --- cooking essentials
 ("ZM-PA-001", "Cooking Oil", "", "750 ml", "750 ml", "pantry", 68.00, "observed", "cooking-oil-750ml", 90, 15, True, None, "Vegetable cooking oil."),
 ("ZM-PA-002", "White Sugar", "", "1 kg", "1 kg", "pantry", 45.00, "observed", "white-spoon-sugar", 100, 20, True, None, "White granulated sugar."),
 ("ZM-PA-003", "Iodised Salt", "", "1 kg", "1 kg", "pantry", 12.00, "estimated", None, 120, 20, False, None, "Table salt."),
 ("ZM-PA-004", "Peanut Butter", "", "400 g", "400 g", "pantry", 48.00, "estimated", None, 40, 8, False, None, "Smooth peanut butter."),
 ("ZM-PA-005", "Tomato Paste", "", "70 g", "70 g", "pantry", 8.00, "estimated", None, 100, 20, False, None, "Tomato paste sachet."),
 ("ZM-PA-006", "Stock Cubes", "", "24 pack", "24 pack", "pantry", 28.00, "estimated", None, 60, 12, False, None, "Beef-flavour stock cubes."),
 ("ZM-PA-007", "Baking Powder", "", "100 g", "100 g", "pantry", 18.00, "estimated", None, 35, 8, False, None, "Baking powder."),
 # --- snacks and breakfast
 ("ZM-SN-001", "Jungle Oats", "Jungle", "1 kg", "1 kg", "snacks", 120.00, "observed", "jungle-oats-1kg", 40, 8, True, None, "Rolled oats porridge."),
 ("ZM-SN-002", "Oreo Original Biscuits", "Oreo", "152 g", "152 g", "snacks", 36.00, "observed", "oreo-original-16-pack-152g", 60, 12, False, None, "Chocolate sandwich biscuits."),
 ("ZM-SN-003", "Corn Flakes", "", "500 g", "500 g", "snacks", 65.00, "estimated", None, 30, 8, False, None, "Breakfast cereal."),
 ("ZM-SN-004", "Salted Crisps", "", "125 g", "125 g", "snacks", 15.00, "estimated", None, 80, 15, False, None, "Salted potato crisps."),
 ("ZM-SN-005", "Tea Biscuits", "", "200 g", "200 g", "snacks", 18.00, "estimated", None, 55, 10, False, None, "Plain tea biscuits."),
 ("ZM-SN-006", "Instant Coffee", "", "100 g", "100 g", "snacks", 85.00, "estimated", None, 25, 6, False, None, "Instant coffee granules."),
 # --- beverages
 ("ZM-BV-001", "Coca-Cola", "Coca-Cola", "2 L", "2 L", "beverages", 32.00, "observed", "coca-cola-2l", 100, 20, True, None, "Carbonated soft drink."),
 ("ZM-BV-002", "Bottled Water", "", "5 L", "5 L", "beverages", 22.00, "estimated", None, 80, 15, False, None, "Still drinking water."),
 ("ZM-BV-003", "Black Tea Bags", "", "100 pack", "100 pack", "beverages", 45.00, "estimated", None, 50, 10, False, None, "Black tea bags."),
 ("ZM-BV-004", "Orange Juice", "", "1 L", "1 L", "beverages", 38.00, "estimated", None, 40, 8, False, None, "Orange fruit drink."),
 ("ZM-BV-005", "Orange Soft Drink", "", "2 L", "2 L", "beverages", 28.00, "estimated", None, 0, 12, False, None, "Orange-flavoured soft drink."),
 # --- household
 ("ZM-HH-001", "Laundry Washing Powder", "", "1 kg", "1 kg", "household", 55.00, "estimated", None, 60, 12, True, "laundry-powder", "Hand and machine washing powder."),
 ("ZM-HH-002", "Dishwashing Liquid", "", "750 ml", "750 ml", "household", 38.00, "estimated", None, 45, 10, False, None, "Lemon dishwashing liquid."),
 ("ZM-HH-003", "Toilet Paper", "", "9 rolls", "9 rolls", "household", 60.00, "estimated", None, 70, 12, False, "toilet-paper", "Soft toilet paper rolls."),
 ("ZM-HH-004", "Bar Soap (Laundry)", "", "400 g", "400 g", "household", 18.00, "estimated", None, 80, 15, False, None, "Laundry bar soap."),
 ("ZM-HH-005", "Bleach", "", "750 ml", "750 ml", "household", 25.00, "estimated", None, 40, 8, False, None, "Household bleach."),
 ("ZM-HH-006", "Candles", "", "6 pack", "6 pack", "household", 20.00, "estimated", None, 90, 15, False, None, "White household candles."),
 # --- personal care and baby
 ("ZM-PC-001", "Toothpaste", "", "100 ml", "100 ml", "personal-care", 28.00, "estimated", None, 60, 12, False, None, "Fluoride toothpaste."),
 ("ZM-PC-002", "Bathing Soap", "", "175 g", "175 g", "personal-care", 12.00, "estimated", None, 100, 20, False, None, "Bath soap bar."),
 ("ZM-PC-003", "Body Lotion", "", "400 ml", "400 ml", "personal-care", 48.00, "estimated", None, 35, 8, False, None, "Moisturising body lotion."),
 ("ZM-PC-004", "Roll-on Deodorant", "", "50 ml", "50 ml", "personal-care", 35.00, "estimated", None, 30, 8, False, None, "Roll-on deodorant."),
 ("ZM-PC-005", "Baby Nappies", "", "size 3, 44 pack", "44 pack", "personal-care", 220.00, "estimated", None, 20, 5, False, None, "Disposable nappies."),
 ("ZM-PC-006", "Baby Wipes", "", "80 pack", "80 pack", "personal-care", 40.00, "estimated", None, 0, 8, False, None, "Unscented baby wipes."),
]

# Demonstration offers (NOT retailer promotions): sku -> (offer price ZMW, ends on). Date-bound so they expire by themselves.
DEMO_OFFERS = {
    "ZM-DE-004": (79.00, date(2026, 11, 30)), "ZM-PA-001": (62.00, date(2026, 11, 30)),
    "ZM-ST-003": (109.00, date(2026, 11, 30)), "ZM-BV-001": (28.00, date(2026, 11, 30)),
    "ZM-MP-001": (125.00, date(2026, 11, 30)), "ZM-HH-001": (49.00, date(2026, 11, 30)),
}


def image_fields(key):
    """image_ref plus alt/source/licence/status for a product, given its IMAGES key (None = placeholder)."""
    if key is None:
        return {}
    title, licence, author = IMAGES[key]
    page = "https://commons.wikimedia.org/wiki/File:" + title.replace(" ", "_")
    return {"image_ref": f"/products/img-{key}.jpg", "image_alt": IMAGE_NOTE[key] + " (generic photograph)",
            "image_source": f"{page} - {author}", "image_license": licence, "image_status": "licensed"}


def credits() -> dict:
    return {f"img-{k}.jpg": {"title": "File:" + t, "license": lic, "author": a,
                             "page": "https://commons.wikimedia.org/wiki/File:" + t.replace(" ", "_")}
            for k, (t, lic, a) in IMAGES.items()}


if __name__ == "__main__":   # catalogue audit report
    missing = [p for p in P if p[12] is None]
    est = [p for p in P if p[7] == "estimated"]
    print(f"{len(P)} products; {len(P) - len(est)} observed prices, {len(est)} estimated prices")
    print(f"{len(P) - len(missing)} with a licensed photograph, {len(missing)} still need a correct photograph:")
    for p in missing:
        print(f"  {p[0]}  {p[1]} {p[3]}")
