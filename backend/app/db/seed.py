"""Reproducible, idempotent demonstration data.

Everything here is SAMPLE data: invented products, invented stock levels, invented demo users. It is not a
retailer's catalogue or inventory feed. Running the seed twice changes nothing; it never updates or deletes
existing rows, so real changes made later are preserved.
"""
from sqlalchemy import select

from ..core import permissions as perm
from ..core.security import hash_password
from . import catalogue_zm as zm
from .models import AppUser, Category, Inventory, PriceHistory, Product, StockMovement

DEMO_PASSWORD = "DemoPass!2026"
DEMO_USERS = [
    ("customer@example.com", "Demo Customer", perm.CUSTOMER),
    ("fraud.analyst@example.com", "Demo Fraud Analyst", perm.FRAUD_ANALYST),
    ("security.analyst@example.com", "Demo Security Analyst", perm.SECURITY_ANALYST),
    ("admin@example.com", "Demo Administrator", perm.ADMIN),
]

CATEGORIES = [
    ("fresh-produce", "Fresh Produce"), ("dairy-eggs", "Dairy & Eggs"), ("bakery", "Bakery"),
    ("meat-poultry", "Meat & Poultry"), ("pantry", "Pantry"), ("beverages", "Beverages"),
    ("frozen", "Frozen Foods"), ("household", "Household"),
]

