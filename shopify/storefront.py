"""What a storefront's homepage HTML says about the store — pure parsing, no
network. fetch.resolve() runs home_facts() once per store and memoises the
result with the store.

An Online Store (Liquid theme) homepage prints, in inline scripts:

    Shopify.shop = "weareallbirds.myshopify.com";
    Shopify.locale = "en-US"; Shopify.currency = {"active":"USD","rate":"1.0"};
    Shopify.country = "US";
    Shopify.theme = {"name":"…","id":130450260048,"schema_name":"Dawn",
                     "schema_version":"10.0.0","theme_store_id":887,"role":"main"};
    … "accessToken":"<32 hex>" …        (the storefront token, see fetch.py)

A headless frontend prints none of that but still references
`<shop>.myshopify.com` (checkout links, image URLs, config blobs).
"""
import html as html_lib
import json
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

import tldextract

from shopify import apps

# Bundled public-suffix snapshot: never fetched at runtime.
_tld_extract = tldextract.TLDExtract(suffix_list_urls=())
_COMMERCE_LABELS = ("checkout", "shop", "store", "secure", "buy", "merch", "order")

_TOKEN_RES = [
    re.compile(r'"accessToken"\s*:\s*"([a-f0-9]{32})"'),
    re.compile(r'[sS]torefront(?:Access|Api|_access_|_api_)?[tT]oken["\']?\s*[:=]\s*["\']([a-f0-9]{32})["\']'),
    re.compile(r'X-Shopify-Storefront-Access-Token["\']?\s*[:,]\s*["\']([a-f0-9]{32})["\']', re.I),
]
_MYSHOPIFY_RE = re.compile(r"\b([a-z0-9][a-z0-9\-]{0,60})\.myshopify\.com\b")
_SHOP_RE = re.compile(r'Shopify\.shop\s*=\s*"([a-z0-9\-]+\.myshopify\.com)"')
_THEME_RE = re.compile(r"Shopify\.theme\s*=\s*(\{.*?\})\s*;")
_LOCALE_RE = re.compile(r'Shopify\.locale\s*=\s*"([A-Za-z\-]{2,10})"')
_COUNTRY_RE = re.compile(r'Shopify\.country\s*=\s*"([A-Z]{2})"')
_CURRENCY_RE = re.compile(r'Shopify\.currency\s*=\s*\{"active"\s*:\s*"([A-Z]{3})"')
_SHOP_ID_RE = re.compile(r'"shopId"\s*:\s*(\d+)')
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'([a-zA-Z:\-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
_STAGING_HINTS = ("stage", "staging", "dev", "test", "sandbox", "uat", "qa")


def _attrs(tag):
    return {name.lower(): (dq if dq != "" or sq == "" else sq) for name, dq, sq in _ATTR_RE.findall(tag)}


def _clean(value):
    if value is None:
        return None
    value = " ".join(html_lib.unescape(str(value)).split())
    return value or None


def _metas(html):
    """{name-or-property (lower): content} for the <head> metas."""
    out = {}
    for tag in _META_RE.findall(html[:400_000]):
        attrs = _attrs(tag)
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and key not in out and attrs.get("content"):
            out[key] = attrs["content"]
    return out


def _favicon(html, base):
    for tag in _LINK_RE.findall(html[:400_000]):
        attrs = _attrs(tag)
        rel = (attrs.get("rel") or "").lower()
        if "icon" in rel and attrs.get("href"):
            return urljoin(base, html_lib.unescape(attrs["href"]))
    return None


def _absolute(link, base):
    if not link:
        return None
    link = html_lib.unescape(link.strip())
    if link.startswith("//"):
        return "https:" + link
    return urljoin(base, link)


def _theme(html):
    match = _THEME_RE.search(html)
    if not match:
        return None
    try:
        raw = json.loads(match.group(1))
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None


