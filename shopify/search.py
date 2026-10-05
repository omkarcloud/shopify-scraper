"""/shopify/search/suggestions — the store's predictive search: what its
search box drops down while typing (query completions, products,
collections, pages, articles). Full product search is products.search."""
from shopify import parsers as P
from shopify import queries as Q
from shopify import shared
from shopify.fetch import gql, resolve

TYPES = ["product", "collection", "page", "article", "query"]


def suggestions(store, query, types=None, limit=5, country=None, language=None):
    shop = resolve(store)
    types = types or TYPES
    data = gql(shop, Q.SUGGESTIONS, {"query": query, "limit": limit, "types": [t.upper() for t in types]},
               label="search suggestions", **shared.context(country, language))
    raw = P.as_dict(data.get("predictiveSearch"))
    queries = [{"text": P.text(q.get("text")), "styled_text": P.text(q.get("styledText"))}
               for q in P.as_list(raw.get("queries")) if isinstance(q, dict) and P.text(q.get("text"))]
    collections = []
    for item in P.as_list(raw.get("collections")):
        if isinstance(item, dict):
            collections.append({**P.collection_ref(shop, item), "image": P.image(item.get("image"))})
    pages = [{k: v for k, v in P.page(shop, item).items() if k in ("id", "handle", "title", "link")}
             for item in P.as_list(raw.get("pages")) if isinstance(item, dict)]
    articles = []
    for item in P.as_list(raw.get("articles")):
        if isinstance(item, dict):
            full = P.article(shop, item)
            articles.append({"id": full["id"], "handle": full["handle"], "title": full["title"],
                             "link": full["link"], "image": full["image"], "blog": full["blog"]})
    return {
        **shared.envelope(shop, data),
        "query": query,
        "queries": queries,
        "products": shared.cards(shop, raw.get("products")),
        "collections": collections,
        "pages": pages,
        "articles": articles,
    }