# (sku, name, description, category slug, price in whole currency units, unit, stock, reorder at, featured, offer price)
PRODUCTS = [
    ("DEMO-FP-001", "Bananas", "Sweet yellow bananas, sold loose.", "fresh-produce", 24.99, "per kg", 120, 20, True, None),
    ("DEMO-FP-002", "Red Apples", "Crisp red apples.", "fresh-produce", 39.99, "1.5 kg bag", 80, 15, False, 32.99),
    ("DEMO-FP-003", "Tomatoes", "Firm salad tomatoes.", "fresh-produce", 29.99, "per kg", 4, 10, False, None),
    ("DEMO-FP-004", "Baby Spinach", "Washed baby spinach leaves.", "fresh-produce", 24.50, "200 g", 0, 10, False, None),
    ("DEMO-FP-005", "Avocados", "Ripe-and-ready avocados.", "fresh-produce", 12.99, "each", 60, 12, True, None),
    ("DEMO-DE-001", "Full Cream Milk", "Fresh full cream milk.", "dairy-eggs", 28.99, "2 L", 150, 30, True, None),
    ("DEMO-DE-002", "Large Eggs", "Free-range large eggs.", "dairy-eggs", 54.99, "18 pack", 70, 15, False, 49.99),
    ("DEMO-DE-003", "Cheddar Cheese", "Mature cheddar block.", "dairy-eggs", 74.99, "400 g", 5, 8, False, None),
    ("DEMO-DE-004", "Plain Yoghurt", "Low-fat plain yoghurt.", "dairy-eggs", 32.99, "1 kg", 45, 10, False, None),
    ("DEMO-DE-005", "Salted Butter", "Creamy salted butter.", "dairy-eggs", 59.99, "500 g", 0, 10, False, None),
    ("DEMO-BK-001", "Brown Bread", "Sliced brown loaf.", "bakery", 19.99, "700 g", 90, 20, True, None),
    ("DEMO-BK-002", "White Rolls", "Soft white rolls.", "bakery", 24.99, "6 pack", 55, 12, False, None),
    ("DEMO-BK-003", "Croissants", "Butter croissants.", "bakery", 34.99, "4 pack", 3, 8, False, 29.99),
    ("DEMO-BK-004", "Sourdough Loaf", "Crusty sourdough.", "bakery", 42.99, "600 g", 25, 6, False, None),
    ("DEMO-BK-005", "Muffins", "Blueberry muffins.", "bakery", 39.99, "4 pack", 30, 8, False, None),
    ("DEMO-MP-001", "Chicken Breast Fillets", "Skinless chicken breast.", "meat-poultry", 89.99, "1 kg", 40, 10, True, 79.99),
    ("DEMO-MP-002", "Beef Mince", "Lean beef mince.", "meat-poultry", 99.99, "1 kg", 35, 8, False, None),
    ("DEMO-MP-003", "Pork Sausages", "Traditional pork sausages.", "meat-poultry", 64.99, "500 g", 6, 10, False, None),
    ("DEMO-MP-004", "Lamb Chops", "Fresh lamb loin chops.", "meat-poultry", 159.99, "per kg", 0, 5, False, None),
    ("DEMO-MP-005", "Whole Chicken", "Whole fresh chicken.", "meat-poultry", 74.99, "1.6 kg", 28, 8, False, None),
    ("DEMO-PA-001", "Long Grain Rice", "Premium long grain rice.", "pantry", 49.99, "2 kg", 100, 20, True, None),
    ("DEMO-PA-002", "Maize Meal", "Super maize meal.", "pantry", 69.99, "5 kg", 85, 15, False, 62.99),
    ("DEMO-PA-003", "Spaghetti", "Durum wheat spaghetti.", "pantry", 18.99, "500 g", 110, 20, False, None),
    ("DEMO-PA-004", "Sunflower Oil", "Cooking oil.", "pantry", 64.99, "2 L", 7, 10, False, None),
    ("DEMO-PA-005", "Baked Beans", "Beans in tomato sauce.", "pantry", 14.99, "410 g", 200, 30, False, None),
    ("DEMO-BV-001", "Still Water", "Natural still water.", "beverages", 9.99, "1.5 L", 300, 50, False, None),
    ("DEMO-BV-002", "Orange Juice", "100% orange juice.", "beverages", 34.99, "1 L", 60, 12, True, 29.99),
    ("DEMO-BV-003", "Rooibos Tea", "Rooibos tea bags.", "beverages", 36.99, "80 bags", 50, 10, False, None),
    ("DEMO-BV-004", "Ground Coffee", "Medium roast ground coffee.", "beverages", 89.99, "250 g", 2, 8, False, None),
    ("DEMO-BV-005", "Cola", "Sparkling cola drink.", "beverages", 24.99, "2 L", 140, 25, False, None),
    ("DEMO-FZ-001", "Frozen Peas", "Garden peas.", "frozen", 29.99, "1 kg", 65, 12, False, None),
    ("DEMO-FZ-002", "Fish Fingers", "Crumbed hake fish fingers.", "frozen", 54.99, "10 pack", 40, 10, True, None),
    ("DEMO-FZ-003", "Vanilla Ice Cream", "Creamy vanilla ice cream.", "frozen", 59.99, "2 L", 0, 8, False, None),
    ("DEMO-FZ-004", "Oven Chips", "Crinkle-cut oven chips.", "frozen", 44.99, "1 kg", 48, 10, False, 39.99),
    ("DEMO-FZ-005", "Mixed Vegetables", "Frozen mixed vegetables.", "frozen", 32.99, "1 kg", 52, 10, False, None),
    ("DEMO-HH-001", "Dishwashing Liquid", "Lemon dishwashing liquid.", "household", 34.99, "750 ml", 75, 15, False, None),
    ("DEMO-HH-002", "Toilet Paper", "Soft 2-ply rolls.", "household", 79.99, "9 rolls", 90, 15, True, 69.99),
    ("DEMO-HH-003", "Laundry Powder", "Washing powder.", "household", 119.99, "2 kg", 4, 8, False, None),
    ("DEMO-HH-004", "Bin Bags", "Heavy duty bin bags.", "household", 29.99, "20 pack", 80, 15, False, None),
    ("DEMO-HH-005", "Kitchen Towels", "Absorbent paper towels.", "household", 39.99, "2 rolls", 66, 12, False, None),
]


def cents(amount: float) -> int:
    return int(round(amount * 100))


def seed_catalogue(session, currency: str) -> dict:
    """Insert any missing demonstration categories/products/inventory. Existing rows are left untouched."""
    added = {"categories": 0, "products": 0}
    cats = {c.slug: c for c in session.scalars(select(Category))}
    for order, (slug, name) in enumerate(CATEGORIES):
        if slug not in cats:
            cats[slug] = Category(slug=slug, name=name, sort_order=order)
            session.add(cats[slug])
            added["categories"] += 1
    session.flush()
    have = set(session.scalars(select(Product.sku)))
    for sku, name, desc, cat, price, unit, stock, reorder, featured, offer in PRODUCTS:
        if sku in have:
            continue
        p = Product(sku=sku, name=name, description=desc + " (Demonstration product)", category_id=cats[cat].id,
                    price_cents=cents(price), offer_price_cents=cents(offer) if offer else None, currency=currency,
                    unit=unit, image_ref=f"/products/{sku}.jpg", is_featured=featured, is_demo=True)
        session.add(p)
        session.flush()
        session.add(Inventory(product_id=p.id, available_quantity=stock, reserved_quantity=0, reorder_threshold=reorder))
        session.add(StockMovement(product_id=p.id, delta_available=stock, delta_reserved=0, reason="initial_stock",
                                  note="seeded demonstration stock"))
        added["products"] += 1
    return added


