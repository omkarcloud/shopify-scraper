"""Offline tests: ref parsing, the request schemas, homepage facts / app
detection and the normalizers against raw Storefront API responses captured
2026-10-05 (shopify/fixtures/*.json from allbirds.com and deathwishcoffee.com).

    python -m pytest shopify/test_parsers.py -q
"""
import json
import os

import pytest

from schema_fields import load_query
from shopify import apps, parsers as P, refs, schemas, shared, stock, storefront
from shopify.fetch import Store

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def html(name):
    with open(os.path.join(FIX, name + ".html"), encoding="utf-8") as f:
        return f.read()


def shop(headless=False, origin="https://www.allbirds.com"):
    return Store(host="allbirds.com", origin=origin, api=origin, token=None,
                 myshopify_domain="weareallbirds.myshopify.com", shop={}, home=None, is_headless=headless)


def _clean_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            assert not key.startswith("_"), f"{path}.{key} is internal"
            _clean_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _clean_keys(value, f"{path}[{i}]")


def _no_gids(obj, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            _no_gids(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_gids(value, f"{path}[{i}]")
    elif isinstance(obj, str):
        assert not obj.startswith("gid://"), f"{path} leaks a gid"


def check(obj):
    _clean_keys(obj)
    _no_gids(obj)
    return obj


# ---- refs -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("allbirds.com", "allbirds.com"), ("WWW.Allbirds.com", "www.allbirds.com"),
    ("https://www.allbirds.com/collections/mens?x=1", "www.allbirds.com"),
    ("//shop.flipperzero.one/products/x", "shop.flipperzero.one"),
    ("weareallbirds.myshopify.com", "weareallbirds.myshopify.com"),
    ("allbirds.com:443/products/x", "allbirds.com"),
])
def test_resolve_store(value, expected):
    assert refs.resolve_store(value) == expected


@pytest.mark.parametrize("value", ["", "allbirds", "not a domain", "http://", "mens-wool-runners"])
def test_resolve_store_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_store(value)


