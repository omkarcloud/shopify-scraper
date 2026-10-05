"""Marshmallow request schemas for every /shopify/* route. Generic fields
come from the shared schema_fields.py; this module adds the Shopify
resolvers. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    store        a store domain (allbirds.com) OR any link on the store
    product      a product handle, numeric id OR a product link
    collection   a collection handle, numeric id OR a collection link
    page         a page handle, numeric id OR a page link
    blog         a blog handle, numeric id OR a blog link
    article      `blog/article` handles, a numeric id OR an article link

An entity given as a link names its own store, so `store` is only required
next to a handle or id.
"""
from marshmallow import ValidationError, fields, post_load, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, CountryCodeField, Flag,
                           LanguageCodeField, LimitField, PositiveInt, Price, QueryField, RefField,
                           StrippedString)
from shopify import refs
from shopify.collection import COLLECTION_LIST_SORTS
from shopify.content import PAGE_SORTS
from shopify.products import COLLECTION_SORTS, PRODUCT_SORTS, SEARCH_SORTS, UNAVAILABLE
from shopify.search import TYPES as SUGGESTION_TYPES

POLICY_TYPES = ["privacy", "refund", "shipping", "terms", "subscription"]


# ---- id-or-link fields -------------------------------------------------------------

class StoreField(RefField):
    resolver = staticmethod(refs.resolve_store)


class ProductField(RefField):
    resolver = staticmethod(refs.resolve_product)


class CollectionField(RefField):
    resolver = staticmethod(refs.resolve_collection)


class PageRefField(RefField):
    resolver = staticmethod(refs.resolve_page)


class BlogField(RefField):
    resolver = staticmethod(refs.resolve_blog)


class ArticleField(RefField):
    resolver = staticmethod(refs.resolve_article)


class CursorField(StrippedString):
    """Opaque next_cursor from the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Length(max=2000))
        super().__init__(**kwargs)


class TextFilter(StrippedString):
    """Optional exact-match filter value (vendor, product type, tag ...)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Length(max=255))
        super().__init__(**kwargs)