def convert_demo_currency(session, currency: str) -> int:
    """Switch the sample (is_demo) products to the store currency. Prices are sample figures, so only the currency
    label changes. Orders already placed keep the currency they were placed in."""
    from sqlalchemy import update
    return session.execute(update(Product).where(Product.is_demo.is_(True), Product.currency != currency)
                           .values(currency=currency)).rowcount


def convert_demo_images(session) -> int:
    """Point sample products that still use the old category illustration at their own photo (/products/<SKU>.jpg).
    Products whose image was changed by the owner are left alone."""
    from sqlalchemy import update
    return session.execute(update(Product).where(Product.is_demo.is_(True), Product.image_ref.like("/products/%.svg"))
                           .values(image_ref="/products/" + Product.sku + ".jpg")).rowcount


def seed_demo_users(session) -> int:
    have = set(session.scalars(select(AppUser.email)))
    added = 0
    for email, name, role in DEMO_USERS:
        if email not in have:
            session.add(AppUser(email=email, full_name=name, role=role, password_hash=hash_password(DEMO_PASSWORD)))
            added += 1
    return added


def seed_zambian_catalogue(session, currency: str) -> dict:
    """Insert any missing products from db/catalogue_zm.py with their price provenance. Existing rows (including
    administrator edits) are never touched. Prices are in kwacha, so nothing is seeded for another store currency."""
    added = {"zm_categories": 0, "zm_products": 0}
    if currency != "ZMW":
        return added
    cats = {c.slug: c for c in session.scalars(select(Category))}
    for order, (slug, name) in enumerate(zm.CATEGORIES):
        if slug not in cats:
            cats[slug] = Category(slug=slug, name=name, sort_order=order)
            session.add(cats[slug])
            added["zm_categories"] += 1
    session.flush()
    have = set(session.scalars(select(Product.sku)))
    for (sku, name, brand, pack, unit, cat, price, status, src, stock, reorder, featured, img, desc) in zm.P:
        if sku in have:
            continue
        offer = zm.DEMO_OFFERS.get(sku)
        observed = status == "observed"
        p = Product(sku=sku, name=name, brand=brand, pack_size=pack, description=desc, category_id=cats[cat].id,
                    price_cents=cents(price), offer_price_cents=cents(offer[0]) if offer else None,
                    offer_ends_on=offer[1] if offer else None, currency=currency, unit=unit,
                    image_ref=f"/products/{cat}.svg", image_alt=name, image_status="placeholder",
                    price_status=status, is_featured=featured, is_demo=True,
                    price_source_name=zm.LD if observed else "Demonstration estimate",
                    price_source_url=zm.LD_BASE + src if observed else "",
                    price_source_type="retailer website" if observed else "estimate",
                    price_checked_on=zm.CHECKED if observed else None)
        for k, v in zm.image_fields(img).items():
            setattr(p, k, v)
        session.add(p)
        session.flush()
        session.add(Inventory(product_id=p.id, available_quantity=stock, reserved_quantity=0, reorder_threshold=reorder))
        session.add(StockMovement(product_id=p.id, delta_available=stock, delta_reserved=0, reason="initial_stock",
                                  note="seeded demonstration stock"))
        session.add(PriceHistory(product_id=p.id, price_cents=p.price_cents, offer_price_cents=p.offer_price_cents,
                                 currency=currency, price_status=status, source_url=p.price_source_url, recorded_by="seed"))
        added["zm_products"] += 1
    return added


def retire_legacy_demo(session) -> int:
    """Hide the original generic DEMO-* products (wrong/generic photos, invented names). Rows stay for order history."""
    from sqlalchemy import update
    return session.execute(update(Product).where(Product.sku.like("DEMO-%"), Product.is_active.is_(True))
                           .values(is_active=False, is_featured=False)).rowcount
