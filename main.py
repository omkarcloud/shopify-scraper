"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The functions live in shopify/ (products, stock, collection,
search, store, content). A store is its domain; a product, collection, page
or article is the validated ref the API builds, so go through shopify.refs
first.
"""
import json
import os

from shopify import products, refs, store

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a product link carries its store: every variant, image, price and rating
    product = refs.resolve_product("https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow")
    save("product_gloss_bomb.json", products.details(product.pop("store"), product))

    # any Shopify store by domain: its best sellers, in rank order
    save("best_sellers_fentybeauty.json", products.best_sellers("fentybeauty.com", limit=25))

    # who the store is: location, currency, payments, markets, theme
    save("store_fentybeauty.json", store.profile("fentybeauty.com"))
