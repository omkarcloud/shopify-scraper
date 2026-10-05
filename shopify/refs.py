"""Shopify reference parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrIdField convention — never a sibling `url`/`id` pair).

Shopify is not one site but millions of stores, so every route is scoped by
`store`, and the entity params also accept a full link that already names
the store:

  store        allbirds.com | www.allbirds.com | https://www.allbirds.com/collections/mens
               | weareallbirds.myshopify.com
  product      mens-wool-runners (handle) | 7340901859408 (id)
               | gid://shopify/Product/7340901859408
               | https://www.allbirds.com/products/mens-wool-runners?variant=...
               | https://www.allbirds.com/en-ca/collections/mens/products/mens-wool-runners
  collection   mens (handle) | 132815978576 (id) | gid://shopify/Collection/...
               | https://www.allbirds.com/collections/mens
  page         our-story (handle) | https://www.allbirds.com/pages/our-story
  blog         news (handle) | https://www.deathwishcoffee.com/blogs/news
  article      news/how-to-use-an-aeropress (blog/article handles)
               | https://www.deathwishcoffee.com/blogs/news/how-to-use-an-aeropress

A handle / id form needs `store`; a link form carries its own store (and
wins over `store` when both are given). Entity resolvers return
{"store": host | None, "handle": str | None, "id": int | None}.
"""
import re
from urllib.parse import unquote, urlparse

_HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9\-]{1,62}$")
_GID_RE = re.compile(r"^gid://shopify/(\w+)/(\d+)", re.I)
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,4})?$", re.I)
_BAD_HANDLE_RE = re.compile(r"[\s/?#<>\"']")
_ID_MIN_DIGITS = 6


def _has_scheme(value):
    return value.lower().startswith(("http://", "https://", "//"))


def _looks_like_link(value):
    """A scheme, or a `host.tld/...` form (handles never contain a slash
    preceded by a dotted host; `news/my-post` has no dot before the slash)."""
    if _has_scheme(value):
        return True
    head = value.split("/", 1)[0].split("?", 1)[0]
    return "/" in value and "." in head and _HOST_RE.match(head.lower().split(":")[0]) is not None


def _parse(value):
    """Any link form -> (host, [path segments]). Raises ValueError."""
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not _HOST_RE.match(host):
        raise ValueError("not a valid store link")
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    return host, segments


def _clean_handle(value):
    value = unquote(str(value)).strip()
    for suffix in (".json", ".js", ".atom", ".oembed", ".xml"):
        if value.lower().endswith(suffix):
            value = value[: -len(suffix)]
    return value


def _after(segments, marker):
    """The path segment after the LAST `marker` segment (a product link may
    be /collections/<c>/products/<p>), else None."""
    for index in range(len(segments) - 1, -1, -1):
        if segments[index].lower() == marker and index + 1 < len(segments):
            return _clean_handle(segments[index + 1])
    return None


# ---- store ----------------------------------------------------------------------

def resolve_store(value):
    """Domain or any link on the store -> the lower-case host."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("store is required")
    try:
        host, _ = _parse(value.split()[0])
    except ValueError:
        raise ValueError("store must be a store domain (allbirds.com) or any link on the store")
    return host


def store_link(host):
    return f"https://{host}" if host else None


# ---- entities -------------------------------------------------------------------

def _entity(value, *, name, marker, gid_type, example):
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    gid = _GID_RE.match(value)
    if gid:
        if gid.group(1).lower() != gid_type.lower():
            raise ValueError(f"{name} must be a {gid_type} id, not a {gid.group(1)} id")
        return {"store": None, "handle": None, "id": int(gid.group(2))}
    if _looks_like_link(value):
        try:
            host, segments = _parse(value)
        except ValueError:
            raise ValueError(f"{name} must be a {name} handle, id or link ({example})")
        handle = _after(segments, marker)
        if not handle:
            raise ValueError(f"{name} link must contain /{marker}/<handle> ({example})")
        return {"store": host, "handle": handle, "id": None}
    value = _clean_handle(value)
    if value.isdigit() and len(value) >= _ID_MIN_DIGITS:
        return {"store": None, "handle": None, "id": int(value)}
    if not value or _BAD_HANDLE_RE.search(value) or len(value) > 255:
        raise ValueError(f"{name} must be a {name} handle, id or link ({example})")
    return {"store": None, "handle": value, "id": None}


def resolve_product(value):
    return _entity(value, name="product", marker="products", gid_type="Product",
                   example="https://www.allbirds.com/products/mens-wool-runners")


def resolve_collection(value):
    return _entity(value, name="collection", marker="collections", gid_type="Collection",
                   example="https://www.allbirds.com/collections/mens")


def resolve_page(value):
    return _entity(value, name="page", marker="pages", gid_type="Page",
                   example="https://www.allbirds.com/pages/our-story")


def resolve_blog(value):
    return _entity(value, name="blog", marker="blogs", gid_type="Blog",
                   example="https://www.deathwishcoffee.com/blogs/news")


def resolve_article(value):
    """`blog/article` handles, an Article id or an article link ->
    {"store", "blog", "handle", "id"}."""
    example = "https://www.deathwishcoffee.com/blogs/news/how-to-use-an-aeropress"
    value = str(value or "").strip()
    if not value:
        raise ValueError("article is required")
    gid = _GID_RE.match(value)
    if gid:
        if gid.group(1).lower() != "article":
            raise ValueError(f"article must be an Article id, not a {gid.group(1)} id")
        return {"store": None, "blog": None, "handle": None, "id": int(gid.group(2))}
    store = None
    if _looks_like_link(value):
        try:
            store, segments = _parse(value)
        except ValueError:
            raise ValueError(f"article must be `blog/article` handles, an id or a link ({example})")
        for index in range(len(segments) - 1, -1, -1):
            if segments[index].lower() == "blogs":
                segments = segments[index + 1:]
                break
        else:
            raise ValueError(f"article link must contain /blogs/<blog>/<article> ({example})")
    else:
        if value.isdigit() and len(value) >= _ID_MIN_DIGITS:
            return {"store": None, "blog": None, "handle": None, "id": int(value)}
        segments = [s for s in value.split("?")[0].split("#")[0].split("/") if s]
    if len(segments) < 2:
        raise ValueError(f"article must name its blog too: `news/how-to-use-an-aeropress` or a link ({example})")
    blog, handle = _clean_handle(segments[0]), _clean_handle(segments[1])
    if _BAD_HANDLE_RE.search(blog) or _BAD_HANDLE_RE.search(handle):
        raise ValueError(f"article must be `blog/article` handles, an id or a link ({example})")
    return {"store": store, "blog": blog, "handle": handle, "id": None}


def strip_locale(segments):
    """Drop a leading market prefix (/en-ca/products/x -> products/x)."""
    if segments and _LOCALE_RE.match(segments[0]) and len(segments) > 1 and segments[0].lower() not in (
            "products", "collections", "pages", "blogs", "policies", "search", "cart", "account"):
        return segments[1:]
    return segments


def gid(kind, numeric_id):
    return f"gid://shopify/{kind}/{numeric_id}"


def numeric_id(value):
    """gid://shopify/Product/123?x -> 123 (int); a bare int passes through."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"/(\d+)(?:\?|$)", str(value))
    if match:
        return int(match.group(1))
    return int(value) if str(value).isdigit() else None
