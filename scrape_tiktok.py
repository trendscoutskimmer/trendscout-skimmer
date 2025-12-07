"""
TrendScout TikTok Product Scraper Agent (v1 - seed data)

For now, this just seeds example products into the database so your
UI + /api/products pipeline is fully working.

Later, you can replace `fetch_tiktok_products()` with REAL scraping
or API logic that pulls from TikTok Shop.
"""

from typing import List, Dict

from main import Product, SessionLocal


def fetch_tiktok_products() -> List[Dict]:
    """
    TODO: Replace this with REAL TikTok Shop scraping / API calls.

    For now, this returns a static list of example products so we can
    prove the whole pipeline works end-to-end.
    """
    return [
        {
            "name": "Car Phone Holder",
            "category": "Auto",
            "price": 14.99,
            "commission": 28.0,
            "agentScore": 12.57,
            "virality": 86.7,
            "views7d": 1_500_000,
            "rating": 4.3,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
        {
            "name": "Baby Head Protector",
            "category": "Baby",
            "price": 16.99,
            "commission": 33.0,
            "agentScore": 13.88,
            "virality": 89.1,
            "views7d": 1_900_000,
            "rating": 4.5,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
        {
            "name": "Portable Smoothie Blender",
            "category": "Gadgets",
            "price": 34.99,
            "commission": 20.0,
            "agentScore": 10.56,
            "virality": 81.2,
            "views7d": 1_200_000,
            "rating": 4.7,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
        {
            "name": "Waterproof Couch Cover",
            "category": "Home",
            "price": 49.99,
            "commission": 27.0,
            "agentScore": 12.84,
            "virality": 90.8,
            "views7d": 2_100_000,
            "rating": 5.0,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
        {
            "name": "LED Galaxy Projector",
            "category": "Home",
            "price": 39.99,
            "commission": 25.0,
            "agentScore": 12.59,
            "virality": 92.3,
            "views7d": 2_300_000,
            "rating": 4.9,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
        {
            "name": "Automatic Soap Dispenser",
            "category": "Home",
            "price": 29.99,
            "commission": 18.0,
            "agentScore": 9.87,
            "virality": 80.2,
            "views7d": 875_000,
            "rating": 4.3,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
        {
            "name": "Sunset Lamp",
            "category": "Home",
            "price": 24.99,
            "commission": 22.0,
            "agentScore": 10.70,
            "virality": 78.9,
            "views7d": 980_000,
            "rating": 4.6,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
        {
            "name": "Pet Hair Remover Roller",
            "category": "Pets",
            "price": 19.99,
            "commission": 30.0,
            "agentScore": 13.18,
            "virality": 88.5,
            "views7d": 1_750_000,
            "rating": 4.8,
            "tiktokUrl": "https://www.tiktok.com/",
            "shopUrl": "https://www.tiktok.com/",
        },
    ]


def upsert_products(products: List[Dict]):
    """
    Insert or update products in the DB (by name).
    """
    db = SessionLocal()
    try:
        for p in products:
            name = p["name"]

            existing = (
                db.query(Product)
                .filter(Product.name == name)
                .one_or_none()
            )

            if existing:
                # Update existing row
                existing.category = p.get("category", existing.category)
                existing.price = p.get("price", existing.price)
                existing.commission = p.get("commission", existing.commission)
                existing.agent_score = p.get("agentScore", existing.agent_score)
                existing.virality = p.get("virality", existing.virality)
                existing.views_7d = p.get("views7d", existing.views_7d)
                existing.rating = p.get("rating", existing.rating)
                existing.tiktok_url = p.get("tiktokUrl", existing.tiktok_url)
                existing.shop_url = p.get("shopUrl", existing.shop_url)
            else:
                # Insert new row
                db.add(
                    Product(
                        name=name,
                        category=p.get("category", "Unknown"),
                        price=p.get("price", 0.0),
                        commission=p.get("commission", 0.0),
                        agent_score=p.get("agentScore", 0.0),
                        virality=p.get("virality", 0.0),
                        views_7d=p.get("views7d", 0),
                        rating=p.get("rating", 0.0),
                        tiktok_url=p.get("tiktokUrl", ""),
                        shop_url=p.get("shopUrl", ""),
                    )
                )

        db.commit()
    finally:
        db.close()


def main():
    print("[TrendScout Agent] Fetching TikTok products (stub data)...")
    products = fetch_tiktok_products()
    print(f"[TrendScout Agent] Got {len(products)} products.")
    upsert_products(products)
    print("[TrendScout Agent] Products saved to products.db")


if __name__ == "__main__":
    main()

