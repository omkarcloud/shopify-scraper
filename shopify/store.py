"""/shopify/store* — store intelligence: the profile, a "is this Shopify?"
check, installed apps, the theme, contact details, markets (countries /
currencies / languages), policies, navigation menus and catalogue statistics.

Sources: the Storefront API (shop, localization, menus, policies, the
catalogue walk), /meta.json (location and catalogue counts) and the
homepage HTML (theme, apps, contacts — storefront.py and the shared
contact_scraper extractors)."""
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from contact_scraper.aggregate import PLATFORM_KEYS, build_output
from contact_scraper.extract_emails import extract_emails
from contact_scraper.extract_phones import extract_phones
from contact_scraper.extract_socials import extract_socials
from contact_scraper.html_text import build_page
from shopify import parsers as P
from shopify import queries as Q
from shopify import refs
from shopify import shared
from shopify.fetch import (ShopifyUpstreamError, gather, gql, inspect, page_optional, resolve,
                           rest_json, run_parallel)

SCAN_PAGE = 250
CONTACT_PATHS = [("/pages/contact", "contact"), ("/pages/contact-us", "contact"),
                 ("/policies/contact-information", "contact"), ("/pages/about-us", "about"),
                 ("/pages/about", "about")]
DEFAULT_MENUS = ["main-menu", "footer"]
# Inline scripts / styles / SVG are most of a Shopify page's bytes and none of
# its contact details (JSON-LD is kept: it carries sameAs / telephone / email).
# Dropping them takes the social-link scan from ~6 s to well under one.
_NOISE_RE = re.compile(r"<script(?![^>]*ld\+json)\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>|<svg\b.*?</svg\s*>",
                       re.I | re.S)
HISTOGRAM_BUCKETS = 10


def _home(shop):
    """The store's homepage facts, or a 502 when the homepage could not be read."""
    if not shop.home:
        raise ShopifyUpstreamError(f"could not load the {shop.domain} homepage")
    return shop.home


# ---- profile / check ------------------------------------------------------------

def profile(store, country=None, language=None):
    """Who the store is: name, description, location, currency, brand
    assets, payment methods, shipping reach, markets, theme and policies."""
    shop = resolve(store)
    parts = gather({
        "api": lambda: gql(shop, Q.SHOP, label="shop", **shared.context(country, language)),
        "meta": lambda: rest_json(shop, "/meta.json"),
    })
    data = parts["api"]
    return {"market": P.market(data.get("_context")),
            "store": P.store_profile(shop, data.get("shop"), data.get("localization"), parts["meta"])}


def check(store):
    """Is this domain a Shopify store? Never a 404: a non-Shopify site
    answers `is_shopify: false`."""
    seen = inspect(store)
    shop, home = seen["store"], P.as_dict(seen["home"])
    signals = list(home.get("signals") or [])
    if shop is not None:
        signals.insert(0, "storefront_api")
    is_shopify = shop is not None
    if is_shopify:
        confidence = "high"
    elif "shopify_theme_object" in signals or "shopify_shop_object" in signals or "powered_by_header" in signals:
        # Shopify markup without a reachable API: a closed / frozen shop.
        is_shopify, confidence = True, "medium"
    elif signals:
        confidence = "low"
    else:
        confidence = "high" if seen["is_reachable"] else "low"
    return {
        "domain": shop.domain if shop else store,
        "link": shop.origin if shop else refs.store_link(store),
        "is_shopify": is_shopify,
        "confidence": confidence,
        "is_reachable": bool(seen["is_reachable"]),
        "is_headless": bool(shop.is_headless) if shop else None,
        "is_storefront_locked": bool(home.get("is_storefront_locked")) if home else None,
        "store_name": P.text(P.as_dict(shop.shop).get("name")) if shop else P.text(home.get("site_name")),
        "store_id": (refs.numeric_id(P.as_dict(shop.shop).get("id")) if shop else None) or home.get("shop_id"),
        "myshopify_domain": (shop.myshopify_domain if shop else None) or home.get("myshopify_domain")
        or (home.get("myshopify_candidates") or [None])[0],
        "signals": signals,
    }


# ---- apps / theme ---------------------------------------------------------------

def apps(store):
    """Apps and third-party tools the storefront loads, grouped by category."""
    shop = resolve(store)
    found = list(_home(shop).get("apps") or [])
    categories = Counter(a["category"] for a in found)
    return {
        "store": shop.domain,
        "count": len(found),
        "categories": [{"category": name, "count": count} for name, count in categories.most_common()],
        "apps": found,
    }


def theme(store):
    """The theme the Online Store runs (name, version, Theme Store id)."""
    shop = resolve(store)
    home = _home(shop)
    return {"store": shop.domain, "is_headless": bool(shop.is_headless), "theme": P.theme(home.get("theme"))}