def myshopify_candidates(html, primary=None):
    """`<shop>.myshopify.com` hosts named in the HTML, most likely first: the
    declared Shopify.shop, then by frequency with staging-looking names last."""
    counts = Counter(_MYSHOPIFY_RE.findall(html))
    counts.pop("cdn", None)
    counts.pop("checkout", None)

    def rank(item):
        name, count = item
        looks_staging = any(hint in name.split("-") or name.startswith(hint + "-") or name.endswith("-" + hint)
                            for hint in _STAGING_HINTS)
        return (looks_staging, -count)

    ordered = [f"{name}.myshopify.com" for name, _ in sorted(counts.items(), key=rank)]
    if primary:
        ordered = [primary] + [d for d in ordered if d != primary]
    return ordered


def commerce_hosts(html, host):
    """Sibling hosts of `host` named in the HTML that look like where a
    headless brand keeps its Shopify backend (checkout.hydrogen.shop,
    shop.bombas.com, store.taylorswift.com), most mentioned first."""
    registrable = _tld_extract(host or "").registered_domain
    if not registrable:
        return []
    found = Counter(re.findall(r"\b((?:[a-z0-9\-]+\.)+" + re.escape(registrable) + r")\b", html))
    return [name for name, _ in found.most_common()
            if name != host and name.split(".")[0] in _COMMERCE_LABELS][:3]


def home_facts(html, final_url, headers=None):
    """Homepage HTML -> the facts every /shopify/store/* endpoint and the
    store resolver share. Never raises; missing facts are None."""
    html = html or ""
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    parsed = urlparse(final_url or "")
    origin = f"{parsed.scheme or 'https'}://{parsed.hostname}" if parsed.hostname else None

    token = None
    for pattern in _TOKEN_RES:
        match = pattern.search(html)
        if match:
            token = match.group(1)
            break

    shop_match = _SHOP_RE.search(html)
    primary = shop_match.group(1) if shop_match else None
    candidates = myshopify_candidates(html, primary)
    theme = _theme(html)
    metas = _metas(html)
    title_match = _TITLE_RE.search(html[:400_000])

    powered_by = headers.get("powered-by") or headers.get("x-powered-by")
    signals = []
    if powered_by and "shopify" in powered_by.lower():
        signals.append("powered_by_header")
    if theme is not None:
        signals.append("shopify_theme_object")
    if primary:
        signals.append("shopify_shop_object")
    elif candidates:
        signals.append("myshopify_domain_in_html")
    if "cdn.shopify.com" in html:
        signals.append("shopify_cdn_assets")
    if token:
        signals.append("storefront_access_token")
    if "shopify-digital-wallet" in html or "monorail-edge.shopifysvc.com" in html:
        signals.append("shopify_checkout_scripts")

    locale = _LOCALE_RE.search(html)
    country = _COUNTRY_RE.search(html)
    currency = _CURRENCY_RE.search(html)
    shop_id = _SHOP_ID_RE.search(html)
    path = (parsed.path or "").rstrip("/")
    return {
        "final_url": final_url,
        "origin": origin,
        "token": token,
        "myshopify_domain": primary,
        "myshopify_candidates": candidates,
        "commerce_hosts": commerce_hosts(html, parsed.hostname),
        "is_online_store": theme is not None or primary is not None,
        # Shopify serves a locked ("opening soon") storefront from one fixed path.
        "is_storefront_locked": path.endswith("/pass" + "word"),
        "shop_id": int(shop_id.group(1)) if shop_id else None,
        "theme": theme,
        "locale": locale.group(1) if locale else None,
        "country": country.group(1) if country else None,
        "currency": currency.group(1) if currency else None,
        "title": _clean(title_match.group(1)) if title_match else None,
        "description": _clean(metas.get("description") or metas.get("og:description")),
        "site_name": _clean(metas.get("og:site_name")),
        "share_image": _absolute(metas.get("og:image:secure_url") or metas.get("og:image"), final_url or ""),
        "favicon": _favicon(html, final_url or ""),
        "theme_color": _clean(metas.get("theme-color")),
        "powered_by": powered_by,
        "signals": signals,
        "apps": apps.detect(html),
    }
