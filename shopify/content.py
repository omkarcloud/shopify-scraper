"""/shopify/pages* and /shopify/blogs* — a store's content: its pages (About,
FAQ, Contact ...), its blogs, their articles and one article in full with
its comments."""
from shopify import parsers as P
from shopify import queries as Q
from shopify import refs
from shopify import shared
from shopify.fetch import ShopifyNotFound, gql, resolve

# public sort -> (PageSortKeys, reverse)
PAGE_SORTS = {
    "title_asc": ("TITLE", False),
    "title_desc": ("TITLE", True),
    "recently_updated": ("UPDATED_AT", True),
    "relevance": ("RELEVANCE", False),
}


def _quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def pages(store, query=None, sort=None, limit=50, cursor=None, country=None, language=None):
    """The store's published pages (title + summary); `query` matches titles."""
    shop = resolve(store)
    sort = sort or ("relevance" if query else "title_asc")
    sort_key, reverse = PAGE_SORTS[sort]
    data = gql(shop, Q.PAGES, {"first": limit, "after": cursor, "sortKey": sort_key, "reverse": reverse,
                               "query": f"title:{query}*" if query else None},
               label="pages", **shared.context(country, language))
    connection = P.as_dict(data.get("pages"))
    next_cursor, has_next = P.page_info(connection)
    items = [P.page(shop, n) for n in P.nodes(connection)]
    return {**shared.envelope(shop, data), "query": query, "sort": sort, "count": len(items),
            "has_next_page": has_next, "next_cursor": next_cursor, "pages": items}


def page_details(store, page, country=None, language=None):
    """One page with its full body (HTML and plain text)."""
    shop = resolve(store)
    by_id, variables = shared.entity_variables(page, "Page")
    data = gql(shop, Q.PAGE_BY_ID if by_id else Q.PAGE_BY_HANDLE, variables, label="page",
               **shared.context(country, language))
    raw = data.get("page")
    if not isinstance(raw, dict):
        raise ShopifyNotFound(f"page '{shared.describe(page)}' not found on {shop.domain}")
    return {**shared.envelope(shop, data), "page": P.page(shop, raw, detailed=True)}


def blogs(store, limit=50, cursor=None, country=None, language=None):
    """The store's blogs with their authors."""
    shop = resolve(store)
    data = gql(shop, Q.BLOGS, {"first": limit, "after": cursor}, label="blogs",
               **shared.context(country, language))
    connection = P.as_dict(data.get("blogs"))
    next_cursor, has_next = P.page_info(connection)
    items = [P.blog(shop, n) for n in P.nodes(connection)]
    return {**shared.envelope(shop, data), "count": len(items), "has_next_page": has_next,
            "next_cursor": next_cursor, "blogs": items}


def articles(store, blog=None, tag=None, author=None, query=None, sort="newest", limit=20, cursor=None,
             country=None, language=None):
    """Articles of one blog — or of every blog when `blog` is omitted —
    newest first, optionally narrowed by tag, author or title words."""
    shop = resolve(store)
    terms = []
    if tag:
        terms.append(f"tag:{_quote(tag)}")
    if author:
        terms.append(f"author:{_quote(author)}")
    if query:
        terms.append(f"title:{_quote(query)}")
    variables = {"first": limit, "after": cursor, "reverse": sort == "newest",
                 "query": " AND ".join(terms) or None}
    parent = None
    if blog is None:
        data = gql(shop, Q.ARTICLES, variables, label="articles", **shared.context(country, language))
        connection = P.as_dict(data.get("articles"))
    else:
        by_id, ref = shared.entity_variables(blog, "Blog")
        variables.update(ref)
        data = gql(shop, Q.BLOG_ARTICLES_BY_ID if by_id else Q.BLOG_ARTICLES_BY_HANDLE, variables,
                   label="blog articles", **shared.context(country, language))
        raw_blog = data.get("blog")
        if not isinstance(raw_blog, dict):
            raise ShopifyNotFound(f"blog '{shared.describe(blog)}' not found on {shop.domain}")
        parent = P.blog_ref(shop, raw_blog)
        connection = P.as_dict(raw_blog.get("articles"))
    next_cursor, has_next = P.page_info(connection)
    items = [P.article(shop, n) for n in P.nodes(connection)]
    return {**shared.envelope(shop, data), "blog": parent,
            "filters": shared.applied_filters(tag=tag, author=author, query=query), "sort": sort,
            "count": len(items), "has_next_page": has_next, "next_cursor": next_cursor, "articles": items}


def article_details(store, article, country=None, language=None):
    """One article in full: content (HTML and text), author, tags, image,
    SEO and its comments."""
    shop = resolve(store)
    blog_raw = None
    if article.get("id") is not None:
        data = gql(shop, Q.ARTICLE_BY_ID, {"id": refs.gid("Article", article["id"])}, label="article",
                   **shared.context(country, language))
        raw = data.get("article")
        label = str(article["id"])
    else:
        data = gql(shop, Q.ARTICLE_BY_HANDLE, {"blog": article["blog"], "handle": article["handle"]},
                   label="article", **shared.context(country, language))
        blog_raw = data.get("blog")
        if not isinstance(blog_raw, dict):
            raise ShopifyNotFound(f"blog '{article['blog']}' not found on {shop.domain}")
        raw = blog_raw.get("articleByHandle")
        label = f"{article['blog']}/{article['handle']}"
    if not isinstance(raw, dict):
        raise ShopifyNotFound(f"article '{label}' not found on {shop.domain}")
    item = P.article(shop, raw, detailed=True, blog_raw=blog_raw)
    return {**shared.envelope(shop, data), "article": item}