# ---- contacts -------------------------------------------------------------------

_JSON_LD_RE = re.compile(r"<script[^>]*ld\+json[^>]*>(.*?)</script\s*>", re.I | re.S)
_LINK_ATTR_RE = re.compile(r"""(?:href|content)\s*=\s*["']([^"']{8,400})["']""", re.I)


def _contact_record(loaded, weight_class, is_homepage, region):
    html = _NOISE_RE.sub(" ", loaded["html"])
    built = build_page(loaded["url"], html)
    # The social-profile regexes cost ~20 us per character of markup. Social
    # links only ever sit in link attributes and JSON-LD, so scan just those
    # (anchors are read from the parsed page either way).
    built.html = "\n".join(_JSON_LD_RE.findall(html) + _LINK_ATTR_RE.findall(html))
    socials, whatsapp = extract_socials(built)
    built.html = html
    return {
        "url": built.url, "is_homepage": is_homepage, "weight_class": weight_class,
        "emails": extract_emails(built), "socials": socials,
        "phones": extract_phones(built, region, extra_candidates=whatsapp),
    }


def contacts(store):
    """Publicly listed emails, phone numbers and social profiles, read from
    the homepage, the contact / about pages and the contact-information
    policy."""
    shop = resolve(store)
    # Phone numbers are parsed against the store's home country (the
    # homepage's Shopify.country is the VISITOR's country, not the store's).
    region = P.text(P.as_dict(P.as_dict(shop.shop).get("paymentSettings")).get("countryCode"))
    targets = [("/", "homepage")] + CONTACT_PATHS
    loaded = run_parallel([(lambda path=path: page_optional(shop.origin + path)) for path, _ in targets])
    if loaded[0] is None and not any(loaded[1:]):
        raise ShopifyUpstreamError(f"could not load the {shop.domain} storefront pages")
    records, seen = [], set()
    for (path, weight_class), result in zip(targets, loaded):
        if not result or result["url"] in seen:
            continue
        final_path = urlparse(result["url"]).path.rstrip("/")
        if path != "/" and (not final_path or final_path == urlparse(shop.origin).path.rstrip("/")
                            or "/pages/" not in final_path + "/" and "/policies/" not in final_path + "/"):
            continue            # a missing page that redirected home
        seen.add(result["url"])
        try:
            records.append(_contact_record(result, weight_class, path == "/", region))
        except Exception:
            continue
    merged = build_output(shop.domain, records)
    socials = {}
    for key in PLATFORM_KEYS:
        links = [entry["value"] for entry in merged.get(key) or []]
        if links:
            socials[key[:-1] if key.endswith("s") and key != "threads" else key] = links
    return {
        "store": shop.domain,
        "emails": [{"value": e["value"], "is_likely_official": bool(e.get("is_likely_official")),
                    "sources": e.get("sources") or []} for e in merged.get("emails") or []],
        "phones": [{"value": p["value"], "is_likely_official": bool(p.get("is_likely_official")),
                    "sources": p.get("sources") or []} for p in merged.get("phones") or []],
        "social_profiles": socials,
        "pages_scanned": [r["url"] for r in records],
    }


# ---- markets / policies / menus -------------------------------------------------

def markets(store):
    """Every country the store sells to with its currency, languages and
    market, plus the store's languages and presentment currencies."""
    shop = resolve(store)
    data = gql(shop, Q.MARKETS, label="markets")
    localization = P.as_dict(data.get("localization"))
    shop_raw = P.as_dict(data.get("shop"))
    payments = P.as_dict(shop_raw.get("paymentSettings"))
    countries = [c for c in (P.country_market(x) for x in P.as_list(localization.get("availableCountries"))) if c]
    currencies = Counter(c["currency"]["code"] for c in countries if c.get("currency"))
    default = P.country_market(localization.get("country")) or {}
    return {
        "store": shop.domain,
        "default_country": default.get("code"),
        "default_currency": P.text(payments.get("currencyCode")),
        "default_language": (P.language_ref(localization.get("language")) or {}).get("code"),
        "countries_count": len(countries),
        "languages": [l for l in (P.language_ref(x) for x in P.as_list(localization.get("availableLanguages"))) if l],
        "currencies": [{"code": code, "countries_count": count} for code, count in currencies.most_common()],
        "enabled_currencies": [c for c in P.as_list(payments.get("enabledPresentmentCurrencies")) if isinstance(c, str)],
        "ships_to_countries": [c for c in P.as_list(shop_raw.get("shipsToCountries")) if isinstance(c, str)],
        "countries": countries,
    }


def policies(store, type=None, country=None, language=None):
    """The store's legal policies in full (privacy, refund, shipping, terms,
    subscription) — all of them, or one `type`."""
    shop = resolve(store)
    data = gql(shop, Q.POLICIES, label="policies", **shared.context(country, language))
    items = P.policies(data.get("shop"), detailed=True)
    if type:
        items = [p for p in items if p["type"] == type]
    return {**shared.envelope(shop, data), "count": len(items), "policies": items}