class OptionField(StrippedString):
    """'Color:Red' -> {"name": "Color", "value": "Red"} (a variant option)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        name, sep, picked = value.partition(":")
        name, picked = name.strip(), picked.strip()
        if not sep or not name or not picked:
            raise ValidationError("Must look like Name:Value (e.g. Color:Red or Size:M).")
        return {"name": name, "value": picked}


class Percent(fields.Float):
    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Range(min=0, max=100))
        super().__init__(**kwargs)


# ---- bases ---------------------------------------------------------------------------

class StoreSchema(BaseSchema):
    store = StoreField()


class MarketSchema(BaseSchema):
    """The market a response is read in: prices follow `country`'s currency,
    texts follow `language` (both default to the store's own)."""
    country = CountryCodeField()
    language = LanguageCodeField()


class StoreMarketSchema(StoreSchema, MarketSchema):
    pass


class _ScopedSchema(MarketSchema):
    """A route addressed by an entity. `store` is optional because a link
    form of the entity already names it; the link's store wins."""
    ENTITY = None
    ENTITY_REQUIRED = True
    store = StoreField(required=False, load_default=None)

    @post_load
    def _scope(self, data, **kwargs):
        entity = data.get(self.ENTITY)
        linked = entity.pop("store", None) if isinstance(entity, dict) else None
        host = linked or data.get("store")
        if not host:
            hint = (f"store is required when `{self.ENTITY}` is a handle or id, not a link."
                    if entity is not None else "Missing data for required field.")
            raise ValidationError({"store": [hint]})
        data["store"] = host
        return data


class PriceRangeSchema(BaseSchema):
    min_price = Price()
    max_price = Price()

    @validates_schema
    def _price_order(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            raise ValidationError("min_price must not exceed max_price.", "min_price")


# ---- store ---------------------------------------------------------------------------

class PoliciesSchema(StoreMarketSchema):
    type = ChoiceField(POLICY_TYPES)


class MenusSchema(StoreMarketSchema):
    menu = CommaListField(upper=False, max_items=6,
                          metadata={"description": "menu handles, comma-separated (default main-menu,footer)"})


class CatalogStatsSchema(StoreMarketSchema):
    max_products = PositiveInt(max_value=10000, load_default=2500)


# ---- products ------------------------------------------------------------------------

class ProductsSchema(StoreMarketSchema, PriceRangeSchema):
    sort = ChoiceField(list(PRODUCT_SORTS), load_default="best_selling")
    title = TextFilter()
    vendor = TextFilter()
    product_type = TextFilter()
    tag = TextFilter()
    is_available = Flag()
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()


class ProductSchema(_ScopedSchema):
    ENTITY = "product"
    product = ProductField()


class RecommendationsSchema(ProductSchema):
    intent = ChoiceField(["related", "complementary"], load_default="related")


class ProductSearchSchema(StoreMarketSchema, PriceRangeSchema):
    query = QueryField(max_length=200)
    sort = ChoiceField(list(SEARCH_SORTS), load_default="relevance")
    vendor = TextFilter()
    product_type = TextFilter()
    tag = TextFilter()
    option = OptionField()
    is_available = Flag()
    unavailable_products = ChoiceField(list(UNAVAILABLE), load_default="last")
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()


class RankedProductsSchema(_ScopedSchema):
    """Best sellers / new arrivals: store-wide, or within `collection`."""
    ENTITY = "collection"
    store = StoreField()
    collection = CollectionField(required=False, load_default=None)
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()


class OnSaleSchema(StoreMarketSchema):
    min_discount_percent = Percent()
    is_available = Flag()
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()


# ---- collections ---------------------------------------------------------------------

class CollectionsSchema(StoreMarketSchema):
    query = TextFilter()
    sort = ChoiceField(list(COLLECTION_LIST_SORTS))
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()

    @validates_schema
    def _relevance_needs_query(self, data, **kwargs):
        if data.get("sort") == "relevance" and not data.get("query"):
            raise ValidationError("sort=relevance needs a query.", "sort")


class CollectionSchema(_ScopedSchema):
    ENTITY = "collection"
    collection = CollectionField()


class CollectionProductsSchema(CollectionSchema, PriceRangeSchema):
    sort = ChoiceField(list(COLLECTION_SORTS), load_default="featured")
    vendor = TextFilter()
    product_type = TextFilter()
    tag = TextFilter()
    option = OptionField()
    is_available = Flag()
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()


# ---- search --------------------------------------------------------------------------

class SuggestionsSchema(StoreMarketSchema):
    query = QueryField(max_length=200)
    types = CommaListField(allowed=SUGGESTION_TYPES, upper=False, max_items=len(SUGGESTION_TYPES))
    limit = LimitField(default=5, max_size=10)


# ---- content -------------------------------------------------------------------------

class PagesSchema(StoreMarketSchema):
    query = TextFilter()
    sort = ChoiceField(list(PAGE_SORTS))
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()

    @validates_schema
    def _relevance_needs_query(self, data, **kwargs):
        if data.get("sort") == "relevance" and not data.get("query"):
            raise ValidationError("sort=relevance needs a query.", "sort")


class PageSchema(_ScopedSchema):
    ENTITY = "page"
    page = PageRefField()


class BlogsSchema(StoreMarketSchema):
    limit = LimitField(default=50, max_size=250)
    cursor = CursorField()


class ArticlesSchema(_ScopedSchema):
    """Articles of `blog`, or of every blog when it is omitted."""
    ENTITY = "blog"
    store = StoreField()
    blog = BlogField(required=False, load_default=None)
    tag = TextFilter()
    author = TextFilter()
    query = TextFilter()
    sort = ChoiceField(["newest", "oldest"], load_default="newest")
    limit = LimitField(default=20, max_size=100)
    cursor = CursorField()


class ArticleSchema(_ScopedSchema):
    ENTITY = "article"
    article = ArticleField()
