"""Shopify transport: plain curl_cffi with browser-impersonated TLS. No
browser, no cookies, no account (validated 2026-10-05 from direct egress on
20 stores).

Every Shopify store answers the same public surfaces on its own domain:

  * STOREFRONT API  POST https://<store>/api/<version>/graphql.json
    Shopify's Storefront GraphQL API. Since 2025 it answers WITHOUT a token
    ("tokenless access", query cost capped at 1000): shop, localization,
    products (sort keys incl. BEST_SELLING, search-syntax filters), product by
    handle or id, search with facets, predictive search, recommendations,
    collections, pages, blogs, articles, menus, policies and carts. This is
    the transport for nearly everything — it also works where the theme JSON
    files are switched off (fashionnova.com, aloyoga.com).

  * STOREFRONT TOKEN  the store's own public Storefront access token, printed
    in every Online Store homepage ("accessToken":"<32 hex>"). It adds the one
    scope tokenless access lacks that matters here: metafields (the standard
    `reviews.rating` / `reviews.rating_count`). It is sent ONLY on the
    id-keyed metafield query (product_metafields): the token's app usually
    lacks scopes tokenless access has — menus and predictive search return
    null with it. Never required; a refused token is forgotten.

  * HEADLESS STORES  a custom frontend (Next.js / Hydrogen: gymshark.com,
    ruggable.com) does not proxy /api/. Its HTML still names the backing
    `<shop>.myshopify.com`, whose Storefront API is open the same way — so a
    store resolves to (public origin, API origin) and both are memoised.

  * THEME JSON  GET /meta.json, /collections/<handle>.json — small extras the
    API lacks (city / province, catalogue counts, per-collection product
    count). Always optional: a 404 / 403 there just leaves fields null.

  * HOMEPAGE HTML  the token, `Shopify.theme`, the myshopify domain, app
    script hosts and contact details (storefront.py reads it).

Blocks: none seen. A 403 / 429 / 430 from a store moves THAT store's calls to
a sticky residential exit (config.shopify_fallback_proxy()) for
config.SHOPIFY_BLOCK_COOLDOWN seconds — blocks are per store (each has its
own WAF rules), so the fallback is too.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  ShopifyUpstreamError  transport failure / 5xx / GraphQL error  — retryable
  ShopifyBlocked        403 / 429 / 430 / throttled               — retryable on a new exit
  ShopifyBadRequest     the API rejected a variable                — never retried
  ShopifyNotFound       not a Shopify store / missing entity       — never retried
"""
import json
import os
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from shopify import queries, storefront

IMPERSONATE = "chrome"
TIMEOUT = 40
PAGE_TIMEOUT = 40
FANOUT_WORKERS = 6
MAX_REDIRECTS = 4
MAX_MYSHOPIFY_CANDIDATES = 3
STORE_MEMO_SIZE = 3000
NOT_FOUND_TTL = 600

JSON_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
}
PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "upgrade-insecure-requests": "1",
}
_BLOCK_STATUSES = (403, 429, 430)


class ShopifyUpstreamError(UpstreamError):
    """Transport failure, 5xx or a GraphQL-level error — retryable."""


class ShopifyQueryError(ShopifyUpstreamError):
    """The API answered with a GraphQL error — deterministic, not retried."""


class ShopifyBlocked(ShopifyUpstreamError, Blocked):
    """403 / 429 / 430 or a throttled query — retryable on a new exit."""


class ShopifyBadRequest(BadRequest):
    """The Storefront API rejected a variable. Never retried."""


class ShopifyNotFound(NotFound):
    """Not a Shopify store, or the entity does not exist — never retried."""


class Store:
    """A resolved store: where the public pages live and where its
    Storefront API answers."""
    __slots__ = ("host", "origin", "api", "token", "myshopify_domain", "shop", "home", "is_headless")

    def __init__(self, host, origin, api, token, myshopify_domain, shop, home, is_headless):
        self.host = host                          # what the caller passed
        self.origin = origin                      # public storefront origin (links)
        self.api = api                            # origin answering /api/<v>/graphql.json
        self.token = token                        # storefront token or None
        self.myshopify_domain = myshopify_domain
        self.shop = shop                          # the probe's shop object
        self.home = home                          # storefront.home_facts() or None
        self.is_headless = is_headless

    @property
    def domain(self):
        return urlparse(self.origin).hostname


