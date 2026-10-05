"""/shopify/products* — a store's catalogue: the product list with sort
orders and typed filters, one product in full (every variant, image, video,
subscription plan), full-text search with facets, best sellers, new
arrivals, products on sale and Shopify's own recommendations.

All from the store's Storefront API (fetch.gql). Lists page with an opaque
`cursor` (the previous response's `next_cursor`)."""
from shopify import parsers as P
from shopify import queries as Q
from shopify import shared
from shopify.fetch import ShopifyNotFound, gql, resolve

MAX_VARIANTS = 2048           # Shopify's own per-product ceiling
ON_SALE_PAGE = 250
ON_SALE_MAX_PAGES = 4

# public sort -> (ProductSortKeys, reverse)
PRODUCT_SORTS = {
    "best_selling": ("BEST_SELLING", False),
    "newest": ("CREATED_AT", True),
    "oldest": ("CREATED_AT", False),
    "recently_updated": ("UPDATED_AT", True),
    "price_asc": ("PRICE", False),
    "price_desc": ("PRICE", True),
    "title_asc": ("TITLE", False),
    "title_desc": ("TITLE", True),
}
# public sort -> (ProductCollectionSortKeys, reverse)
COLLECTION_SORTS = {
    "featured": ("COLLECTION_DEFAULT", False),
    "best_selling": ("BEST_SELLING", False),
    "newest": ("CREATED", True),
    "oldest": ("CREATED", False),
    "price_asc": ("PRICE", False),
    "price_desc": ("PRICE", True),
    "title_asc": ("TITLE", False),
    "title_desc": ("TITLE", True),
    "manual": ("MANUAL", False),
}
# public sort -> (SearchSortKeys, reverse)
SEARCH_SORTS = {
    "relevance": ("RELEVANCE", False),
    "price_asc": ("PRICE", False),
    "price_desc": ("PRICE", True),
}
UNAVAILABLE = {"show": "SHOW", "hide": "HIDE", "last": "LAST"}


def _list(store, data, connection, sort, filters):
    next_cursor, has_next = P.page_info(connection)
    products = shared.cards(store, P.as_dict(connection).get("nodes"))
    return {
        **shared.envelope(store, data),
        "sort": sort,
        "filters": filters,
        "count": len(products),
        "has_next_page": has_next,
        "next_cursor": next_cursor,
        "products": products,
    }


def list_products(store, sort="best_selling", title=None, vendor=None, product_type=None, tag=None,
                  is_available=None, min_price=None, max_price=None, limit=50, cursor=None,
                  country=None, language=None):
    """The store's products in one of Shopify's sort orders, optionally
    narrowed by title, vendor, product type, tag, availability or price.

    These filters ride Shopify's search syntax, so text values match as
    phrases (vendor "Death Wish Coffee" also finds "Death Wish Coffee
    Company") and a price bound holds when ANY variant is in range. The
    collection and search routes filter exactly (ProductFilter)."""
    shop = resolve(store)
    sort_key, reverse = PRODUCT_SORTS[sort]
    query = shared.product_query(vendor=vendor, product_type=product_type, tag=tag, title=title,
                                 is_available=is_available, min_price=min_price, max_price=max_price)
    data = gql(shop, Q.PRODUCTS, {"first": limit, "after": cursor, "sortKey": sort_key, "reverse": reverse,
                                  "query": query},
               label="products", **shared.context(country, language))
    filters = shared.applied_filters(title=title, vendor=vendor, product_type=product_type, tag=tag,
                                     is_available=is_available, min_price=min_price, max_price=max_price)
    return _list(shop, data, data.get("products"), sort, filters)


def _collection_products(shop, collection, sort, filters, limit, cursor, country, language):
    """(data, raw collection) for one page of a collection's products."""
    sort_key, reverse = COLLECTION_SORTS[sort]
    by_id, variables = shared.entity_variables(collection, "Collection")
    variables.update({"first": limit, "after": cursor, "sortKey": sort_key, "reverse": reverse, "filters": filters})
    data = gql(shop, Q.COLLECTION_PRODUCTS_BY_ID if by_id else Q.COLLECTION_PRODUCTS_BY_HANDLE, variables,
               label="collection products", **shared.context(country, language))
    raw = data.get("collection")
    if not isinstance(raw, dict):
        raise ShopifyNotFound(f"collection '{shared.describe(collection)}' not found on {shop.domain}")
    return data, raw