def menus(store, menu=None, country=None, language=None):
    """Navigation menus by handle (default: main-menu and footer), three
    levels deep, each item with the product / collection / page it points at."""
    shop = resolve(store)
    handles = menu or DEFAULT_MENUS
    data = gql(shop, Q.menus(handles), label="menus", **shared.context(country, language))
    found = [P.menu(data.get(f"m{index}")) for index in range(len(handles)) if isinstance(data.get(f"m{index}"), dict)]
    return {**shared.envelope(shop, data), "requested": handles, "count": len(found), "menus": found}


# ---- catalogue statistics -------------------------------------------------------

def _percentile(ordered, fraction):
    if not ordered:
        return None
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 2)


def _histogram(ordered):
    if not ordered:
        return []
    low, high = ordered[0], ordered[-1]
    if high <= low:
        return [{"from": low, "to": high, "count": len(ordered)}]
    width = (high - low) / HISTOGRAM_BUCKETS
    counts = [0] * HISTOGRAM_BUCKETS
    for value in ordered:
        counts[min(int((value - low) / width), HISTOGRAM_BUCKETS - 1)] += 1
    return [{"from": round(low + width * i, 2), "to": round(low + width * (i + 1), 2), "count": count}
            for i, count in enumerate(counts)]


def _top(counter, size):
    return [{"name": name, "count": count} for name, count in counter.most_common(size)]


def catalog_stats(store, max_products=2500, country=None, language=None):
    """Statistics over the store's catalogue: price distribution, discount
    depth, availability, vendors, product types, tags and how fast new
    products are added. Walks up to `max_products` products."""
    shop = resolve(store)
    prices, discounts = [], []
    vendors, types, tags = Counter(), Counter(), Counter()
    available = on_sale = scanned = 0
    created, currency = [], None
    after, complete, data = None, False, {}
    while scanned < max_products:
        data = gql(shop, Q.PRODUCTS_SCAN, {"first": min(SCAN_PAGE, max_products - scanned), "after": after},
                   label="catalogue walk", **shared.context(country, language))
        connection = P.as_dict(data.get("products"))
        rows = P.nodes(connection)
        for row in rows:
            scanned += 1
            block = P.pricing(row.get("priceRange"), row.get("compareAtPriceRange"))
            currency = currency or block["currency"]
            if block["price"] is not None:
                prices.append(block["price"])
            if block["is_on_sale"]:
                on_sale += 1
                if block["discount_percent"] is not None:
                    discounts.append(block["discount_percent"])
            if row.get("availableForSale"):
                available += 1
            if P.text(row.get("vendor")):
                vendors[P.text(row.get("vendor"))] += 1
            if P.text(row.get("productType")):
                types[P.text(row.get("productType"))] += 1
            for tag in P.as_list(row.get("tags")):
                if P.text(tag):
                    tags[P.text(tag)] += 1
            stamp = P.iso_datetime(row.get("createdAt"))
            if stamp:
                created.append(stamp)
        after, has_next = P.page_info(connection)
        if not has_next or not rows:
            complete = True
            break

    prices.sort()
    created.sort()
    now = datetime.now(timezone.utc)

    def added_since(days):
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return sum(1 for stamp in created if stamp >= cutoff)

    return {
        **shared.envelope(shop, data),
        "products_scanned": scanned,
        "is_complete": complete,
        "prices": {
            "currency": currency,
            "min": prices[0] if prices else None,
            "max": prices[-1] if prices else None,
            "average": round(statistics.fmean(prices), 2) if prices else None,
            "median": _percentile(prices, 0.5),
            "percentile_25": _percentile(prices, 0.25),
            "percentile_75": _percentile(prices, 0.75),
            "histogram": _histogram(prices),
        },
        "discounts": {
            "on_sale_count": on_sale,
            "on_sale_percent": round(on_sale * 100 / scanned, 1) if scanned else None,
            "average_discount_percent": round(statistics.fmean(discounts), 1) if discounts else None,
            "max_discount_percent": max(discounts) if discounts else None,
        },
        "availability": {
            "available_count": available,
            "unavailable_count": scanned - available,
            "available_percent": round(available * 100 / scanned, 1) if scanned else None,
        },
        "new_products": {
            "last_7_days": added_since(7),
            "last_30_days": added_since(30),
            "last_90_days": added_since(90),
            "newest_created_at": created[-1] if created else None,
            "oldest_created_at": created[0] if created else None,
        },
        "vendors_count": len(vendors),
        "vendors": _top(vendors, 50),
        "product_types_count": len(types),
        "product_types": _top(types, 50),
        "tags_count": len(tags),
        "tags": _top(tags, 100),
    }
