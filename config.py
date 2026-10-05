"""Configuration for the Shopify Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT           port the API listens on (default 8000)
    SHOPIFY_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                   (default: none — direct). Shopify stores answered a
                   240-request burst from one IP without a single block, so you
                   very likely don't need this. Set it only if a store starts
                   answering 403 / 429 / 430 at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# Storefront API version the scraper talks to. Shopify keeps serving a
# retired version from the oldest one it still supports, so this ages well.
SHOPIFY_API_VERSION = "2026-07"

# How long a resolved store (where its API answers, its homepage facts) is
# remembered in memory, in seconds.
SHOPIFY_STORE_TTL = 6 * 3600

# Block fallback: after a 403 / 429 / 430 a store's requests may switch to a
# separate proxy for SHOPIFY_BLOCK_COOLDOWN seconds. Off here — with
# SHOPIFY_PROXY set every request already goes through it.
SHOPIFY_BLOCK_COOLDOWN = 900


def shopify_proxy():
    """Proxy URL for a new session (None = direct)."""
    return os.environ.get("SHOPIFY_PROXY") or None


def shopify_fallback_proxy():
    """Proxy for a store that refused the direct connection (None = no
    fallback; see above)."""
    return None
