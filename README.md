# 🛍️ Shopify Scraper

Shopify Scraper is a **free and open-source** scraper that gets you **unlimited** detailed data from any Shopify store for free.

## ✨ What Can I Get?

- 🛍️ **Full product details from any of Shopify's millions of stores** — every variant, price, SKU, barcode, image, video & review rating
- 🏆 **Best sellers, new arrivals & sales — 250 products per call** — ranked the way the store ranks them, with live stock per variant
- 🕵️ **Store intelligence with 180+ apps detected** — theme, contacts, markets, policies, menus & catalog statistics
- 📝 **26 endpoints, one store domain** — search with facets, collections, pages & blog articles

## 🎥 Example: A Full Shopify Product

```json
{
  "store": "fentybeauty.com",
  "market": { "country": "US", "language": "en" },
  "product": {
    "id": 5293605486637,
    "handle": "gloss-bomb-universal-lip-luminizer-fenty-glow",
    "title": "Gloss Bomb Universal Lip Luminizer — Fenty Glow",
    "link": "https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow",
    "vendor": "Fenty Beauty",
    "product_type": "Lip Gloss",
    "category": { "id": "hb-3-2-6-5-2", "name": "Lip Gloss", "path": ["Health & Beauty", "Personal Care", "Cosmetics", "Makeup", "Lip Makeup", "Lip Gloss"] },
    "description": "Our Number One gloss now with pure, creamy, color and incredible shine. Lips are instantly smoother and voluminous looking.",
    "is_available": true,
    "rating": 4.7,
    "reviews_count": 7506,
    "pricing": { "currency": "USD", "price": 16.0, "price_max": 23.0, "is_on_sale": false, "discount_percent": null },
    "image": { "link": "https://cdn.shopify.com/s/files/1/0341/3458/9485/files/FB3006_PROD_GLOSS_BOMB_FENTY_GLOW_CLOSED_72_1.jpg?v=1762198594", "width": 1200, "height": 1500 },
    "media": [
      { "type": "external_video", "host": "vimeo", "embed_link": "https://player.vimeo.com/video/1131795599" }
    ],
    "options": [
      { "name": "Color", "values": ["Fenty Glow"] },
      { "name": "Size", "values": ["Standard", "Mini"] }
    ],
    "variants_count": 2,
    "variants": [
      {
        "id": 35110478774317,
        "title": "Fenty Glow / Standard",
        "sku": "22513",
        "barcode": "816657022513",
        "link": "https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow?variant=35110478774317",
        "is_available": true,
        "price": 23.0,
        "currency": "USD",
        "weight": { "value": 0.0816, "unit": "pounds" },
        "options": [{ "name": "Color", "value": "Fenty Glow" }, { "name": "Size", "value": "Standard" }]
      }
    ],
    "subscriptions": [
      {
        "name": "Subscribe and Save",
        "plans": [
          { "name": "Delivered every month. Get 10% off today and all future orders.", "price_adjustments": [{ "type": "percentage", "value": 10.0 }] }
        ]
      }
    ],
    "collections": [
      { "id": 260523622445, "handle": "gloss-bomb-universal-lip-luminizer", "title": "Gloss Bomb Universal Lip Luminizer", "link": "https://fentybeauty.com/collections/gloss-bomb-universal-lip-luminizer" }
    ],
    "created_at": "2021-01-27T00:48:55Z",
    "updated_at": "2026-10-05T09:34:27Z"
  }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Shopify Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/shopify-scraper
cd shopify-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow"
```

```json
{
  "store": "fentybeauty.com",
  "market": { "country": "US", "language": "en" },
  "product": {
    "id": 5293605486637,
    "title": "Gloss Bomb Universal Lip Luminizer — Fenty Glow",
    "link": "https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow",
    "vendor": "Fenty Beauty",
    "product_type": "Lip Gloss",
    "is_available": true,
    "rating": 4.7,
    "reviews_count": 7506,
    "pricing": { "currency": "USD", "price": 16.0, "price_max": 23.0, "is_on_sale": false },
    "variants_count": 2,
    "variants": [
      { "id": 35110478774317, "title": "Fenty Glow / Standard", "sku": "22513", "barcode": "816657022513", "price": 23.0, "is_available": true }
    ],
    "collections": [
      { "handle": "gloss-bomb-universal-lip-luminizer", "title": "Gloss Bomb Universal Lip Luminizer" }
    ]
  }
}
```

All 26 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

26 endpoints cover everything you need. Every one works on any Shopify store — just pass its domain.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything about one product in a single call |
| Search Products | `/products/search` | Keyword search with total count, facets, sort and filters |
| List Products | `/products` | The whole catalog, 250 per call, 8 sort orders |
| Best Sellers / New Arrivals | `/products/best-sellers`, `/products/new-arrivals` | The store's winners and latest launches, ranked |
| Products On Sale | `/products/on-sale` | Every discounted product with its discount percent |
| Product Recommendations | `/products/recommendations` | Related and complementary products for any product |
| Product Inventory | `/products/inventory` | Units in stock for every variant |
| List Collections / Collection Details | `/collections`, `/collections/details` | Every collection, with product count and facets |
| Collection Products | `/collections/products` | One collection's products with sort, filters and facets |
| Search Suggestions | `/search/suggestions` | Typeahead: queries, products, collections, pages, articles |
| Store Profile | `/store` | Name, location, currency, payments, markets, theme, policies |
| Shopify Store Check | `/store/check` | Tells you if any website runs on Shopify |
| Store Apps / Store Theme | `/store/apps`, `/store/theme` | The apps and theme a store runs |
| Store Contacts | `/store/contacts` | Emails, phone numbers and social profiles |
| Store Markets | `/store/markets` | Every country sold to, with currency and languages |
| Store Policies / Store Menus | `/store/policies`, `/store/menus` | Full legal policies and navigation menus |
| Catalog Statistics | `/store/catalog-stats` | Price distribution, discounts, top vendors, types and tags |
| List Pages / Page Details | `/pages`, `/pages/details` | About, FAQ and contact pages with full body |
| List Blogs / Blog Articles | `/blogs`, `/blogs/articles` | Every blog and its articles, newest first |
| Article Details | `/blogs/articles/details` | Full article content, author, tags and comments |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-shopify-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-shopify-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-shopify-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Shopify Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Shopify%20Scraper%20API.)

[![Ask Us by Email about Shopify Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Shopify%20Scraper%20API&body=I%20need%20help%20using%20the%20Shopify%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/shopify-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/shopify-scraper)
