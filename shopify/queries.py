"""Storefront API GraphQL documents for every /shopify/* endpoint.

Every operation takes `$country` / `$language` and runs `@inContext`, so one
document serves every market (null = the store's default market).

Everything runs tokenless except PRODUCT_METAFIELDS: metafields are the one
scope tokenless access lacks, so they are read in a second, id-keyed query
with the store's storefront token (fetch.product_metafields) and merged
into the product nodes. The token is kept out of every other call because
its app often lacks scopes tokenless access has (menus and predictive search
come back null with it).

Costs (tokenless cap = 1000 per query, measured 2026-10-05 on allbirds.com):
product cards x250 = 144, product details with 250 variants = 290.
"""

MONEY = "{amount currencyCode}"
IMAGE = "{url altText width height}"

# Shopify's standard review metafields (written by Judge.me, Yotpo, Loox,
# Okendo, Stamped, Shopify Product Reviews ...).
CARD_METAFIELDS = """
  rating: metafield(namespace: "reviews", key: "rating") { value }
  ratingCount: metafield(namespace: "reviews", key: "rating_count") { value }
"""

# Standard / very common product metafield definitions, read on details.
DETAIL_METAFIELD_IDS = [
    ("descriptors", "subtitle"), ("descriptors", "care_guide"),
    ("facts", "isbn"), ("facts", "upc"), ("facts", "ean"),
    ("custom", "subtitle"), ("custom", "ingredients"), ("custom", "materials"),
    ("custom", "material"), ("custom", "care_instructions"), ("custom", "features"),
    ("custom", "specifications"), ("custom", "size_guide"), ("custom", "shipping_info"),
    ("global", "title_tag"), ("global", "description_tag"),
    ("my_fields", "subtitle"), ("my_fields", "ingredients"),
    ("shopify", "color-pattern"), ("shopify", "size"), ("shopify", "material"),
    ("shopify", "target-gender"), ("shopify", "age-group"), ("shopify", "fabric"),
]
DETAIL_METAFIELDS = CARD_METAFIELDS + "  metafields(identifiers: [%s]) { namespace key type value }\n" % ", ".join(
    '{namespace: "%s", key: "%s"}' % pair for pair in DETAIL_METAFIELD_IDS)

PRODUCT_CARD = """
fragment ProductCard on Product {
  id handle title vendor productType
  description(truncateAt: 400)
  availableForSale isGiftCard requiresSellingPlan
  createdAt updatedAt publishedAt tags onlineStoreUrl
  featuredImage %(image)s
  priceRange { minVariantPrice %(money)s maxVariantPrice %(money)s }
  compareAtPriceRange { minVariantPrice %(money)s maxVariantPrice %(money)s }
  options { name optionValues { name } }
  category { id name }
  variantsCount { count }
}
""" % {"money": MONEY, "image": IMAGE}

VARIANT_FIELDS = """
  id title sku barcode availableForSale currentlyNotInStock requiresShipping taxable
  weight weightUnit
  price %(money)s compareAtPrice %(money)s unitPrice %(money)s
  unitPriceMeasurement { measuredType quantityUnit quantityValue referenceUnit referenceValue }
  selectedOptions { name value }
  image { id url altText width height }
  quantityRule { minimum maximum increment }
""" % {"money": MONEY}

FILTERS = "{ id label type values { id label count input } }"
PAGE_INFO = "pageInfo { hasNextPage endCursor }"


def _op(name, args, body, fragments=""):
    extra = (", " + args) if args else ""
    return (f"query {name}($country: CountryCode, $language: LanguageCode{extra}) "
            f"@inContext(country: $country, language: $language) {{{body}}}\n{fragments}")


# ---- store ---------------------------------------------------------------------------

_POLICY = "{ id title handle url body }"

# The resolution probe: the cheapest query that proves a Storefront API.
PROBE = "{ shop { id name primaryDomain { url host } paymentSettings { countryCode currencyCode } } }"

SHOP = _op("Shop", "", """
  shop {
    id name description moneyFormat
    primaryDomain { url host }
    brand {
      slogan shortDescription
      logo { image %(image)s }
      squareLogo { image %(image)s }
      coverImage { image %(image)s }
      colors { primary { background foreground } secondary { background foreground } }
    }
    paymentSettings {
      currencyCode countryCode enabledPresentmentCurrencies acceptedCardBrands supportedDigitalWallets
    }
    shipsToCountries
    privacyPolicy { title handle url }
    refundPolicy { title handle url }
    shippingPolicy { title handle url }
    termsOfService { title handle url }
    subscriptionPolicy { title handle url }
  }
  localization {
    country { isoCode name unitSystem currency { isoCode name symbol } }
    language { isoCode name endonymName }
    availableLanguages { isoCode name endonymName }
    availableCountries { isoCode }
  }
""" % {"image": IMAGE})