# ---- sessions ------------------------------------------------------------------
# Per worker thread: one direct session and one proxied session. A store that
# refused the direct egress is served through the proxy for a cooldown.
_local = threading.local()
_blocked_until = {}
_blocked_lock = threading.Lock()


def _host_of(url):
    return (urlparse(url).hostname or "").lower()


def _is_blocked(host):
    until = _blocked_until.get(host)
    return bool(until and until > time.time())


def _note_block(host):
    if config.shopify_fallback_proxy() is None:
        return
    with _blocked_lock:
        if len(_blocked_until) > 5000:
            now = time.time()
            for key in [k for k, v in _blocked_until.items() if v <= now]:
                _blocked_until.pop(key, None)
        _blocked_until[host] = time.time() + config.SHOPIFY_BLOCK_COOLDOWN


def _session(host):
    forced = config.shopify_proxy()
    kind = "proxy" if (forced or _is_blocked(host)) else "direct"
    sessions = getattr(_local, "sessions", None)
    if sessions is None:
        sessions = _local.sessions = {}
    sess = sessions.get(kind)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if kind == "proxy":
            proxy = forced or config.shopify_fallback_proxy()
            if proxy:
                sess.proxies = {"http": proxy, "https": proxy}
        sessions[kind] = sess
    return sess


def _drop_sessions():
    sessions = getattr(_local, "sessions", None) or {}
    _local.sessions = {}
    for sess in sessions.values():
        try:
            sess.close()
        except Exception:
            pass


