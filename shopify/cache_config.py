"""Cache TTL per /shopify/* endpoint (cache.py, keyed on the validated params).

Tiers follow how fast a store moves each surface: stock changes with every
order, prices and availability a few times a day, the catalogue's shape and
the store's own identity far more slowly.
"""
from datetime import timedelta

# --- store -------------------------------------------------------------------
# Name, location, currency, brand, payments: edited a few times a year.
STORE_CACHE = timedelta(hours=12)
# is-it-Shopify verdicts barely change; short enough to notice a migration.
CHECK_CACHE = timedelta(hours=12)
# Apps, theme and contact details change when the merchant redesigns.
APPS_CACHE = timedelta(hours=12)
CONTACTS_CACHE = timedelta(days=1)
MARKETS_CACHE = timedelta(days=1)
POLICIES_CACHE = timedelta(days=1)
MENUS_CACHE = timedelta(hours=6)
# A catalogue walk is 10+ upstream calls; the aggregates drift slowly.
STATS_CACHE = timedelta(hours=6)

# --- products ----------------------------------------------------------------
# Price / availability / compare-at move with sales and restocks.
PRODUCTS_CACHE = timedelta(minutes=30)
PRODUCT_CACHE = timedelta(minutes=30)
SEARCH_CACHE = timedelta(minutes=30)
# Best-seller order and recommendations are recomputed by Shopify daily-ish.
RANKING_CACHE = timedelta(hours=2)
RECOMMENDATIONS_CACHE = timedelta(hours=6)
# Stock is the fastest-moving number here.
INVENTORY_CACHE = timedelta(minutes=5)

# --- collections / content ---------------------------------------------------
COLLECTIONS_CACHE = timedelta(hours=6)
COLLECTION_CACHE = timedelta(hours=2)
SUGGESTIONS_CACHE = timedelta(hours=2)
PAGES_CACHE = timedelta(hours=12)
BLOGS_CACHE = timedelta(hours=12)
ARTICLES_CACHE = timedelta(hours=2)
ARTICLE_CACHE = timedelta(hours=12)