MARKETS = _op("Markets", "", """
  localization {
    country { isoCode name unitSystem currency { isoCode name symbol } market { handle } }
    language { isoCode name endonymName }
    availableLanguages { isoCode name endonymName }
    availableCountries {
      isoCode name unitSystem
      currency { isoCode name symbol }
      availableLanguages { isoCode name endonymName }
      market { handle }
    }
  }
  shop { shipsToCountries paymentSettings { currencyCode enabledPresentmentCurrencies } }
""")

POLICIES = _op("Policies", "", """
  shop {
    privacyPolicy %(p)s refundPolicy %(p)s shippingPolicy %(p)s
    termsOfService %(p)s subscriptionPolicy %(p)s
  }
""" % {"p": _POLICY})

_MENU_ITEM = "id title type url tags resource { __typename ... on Product { handle } ... on Collection { handle } ... on Page { handle } ... on Blog { handle } ... on Article { handle } }"


def menus(handles):
    """One aliased `menu(handle:)` per handle (three levels deep, Shopify's
    own nesting limit)."""
    body = ""
    for index, handle in enumerate(handles):
        body += """
  m%d: menu(handle: %s) {
    id handle title itemsCount
    items { %s items { %s items { %s } } }
  }""" % (index, _gql_string(handle), _MENU_ITEM, _MENU_ITEM, _MENU_ITEM)
    return _op("Menus", "", body + "\n")