def dump_debug(name, text):
    dbg = os.environ.get("SHOPIFY_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- raw requests ---------------------------------------------------------------

def _send(method, url, **kwargs):
    """One HTTP call on the calling thread's session for that host. Transport
    errors -> ShopifyUpstreamError (ShopifyNotFound when the host does not
    resolve)."""
    host = _host_of(url)
    try:
        return _session(host).request(method, url, **kwargs)
    except Exception as e:
        message = str(e)
        if "Could not resolve host" in message or "curl: (6)" in message:
            raise ShopifyNotFound(f"'{host}' does not resolve — check the store domain")
        raise ShopifyUpstreamError(f"request to {host} failed: {type(e).__name__}: {message[:200]}")


def _retrying(fn):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except ShopifyQueryError:
            raise
        except ShopifyUpstreamError as e:      # includes ShopifyBlocked
            last = e
            _drop_sessions()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _post_graphql(api_origin, document, variables, token):
    headers = dict(JSON_HEADERS)
    if token:
        headers["X-Shopify-Storefront-Access-Token"] = token
    url = f"{api_origin}/api/{config.SHOPIFY_API_VERSION}/graphql.json"
    body = json.dumps({"query": document, "variables": variables or {}})
    return _send("POST", url, data=body, headers=headers, timeout=TIMEOUT, allow_redirects=False)


def _body_json(resp):
    text = resp.text or ""
    if not text.lstrip().startswith("{"):
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


# ---- store resolution -----------------------------------------------------------

_stores = OrderedDict()            # host -> (expires, Store | ShopifyNotFound)
_stores_lock = threading.Lock()


def _memo_get(host):
    with _stores_lock:
        hit = _stores.get(host)
        if hit and hit[0] > time.time():
            _stores.move_to_end(host)
            return hit[1]
        if hit:
            _stores.pop(host, None)
    return None


def _memo_put(host, value, ttl):
    with _stores_lock:
        _stores[host] = (time.time() + ttl, value)
        _stores.move_to_end(host)
        while len(_stores) > STORE_MEMO_SIZE:
            _stores.popitem(last=False)


def forget(host):
    with _stores_lock:
        _stores.pop(host, None)


def _probe(origin):
    """Does `origin` answer the Storefront API? -> (api origin, shop dict) or
    None. A redirect is followed by hand so the POST stays a POST
    (allbirds.com -> www.allbirds.com). Raises ShopifyBlocked on 403/429."""
    for _ in range(MAX_REDIRECTS):
        resp = _post_graphql(origin, queries.PROBE, None, None)
        status = resp.status_code
        if status in (301, 302, 303, 307, 308):
            location = resp.headers.get("location") or ""
            target = urlparse(location)
            if not target.hostname:
                return None
            moved = f"{target.scheme or 'https'}://{target.hostname.lower()}"
            if moved == origin:
                return None
            origin = moved
            continue
        if status in _BLOCK_STATUSES:
            body = _body_json(resp)
            if body is None:
                _note_block(_host_of(origin))
                raise ShopifyBlocked(f"HTTP {status} from {_host_of(origin)}")
        body = _body_json(resp)
        shop = ((body or {}).get("data") or {}).get("shop") if body else None
        if isinstance(shop, dict) and shop.get("id"):
            return origin, shop
        return None
    return None


def _probe_retrying(origin):
    """_probe, repeated through the fallback exit when the direct egress is
    refused. A store that cannot be reached at all is 'no API here'."""
    blocked = None
    for _ in range(2):
        try:
            return _probe(origin)
        except ShopifyBlocked as e:
            blocked = e
            _drop_sessions()
            if config.shopify_fallback_proxy() is None:
                break
        except ShopifyNotFound:
            raise
        except ShopifyUpstreamError:
            return None
    raise blocked


def _load_home(host):
    """The storefront homepage -> storefront.home_facts() or None. Never raises."""
    for _ in range(2):
        try:
            resp = _send("GET", f"https://{host}/", headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT,
                         allow_redirects=True)
        except Exception:
            return None
        if resp.status_code in _BLOCK_STATUSES and not _is_blocked(host) \
                and config.shopify_fallback_proxy() is not None:
            _note_block(host)
            _drop_sessions()
            continue
        if resp.status_code != 200:
            return None
        return storefront.home_facts(resp.text or "", str(resp.url), dict(resp.headers))
    return None


def resolve(host):
    """Store host -> Store (memoised config.SHOPIFY_STORE_TTL seconds).
    Raises ShopifyNotFound when no Storefront API can be found for it."""
    host = (host or "").lower()
    hit = _memo_get(host)
    if isinstance(hit, Store):
        return hit
    if isinstance(hit, ShopifyNotFound):
        raise ShopifyNotFound(str(hit))
    try:
        store = _resolve(host)
    except ShopifyNotFound as e:
        _memo_put(host, e, NOT_FOUND_TTL)
        raise
    _memo_put(host, store, config.SHOPIFY_STORE_TTL)
    return store


def _resolve(host):
    origin = f"https://{host}"
    with ThreadPoolExecutor(max_workers=2) as ex:
        home_future = ex.submit(_load_home, host)
        probe_error = None
        try:
            found = _probe_retrying(origin)
        except ShopifyBlocked as e:
            found, probe_error = None, e
        home = home_future.result()

    public_origin = (home or {}).get("origin") or origin
    if home and "checkout" in _host_of(public_origin).split(".") and not host.startswith("www."):
        # An apex that only forwards to the checkout domain (gymshark.com ->
        # us.checkout.gymshark.com): the storefront people browse is on www.
        www_home = _load_home("www." + host)
        if www_home and "checkout" not in _host_of(www_home.get("origin") or "").split("."):
            if not www_home.get("token"):
                www_home["token"] = home.get("token")
            if not www_home.get("myshopify_domain"):
                www_home["myshopify_domain"] = home.get("myshopify_domain")
            home, public_origin = www_home, www_home.get("origin") or public_origin
    if not found and home:
        candidates = []
        if public_origin != origin:
            candidates.append(public_origin)
        for name in (home.get("myshopify_candidates") or [])[:MAX_MYSHOPIFY_CANDIDATES]:
            candidates.append(f"https://{name}")
        siblings = [f"https://{name}" for name in home.get("commerce_hosts") or []]
        for candidate in candidates + siblings:
            try:
                found = _probe_retrying(candidate)
            except (ShopifyUpstreamError, ShopifyNotFound):
                found = None
            if not found:
                continue
            if candidate in siblings:
                # A brand site that only LINKS to its shop (taylorswift.com ->
                # store.taylorswift.com): when that host serves its own Online
                # Store, it — not the brand site — is the storefront.
                shop_home = _load_home(_host_of(found[0]))
                if shop_home and shop_home.get("is_online_store") \
                        and _host_of(shop_home.get("origin") or "") == _host_of(found[0]):
                    home, public_origin = shop_home, shop_home["origin"]
            break
    if not found:
        # A WAF refusing the API path of a site whose homepage shows nothing
        # of Shopify is "not a Shopify store", not a block worth retrying.
        if probe_error is not None and not (home and not home.get("signals")):
            raise probe_error
        raise ShopifyNotFound(f"'{host}' is not a Shopify store (no Storefront API found on it)")

    api_origin, shop = found
    api_host = _host_of(api_origin)
    if home is None and api_host != host and not api_host.endswith(".myshopify.com"):
        public_origin = api_origin          # the probe followed a redirect the homepage could not
    myshopify = (home or {}).get("myshopify_domain")
    if api_host.endswith(".myshopify.com"):
        myshopify = api_host
    # Headless = the public site is a custom frontend, not a Liquid theme.
    is_headless = home is not None and not home.get("is_online_store")
    return Store(host=host, origin=public_origin, api=api_origin, token=(home or {}).get("token"),
                 myshopify_domain=myshopify, shop=shop, home=home, is_headless=is_headless)


# ---- storefront API -------------------------------------------------------------

_BAD_VARIABLE_CODES = {"INVALID_VARIABLE", "argumentLiteralsIncompatible", "variableMismatch",
                       "BAD_USER_INPUT", "invalid"}


def _error_text(errors):
    parts = []
    for err in errors or []:
        if isinstance(err, dict) and err.get("message"):
            parts.append(str(err["message"]))
    return "; ".join(parts)[:400] or "unknown GraphQL error"


def _error_codes(errors):
    return {str(((e or {}).get("extensions") or {}).get("code") or "") for e in errors or [] if isinstance(e, dict)}


def gql(store, document, variables=None, *, country=None, language=None, label=None, use_token=False):
    """Run one Storefront API document for a store -> its `data` dict, with
    the resolved market under `_context` ({"country", "language"}).

    Tokenless unless `use_token` (see product_metafields): a token call that
    is refused raises ShopifyQueryError and forgets the token."""
    label = label or "storefront api"
    payload = dict(variables or {})
    if not use_token:
        payload["country"] = country
        payload["language"] = language
    token = store.token if use_token else None

    def once():
        resp = _post_graphql(store.api, document, payload, token)
        status = resp.status_code
        body = _body_json(resp)
        if token and (status in (401, 403) or (body and "ACCESS_DENIED" in _error_codes(body.get("errors")))):
            store.token = None
            raise ShopifyQueryError(f"{store.domain} storefront token refused on {label}")
        if status in (301, 302, 303, 307, 308, 404):
            forget(store.host)                 # the store moved: resolve again next call
            raise ShopifyUpstreamError(f"{store.domain} stopped answering its Storefront API (HTTP {status})")
        if status == 402:
            raise ShopifyNotFound(f"{store.domain} is unavailable (the shop is frozen or closed)")
        if status in _BLOCK_STATUSES and body is None:
            dump_debug("blocked", resp.text)
            _note_block(_host_of(store.api))
            raise ShopifyBlocked(f"HTTP {status} on {label}")
        if body is None:
            dump_debug("nonjson", resp.text)
            if status >= 500:
                raise ShopifyUpstreamError(f"HTTP {status} on {label}")
            raise ShopifyBlocked(f"{label} returned HTML, not JSON (HTTP {status})")
        errors = body.get("errors")
        data = body.get("data")
        if errors and not data:
            codes = _error_codes(errors)
            message = _error_text(errors)
            if "THROTTLED" in codes:
                _note_block(_host_of(store.api))
                raise ShopifyBlocked(f"throttled on {label}")
            if codes & _BAD_VARIABLE_CODES or "invalid value" in message or "cursor" in message.lower():
                raise ShopifyBadRequest(message)
            dump_debug("graphql_error", json.dumps(body)[:20000])
            if message.startswith("Internal error"):
                # Shopify-side hiccup, seen at random on heavy pages: retry.
                raise ShopifyUpstreamError(f"{label}: Shopify internal error")
            raise ShopifyQueryError(f"{label}: {message}")
        if not isinstance(data, dict):
            raise ShopifyUpstreamError(f"{label} returned no data")
        context = (body.get("extensions") or {}).get("context")
        data["_context"] = context if isinstance(context, dict) else None
        return data

    return _retrying(once)


def product_metafields(store, product_gids, detailed=False):
    """{product gid: {"rating", "ratingCount"[, "metafields"]}} read with the
    store's storefront token. Optional data: no token, a refused token or any
    failure -> {}."""
    ids = [g for g in product_gids if g][:250]
    if not ids or not store.token:
        return {}
    try:
        data = gql(store, queries.product_metafields(detailed), {"ids": ids}, label="product metafields",
                   use_token=True)
    except Exception:
        return {}
    return {node["id"]: node for node in data.get("nodes") or [] if isinstance(node, dict) and node.get("id")}


def mutate(store, document, variables, label="storefront api"):
    """A tokenless mutation (carts) -> `data`. Same failure mapping as gql."""
    def once():
        resp = _post_graphql(store.api, document, variables, None)
        status = resp.status_code
        body = _body_json(resp)
        if status in _BLOCK_STATUSES and body is None:
            _note_block(_host_of(store.api))
            raise ShopifyBlocked(f"HTTP {status} on {label}")
        if body is None:
            raise ShopifyUpstreamError(f"HTTP {status} on {label}")
        data = body.get("data")
        if body.get("errors") and not data:
            if "THROTTLED" in _error_codes(body["errors"]):
                raise ShopifyBlocked(f"throttled on {label}")
            raise ShopifyQueryError(f"{label}: {_error_text(body['errors'])}")
        return data if isinstance(data, dict) else {}
    return _retrying(once)


# ---- theme JSON / pages ---------------------------------------------------------

def _rest_origin(store):
    """Theme files live on the Online Store domain; a headless store only
    has them (if at all) on its myshopify domain."""
    if store.is_headless and store.myshopify_domain:
        return f"https://{store.myshopify_domain}"
    return store.origin


def rest_json(store, path, params=None):
    """GET one theme JSON file (/meta.json, /collections/<h>.json). Optional
    data: any failure -> None."""
    try:
        resp = _send("GET", _rest_origin(store) + path, params=params, headers={"accept": "application/json"},
                     timeout=TIMEOUT, allow_redirects=True)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return _body_json(resp)


def page(url):
    """GET one HTML page -> {"url": final url, "html", "headers", "status"}.
    Raises ShopifyBlocked / ShopifyUpstreamError / ShopifyNotFound."""
    host = _host_of(url)

    def once():
        resp = _send("GET", url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, allow_redirects=True)
        status = resp.status_code
        if status == 404:
            raise ShopifyNotFound(f"{url} not found")
        if status in _BLOCK_STATUSES:
            _note_block(host)
            raise ShopifyBlocked(f"HTTP {status} on {host}")
        if status != 200:
            raise ShopifyUpstreamError(f"HTTP {status} on {host}")
        return {"url": str(resp.url), "html": resp.text or "", "headers": dict(resp.headers), "status": status}
    return _retrying(once)


def page_optional(url):
    """page(), but any failure -> None (one attempt, never raises)."""
    try:
        resp = _send("GET", url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, allow_redirects=True)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return {"url": str(resp.url), "html": resp.text or "", "headers": dict(resp.headers), "status": 200}


def inspect(host):
    """Everything /store/check needs, without raising for a non-Shopify
    site: {"store": Store | None, "home": facts | None, "reason": str | None,
    "is_reachable": bool}."""
    try:
        store = resolve(host)
        return {"store": store, "home": store.home, "reason": None, "is_reachable": True}
    except ShopifyNotFound as e:
        home = _load_home(host)
        return {"store": None, "home": home, "reason": str(e),
                "is_reachable": home is not None or "does not resolve" not in str(e)}


# ---- fan-out ------------------------------------------------------------------------

def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    with ThreadPoolExecutor(max_workers=min(FANOUT_WORKERS, len(fns))) as ex:
        futures = [ex.submit(fn) for fn in fns]
        return [f.result() for f in futures]


def gather(mapping):
    """{key: callable} in parallel -> {key: result}."""
    keys = list(mapping)
    return dict(zip(keys, run_parallel([mapping[k] for k in keys])))


if __name__ == "__main__":
    # Smoke test: python shopify/fetch.py [store]
    target = sys.argv[1] if len(sys.argv) > 1 else "allbirds.com"
    s = resolve(target)
    print(f"store {target}: origin={s.origin} api={s.api} token={'yes' if s.token else 'no'} "
          f"myshopify={s.myshopify_domain} headless={s.is_headless}")
    data = gql(s, queries.PRODUCTS, {"first": 3, "sortKey": "BEST_SELLING"})
    print("best sellers:", [(p["handle"], p["priceRange"]["minVariantPrice"]["amount"]) for p in data["products"]["nodes"]])
