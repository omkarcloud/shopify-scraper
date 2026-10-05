"""Bits every /shopify/* endpoint module shares: the market context
variables, the response envelope, Shopify search-syntax and ProductFilter
builders, and the entity -> query variable choice (handle or id)."""
from shopify import parsers as P
from shopify import refs
from shopify.fetch import product_metafields

# Storefront LanguageCode only has region variants for these.
_REGIONAL_LANGUAGES = {"pt-br": "PT_BR", "pt-pt": "PT_PT", "zh-cn": "ZH_CN", "zh-tw": "ZH_TW"}


def language_enum(language):
    """'en' / 'pt-BR' -> the LanguageCode enum value ('EN', 'PT_BR')."""
    if not language:
        return None
    low = language.lower()
    return _REGIONAL_LANGUAGES.get(low, low.split("-")[0].upper())


def context(country, language):
    """kwargs for fetch.gql()."""
    return {"country": country, "language": language_enum(language)}


def envelope(store, data):
    """The keys every response opens with: which store, which market."""
    return {"store": store.domain, "market": P.market(data.get("_context"))}


def entity_variables(entity, kind):
    """A resolved ref -> (is_by_id, variables)."""
    if entity.get("id") is not None:
        return True, {"id": refs.gid(kind, entity["id"])}
    return False, {"handle": entity["handle"]}


def describe(entity):
    return str(entity.get("id") if entity.get("id") is not None else entity.get("handle"))


def _quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _number(value):
    return f"{value:f}".rstrip("0").rstrip(".")


def product_query(vendor=None, product_type=None, tag=None, title=None, is_available=None,
                  min_price=None, max_price=None):
    """Typed filters -> Shopify search syntax for `products(query:)`. Text
    terms are phrase matches, not equality — the syntax has no exact operator."""
    terms = []
    if title:
        terms.append(f"title:{_quote(title)}")
    if vendor:
        terms.append(f"vendor:{_quote(vendor)}")
    if product_type:
        terms.append(f"product_type:{_quote(product_type)}")
    if tag:
        terms.append(f"tag:{_quote(tag)}")
    if is_available is not None:
        terms.append(f"available_for_sale:{'true' if is_available else 'false'}")
    if min_price is not None:
        terms.append(f"variants.price:>={_number(min_price)}")
    if max_price is not None:
        terms.append(f"variants.price:<={_number(max_price)}")
    return " AND ".join(terms) or None


def product_filters(vendor=None, product_type=None, tag=None, is_available=None,
                    min_price=None, max_price=None, option=None):
    """Typed filters -> the `[ProductFilter!]` list search and collections take."""
    filters = []
    if is_available is not None:
        filters.append({"available": bool(is_available)})
    if min_price is not None or max_price is not None:
        price = {}
        if min_price is not None:
            price["min"] = float(min_price)
        if max_price is not None:
            price["max"] = float(max_price)
        filters.append({"price": price})
    if vendor:
        filters.append({"productVendor": vendor})
    if product_type:
        filters.append({"productType": product_type})
    if tag:
        filters.append({"tag": tag})
    if option:
        filters.append({"variantOption": {"name": option["name"], "value": option["value"]}})
    return filters or None


def applied_filters(**filters):
    """Echo of the filters in effect (only the ones the caller set)."""
    return {key: value for key, value in filters.items() if value is not None}


def with_metafields(shop, raw_products, detailed=False):
    """Merge the token-only metafields (review rating / count, and the
    detail set) into raw product nodes, in place. Returns the same list."""
    raw_products = [n for n in raw_products or [] if isinstance(n, dict)]
    extra = product_metafields(shop, [n.get("id") for n in raw_products], detailed)
    for node in raw_products:
        found = extra.get(node.get("id"))
        if found:
            for key in ("rating", "ratingCount", "metafields"):
                if key in found:
                    node[key] = found[key]
    return raw_products


def cards(shop, raw_products):
    """Raw product nodes -> product cards, ratings included."""
    return P.product_cards(shop, with_metafields(shop, raw_products))
