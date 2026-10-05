"""The 26 Shopify endpoints. Every path is served with and without the
`/shopify` prefix, so code generated against the hosted API on RapidAPI
(paths like /products/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in shopify/schemas.py (the
same ones the hosted API uses): ONE param per input — `store` takes a store
domain or any link on the store; `product`, `collection`, `page`, `blog` and
`article` take a handle, a numeric id or a link (a link names its own store,
so `store` is then optional). Unknown params are rejected with a 400 so typos
surface.

Lists page with `cursor`: pass the previous response's `next_cursor`."""
import json

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, NotFound
from shopify import collection, content, products, search, stock, store
from shopify import schemas as S


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Café" would arrive as "CafÃ©")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema, fn):
    """Validate the query, run the scraper, map errors: bad params -> 400,
    missing entity / not a Shopify store -> 404, transport/blocks -> 500."""
    data, error = load_query(schema, query_dict())
    if error:
        return json_response(error, 400)
    try:
        result = fn(**data)
    except ValueError as e:                # bad id / params
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                # the store's API rejected the request
        return json_response({"error": f"shopify rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"shopify {label} failed: {e}"}, 500)
    return json_response(result)


def mount(path, schema, fn):
    """Serve an endpoint at /path and /shopify/path."""
    def handler():
        return call(path.strip("/"), schema, fn)
    handler.__name__ = "shopify_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/shopify" + path, method="GET")(handler)


ENDPOINTS = [
    ("/products/details", S.ProductSchema, products.details),
    ("/products/search", S.ProductSearchSchema, products.search),
    ("/products", S.ProductsSchema, products.list_products),
    ("/products/best-sellers", S.RankedProductsSchema, products.best_sellers),
    ("/products/new-arrivals", S.RankedProductsSchema, products.new_arrivals),
    ("/products/on-sale", S.OnSaleSchema, products.on_sale),
    ("/products/recommendations", S.RecommendationsSchema, products.recommendations),
    ("/products/inventory", S.ProductSchema, stock.inventory),
    ("/collections", S.CollectionsSchema, collection.list_collections),
    ("/collections/details", S.CollectionSchema, collection.details),
    ("/collections/products", S.CollectionProductsSchema, products.collection_products),
    ("/search/suggestions", S.SuggestionsSchema, search.suggestions),
    ("/store", S.StoreMarketSchema, store.profile),
    ("/store/check", S.StoreSchema, store.check),
    ("/store/apps", S.StoreSchema, store.apps),
    ("/store/theme", S.StoreSchema, store.theme),
    ("/store/contacts", S.StoreSchema, store.contacts),
    ("/store/markets", S.StoreSchema, store.markets),
    ("/store/policies", S.PoliciesSchema, store.policies),
    ("/store/menus", S.MenusSchema, store.menus),
    ("/store/catalog-stats", S.CatalogStatsSchema, store.catalog_stats),
    ("/pages", S.PagesSchema, content.pages),
    ("/pages/details", S.PageSchema, content.page_details),
    ("/blogs", S.BlogsSchema, content.blogs),
    ("/blogs/articles", S.ArticlesSchema, content.articles),
    ("/blogs/articles/details", S.ArticleSchema, content.article_details),
]

for _path, _schema, _fn in ENDPOINTS:
    mount(_path, _schema, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