def _gql_string(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---- products --------------------------------------------------------------------------

PRODUCTS = _op("Products", "$first: Int!, $after: String, $sortKey: ProductSortKeys, $reverse: Boolean, $query: String", """
  products(first: $first, after: $after, sortKey: $sortKey, reverse: $reverse, query: $query) {
    %s
    nodes { ...ProductCard }
  }
""" % PAGE_INFO, PRODUCT_CARD)

# The light walk behind /store/catalog-stats and /products/on-sale.
PRODUCTS_SCAN = _op("ProductsScan", "$first: Int!, $after: String", """
  products(first: $first, after: $after, sortKey: ID) {
    %s
    nodes {
      id handle vendor productType tags availableForSale createdAt updatedAt
      priceRange { minVariantPrice %s maxVariantPrice %s }
      compareAtPriceRange { minVariantPrice %s maxVariantPrice %s }
    }
  }
""" % (PAGE_INFO, MONEY, MONEY, MONEY, MONEY))

_PRODUCT_DETAILS_BODY = """
    ...ProductCard
    descriptionHtml
    fullDescription: description
    seo { title description }
    category { id name ancestors { id name } }
    options { id name optionValues { id name swatch { color image { previewImage { url } } } } }
    images(first: 100) { nodes { id url altText width height } }
    media(first: 50) {
      nodes {
        id mediaContentType alt
        previewImage { url altText width height }
        ... on Video { sources { url mimeType format height width } }
        ... on ExternalVideo { embedUrl host originUrl }
        ... on Model3d { sources { url format mimeType filesize } }
      }
    }
    collections(first: 50) { nodes { id handle title onlineStoreUrl } }
    sellingPlanGroups(first: 10) {
      nodes {
        name appName
        options { name values }
        sellingPlans(first: 20) {
          nodes {
            id name description recurringDeliveries
            options { name value }
            priceAdjustments {
              orderCount
              adjustmentValue {
                __typename
                ... on SellingPlanPercentagePriceAdjustment { adjustmentPercentage }
                ... on SellingPlanFixedAmountPriceAdjustment { adjustmentAmount %(money)s }
                ... on SellingPlanFixedPriceAdjustment { price %(money)s }
              }
            }
          }
        }
      }
    }
    variants(first: 250) { %(page)s nodes { %(variant)s } }
""" % {"money": MONEY, "page": PAGE_INFO, "variant": VARIANT_FIELDS}

PRODUCT_BY_HANDLE = _op("ProductByHandle", "$handle: String!", """
  product(handle: $handle) {%s}
""" % _PRODUCT_DETAILS_BODY, PRODUCT_CARD)

PRODUCT_BY_ID = _op("ProductById", "$id: ID!", """
  product(id: $id) {%s}
""" % _PRODUCT_DETAILS_BODY, PRODUCT_CARD)

PRODUCT_VARIANTS_PAGE = _op("ProductVariants", "$id: ID!, $after: String", """
  product(id: $id) { variants(first: 250, after: $after) { %s nodes { %s } } }
""" % (PAGE_INFO, VARIANT_FIELDS))

# Light product + variant list for /products/inventory.
_STOCK_BODY = """
    id handle title onlineStoreUrl availableForSale
    variants(first: 250, after: $after) {
      %s
      nodes { id title sku availableForSale currentlyNotInStock selectedOptions { name value } }
    }
""" % PAGE_INFO
PRODUCT_STOCK_BY_HANDLE = _op("ProductStockByHandle", "$handle: String!, $after: String",
                              "\n  product(handle: $handle) {%s}\n" % _STOCK_BODY)
PRODUCT_STOCK_BY_ID = _op("ProductStockById", "$id: ID!, $after: String",
                          "\n  product(id: $id) {%s}\n" % _STOCK_BODY)

# A cart holding an oversized quantity of each variant: Shopify trims every
# line to what can actually be bought, which is the stock level.
CART_PROBE = """
mutation CartProbe($lines: [CartLineInput!]!) {
  cartCreate(input: {lines: $lines}) {
    cart { lines(first: 250) { nodes { quantity merchandise { ... on ProductVariant { id } } } } }
    userErrors { code message }
    warnings { code message target }
  }
}
"""

RECOMMENDATIONS_BY_HANDLE = _op("RecommendationsByHandle", "$handle: String!, $intent: ProductRecommendationIntent", """
  productRecommendations(productHandle: $handle, intent: $intent) { ...ProductCard }
""", PRODUCT_CARD)

RECOMMENDATIONS_BY_ID = _op("RecommendationsById", "$id: ID!, $intent: ProductRecommendationIntent", """
  productRecommendations(productId: $id, intent: $intent) { ...ProductCard }
""", PRODUCT_CARD)

SEARCH_PRODUCTS = _op(
    "SearchProducts",
    "$query: String!, $first: Int!, $after: String, $sortKey: SearchSortKeys, $reverse: Boolean, "
    "$filters: [ProductFilter!], $unavailable: SearchUnavailableProductsType", """
  search(query: $query, first: $first, after: $after, sortKey: $sortKey, reverse: $reverse,
         productFilters: $filters, types: [PRODUCT], unavailableProducts: $unavailable) {
    totalCount
    %s
    productFilters %s
    nodes { ... on Product { ...ProductCard } }
  }
""" % (PAGE_INFO, FILTERS), PRODUCT_CARD)

SUGGESTIONS = _op("Suggestions", "$query: String!, $limit: Int!, $types: [PredictiveSearchType!]", """
  predictiveSearch(query: $query, limit: $limit, types: $types, limitScope: EACH) {
    queries { text styledText }
    products { ...ProductCard }
    collections { id handle title onlineStoreUrl image %(image)s }
    pages { id handle title onlineStoreUrl }
    articles { id handle title onlineStoreUrl image %(image)s blog { handle title } }
  }
""" % {"image": IMAGE}, PRODUCT_CARD)


# ---- collections -----------------------------------------------------------------------

_COLLECTION_FIELDS = """
    id handle title description descriptionHtml updatedAt onlineStoreUrl
    image %s
    seo { title description }
""" % IMAGE

COLLECTIONS = _op("Collections", "$first: Int!, $after: String, $sortKey: CollectionSortKeys, $reverse: Boolean, $query: String", """
  collections(first: $first, after: $after, sortKey: $sortKey, reverse: $reverse, query: $query) {
    %s
    nodes {%s}
  }
""" % (PAGE_INFO, _COLLECTION_FIELDS))

_COLLECTION_DETAILS_BODY = """%s
    products(first: 1) { filters %s }
""" % (_COLLECTION_FIELDS, FILTERS)

COLLECTION_BY_HANDLE = _op("CollectionByHandle", "$handle: String!",
                           "\n  collection(handle: $handle) {%s}\n" % _COLLECTION_DETAILS_BODY)
COLLECTION_BY_ID = _op("CollectionById", "$id: ID!",
                       "\n  collection(id: $id) {%s}\n" % _COLLECTION_DETAILS_BODY)

_COLLECTION_PRODUCTS_BODY = """
    id handle title onlineStoreUrl
    products(first: $first, after: $after, sortKey: $sortKey, reverse: $reverse, filters: $filters) {
      %s
      filters %s
      nodes { ...ProductCard }
    }
""" % (PAGE_INFO, FILTERS)
_COLLECTION_PRODUCTS_ARGS = ("$first: Int!, $after: String, $sortKey: ProductCollectionSortKeys, "
                             "$reverse: Boolean, $filters: [ProductFilter!]")

COLLECTION_PRODUCTS_BY_HANDLE = _op("CollectionProductsByHandle", "$handle: String!, " + _COLLECTION_PRODUCTS_ARGS,
                                    "\n  collection(handle: $handle) {%s}\n" % _COLLECTION_PRODUCTS_BODY, PRODUCT_CARD)
COLLECTION_PRODUCTS_BY_ID = _op("CollectionProductsById", "$id: ID!, " + _COLLECTION_PRODUCTS_ARGS,
                                "\n  collection(id: $id) {%s}\n" % _COLLECTION_PRODUCTS_BODY, PRODUCT_CARD)


# ---- content ---------------------------------------------------------------------------

_PAGE_CARD = "id handle title bodySummary createdAt updatedAt onlineStoreUrl seo { title description }"

PAGES = _op("Pages", "$first: Int!, $after: String, $sortKey: PageSortKeys, $reverse: Boolean, $query: String", """
  pages(first: $first, after: $after, sortKey: $sortKey, reverse: $reverse, query: $query) {
    %s
    nodes { %s }
  }
""" % (PAGE_INFO, _PAGE_CARD))

PAGE_BY_HANDLE = _op("PageByHandle", "$handle: String!", "\n  page(handle: $handle) { %s body }\n" % _PAGE_CARD)
PAGE_BY_ID = _op("PageById", "$id: ID!", "\n  page(id: $id) { %s body }\n" % _PAGE_CARD)

BLOGS = _op("Blogs", "$first: Int!, $after: String", """
  blogs(first: $first, after: $after) {
    %s
    nodes { id handle title onlineStoreUrl seo { title description } authors { name bio } }
  }
""" % PAGE_INFO)

_ARTICLE_CARD = """
      id handle title excerpt publishedAt onlineStoreUrl tags
      summary: content(truncateAt: 400)
      image %s
      authorV2 { name bio }
      blog { id handle title onlineStoreUrl }
      seo { title description }
""" % IMAGE

_ARTICLES_ARGS = "$first: Int!, $after: String, $reverse: Boolean, $query: String"

ARTICLES = _op("Articles", _ARTICLES_ARGS, """
  articles(first: $first, after: $after, sortKey: PUBLISHED_AT, reverse: $reverse, query: $query) {
    %s
    nodes {%s}
  }
""" % (PAGE_INFO, _ARTICLE_CARD))

BLOG_ARTICLES_BY_HANDLE = _op("BlogArticlesByHandle", "$handle: String!, " + _ARTICLES_ARGS, """
  blog(handle: $handle) {
    id handle title onlineStoreUrl
    articles(first: $first, after: $after, sortKey: PUBLISHED_AT, reverse: $reverse, query: $query) {
      %s
      nodes {%s}
    }
  }
""" % (PAGE_INFO, _ARTICLE_CARD))

BLOG_ARTICLES_BY_ID = BLOG_ARTICLES_BY_HANDLE.replace("BlogArticlesByHandle", "BlogArticlesById").replace(
    "$handle: String!", "$id: ID!").replace("blog(handle: $handle)", "blog(id: $id)")

_ARTICLE_DETAILS = """%s
      content contentHtml excerptHtml
      comments(first: 50) { nodes { id content contentHtml author { name } } }
""" % _ARTICLE_CARD

ARTICLE_BY_HANDLE = _op("ArticleByHandle", "$blog: String!, $handle: String!", """
  blog(handle: $blog) {
    id handle title onlineStoreUrl
    articleByHandle(handle: $handle) {%s}
  }
""" % _ARTICLE_DETAILS)

ARTICLE_BY_ID = _op("ArticleById", "$id: ID!", "\n  article(id: $id) {%s}\n" % _ARTICLE_DETAILS)


def product_metafields(detailed=False):
    """Token query: the metafields of up to 250 products by id."""
    return """
query ProductMetafields($ids: [ID!]!) {
  nodes(ids: $ids) { ... on Product { id %s } }
}
""" % (DETAIL_METAFIELDS if detailed else CARD_METAFIELDS)