def collection_products(store, collection, sort="featured", vendor=None, product_type=None, tag=None,
                        option=None, is_available=None, min_price=None, max_price=None, limit=50,
                        cursor=None, country=None, language=None):
    """Products of one collection, with the collection's own facets."""
    shop = resolve(store)
    filters = shared.product_filters(vendor=vendor, product_type=product_type, tag=tag, option=option,
                                     is_available=is_available, min_price=min_price, max_price=max_price)
    data, raw = _collection_products(shop, collection, sort, filters, limit, cursor, country, language)
    connection = P.as_dict(raw.get("products"))
    out = _list(shop, data, connection, sort, shared.applied_filters(
        vendor=vendor, product_type=product_type, tag=tag, option=option, is_available=is_available,
        min_price=min_price, max_price=max_price))
    products = out.pop("products")
    out["collection"] = P.collection_ref(shop, raw)
    out["facets"] = P.facets(connection.get("filters"))
    out["products"] = products
    return out


def _ranked(store, collection, sort, limit, cursor, country, language):
    """Best sellers / new arrivals: store-wide, or inside one collection."""
    if collection is None:
        return list_products(store, sort=sort, limit=limit, cursor=cursor, country=country, language=language)
    shop = resolve(store)
    data, raw = _collection_products(shop, collection, sort, None, limit, cursor, country, language)
    out = _list(shop, data, raw.get("products"), sort, {})
    products = out.pop("products")
    out["collection"] = P.collection_ref(shop, raw)
    out["products"] = products
    return out


def best_sellers(store, collection=None, limit=50, cursor=None, country=None, language=None):
    """The store's (or one collection's) products, best selling first."""
    return _ranked(store, collection, "best_selling", limit, cursor, country, language)


def new_arrivals(store, collection=None, limit=50, cursor=None, country=None, language=None):
    """The store's (or one collection's) most recently created products."""
    return _ranked(store, collection, "newest", limit, cursor, country, language)


def search(store, query, sort="relevance", vendor=None, product_type=None, tag=None, option=None,
           is_available=None, min_price=None, max_price=None, unavailable_products="last", limit=50,
           cursor=None, country=None, language=None):
    """The store's own product search: results, the total and the facets."""
    shop = resolve(store)
    sort_key, reverse = SEARCH_SORTS[sort]
    filters = shared.product_filters(vendor=vendor, product_type=product_type, tag=tag, option=option,
                                     is_available=is_available, min_price=min_price, max_price=max_price)
    data = gql(shop, Q.SEARCH_PRODUCTS, {"query": query, "first": limit, "after": cursor, "sortKey": sort_key,
                                         "reverse": reverse, "filters": filters,
                                         "unavailable": UNAVAILABLE[unavailable_products]},
               label="search", **shared.context(country, language))
    connection = P.as_dict(data.get("search"))
    out = _list(shop, data, connection, sort, shared.applied_filters(
        vendor=vendor, product_type=product_type, tag=tag, option=option, is_available=is_available,
        min_price=min_price, max_price=max_price))
    products = out.pop("products")
    head = {key: out.pop(key) for key in ("store", "market")}
    return {**head, "query": query, "total_count": P.to_int(connection.get("totalCount")), **out,
            "facets": P.facets(connection.get("productFilters")), "products": products}


def _split_cursor(cursor):
    """on-sale cursor '<skip>.<api cursor>' -> (skip, api cursor | None)."""
    if not cursor:
        return 0, None
    head, _, tail = cursor.partition(".")
    if not head.isdigit():
        raise ValueError("cursor is not a next_cursor returned by this endpoint")
    return int(head), (tail or None)


