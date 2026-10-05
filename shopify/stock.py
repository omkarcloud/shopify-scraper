"""/shopify/products/inventory — how many units of each variant can be
bought right now.

The Storefront API hides `quantityAvailable` behind a scope stores rarely
grant, but a cart tells the same thing: ask for an oversized quantity of
every variant in one `cartCreate` and Shopify trims each line to what is
actually purchasable (warnings MERCHANDISE_NOT_ENOUGH_STOCK /
MERCHANDISE_OUT_OF_STOCK). The cart is anonymous, never checked out and
reserves nothing.

What the number means:
  * a line trimmed below the ask     -> that many units are in stock
  * a line left at the full ask      -> stock is not tracked, or the store
                                        keeps selling when out of stock
  * the store rejects the cart (a per-order quantity limit app, a B2B
    rule)                            -> unknown for that product
"""
from shopify import parsers as P
from shopify import queries as Q
from shopify import refs
from shopify import shared
from shopify.fetch import ShopifyNotFound, gql, mutate, resolve

PROBE_QUANTITY = 100000
LINES_PER_CART = 100
MAX_VARIANTS = 2048


def _probe(shop, variant_ids):
    """Probe up to LINES_PER_CART variant gids in one cart."""
    lines = [{"merchandiseId": vid, "quantity": PROBE_QUANTITY} for vid in variant_ids]
    data = mutate(shop, Q.CART_PROBE, {"lines": lines}, label="stock probe")
    return cart_quantities(data.get("cartCreate"), variant_ids)


def inventory(store, product, country=None, language=None):
    """Purchasable stock per variant of one product."""
    shop = resolve(store)
    by_id, variables = shared.entity_variables(product, "Product")
    document = Q.PRODUCT_STOCK_BY_ID if by_id else Q.PRODUCT_STOCK_BY_HANDLE
    raw, variants, after, data = None, [], None, {}
    while len(variants) < MAX_VARIANTS:
        data = gql(shop, document, {**variables, "after": after}, label="product", **shared.context(country, language))
        raw = data.get("product")
        if not isinstance(raw, dict):
            raise ShopifyNotFound(f"product '{shared.describe(product)}' not found on {shop.domain}")
        connection = P.as_dict(raw.get("variants"))
        variants.extend(P.nodes(connection))
        after, has_next = P.page_info(connection)
        if not has_next:
            break

    quantities, notes = {}, []
    ids = [v.get("id") for v in variants if v.get("id")]
    for start in range(0, len(ids), LINES_PER_CART):
        chunk = ids[start:start + LINES_PER_CART]
        found, errors = _probe(shop, chunk)
        if found is None:
            for message in errors:
                if message and message not in notes:
                    notes.append(message)
            continue
        quantities.update(found)
    return {**shared.envelope(shop, data), **summarize(shop, raw, variants, quantities, notes)}


def cart_quantities(result, variant_ids):
    """A cartCreate payload -> ({variant gid: quantity}, []) or
    (None, [the store's rejection messages])."""
    result = P.as_dict(result)
    cart = result.get("cart")
    if not isinstance(cart, dict):
        return None, [m for m in (P.text(e.get("message")) for e in P.as_list(result.get("userErrors"))
                                  if isinstance(e, dict)) if m]
    quantities = {vid: 0 for vid in variant_ids}        # a dropped line = sold out
    for line in P.nodes(cart.get("lines")):
        vid = P.as_dict(line.get("merchandise")).get("id")
        if vid in quantities:
            quantities[vid] = P.to_int(line.get("quantity")) or 0
    return quantities, []


def summarize(shop, raw, variants, quantities, notes):
    """Raw product + variants + probed quantities -> the public stock report."""
    link = P.product_link(shop, raw)
    rows, total, exact = [], 0, True
    for item in variants:
        vid = item.get("id")
        quantity = quantities.get(vid)
        is_available = P.bool_or_none(item.get("availableForSale"))
        if quantity is None:
            status, stock = "unknown", None
        elif quantity >= PROBE_QUANTITY:
            status, stock = "not_tracked", None
        elif quantity > 0:
            status, stock = "in_stock", quantity
        else:
            status, stock = "out_of_stock", 0
        if stock is None:
            exact = False
        else:
            total += stock
        title = P.text(item.get("title"))
        variant_id = refs.numeric_id(vid)
        rows.append({
            "id": variant_id,
            "title": None if title == P.DEFAULT_VALUE else title,
            "sku": P.text(item.get("sku")),
            "link": f"{link}?variant={variant_id}" if link and variant_id else None,
            "is_available": is_available,
            "is_backordered": P.bool_or_none(item.get("currentlyNotInStock")),
            "stock_status": status,
            "stock_quantity": stock,
            "options": [{"name": P.text(o.get("name")), "value": P.text(o.get("value"))}
                        for o in P.as_list(item.get("selectedOptions")) if isinstance(o, dict)
                        and not (o.get("name") == P.DEFAULT_OPTION and o.get("value") == P.DEFAULT_VALUE)],
        })
    return {
        "product": {"id": refs.numeric_id(raw.get("id")), "handle": P.text(raw.get("handle")),
                    "title": P.text(raw.get("title")), "link": link,
                    "is_available": P.bool_or_none(raw.get("availableForSale"))},
        "total_stock_quantity": total if exact and rows else None,
        "tracked_stock_quantity": total,
        "is_exact": bool(exact and rows),
        "variants_count": len(rows),
        "notes": notes,
        "variants": rows,
    }
