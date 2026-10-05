"""/shopify/collections* — a store's collections: the list (searchable,
sortable) and one collection with its product count and facets. The
collection's products live in products.collection_products."""
from shopify import parsers as P
from shopify import queries as Q
from shopify import shared
from shopify.fetch import ShopifyNotFound, gather, gql, resolve, rest_json

# public sort -> (CollectionSortKeys, reverse)
COLLECTION_LIST_SORTS = {
    "title_asc": ("TITLE", False),
    "title_desc": ("TITLE", True),
    "recently_updated": ("UPDATED_AT", True),
    "relevance": ("RELEVANCE", False),
}


def list_collections(store, query=None, sort=None, limit=50, cursor=None, country=None, language=None):
    """The store's collections; `query` matches the collection title."""
    shop = resolve(store)
    sort = sort or ("relevance" if query else "title_asc")
    sort_key, reverse = COLLECTION_LIST_SORTS[sort]
    data = gql(shop, Q.COLLECTIONS, {"first": limit, "after": cursor, "sortKey": sort_key, "reverse": reverse,
                                     "query": f"title:{query}*" if query else None},
               label="collections", **shared.context(country, language))
    connection = P.as_dict(data.get("collections"))
    next_cursor, has_next = P.page_info(connection)
    collections = [P.collection(shop, n) for n in P.nodes(connection)]
    return {**shared.envelope(shop, data), "query": query, "sort": sort, "count": len(collections),
            "has_next_page": has_next, "next_cursor": next_cursor, "collections": collections}


def details(store, collection, country=None, language=None):
    """One collection: description, image, SEO, how many products it holds
    and the facets (filters with counts) its products can be narrowed by."""
    shop = resolve(store)
    by_id, variables = shared.entity_variables(collection, "Collection")

    def api():
        return gql(shop, Q.COLLECTION_BY_ID if by_id else Q.COLLECTION_BY_HANDLE, variables,
                   label="collection", **shared.context(country, language))

    def theme_json():
        # /collections/<handle>.json is the only place Shopify prints the
        # exact product count; unavailable on headless stores.
        if by_id:
            return None
        return rest_json(shop, f"/collections/{collection['handle']}.json")

    parts = gather({"api": api, "rest": theme_json})
    data = parts["api"]
    raw = data.get("collection")
    if not isinstance(raw, dict):
        raise ShopifyNotFound(f"collection '{shared.describe(collection)}' not found on {shop.domain}")
    filters = P.as_dict(raw.get("products")).get("filters")
    rest = P.as_dict(P.as_dict(parts["rest"]).get("collection"))
    count = P.to_int(rest.get("products_count"))
    item = P.collection(shop, raw)
    updated_at = item.pop("updated_at")
    item["products_count"] = count if count is not None else P.facet_total(filters)
    item["published_at"] = P.iso_datetime(rest.get("published_at"))
    item["updated_at"] = updated_at
    item["facets"] = P.facets(filters)
    return {**shared.envelope(shop, data), "collection": item}