def on_sale(store, min_discount_percent=None, is_available=None, limit=50, cursor=None,
            country=None, language=None):
    """Products selling below their compare-at price, best sellers first.
    Shopify cannot filter on that, so this walks the catalogue (up to 1,000
    products per call) and keeps the discounted ones; `next_cursor` resumes
    exactly where the call stopped."""
    shop = resolve(store)
    skip, after = _split_cursor(cursor)
    query = shared.product_query(is_available=is_available)
    found, scanned, data = [], 0, {}
    next_cursor, exhausted = None, False
    for _ in range(ON_SALE_MAX_PAGES):
        data = gql(shop, Q.PRODUCTS, {"first": ON_SALE_PAGE, "after": after, "sortKey": "BEST_SELLING",
                                      "reverse": False, "query": query},
                   label="products", **shared.context(country, language))
        connection = P.as_dict(data.get("products"))
        page_next, has_next = P.page_info(connection)
        rows = [n for n in P.nodes(connection) if n.get("handle")]
        scanned += len(rows)
        matches = []
        for row in rows:
            block = P.pricing(row.get("priceRange"), row.get("compareAtPriceRange"))
            if block["is_on_sale"] and (min_discount_percent is None
                                        or (block["discount_percent"] or 0) >= min_discount_percent):
                matches.append(row)
        matches = matches[skip:]
        room = limit - len(found)
        if len(matches) > room:
            found.extend(matches[:room])
            next_cursor = f"{skip + room}.{after or ''}"       # same page, further in
            break
        found.extend(matches)
        skip = 0
        if not has_next:
            exhausted = True
            break
        after = page_next
        next_cursor = f"0.{after}"
        if len(found) >= limit:
            break
    return {
        **shared.envelope(shop, data),
        "filters": shared.applied_filters(min_discount_percent=min_discount_percent, is_available=is_available),
        "count": len(found),
        "scanned_count": scanned,
        "has_next_page": not exhausted and next_cursor is not None,
        "next_cursor": None if exhausted else next_cursor,
        "products": shared.cards(shop, found),
    }


def _product(shop, product, document_by_handle, document_by_id, label, country, language):
    by_id, variables = shared.entity_variables(product, "Product")
    data = gql(shop, document_by_id if by_id else document_by_handle, variables,
               label=label, **shared.context(country, language))
    raw = data.get("product")
    if not isinstance(raw, dict):
        raise ShopifyNotFound(f"product '{shared.describe(product)}' not found on {shop.domain}")
    return data, raw


def details(store, product, country=None, language=None):
    """One product in full: description, every variant with price / SKU /
    barcode / availability, images, videos and 3D models, option swatches,
    subscription plans, the collections it is in, review rating and SEO."""
    shop = resolve(store)
    data, raw = _product(shop, product, Q.PRODUCT_BY_HANDLE, Q.PRODUCT_BY_ID, "product", country, language)
    shared.with_metafields(shop, [raw], detailed=True)
    connection = P.as_dict(raw.get("variants"))
    variants = P.nodes(connection)
    after, has_next = P.page_info(connection)
    while has_next and after and len(variants) < MAX_VARIANTS:
        more = gql(shop, Q.PRODUCT_VARIANTS_PAGE, {"id": raw.get("id"), "after": after}, label="product variants",
                   **shared.context(country, language))
        connection = P.as_dict(P.as_dict(more.get("product")).get("variants"))
        page_nodes = P.nodes(connection)
        if not page_nodes:
            break
        variants.extend(page_nodes)
        after, has_next = P.page_info(connection)
    return {**shared.envelope(shop, data), "product": P.product_details(shop, raw, variants)}


def recommendations(store, product, intent="related", country=None, language=None):
    """Shopify's "you may also like" (related) or "pairs well with"
    (complementary) products for one product."""
    shop = resolve(store)
    by_id, variables = shared.entity_variables(product, "Product")
    variables["intent"] = intent.upper()
    data = gql(shop, Q.RECOMMENDATIONS_BY_ID if by_id else Q.RECOMMENDATIONS_BY_HANDLE, variables,
               label="recommendations", **shared.context(country, language))
    raw = data.get("productRecommendations")
    if raw is None:
        raise ShopifyNotFound(f"product '{shared.describe(product)}' not found on {shop.domain}")
    products = shared.cards(shop, raw)
    return {**shared.envelope(shop, data), "product": shared.describe(product), "intent": intent,
            "count": len(products), "products": products}
