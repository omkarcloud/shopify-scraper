"""Live endpoint smoke tests: one call per /shopify/* route against a running
service, with example values proven to return data (2026-10-05). The
listing tooling reads each route's FIRST call from this file's AST as its
working example, so the values stay literals.

Skipped unless SHOPIFY_BASE points at a running service:

    ONLY_SCRAPER=shopify python run.py
    SHOPIFY_BASE=http://127.0.0.1:6002 python -m pytest shopify/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("SHOPIFY_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set SHOPIFY_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_store():
    store = call("/shopify/store", store="allbirds.com")["store"]
    assert store["name"] == "Allbirds" and store["myshopify_domain"] == "weareallbirds.myshopify.com"
    assert store["currency"] == "USD" and store["location"]["country"] == "US" and store["products_count"] > 100
    assert call("/shopify/store/check", store="deathwishcoffee.com")["is_shopify"] is True
    assert call("/shopify/store/apps", store="colourpop.com")["count"] > 5
    assert call("/shopify/store/theme", store="deathwishcoffee.com")["theme"]["name"]
    contacts = call("/shopify/store/contacts", store="deathwishcoffee.com")
    assert contacts["emails"] and contacts["social_profiles"]["instagram"]
    markets = call("/shopify/store/markets", store="deathwishcoffee.com")
    assert markets["countries_count"] > 50 and markets["default_currency"] == "USD"
    assert call("/shopify/store/policies", store="deathwishcoffee.com")["policies"][0]["body_text"]
    assert call("/shopify/store/menus", store="deathwishcoffee.com")["menus"][0]["items"]
    stats = call("/shopify/store/catalog-stats", store="deathwishcoffee.com")
    assert stats["is_complete"] is True and stats["prices"]["median"] > 0 and stats["vendors"]


def test_store_variants():
    # a headless store (Next.js frontend) resolved through its myshopify domain
    headless = call("/shopify/store", store="gymshark.com")["store"]
    assert headless["is_headless"] is True and headless["domain"] == "www.gymshark.com"
    assert call("/shopify/store/check", store="https://www.wikipedia.org/")["is_shopify"] is False
    assert len(call("/shopify/store/policies", store="deathwishcoffee.com", type="refund")["policies"]) == 1
    assert call("/shopify/store/menus", store="deathwishcoffee.com", menu="footer")["count"] == 1


def test_products():
    page = call("/shopify/products", store="allbirds.com", limit=10)
    assert len(page["products"]) == 10 and page["next_cursor"] and page["products"][0]["rating"]
    more = call("/shopify/products", store="allbirds.com", limit=10, cursor=page["next_cursor"])
    assert {p["id"] for p in more["products"]}.isdisjoint({p["id"] for p in page["products"]})
    cheap = call("/shopify/products", store="deathwishcoffee.com", sort="price_asc", product_type="Coffee",
                 is_available="true", max_price=30)["products"]
    # product_type / vendor are phrase matches here ("Coffee" also finds "Coffee Bundle")
    assert cheap and all(p["pricing"]["price"] <= 30 and p["product_type"].startswith("Coffee") for p in cheap)

    product = call("/shopify/products/details", product="https://www.allbirds.com/products/mens-wool-runners")["product"]
    assert product["variants"] and product["variants"][0]["sku"] and product["images"] and product["collections"]
    by_id = call("/shopify/products/details", store="allbirds.com", product=str(product["id"]))["product"]
    assert by_id["handle"] == "mens-wool-runners"
    canada = call("/shopify/products/details", store="kyliecosmetics.com", product="matte-lip-kit", country="CA")
    assert canada["market"]["country"] == "CA" and canada["product"]["pricing"]["currency"] == "CAD"

    found = call("/shopify/products/search", store="allbirds.com", query="wool runner")
    assert found["total_count"] > 10 and found["products"] and found["facets"]
    assert call("/shopify/products/search", store="gymshark.com", query="shorts", option="Size:M",
                is_available="true", sort="price_asc")["products"]

    assert call("/shopify/products/best-sellers", store="gymshark.com", limit=5)["products"][0]["link"].startswith(
        "https://www.gymshark.com/products/")
    assert call("/shopify/products/best-sellers", store="allbirds.com", collection="mens")["collection"]["handle"] == "mens"
    newest = call("/shopify/products/new-arrivals", store="colourpop.com", limit=5)["products"]
    assert newest[0]["created_at"] >= newest[-1]["created_at"]

    sale = call("/shopify/products/on-sale", store="deathwishcoffee.com", limit=5)
    assert sale["products"] and all(p["pricing"]["is_on_sale"] for p in sale["products"]) and sale["next_cursor"]
    assert call("/shopify/products/on-sale", store="deathwishcoffee.com", limit=5, cursor=sale["next_cursor"])["products"]

    assert call("/shopify/products/recommendations", store="allbirds.com", product="mens-wool-runners")["products"]
    stock = call("/shopify/products/inventory", store="allbirds.com", product="mens-wool-runners")
    assert stock["variants"] and any(v["stock_quantity"] for v in stock["variants"])


def test_collections():
    page = call("/shopify/collections", store="allbirds.com", limit=10)
    assert len(page["collections"]) == 10 and page["next_cursor"]
    assert call("/shopify/collections", store="allbirds.com", query="men")["collections"]
    collection = call("/shopify/collections/details", store="allbirds.com", collection="mens")["collection"]
    assert collection["products_count"] > 10 and collection["facets"]
    products = call("/shopify/collections/products", store="allbirds.com", collection="mens", sort="price_asc",
                    max_price=100, limit=10)
    assert products["products"] and all(p["pricing"]["price"] <= 100 for p in products["products"])
    prices = [p["pricing"]["price"] for p in products["products"]]
    assert prices == sorted(prices)


def test_search_suggestions():
    out = call("/shopify/search/suggestions", store="deathwishcoffee.com", query="cof")
    assert out["products"] and out["queries"]
    assert call("/shopify/search/suggestions", store="deathwishcoffee.com", query="cof", types="product")["collections"] == []


def test_content():
    assert call("/shopify/pages", store="deathwishcoffee.com", limit=5)["pages"]
    assert call("/shopify/pages/details", store="deathwishcoffee.com", page="about")["page"]["title"]
    assert call("/shopify/blogs", store="deathwishcoffee.com")["blogs"]
    articles = call("/shopify/blogs/articles", store="deathwishcoffee.com", blog="news", limit=5)
    assert len(articles["articles"]) == 5 and articles["blog"]["handle"] == "news" and articles["next_cursor"]
    assert call("/shopify/blogs/articles", store="deathwishcoffee.com", tag="Coffee Knowledge")["articles"]
    article = call("/shopify/blogs/articles/details",
                   article="https://www.deathwishcoffee.com/blogs/news/how-to-use-an-aeropress")["article"]
    assert article["content_html"] and article["author"]["name"]
    assert call("/shopify/blogs/articles/details", store="deathwishcoffee.com",
                article=str(article["id"]))["article"]["handle"] == "how-to-use-an-aeropress"


def test_errors():
    # paths via variables so the listing tooling never reads an error case
    # as a route's working example
    products, details, collection = "/shopify/products", "/shopify/products/details", "/shopify/collections/products"
    call(products, status=404, store="wikipedia.org")
    call(products, status=400, store="not a domain")
    call(products, status=400, store="allbirds.com", cursor="zzz")
    call(details, status=400, product="mens-wool-runners")
    call(details, status=404, store="allbirds.com", product="nope-nope-nope")
    call(collection, status=404, store="allbirds.com", collection="nope-nope-nope")
