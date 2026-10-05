"""Normalizers: raw Storefront API nodes -> the public /shopify/* shapes.

House rules applied everywhere: snake_case keys, `link` not `url`, booleans
that read as questions (`is_available`, `is_on_sale`), numbers as numbers,
prices as a numeric amount next to ONE `currency`, ISO-8601 UTC timestamps,
null for anything missing, numeric ids (the `gid://shopify/Product/` prefix is
noise), identity first / nested objects after / timestamps last. Every
function tolerates a partial node — a missing or mistyped field becomes null,
never an exception.
"""
import json
import re
from datetime import datetime, timezone

from contact_scraper.html_text import html_to_soup, soup_to_text
from shopify import refs

DEFAULT_OPTION = "Title"
DEFAULT_VALUE = "Default Title"


# ---- scalars --------------------------------------------------------------------

def text(value):
    """Trimmed string or None ("" and whitespace are None)."""
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    return value or None


def to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


def iso_datetime(value):
    """'2026-10-05T07:40:58Z' / '...-04:00' -> '2026-10-05T07:40:58Z' (UTC)."""
    value = text(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def nodes(connection):
    """A connection's node dicts ([] for null / malformed)."""
    return [n for n in as_list(as_dict(connection).get("nodes")) if isinstance(n, dict)]


def html_to_text(html):
    """HTML body -> readable plain text (block elements break lines)."""
    html = text(html)
    if not html:
        return None
    if "<" not in html:
        return html
    try:
        out = soup_to_text(html_to_soup(html))
    except Exception:
        out = re.sub(r"<[^>]+>", " ", html)
    out = re.sub(r"[ \t ]+", " ", out)
    out = re.sub(r"\s*\n\s*", "\n", out).strip()
    return out or None


def amount(money):
    return to_float(as_dict(money).get("amount"))


def currency_of(*moneys):
    for money in moneys:
        code = text(as_dict(money).get("currencyCode"))
        if code:
            return code
    return None


def image(raw):
    """{url altText width height} -> {link, alt_text, width, height} or None."""
    raw = as_dict(raw)
    link = text(raw.get("url"))
    if not link:
        return None
    out = {}
    if raw.get("id") is not None:
        out["id"] = refs.numeric_id(raw.get("id"))
    out.update({"link": link, "alt_text": text(raw.get("altText")),
                "width": to_int(raw.get("width")), "height": to_int(raw.get("height"))})
    return out


def seo(raw):
    raw = as_dict(raw)
    return {"title": text(raw.get("title")), "description": text(raw.get("description"))}


def page_info(connection):
    """-> (next_cursor | None, has_next_page)."""
    info = as_dict(as_dict(connection).get("pageInfo"))
    has_next = bool(info.get("hasNextPage"))
    return (text(info.get("endCursor")) if has_next else None), has_next


def market(context):
    """The `@inContext` market the API actually served."""
    context = as_dict(context)
    language = text(context.get("language"))
    return {"country": text(context.get("country")),
            "language": language.lower().replace("_", "-") if language else None}


def discount_percent(price, compare_at):
    if price is None or not compare_at or compare_at <= price:
        return None
    return round((1 - price / compare_at) * 100, 1)


# ---- products -------------------------------------------------------------------

def link_of(store, raw, path):
    """Public link of an entity: Shopify's onlineStoreUrl on an Online Store;
    on a headless store that URL points at the hidden backend domain
    (us.checkout.gymshark.com), so the link is built on the public origin."""
    link = text(as_dict(raw).get("onlineStoreUrl"))
    if link and not store.is_headless:
        return link
    return f"{store.origin}{path}" if path else link


def product_link(store, raw):
    handle = text(as_dict(raw).get("handle"))
    return link_of(store, raw, f"/products/{handle}" if handle else None)


def _category(raw):
    raw = as_dict(raw)
    if not raw.get("id") and not raw.get("name"):
        return None
    category_id = text(raw.get("id"))
    out = {"id": category_id.rsplit("/", 1)[-1] if category_id else None, "name": text(raw.get("name"))}
    if "ancestors" in raw:
        path = [text(a.get("name")) for a in as_list(raw.get("ancestors")) if isinstance(a, dict)]
        out["path"] = [p for p in reversed(path) if p] + ([out["name"]] if out["name"] else [])
    return out


def _is_default_option(option):
    values = [as_dict(v).get("name") for v in as_list(option.get("optionValues"))]
    return option.get("name") == DEFAULT_OPTION and values == [DEFAULT_VALUE]


def _options(raw_options, detailed=False):
    out = []
    for option in as_list(raw_options):
        if not isinstance(option, dict) or _is_default_option(option):
            continue
        values = [v for v in as_list(option.get("optionValues")) if isinstance(v, dict)]
        item = {"name": text(option.get("name")), "values": [n for n in (text(v.get("name")) for v in values) if n]}
        if detailed:
            swatches = []
            for value in values:
                swatch = as_dict(value.get("swatch"))
                color = text(swatch.get("color"))
                picture = text(as_dict(as_dict(swatch.get("image")).get("previewImage")).get("url"))
                if color or picture:
                    swatches.append({"value": text(value.get("name")), "color": color, "image_link": picture})
            item["swatches"] = swatches
        out.append(item)
    return out


def _rating(raw):
    """The standard reviews.rating / reviews.rating_count metafields ->
    (rating, reviews_count). Absent without the store token."""
    rating = count = None
    value = text(as_dict(raw.get("rating")).get("value"))
    if value:
        try:
            parsed = json.loads(value)
            rating = to_float(parsed.get("value")) if isinstance(parsed, dict) else to_float(parsed)
        except ValueError:
            rating = to_float(value)
    count = to_int(as_dict(raw.get("ratingCount")).get("value"))
    if rating is not None:
        rating = round(rating, 2)
    return rating, count


def pricing(price_range, compare_range):
    """priceRange + compareAtPriceRange -> one pricing block. Shopify reports
    "0.0" for a missing compare-at price."""
    price_range, compare_range = as_dict(price_range), as_dict(compare_range)
    low, high = amount(price_range.get("minVariantPrice")), amount(price_range.get("maxVariantPrice"))
    compare_low = amount(compare_range.get("minVariantPrice")) or None
    compare_high = amount(compare_range.get("maxVariantPrice")) or None
    compare = compare_low or compare_high
    is_on_sale = bool(low is not None and compare_high and (
        (compare_low and compare_low > low) or (high is not None and compare_high > high)))
    return {
        "currency": currency_of(price_range.get("minVariantPrice"), price_range.get("maxVariantPrice")),
        "price": low,
        "price_max": high,
        "compare_at_price": compare if is_on_sale else None,
        "compare_at_price_max": compare_high if is_on_sale else None,
        "is_on_sale": is_on_sale,
        "discount_percent": discount_percent(low, compare if (compare and low is not None and compare > low) else compare_high)
        if is_on_sale else None,
        "has_price_range": bool(low is not None and high is not None and high > low),
    }


def product_card(store, raw):
    raw = as_dict(raw)
    rating, reviews_count = _rating(raw)
    return {
        "id": refs.numeric_id(raw.get("id")),
        "handle": text(raw.get("handle")),
        "title": text(raw.get("title")),
        "link": product_link(store, raw),
        "vendor": text(raw.get("vendor")),
        "product_type": text(raw.get("productType")),
        "category": _category(raw.get("category")),
        "description": text(raw.get("description")),
        "tags": [t for t in (text(t) for t in as_list(raw.get("tags"))) if t],
        "is_available": bool_or_none(raw.get("availableForSale")),
        "is_gift_card": bool_or_none(raw.get("isGiftCard")),
        "is_subscription_only": bool_or_none(raw.get("requiresSellingPlan")),
        "rating": rating,
        "reviews_count": reviews_count,
        "pricing": pricing(raw.get("priceRange"), raw.get("compareAtPriceRange")),
        "image": image(raw.get("featuredImage")),
        "options": _options(raw.get("options")),
        "variants_count": to_int(as_dict(raw.get("variantsCount")).get("count")),
        "created_at": iso_datetime(raw.get("createdAt")),
        "updated_at": iso_datetime(raw.get("updatedAt")),
        "published_at": iso_datetime(raw.get("publishedAt")),
    }


def product_cards(store, raw_nodes):
    return [product_card(store, n) for n in as_list(raw_nodes) if isinstance(n, dict) and n.get("handle")]


def variant(raw, link=None):
    raw = as_dict(raw)
    variant_id = refs.numeric_id(raw.get("id"))
    price, compare = amount(raw.get("price")), amount(raw.get("compareAtPrice")) or None
    is_on_sale = bool(price is not None and compare and compare > price)
    title = text(raw.get("title"))
    selected = [{"name": text(o.get("name")), "value": text(o.get("value"))}
                for o in as_list(raw.get("selectedOptions")) if isinstance(o, dict)
                and not (o.get("name") == DEFAULT_OPTION and o.get("value") == DEFAULT_VALUE)]
    unit = None
    measure = as_dict(raw.get("unitPriceMeasurement"))
    if amount(raw.get("unitPrice")) is not None:
        unit = {
            "amount": amount(raw.get("unitPrice")),
            "currency": currency_of(raw.get("unitPrice")),
            "measured_type": (text(measure.get("measuredType")) or "").lower() or None,
            "quantity_value": to_float(measure.get("quantityValue")),
            "quantity_unit": (text(measure.get("quantityUnit")) or "").lower() or None,
            "reference_value": to_float(measure.get("referenceValue")),
            "reference_unit": (text(measure.get("referenceUnit")) or "").lower() or None,
        }
    weight = to_float(raw.get("weight"))
    rule = as_dict(raw.get("quantityRule"))
    return {
        "id": variant_id,
        "title": None if title == DEFAULT_VALUE else title,
        "sku": text(raw.get("sku")),
        "barcode": text(raw.get("barcode")),
        "link": f"{link}{'&' if '?' in link else '?'}variant={variant_id}" if link and variant_id else None,
        "is_available": bool_or_none(raw.get("availableForSale")),
        "is_backordered": bool_or_none(raw.get("currentlyNotInStock")),
        "requires_shipping": bool_or_none(raw.get("requiresShipping")),
        "is_taxable": bool_or_none(raw.get("taxable")),
        "price": price,
        "compare_at_price": compare if is_on_sale else None,
        "currency": currency_of(raw.get("price")),
        "is_on_sale": is_on_sale,
        "discount_percent": discount_percent(price, compare) if is_on_sale else None,
        "unit_price": unit,
        "weight": {"value": weight, "unit": (text(raw.get("weightUnit")) or "").lower() or None} if weight else None,
        "options": selected,
        "image": image(raw.get("image")),
        "quantity_rule": {"minimum": to_int(rule.get("minimum")), "maximum": to_int(rule.get("maximum")),
                          "increment": to_int(rule.get("increment"))},
    }


_MEDIA_TYPES = {"VIDEO": "video", "EXTERNAL_VIDEO": "external_video", "MODEL_3D": "model_3d", "IMAGE": "image"}


def media_item(raw):
    """A non-image media node (video / external video / 3D model)."""
    raw = as_dict(raw)
    sources = []
    for source in as_list(raw.get("sources")):
        if isinstance(source, dict) and text(source.get("url")):
            sources.append({"link": text(source.get("url")), "mime_type": text(source.get("mimeType")),
                            "format": text(source.get("format")), "width": to_int(source.get("width")),
                            "height": to_int(source.get("height")), "file_size": to_int(source.get("filesize"))})
    return {
        "id": refs.numeric_id(raw.get("id")),
        "type": _MEDIA_TYPES.get(raw.get("mediaContentType"), (text(raw.get("mediaContentType")) or "").lower() or None),
        "alt_text": text(raw.get("alt")),
        "host": (text(raw.get("host")) or "").lower() or None,
        "embed_link": text(raw.get("embedUrl")),
        "origin_link": text(raw.get("originUrl")),
        "preview_image": image(raw.get("previewImage")),
        "sources": sources,
    }


_ADJUSTMENTS = {
    "SellingPlanPercentagePriceAdjustment": "percentage",
    "SellingPlanFixedAmountPriceAdjustment": "fixed_amount",
    "SellingPlanFixedPriceAdjustment": "fixed_price",
}


def _price_adjustment(raw):
    raw = as_dict(raw)
    value = as_dict(raw.get("adjustmentValue"))
    kind = _ADJUSTMENTS.get(value.get("__typename"))
    money = value.get("adjustmentAmount") or value.get("price")
    return {
        "type": kind,
        "value": to_float(value.get("adjustmentPercentage")) if kind == "percentage" else amount(money),
        "currency": currency_of(money),
        "order_count": to_int(raw.get("orderCount")),
    }


def subscription_group(raw):
    raw = as_dict(raw)
    plans = []
    for plan in nodes(raw.get("sellingPlans")):
        plans.append({
            "id": refs.numeric_id(plan.get("id")),
            "name": text(plan.get("name")),
            "description": text(plan.get("description")),
            "is_recurring_delivery": bool_or_none(plan.get("recurringDeliveries")),
            "options": [{"name": text(o.get("name")), "value": text(o.get("value"))}
                        for o in as_list(plan.get("options")) if isinstance(o, dict)],
            "price_adjustments": [_price_adjustment(a) for a in as_list(plan.get("priceAdjustments"))
                                  if isinstance(a, dict)],
        })
    return {
        "name": text(raw.get("name")),
        "app_name": text(raw.get("appName")),
        "options": [{"name": text(o.get("name")), "values": [v for v in as_list(o.get("values")) if isinstance(v, str)]}
                    for o in as_list(raw.get("options")) if isinstance(o, dict)],
        "plans": plans,
    }


def metafields(raw_list):
    out = []
    for field in as_list(raw_list):
        if not isinstance(field, dict) or field.get("value") in (None, ""):
            continue
        value = field.get("value")
        kind = text(field.get("type"))
        if kind and (kind.startswith("json") or kind.startswith("list.") or kind in ("rating", "dimension", "weight", "volume", "money")):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                pass
        elif kind in ("number_integer", "number_decimal"):
            value = to_float(value) if kind == "number_decimal" else to_int(value)
        elif kind == "boolean":
            value = str(value).lower() == "true"
        out.append({"namespace": text(field.get("namespace")), "key": text(field.get("key")), "type": kind, "value": value})
    return out


def collection_ref(store, raw):
    raw = as_dict(raw)
    handle = text(raw.get("handle"))
    return {"id": refs.numeric_id(raw.get("id")), "handle": handle, "title": text(raw.get("title")),
            "link": link_of(store, raw, f"/collections/{handle}" if handle else None)}


def product_details(store, raw, variants):
    """The full product. `variants` is the complete raw variant list (the
    caller pages past the first 250)."""
    raw = as_dict(raw)
    card = product_card(store, raw)
    link = card["link"]
    parsed_variants = [variant(v, link) for v in variants if isinstance(v, dict)]
    images = [i for i in (image(n) for n in nodes(raw.get("images"))) if i]
    out = {
        "id": card["id"], "handle": card["handle"], "title": card["title"], "link": link,
        "vendor": card["vendor"], "product_type": card["product_type"],
        "category": _category(raw.get("category")),
        "description": text(raw.get("fullDescription")) or card["description"],
        "description_html": text(raw.get("descriptionHtml")),
        "tags": card["tags"],
        "is_available": card["is_available"],
        "is_gift_card": card["is_gift_card"],
        "is_subscription_only": card["is_subscription_only"],
        "has_only_default_variant": not _options(raw.get("options")),
        "rating": card["rating"],
        "reviews_count": card["reviews_count"],
        "pricing": card["pricing"],
        "image": card["image"],
        "images": images,
        "media": [media_item(m) for m in nodes(raw.get("media")) if m.get("mediaContentType") != "IMAGE"],
        "options": _options(raw.get("options"), detailed=True),
        "variants_count": card["variants_count"] if card["variants_count"] is not None else len(parsed_variants),
        "variants": parsed_variants,
        "subscriptions": [subscription_group(g) for g in nodes(raw.get("sellingPlanGroups"))],
        "collections": [collection_ref(store, c) for c in nodes(raw.get("collections"))],
        "metafields": metafields(raw.get("metafields")),
        "seo": seo(raw.get("seo")),
        "created_at": card["created_at"],
        "updated_at": card["updated_at"],
        "published_at": card["published_at"],
    }
    return out


# ---- facets ---------------------------------------------------------------------

def facets(raw_filters):
    """Search / collection `filters` -> the facets a storefront sidebar shows.
    The opaque `input` JSON is dropped except for the price bounds."""
    out = []
    for raw in as_list(raw_filters):
        if not isinstance(raw, dict):
            continue
        kind = (text(raw.get("type")) or "").lower() or None
        item = {"id": text(raw.get("id")), "label": text(raw.get("label")), "type": kind}
        values = [v for v in as_list(raw.get("values")) if isinstance(v, dict)]
        if kind == "price_range":
            bounds = {}
            try:
                bounds = as_dict(as_dict(json.loads(values[0].get("input") or "{}")).get("price")) if values else {}
            except ValueError:
                pass
            item["min"], item["max"] = to_float(bounds.get("min")), to_float(bounds.get("max"))
        else:
            item["values"] = [{"label": text(v.get("label")), "count": to_int(v.get("count"))} for v in values]
        out.append(item)
    return out


def facet_total(raw_filters):
    """Products behind a filter set = in stock + out of stock, read from the
    availability facet (None when the store hides that facet)."""
    for raw in as_list(raw_filters):
        if isinstance(raw, dict) and str(raw.get("id") or "").endswith("availability"):
            counts = [to_int(v.get("count")) for v in as_list(raw.get("values")) if isinstance(v, dict)]
            counts = [c for c in counts if c is not None]
            return sum(counts) if counts else None
    return None


# ---- collections ----------------------------------------------------------------

def collection(store, raw):
    raw = as_dict(raw)
    ref = collection_ref(store, raw)
    return {
        **ref,
        "description": text(raw.get("description")),
        "description_html": text(raw.get("descriptionHtml")),
        "image": image(raw.get("image")),
        "seo": seo(raw.get("seo")),
        "updated_at": iso_datetime(raw.get("updatedAt")),
    }


# ---- content --------------------------------------------------------------------

def _content_link(store, raw, path):
    return link_of(store, raw, path)


def page(store, raw, detailed=False):
    raw = as_dict(raw)
    handle = text(raw.get("handle"))
    out = {
        "id": refs.numeric_id(raw.get("id")),
        "handle": handle,
        "title": text(raw.get("title")),
        "link": _content_link(store, raw, f"/pages/{handle}" if handle else None),
        "summary": text(raw.get("bodySummary")),
    }
    if detailed:
        out["body_text"] = html_to_text(raw.get("body"))
        out["body_html"] = text(raw.get("body"))
    out["seo"] = seo(raw.get("seo"))
    out["created_at"] = iso_datetime(raw.get("createdAt"))
    out["updated_at"] = iso_datetime(raw.get("updatedAt"))
    return out


def blog_ref(store, raw):
    raw = as_dict(raw)
    if not raw:
        return None
    handle = text(raw.get("handle"))
    return {"id": refs.numeric_id(raw.get("id")), "handle": handle, "title": text(raw.get("title")),
            "link": _content_link(store, raw, f"/blogs/{handle}" if handle else None)}


def blog(store, raw):
    raw = as_dict(raw)
    out = blog_ref(store, raw) or {"id": None, "handle": None, "title": None, "link": None}
    out["authors"] = [{"name": text(a.get("name")), "bio": text(a.get("bio"))}
                      for a in as_list(raw.get("authors")) if isinstance(a, dict) and text(a.get("name"))]
    out["seo"] = seo(raw.get("seo"))
    return out


def article(store, raw, detailed=False, blog_raw=None):
    raw = as_dict(raw)
    handle = text(raw.get("handle"))
    parent = blog_ref(store, raw.get("blog") or blog_raw)
    path = f"/blogs/{parent['handle']}/{handle}" if parent and parent.get("handle") and handle else None
    author = as_dict(raw.get("authorV2"))
    out = {
        "id": refs.numeric_id(raw.get("id")),
        "handle": handle,
        "title": text(raw.get("title")),
        "link": _content_link(store, raw, path),
        "excerpt": text(raw.get("excerpt")),
        "summary": text(raw.get("summary")),
    }
    if detailed:
        out["content"] = text(raw.get("content"))
        out["content_html"] = text(raw.get("contentHtml"))
        out["excerpt_html"] = text(raw.get("excerptHtml"))
    out["tags"] = [t for t in (text(t) for t in as_list(raw.get("tags"))) if t]
    out["image"] = image(raw.get("image"))
    out["author"] = {"name": text(author.get("name")), "bio": text(author.get("bio"))} if author else None
    out["blog"] = parent
    if detailed:
        comments = [{"id": refs.numeric_id(c.get("id")), "author_name": text(as_dict(c.get("author")).get("name")),
                     "content": text(c.get("content")), "content_html": text(c.get("contentHtml"))}
                    for c in nodes(raw.get("comments"))]
        out["comments_count"] = len(comments)
        out["comments"] = comments
    out["seo"] = seo(raw.get("seo"))
    out["published_at"] = iso_datetime(raw.get("publishedAt"))
    return out


# ---- menus ----------------------------------------------------------------------

def _menu_item(raw):
    raw = as_dict(raw)
    resource = as_dict(raw.get("resource"))
    return {
        "id": refs.numeric_id(raw.get("id")),
        "title": text(raw.get("title")),
        "link": text(raw.get("url")),
        "type": (text(raw.get("type")) or "").lower() or None,
        "resource": {"type": (text(resource.get("__typename")) or "").lower() or None,
                     "handle": text(resource.get("handle"))} if resource else None,
        "tags": [t for t in (text(t) for t in as_list(raw.get("tags"))) if t],
        "items": [_menu_item(i) for i in as_list(raw.get("items")) if isinstance(i, dict)],
    }


def menu(raw):
    raw = as_dict(raw)
    return {
        "id": refs.numeric_id(raw.get("id")),
        "handle": text(raw.get("handle")),
        "title": text(raw.get("title")),
        "items_count": to_int(raw.get("itemsCount")),
        "items": [_menu_item(i) for i in as_list(raw.get("items")) if isinstance(i, dict)],
    }


# ---- store ----------------------------------------------------------------------

def _lower_codes(values):
    return [str(v).lower().replace("_", "-") for v in as_list(values) if isinstance(v, str)]


def language_ref(raw):
    raw = as_dict(raw)
    code = text(raw.get("isoCode"))
    if not code:
        return None
    return {"code": code.lower().replace("_", "-"), "name": text(raw.get("name")),
            "native_name": text(raw.get("endonymName"))}


def _currency(raw):
    raw = as_dict(raw)
    if not raw.get("isoCode"):
        return None
    return {"code": text(raw.get("isoCode")), "name": text(raw.get("name")), "symbol": text(raw.get("symbol"))}


def country_market(raw):
    raw = as_dict(raw)
    if not raw.get("isoCode"):
        return None
    unit = text(raw.get("unitSystem"))
    return {
        "code": text(raw.get("isoCode")),
        "name": text(raw.get("name")),
        "market": text(as_dict(raw.get("market")).get("handle")),
        "unit_system": unit.replace("_SYSTEM", "").lower() if unit else None,
        "currency": _currency(raw.get("currency")),
        "languages": [l for l in (language_ref(x) for x in as_list(raw.get("availableLanguages"))) if l],
    }


def policy_ref(kind, raw, detailed=False):
    raw = as_dict(raw)
    if not raw:
        return None
    out = {"type": kind}
    if detailed:
        out["id"] = refs.numeric_id(raw.get("id"))
    out.update({"title": text(raw.get("title")), "handle": text(raw.get("handle")), "link": text(raw.get("url"))})
    if detailed:
        out["body_text"] = html_to_text(raw.get("body"))
        out["body_html"] = text(raw.get("body"))
    return out


POLICY_KEYS = [("privacy", "privacyPolicy"), ("refund", "refundPolicy"), ("shipping", "shippingPolicy"),
               ("terms", "termsOfService"), ("subscription", "subscriptionPolicy")]


def policies(shop, detailed=False):
    shop = as_dict(shop)
    return [p for p in (policy_ref(kind, shop.get(key), detailed) for kind, key in POLICY_KEYS) if p]


def theme(raw):
    """`Shopify.theme` -> the theme block (None on a headless store)."""
    raw = as_dict(raw)
    if not raw:
        return None
    store_id = to_int(raw.get("theme_store_id"))
    return {
        "id": to_int(raw.get("id")),
        "name": text(raw.get("schema_name")),
        "version": text(raw.get("schema_version")),
        "installed_name": text(raw.get("name")),
        "theme_store_id": store_id,
        "is_theme_store_theme": store_id is not None,
        "role": text(raw.get("role")),
    }


def _brand_colors(raw):
    out = []
    for group in as_list(raw):
        if isinstance(group, dict) and (group.get("background") or group.get("foreground")):
            out.append({"background": text(group.get("background")), "foreground": text(group.get("foreground"))})
    return out


def brand(raw):
    raw = as_dict(raw)
    colors = as_dict(raw.get("colors"))
    return {
        "slogan": text(raw.get("slogan")),
        "short_description": text(raw.get("shortDescription")),
        "logo": image(as_dict(raw.get("logo")).get("image")),
        "square_logo": image(as_dict(raw.get("squareLogo")).get("image")),
        "cover_image": image(as_dict(raw.get("coverImage")).get("image")),
        "primary_colors": _brand_colors(colors.get("primary")),
        "secondary_colors": _brand_colors(colors.get("secondary")),
    }


def store_profile(store, shop, localization, meta):
    """GraphQL shop + localization, /meta.json and the homepage facts -> the
    store profile."""
    shop, localization, meta = as_dict(shop), as_dict(localization), as_dict(meta)
    home = as_dict(store.home)
    payments = as_dict(shop.get("paymentSettings"))
    ships_to = [c for c in as_list(shop.get("shipsToCountries")) if isinstance(c, str)]
    country = as_dict(localization.get("country"))
    languages = [l for l in (language_ref(x) for x in as_list(localization.get("availableLanguages"))) if l]
    installments = meta.get("offers_shop_pay_installments")
    return {
        "id": refs.numeric_id(shop.get("id")) or to_int(meta.get("id")),
        "name": text(shop.get("name")) or text(meta.get("name")),
        "domain": store.domain,
        "link": store.origin,
        "myshopify_domain": text(meta.get("myshopify_domain")) or store.myshopify_domain,
        "description": text(shop.get("description")) or text(meta.get("description")) or text(home.get("description")),
        "is_headless": bool(store.is_headless),
        "is_storefront_locked": bool(home.get("is_storefront_locked")) if home else None,
        "products_count": to_int(meta.get("published_products_count")),
        "collections_count": to_int(meta.get("published_collections_count")),
        "location": {
            "city": text(meta.get("city")),
            "province": text(meta.get("province")),
            "country": text(meta.get("country")) or text(payments.get("countryCode")),
        },
        "currency": text(payments.get("currencyCode")) or text(meta.get("currency")),
        "money_format": text(shop.get("moneyFormat")) or text(meta.get("money_format")),
        "brand": brand(shop.get("brand")),
        "share_image_link": text(home.get("share_image")),
        "favicon_link": text(home.get("favicon")),
        "payments": {
            "accepted_card_brands": _lower_codes(payments.get("acceptedCardBrands")),
            "digital_wallets": _lower_codes(payments.get("supportedDigitalWallets")),
            "enabled_currencies": [c for c in as_list(payments.get("enabledPresentmentCurrencies")) if isinstance(c, str)],
            "has_shop_pay_installments": installments if isinstance(installments, bool) else None,
        },
        "shipping": {"ships_to_countries_count": len(ships_to), "ships_to_countries": ships_to},
        "localization": {
            "default_country": text(country.get("isoCode")),
            "default_language": (language_ref(localization.get("language")) or {}).get("code"),
            "unit_system": (text(country.get("unitSystem")) or "").replace("_SYSTEM", "").lower() or None,
            "markets_count": len(as_list(localization.get("availableCountries"))),
            "languages": languages,
        },
        "theme": theme(home.get("theme")),
        "apps_count": len(as_list(home.get("apps"))) if home else None,
        "policies": policies(shop),
    }