@pytest.mark.parametrize("value, expected", [
    ("mens-wool-runners", {"store": None, "handle": "mens-wool-runners", "id": None}),
    ("7340901859408", {"store": None, "handle": None, "id": 7340901859408}),
    ("gid://shopify/Product/7340901859408", {"store": None, "handle": None, "id": 7340901859408}),
    ("https://www.allbirds.com/products/mens-wool-runners?variant=31338073981072",
     {"store": "www.allbirds.com", "handle": "mens-wool-runners", "id": None}),
    ("www.allbirds.com/en-ca/collections/mens/products/mens-wool-runners.json",
     {"store": "www.allbirds.com", "handle": "mens-wool-runners", "id": None}),
    ("https://loom.fr/products/t-shirt-%C3%A9t%C3%A9", {"store": "loom.fr", "handle": "t-shirt-été", "id": None}),
    ("12345", {"store": None, "handle": "12345", "id": None}),      # short digits = a handle
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value", ["", "https://www.allbirds.com/collections/mens", "has space",
                                   "gid://shopify/Collection/1", "a/b"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


def test_resolve_collection_page_blog():
    assert refs.resolve_collection("https://www.allbirds.com/collections/mens/products/x") == {
        "store": "www.allbirds.com", "handle": "mens", "id": None}
    assert refs.resolve_collection("https://www.allbirds.com/collections/mens")["handle"] == "mens"
    assert refs.resolve_collection("gid://shopify/Collection/132815978576")["id"] == 132815978576
    assert refs.resolve_page("https://www.allbirds.com/pages/our-story")["handle"] == "our-story"
    assert refs.resolve_blog("https://www.deathwishcoffee.com/blogs/news/some-post")["handle"] == "news"
    assert refs.resolve_blog("news.atom")["handle"] == "news"


@pytest.mark.parametrize("value, expected", [
    ("news/how-to-use-an-aeropress", {"store": None, "blog": "news", "handle": "how-to-use-an-aeropress", "id": None}),
    ("https://www.deathwishcoffee.com/blogs/news/how-to-use-an-aeropress?x=1",
     {"store": "www.deathwishcoffee.com", "blog": "news", "handle": "how-to-use-an-aeropress", "id": None}),
    ("gid://shopify/Article/16359541", {"store": None, "blog": None, "handle": None, "id": 16359541}),
    ("16359541", {"store": None, "blog": None, "handle": None, "id": 16359541}),
])
def test_resolve_article(value, expected):
    assert refs.resolve_article(value) == expected


@pytest.mark.parametrize("value", ["", "how-to-use-an-aeropress", "https://www.deathwishcoffee.com/blogs/news",
                                   "https://www.deathwishcoffee.com/pages/x/y"])
def test_resolve_article_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_article(value)


def test_numeric_id_and_gid():
    assert refs.numeric_id("gid://shopify/Cart/abc?key=1") is None
    assert refs.numeric_id("gid://shopify/ProductVariant/31338073981072") == 31338073981072
    assert refs.gid("Product", 5) == "gid://shopify/Product/5"


# ---- schemas --------------------------------------------------------------------------

def test_entity_link_names_its_store():
    data, error = load_query(schemas.ProductSchema, {"product": "https://www.allbirds.com/products/mens-wool-runners"})
    assert error is None
    assert data["store"] == "www.allbirds.com" and data["product"] == {"handle": "mens-wool-runners", "id": None}


def test_entity_handle_needs_store():
    data, error = load_query(schemas.ProductSchema, {"product": "mens-wool-runners"})
    assert data is None and "store" in error["errors"]
    data, error = load_query(schemas.ProductSchema, {"product": "mens-wool-runners", "store": "allbirds.com"})
    assert error is None and data["store"] == "allbirds.com"


def test_link_store_wins_over_store_param():
    data, _ = load_query(schemas.CollectionSchema, {"collection": "https://a-store.com/collections/x",
                                                    "store": "other-store.com"})
    assert data["store"] == "a-store.com"


def test_optional_entity_schemas():
    data, error = load_query(schemas.RankedProductsSchema, {"store": "allbirds.com"})
    assert error is None and data["collection"] is None and data["limit"] == 50
    data, error = load_query(schemas.ArticlesSchema, {})
    assert data is None and "store" in error["errors"]
    # list routes always take `store`, even next to a collection / blog link
    assert load_query(schemas.RankedProductsSchema, {"collection": "https://www.allbirds.com/collections/mens"})[1]


def test_schema_validation_errors():
    assert load_query(schemas.ProductsSchema, {"store": "allbirds.com", "sort": "nope"})[1]
    assert load_query(schemas.ProductsSchema, {"store": "allbirds.com", "limit": "251"})[1]
    assert load_query(schemas.ProductsSchema, {"store": "allbirds.com", "min_price": "9", "max_price": "5"})[1]
    assert load_query(schemas.ProductsSchema, {"store": "allbirds.com", "typo": "1"})[1]
    assert load_query(schemas.ProductSearchSchema, {"store": "allbirds.com", "query": "x", "option": "Red"})[1]
    assert load_query(schemas.CollectionsSchema, {"store": "allbirds.com", "sort": "relevance"})[1]
    assert load_query(schemas.StoreMarketSchema, {"store": "allbirds.com", "country": "ZZ"})[1]
    data, error = load_query(schemas.ProductSearchSchema, {"store": "allbirds.com", "query": " wool ",
                                                           "option": "Color: Red", "country": "ca", "language": "FR"})
    assert error is None
    assert data["option"] == {"name": "Color", "value": "Red"} and data["country"] == "CA" and data["language"] == "fr"


# ---- shared builders --------------------------------------------------------------------

def test_product_query_and_filters():
    assert shared.product_query() is None
    assert shared.product_query(vendor='Death "Wish"', tag="Merch", is_available=True, min_price=10, max_price=25.5) == \
        'vendor:"Death \\"Wish\\"" AND tag:"Merch" AND available_for_sale:true AND variants.price:>=10 AND variants.price:<=25.5'
    assert shared.product_filters() is None
    assert shared.product_filters(is_available=False, min_price=5, option={"name": "Size", "value": "M"}) == [
        {"available": False}, {"price": {"min": 5.0}}, {"variantOption": {"name": "Size", "value": "M"}}]
    assert shared.language_enum("pt-BR") == "PT_BR" and shared.language_enum("en-US") == "EN"
    assert shared.language_enum(None) is None


# ---- homepage facts / apps --------------------------------------------------------------

def test_home_facts_online_store():
    facts = storefront.home_facts(html("home"), "https://www.acmecoffee.com/", {"Powered-By": "Shopify"})
    assert facts["origin"] == "https://www.acmecoffee.com"
    assert facts["token"] == "0123456789abcdef0123456789abcdef"
    assert facts["myshopify_domain"] == "acme-coffee.myshopify.com"
    assert facts["myshopify_candidates"][0] == "acme-coffee.myshopify.com"
    assert facts["is_online_store"] is True and facts["is_storefront_locked"] is False
    assert facts["shop_id"] == 2717209 and facts["locale"] == "en" and facts["currency"] == "USD"
    assert facts["title"] == "Acme Coffee & Co. | Strong Coffee" and facts["site_name"] == "Acme Coffee"
    assert facts["share_image"] == "https://cdn.shopify.com/s/files/1/0001/0002/files/share.jpg?v=1"
    assert facts["favicon"] == "https://www.acmecoffee.com/cdn/shop/files/favicon.png?v=2"
    assert {"powered_by_header", "shopify_theme_object", "shopify_shop_object", "storefront_access_token"} <= set(facts["signals"])
    theme = P.theme(facts["theme"])
    assert theme == {"id": 133466587191, "name": "Dawn", "version": "10.0.0", "installed_name": "acme/production",
                     "theme_store_id": 887, "is_theme_store_theme": True, "role": "main"}


def test_home_facts_headless_and_empty():
    facts = storefront.home_facts(html("home_headless"), "https://www.brand.com/en-us", {})
    assert facts["is_online_store"] is False and facts["token"] is None and facts["theme"] is None
    assert facts["myshopify_candidates"] == ["brandusa.myshopify.com", "brand-stage-eu.myshopify.com"]
    assert facts["commerce_hosts"] == ["checkout.brand.com"]
    assert facts["origin"] == "https://www.brand.com"
    empty = storefront.home_facts("", "", None)
    assert empty["signals"] == [] and empty["apps"] == [] and empty["origin"] is None


def test_apps_detect():
    found = apps.detect(html("home"))
    names = [a["name"] for a in found]
    assert names[:2] == ["Klaviyo", "Some Brand New App"]        # app embeds first, unknown ones kept
    assert names.count("Klaviyo") == 1                            # embed + script host = one app
    assert {"Judge.me Product Reviews", "Smile Rewards"} <= set(names)
    by_name = {a["name"]: a for a in found}
    assert by_name["Klaviyo"] == {"name": "Klaviyo", "category": "email_sms_marketing",
                                  "handle": "klaviyo-email-marketing-sms", "detected_via": "app_embed"}
    assert by_name["Some Brand New App"]["category"] == "other"
    assert by_name["Smile Rewards"]["detected_via"] == "script"
    assert apps.detect("") == [] and apps.detect(None) == []
    check(found)


# ---- products ---------------------------------------------------------------------------

def test_product_cards():
    raw = fx("products")["products"]
    extra = {n["id"]: n for n in fx("product_metafields")["nodes"]}
    for node in raw["nodes"]:
        node.update({k: v for k, v in extra.get(node["id"], {}).items() if k != "id"})
    cards = check(P.product_cards(shop(), raw["nodes"]))
    assert len(cards) == 3
    first = cards[0]
    assert list(first)[:4] == ["id", "handle", "title", "link"]
    assert first["id"] == 1878193471557 and first["handle"] == "mens-wool-runners"
    assert first["link"] == "https://www.allbirds.com/products/mens-wool-runners"
    assert first["vendor"] == "Allbirds" and first["product_type"] == "Shoes"
    assert first["category"] == {"id": "aa-8", "name": "Shoes"}
    assert first["is_available"] is True and first["is_gift_card"] is False
    assert isinstance(first["rating"], float) and 1 <= first["rating"] <= 5 and first["reviews_count"] > 1000
    assert first["pricing"]["currency"] == "USD" and isinstance(first["pricing"]["price"], float)
    assert first["pricing"]["is_on_sale"] is False and first["pricing"]["compare_at_price"] is None
    assert first["options"] == [{"name": "Size", "values": ["8", "9", "10", "11", "12", "13", "14"]}]
    assert first["variants_count"] == 7
    assert first["image"]["link"].startswith("https://cdn.shopify.com/") and first["image"]["width"] == 1600
    assert first["created_at"] == "2018-11-12T22:25:43Z"
    assert P.page_info(raw)[1] is True and P.page_info(raw)[0]


def test_product_card_without_token_has_null_rating():
    card = P.product_card(shop(), fx("products")["products"]["nodes"][0])
    assert card["rating"] is None and card["reviews_count"] is None


def test_product_details():
    raw = fx("product_details")["product"]
    raw.update({k: v for k, v in fx("product_details_metafields")["nodes"][0].items() if k != "id"})
    item = check(P.product_details(shop(), raw, P.nodes(raw["variants"])))
    assert item["id"] == 1878193471557 and item["has_only_default_variant"] is False
    assert item["category"]["path"] == ["Apparel & Accessories", "Shoes"]
    assert item["description"] and item["description_html"].startswith("<")
    assert len(item["variants"]) == item["variants_count"] == 7
    variant = item["variants"][0]
    assert variant["id"] == 31338073981072 and variant["title"] == "8" and variant["sku"] == "WR3MNCW080"
    assert variant["barcode"] == "843416126274"
    assert variant["link"] == "https://www.allbirds.com/products/mens-wool-runners?variant=31338073981072"
    assert variant["price"] == 110.0 and variant["currency"] == "USD" and variant["is_on_sale"] is False
    assert variant["options"] == [{"name": "Size", "value": "8"}]
    assert variant["weight"] == {"value": 1.872, "unit": "pounds"}
    assert variant["quantity_rule"] == {"minimum": 1, "maximum": None, "increment": 1}
    assert item["images"] and all(i["link"] for i in item["images"])
    assert all(m["type"] != "image" for m in item["media"])
    assert any(c["handle"] == "mens" and c["link"] == "https://www.allbirds.com/collections/mens"
               for c in item["collections"])
    assert item["rating"] is not None and set(item["seo"]) == {"title", "description"}
    assert list(item)[-3:] == ["created_at", "updated_at", "published_at"]


def test_product_subscription_and_default_variant_noise():
    raw = fx("product_subscription")["product"]
    item = check(P.product_details(shop(origin="https://www.deathwishcoffee.com"), raw, P.nodes(raw["variants"])))
    group = item["subscriptions"][0]
    assert group["name"] == "Subscribe and Save" and group["options"][0]["values"] == ["30 days", "60 days", "90 days"]
    assert group["plans"][0]["is_recurring_delivery"] is True and group["plans"][0]["id"]
    assert item["rating"] is None and item["metafields"] == []        # captured tokenless
    default = P.variant({"id": "gid://shopify/ProductVariant/9", "title": "Default Title",
                         "selectedOptions": [{"name": "Title", "value": "Default Title"}],
                         "price": {"amount": "10.0", "currencyCode": "USD"},
                         "compareAtPrice": {"amount": "20.0", "currencyCode": "USD"}}, "https://x.com/products/y")
    assert default["title"] is None and default["options"] == []
    assert default["is_on_sale"] is True and default["compare_at_price"] == 20.0 and default["discount_percent"] == 50.0
    assert P._options([{"name": "Title", "optionValues": [{"name": "Default Title"}]}]) == []


def test_pricing_block():
    money = lambda v: {"amount": v, "currencyCode": "EUR"}
    block = P.pricing({"minVariantPrice": money("15.0"), "maxVariantPrice": money("30.0")},
                      {"minVariantPrice": money("20.0"), "maxVariantPrice": money("40.0")})
    assert block == {"currency": "EUR", "price": 15.0, "price_max": 30.0, "compare_at_price": 20.0,
                     "compare_at_price_max": 40.0, "is_on_sale": True, "discount_percent": 25.0,
                     "has_price_range": True}
    plain = P.pricing({"minVariantPrice": money("15.0"), "maxVariantPrice": money("15.0")},
                      {"minVariantPrice": money("0.0"), "maxVariantPrice": money("0.0")})
    assert plain["is_on_sale"] is False and plain["compare_at_price"] is None and plain["discount_percent"] is None
    assert P.pricing(None, None)["price"] is None


def test_headless_links_use_public_origin():
    raw = {"handle": "shorts", "onlineStoreUrl": "https://us.checkout.gymshark.com/products/shorts"}
    assert P.product_link(shop(headless=True, origin="https://www.gymshark.com"), raw) == \
        "https://www.gymshark.com/products/shorts"
    assert P.product_link(shop(), raw) == "https://us.checkout.gymshark.com/products/shorts"
    assert P.product_link(shop(), {"handle": "x", "onlineStoreUrl": None}) == "https://www.allbirds.com/products/x"


def test_media_and_metafields():
    video = P.media_item({"id": "gid://shopify/Video/7", "mediaContentType": "VIDEO", "alt": "clip",
                          "previewImage": {"url": "https://cdn/x.jpg"},
                          "sources": [{"url": "https://cdn/x.mp4", "mimeType": "video/mp4", "format": "mp4",
                                       "height": 720, "width": 1280}]})
    assert check(video)["type"] == "video" and video["sources"][0]["link"] == "https://cdn/x.mp4"
    fields = P.metafields([None, {"namespace": "reviews", "key": "rating", "type": "rating",
                                  "value": '{"scale_min":"1.0","scale_max":"5.0","value":"4.6"}'},
                           {"namespace": "custom", "key": "pieces", "type": "number_integer", "value": "3"},
                           {"namespace": "custom", "key": "empty", "type": "single_line_text_field", "value": ""}])
    assert fields == [{"namespace": "reviews", "key": "rating", "type": "rating",
                       "value": {"scale_min": "1.0", "scale_max": "5.0", "value": "4.6"}},
                      {"namespace": "custom", "key": "pieces", "type": "number_integer", "value": 3}]


def test_search_and_facets():
    raw = fx("search")["search"]
    assert raw["totalCount"] > 100
    assert len(P.product_cards(shop(), raw["nodes"])) == 2
    found = check(P.facets(raw["productFilters"]))
    assert all(set(f) >= {"id", "label", "type"} for f in found)
    price = next(f for f in found if f["type"] == "price_range")
    assert price["min"] == 0.0 and price["max"] > 0 and "values" not in price
    listed = next(f for f in found if f["type"] == "list")
    assert listed["values"] and set(listed["values"][0]) == {"label", "count"}


def test_stock_report():
    raw = fx("product_stock")["product"]
    variants = P.nodes(raw["variants"])
    ids = [v["id"] for v in variants]
    quantities, notes = stock.cart_quantities(fx("cart_probe")["cartCreate"], ids)
    assert notes == [] and set(quantities) == set(ids)
    report = check(stock.summarize(shop(), raw, variants, quantities, notes))
    assert report["variants_count"] == 7 and report["is_exact"] is True
    assert report["total_stock_quantity"] == sum(v["stock_quantity"] for v in report["variants"])
    statuses = {v["stock_status"] for v in report["variants"]}
    assert statuses <= {"in_stock", "out_of_stock"} and "in_stock" in statuses
    for row in report["variants"]:
        assert (row["stock_status"] == "out_of_stock") == (row["stock_quantity"] == 0)

    # an untracked variant keeps the full ask; a rejected cart is "unknown"
    quantities[ids[0]] = stock.PROBE_QUANTITY
    untracked = stock.summarize(shop(), raw, variants, quantities, [])
    assert untracked["variants"][0]["stock_status"] == "not_tracked" and untracked["variants"][0]["stock_quantity"] is None
    assert untracked["is_exact"] is False and untracked["total_stock_quantity"] is None
    rejected, messages = stock.cart_quantities({"cart": None, "userErrors": [{"message": "Max 10 per order."}]}, ids)
    assert rejected is None and messages == ["Max 10 per order."]
    unknown = stock.summarize(shop(), raw, variants, {}, messages)
    assert {v["stock_status"] for v in unknown["variants"]} == {"unknown"} and unknown["notes"] == messages


# ---- collections ------------------------------------------------------------------------

def test_collections():
    rows = check([P.collection(shop(), n) for n in P.nodes(fx("collections")["collections"])])
    assert len(rows) == 3 and all(r["handle"] and r["link"].startswith("https://www.allbirds.com/collections/") for r in rows)
    raw = fx("collection")["collection"]
    item = check(P.collection(shop(), raw))
    assert item["id"] == 132815978576 and item["title"] == "Men's Shoes" and item["seo"]["title"]
    assert item["updated_at"].endswith("Z")
    filters = raw["products"]["filters"]
    assert P.facets(filters)
    assert P.facet_total([{"id": "filter.v.availability", "values": [{"count": 700}, {"count": 260}]}]) == 960
    assert P.facet_total([{"id": "filter.v.price", "values": []}]) is None


# ---- content ----------------------------------------------------------------------------

def test_pages_blogs_articles():
    dwc = shop(origin="https://www.deathwishcoffee.com")
    pages = check([P.page(dwc, n) for n in P.nodes(fx("pages")["pages"])])
    assert len(pages) == 3 and "body_html" not in pages[0] and pages[0]["link"].startswith("https://")
    page = check(P.page(dwc, fx("page")["page"], detailed=True))
    assert page["handle"] == "about" and "body_html" in page and "body_text" in page

    blogs = check([P.blog(dwc, n) for n in P.nodes(fx("blogs")["blogs"])])
    assert blogs[0]["handle"] == "news" and blogs[0]["authors"] and blogs[0]["link"].endswith("/blogs/news")

    parent = fx("blog_articles")["blog"]
    cards = check([P.article(dwc, n) for n in P.nodes(parent["articles"])])
    assert len(cards) == 2 and cards[0]["blog"]["handle"] == "news" and cards[0]["published_at"].endswith("Z")
    assert "content_html" not in cards[0]

    raw = fx("article")["blog"]
    full = check(P.article(dwc, raw["articleByHandle"], detailed=True, blog_raw=raw))
    assert full["handle"] == "how-to-use-an-aeropress" and full["author"]["name"] == "Teah Teriele"
    assert full["link"] == "https://www.deathwishcoffee.com/blogs/news/how-to-use-an-aeropress"
    assert full["content"] and full["content_html"].startswith("<") and full["tags"] == ["Coffee Knowledge"]
    assert full["comments_count"] == len(full["comments"]) == 3 and full["comments"][0]["author_name"]
    assert "email" not in json.dumps(full["comments"])


def test_suggestions_shapes():
    raw = fx("suggestions")["predictiveSearch"]
    assert len(P.product_cards(shop(), raw["products"])) == 2
    assert all(q["text"] for q in raw["queries"])


def test_html_to_text():
    assert P.html_to_text("<p>Hello <b>big</b> world</p><ul><li>one</li><li>two</li></ul>") == "Hello big world\none\ntwo"
    assert P.html_to_text("plain") == "plain" and P.html_to_text("") is None and P.html_to_text(None) is None


# ---- menus / store ----------------------------------------------------------------------

def test_menus():
    data = fx("menus")
    assert data["m2"] is None                                   # an unknown handle is simply absent
    main = check(P.menu(data["m0"]))
    assert main["handle"] == "main-menu" and main["items_count"] == len(main["items"])
    shop_item = next(i for i in main["items"] if i["title"] == "Shop")
    coffee = shop_item["items"][0]
    assert coffee["type"] == "collection" and coffee["resource"] == {"type": "collection", "handle": "coffee"}
    assert coffee["items"] and coffee["items"][0]["link"].startswith("https://")


def test_store_profile():
    data = fx("shop")
    store = shop()
    store.home = storefront.home_facts(html("home"), "https://www.allbirds.com/", {})
    profile = check(P.store_profile(store, data["shop"], data["localization"], fx("meta")))
    assert list(profile)[:4] == ["id", "name", "domain", "link"]
    assert profile["id"] == 11044168 and profile["name"] == "Allbirds" and profile["domain"] == "www.allbirds.com"
    assert profile["myshopify_domain"] == "weareallbirds.myshopify.com"
    assert profile["location"] == {"city": "Beverly Hills", "province": "California", "country": "US"}
    assert profile["currency"] == "USD" and profile["products_count"] > 100 and profile["collections_count"] > 100
    assert "visa" in profile["payments"]["accepted_card_brands"]
    assert profile["payments"]["has_shop_pay_installments"] is True
    assert profile["brand"]["logo"]["link"].startswith("https://cdn.shopify.com/")
    assert profile["localization"]["default_country"] == "US" and profile["localization"]["languages"][0]["code"] == "en"
    assert profile["theme"]["name"] == "Dawn" and profile["apps_count"] >= 3
    assert {p["type"] for p in profile["policies"]} >= {"privacy", "refund"}

    # nothing but a store: every field degrades to null / empty, no crash
    bare = check(P.store_profile(shop(), None, None, None))
    assert bare["name"] is None and bare["theme"] is None and bare["apps_count"] is None and bare["policies"] == []


def test_markets_and_policies():
    data = fx("markets")
    rows = check([P.country_market(c) for c in data["localization"]["availableCountries"]])
    assert rows[0]["code"] and rows[0]["currency"]["code"] and rows[0]["languages"][0]["code"] == "en"
    assert rows[0]["unit_system"] in ("metric", "imperial")
    full = check(P.policies(fx("policies")["shop"], detailed=True))
    assert {p["type"] for p in full} >= {"privacy", "refund", "terms"}
    assert all(p["body_text"] and p["link"].startswith("https://") for p in full)
    assert all("body_html" not in p for p in P.policies(fx("policies")["shop"]))


# ---- robustness -------------------------------------------------------------------------

@pytest.mark.parametrize("junk", [None, {}, [], "x", 5, {"id": None, "variants": None, "options": "bad", "tags": 7}])
def test_parsers_survive_partial_nodes(junk):
    store = shop()
    P.product_card(store, junk)
    P.product_details(store, junk, [junk] if isinstance(junk, dict) else [])
    P.variant(junk, None)
    P.collection(store, junk)
    P.page(store, junk, detailed=True)
    P.blog(store, junk)
    P.article(store, junk, detailed=True)
    P.menu(junk)
    P.media_item(junk)
    P.subscription_group(junk)
    P.facets(junk)
    P.metafields(junk)
    P.policies(junk, detailed=True)
    P.country_market(junk)
    P.store_profile(store, junk, junk, junk)
    assert P.product_cards(store, junk) == []
    assert P.page_info(junk) == (None, False)
    assert P.market(junk) == {"country": None, "language": None}
    stock.summarize(store, junk if isinstance(junk, dict) else {}, [], {}, [])


def test_scalars():
    assert P.iso_datetime("2026-09-25T08:48:06-04:00") == "2026-09-25T12:48:06Z"
    assert P.iso_datetime("garbage") is None and P.iso_datetime(None) is None
    assert P.to_float("110.0") == 110.0 and P.to_float("x") is None and P.to_int("7.0") == 7 and P.to_int(True) is None
    assert P.text("  ") is None and P.text({"a": 1}) is None
    assert P.discount_percent(15, 20) == 25.0 and P.discount_percent(20, 20) is None and P.discount_percent(None, 5) is None
    assert P.market({"country": "CA", "language": "PT_BR"}) == {"country": "CA", "language": "pt-br"}
