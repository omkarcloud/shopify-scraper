"""Which Shopify apps / third-party tools a storefront runs, read from its
homepage HTML. Two signals:

  * APP EMBEDS  Online Store 2.0 prints every enabled theme app extension as
    `<!-- BEGIN app block: shopify://apps/<app-handle>/blocks/<block>/... -->`.
    That names the app exactly, whatever it is — no table needed.
  * SCRIPT HOSTS  apps injected the older way (ScriptTag / pasted snippets)
    are recognised by the hosts they load from (SIGNATURES).

detect(html) -> [{"name", "category", "handle", "detected_via"}], deduped by
app, embeds first.
"""
import re

_APP_BLOCK_RE = re.compile(r"shopify://apps/([a-z0-9\-]+)/blocks/([a-z0-9_\-]+)")

# (name, category, needles). A needle is a plain substring of the HTML —
# almost always the host the app's script or widget loads from.
SIGNATURES = [
    # reviews / UGC
    ("Judge.me Product Reviews", "reviews", ["judge.me"]),
    ("Yotpo Reviews", "reviews", ["staticw2.yotpo.com", "cdn-widgetsrepository.yotpo.com", "p.yotpo.com"]),
    ("Okendo Reviews", "reviews", ["okendo.io"]),
    ("Loox Reviews", "reviews", ["loox.io"]),
    ("Stamped Reviews", "reviews", ["stamped.io"]),
    ("Junip Reviews", "reviews", ["juniphq.com"]),
    ("Reviews.io", "reviews", ["widget.reviews.io", "widget.reviews.co.uk"]),
    ("Trustpilot", "reviews", ["widget.trustpilot.com"]),
    ("Bazaarvoice", "reviews", ["apps.bazaarvoice.com", "display.ugc.bazaarvoice.com"]),
    ("PowerReviews", "reviews", ["ui.powerreviews.com"]),
    ("Ryviu Reviews", "reviews", ["ryviu.com"]),
    ("Ali Reviews", "reviews", ["alireviews.io", "alireviews.fireapps.io"]),
    ("Shopify Product Reviews", "reviews", ["productreviews.shopifycdn.com"]),
    ("Fera Reviews", "reviews", ["cdn.fera.ai"]),
    ("Opinew Reviews", "reviews", ["opinew.com"]),
    ("Rivyo Reviews", "reviews", ["rivyo.com"]),
    ("Foursixty", "ugc", ["foursixty.com"]),
    ("Tolstoy Shoppable Video", "ugc", ["gotolstoy.com"]),
    ("Firework Shoppable Video", "ugc", ["fwcdn3.com", "fwcdn2.com"]),
    ("Videowise", "ugc", ["videowise.com"]),
    # email / SMS / popups
    ("Klaviyo", "email_sms_marketing", ["static.klaviyo.com", "a.klaviyo.com"]),
    ("Attentive", "email_sms_marketing", ["cdn.attn.tv", ".attn.tv"]),
    ("Postscript", "email_sms_marketing", ["sdk.postscript.io"]),
    ("Omnisend", "email_sms_marketing", ["omnisnippet1.com", "omnisrc.com"]),
    ("Mailchimp", "email_sms_marketing", ["chimpstatic.com", "list-manage.com"]),
    ("Privy", "email_sms_marketing", ["widget.privy.com"]),
    ("Justuno", "email_sms_marketing", ["cdn.jst.ai", "justuno.com"]),
    ("Sendlane", "email_sms_marketing", ["sendlane.com"]),
    ("Drip", "email_sms_marketing", ["tag.getdrip.com"]),
    ("Yotpo SMS & Email (SMSBump)", "email_sms_marketing", ["smsbump.com"]),
    ("Emotive", "email_sms_marketing", ["emotivecdn.io"]),
    ("Listrak", "email_sms_marketing", ["listrakbi.com"]),
    ("Ometria", "email_sms_marketing", ["cdn.ometria.com"]),
    ("Iterable", "email_sms_marketing", ["js.iterable.com"]),
    ("Brevo", "email_sms_marketing", ["sibautomation.com"]),
    ("ActiveCampaign", "email_sms_marketing", ["trackcmp.net"]),
    ("Shopify Forms", "email_sms_marketing", ["shopify-forms"]),
    ("OptiMonk", "email_sms_marketing", ["optimonk.com"]),
    ("Wisepops", "email_sms_marketing", ["wisepops.com"]),
    ("Alia Popups", "email_sms_marketing", ["alia-cloudflare"]),
    # subscriptions
    ("Recharge Subscriptions", "subscriptions", ["rechargecdn.com", "rechargepayments.com"]),
    ("Ordergroove", "subscriptions", ["static.ordergroove.com"]),
    ("Skio Subscriptions", "subscriptions", ["skio.com"]),
    ("Bold Subscriptions", "subscriptions", ["sub.boldapps.net"]),
    ("Smartrr", "subscriptions", ["smartrr.com"]),
    ("Loop Subscriptions", "subscriptions", ["loopwork.co"]),
    ("Stay AI", "subscriptions", ["stay.ai", "retextion.com"]),
    ("Seal Subscriptions", "subscriptions", ["sealsubscriptions.com"]),
    ("Appstle Subscriptions", "subscriptions", ["appstle.com"]),
    # upsell / personalization / search
    ("Rebuy", "upsell_personalization", ["rebuyengine.com"]),
    ("Nosto", "upsell_personalization", ["connect.nosto.com"]),
    ("LimeSpot", "upsell_personalization", ["limespot.com"]),
    ("Dynamic Yield", "upsell_personalization", ["dynamicyield.com", "dy-api.com"]),
    ("Bold Upsell", "upsell_personalization", ["upsells.boldapps.net"]),
    ("ReConvert", "upsell_personalization", ["reconvert"]),
    ("Zipify OneClickUpsell", "upsell_personalization", ["zipify.com"]),
    ("Frequently Bought Together", "upsell_personalization", ["codeblackbelt.com"]),
    ("Intelligems A/B Testing", "ab_testing", ["cdn.intelligems.io"]),
    ("Shoplift A/B Testing", "ab_testing", ["shoplift.ai"]),
    ("Optimizely", "ab_testing", ["cdn.optimizely.com"]),
    ("VWO", "ab_testing", ["visualwebsiteoptimizer.com"]),
    ("Klevu Search", "search", ["klevu.com"]),
    ("Searchspring", "search", ["searchspring.net"]),
    ("Algolia", "search", ["algolia.net", "algolianet.com", "algoliasearch"]),
    ("Boost AI Search & Filter", "search", ["boostcommerce.io", "bc-sf-filter"]),
    ("Searchanise", "search", ["searchanise.com", "searchserverapi.com"]),
    ("Findify", "search", ["findify.io"]),
    ("Constructor", "search", ["cnstrc.com"]),
    ("Shopify Search & Discovery", "search", ["search-and-discovery"]),
    # loyalty / referrals / wishlist
    ("Smile Rewards", "loyalty_referrals", ["js.smile.io", "cdn.sweettooth.io"]),
    ("Yotpo Loyalty", "loyalty_referrals", ["cdn-loyalty.yotpo.com", "cdn-swell-assets.yotpo.com"]),
    ("LoyaltyLion", "loyalty_referrals", ["loyaltylion.com"]),
    ("Rise.ai", "loyalty_referrals", ["rise-ai.com"]),
    ("Friendbuy", "loyalty_referrals", ["friendbuy.com", "fbot.me"]),
    ("ReferralCandy", "loyalty_referrals", ["referralcandy.com"]),
    ("Refersion", "loyalty_referrals", ["refersion.com"]),
    ("Social Snowball", "loyalty_referrals", ["socialsnowball.io"]),
    ("Growave", "loyalty_referrals", ["growave.io"]),
    ("ShopMy", "loyalty_referrals", ["static.shopmy.us"]),
    ("Swym Wishlist Plus", "wishlist", ["swymrelay.com"]),
    ("Wishlist King", "wishlist", ["appmate.io"]),
    ("Wishlist Hero", "wishlist", ["wishlisthero"]),
    # support / chat
    ("Gorgias", "customer_support", ["config.gorgias.chat", "gorgias.help"]),
    ("Zendesk", "customer_support", ["static.zdassets.com"]),
    ("Intercom", "customer_support", ["widget.intercom.io", "js.intercomcdn.com"]),
    ("Tidio", "customer_support", ["code.tidio.co"]),
    ("Gladly", "customer_support", ["cdn.gladly.com"]),
    ("Re:amaze", "customer_support", ["cdn.reamaze.com"]),
    ("Kustomer", "customer_support", ["cdn.kustomerapp.com"]),
    ("Shopify Inbox", "customer_support", ["shopifyChatV1", "chat-button-container"]),
    ("Siena AI", "customer_support", ["chat.siena.cx"]),
    ("Drift", "customer_support", ["js.driftt.com"]),
    ("Richpanel", "customer_support", ["richpanel.com"]),
    ("Crisp", "customer_support", ["client.crisp.chat"]),
    # returns / shipping / protection
    ("Loop Returns", "returns_shipping", ["loopreturns.com"]),
    ("Redo Returns", "returns_shipping", ["getredo.com"]),
    ("Narvar", "returns_shipping", ["narvar.com"]),
    ("AfterShip", "returns_shipping", ["aftership.com"]),
    ("Route Protection", "returns_shipping", ["routeapp.io"]),
    ("Navidium", "returns_shipping", ["navidiumapp.com"]),
    ("Corso", "returns_shipping", ["corso.com"]),
    ("Global-e", "cross_border", ["global-e.com"]),
    ("Zonos", "cross_border", ["zonos.com"]),
    ("Reach", "cross_border", ["withreach.com"]),
    # payments / BNPL
    ("Klarna", "payments", ["klarnaservices.com", "js.klarna.com"]),
    ("Afterpay", "payments", ["js.afterpay.com", "static.afterpay.com", "portal.afterpay.com"]),
    ("Affirm", "payments", ["cdn1.affirm.com", "affirm.com/js"]),
    ("Sezzle", "payments", ["widget.sezzle.com"]),
    ("Catch", "payments", ["getcatch.com"]),
    ("Amazon Pay", "payments", ["payments.amazon.com"]),
    ("PayPal", "payments", ["paypalobjects.com", "paypal.com/sdk"]),
    ("Shop Pay Installments", "payments", ["shop-pay-installments", "shopify-payment-terms"]),
    ("GovX ID", "payments", ["id-shop.govx.com"]),
    # back in stock / inventory
    ("Back in Stock", "inventory_alerts", ["backinstock.useamp.com", "backinstock.org"]),
    ("Restock Rocket", "inventory_alerts", ["restockrocket.io"]),
    ("STOQ Restock Alerts", "inventory_alerts", ["stoqapp.com"]),
    ("MinMaxify Order Limits", "inventory_alerts", ["minmaxify.com"]),
    # analytics / attribution / pixels
    ("Google Tag Manager", "analytics", ["googletagmanager.com/gtm.js", "googletagmanager.com/ns.html"]),
    ("Google Analytics", "analytics", ["google-analytics.com", "googletagmanager.com/gtag/js"]),
    ("Meta Pixel", "analytics", ["connect.facebook.net"]),
    ("TikTok Pixel", "analytics", ["analytics.tiktok.com"]),
    ("Pinterest Tag", "analytics", ["s.pinimg.com/ct", "ct.pinterest.com"]),
    ("Snap Pixel", "analytics", ["sc-static.net"]),
    ("Microsoft Clarity", "analytics", ["clarity.ms"]),
    ("Microsoft Ads UET", "analytics", ["bat.bing.com"]),
    ("Hotjar", "analytics", ["static.hotjar.com"]),
    ("Heap", "analytics", ["heap-api.com", "heapanalytics.com"]),
    ("Lucky Orange", "analytics", ["luckyorange.com"]),
    ("Triple Whale", "analytics", ["triplewhale", "config-security.com"]),
    ("Northbeam", "analytics", ["northbeam.io"]),
    ("Elevar", "analytics", ["getelevar.com"]),
    ("Littledata", "analytics", ["littledata.io"]),
    ("Segment", "analytics", ["cdn.segment.com"]),
    ("Rockerbox", "analytics", ["rockerbox.com"]),
    ("Polar Analytics", "analytics", ["polaranalytics.com"]),
    ("Proxima", "analytics", ["proxima.ai"]),
    ("The Trade Desk", "advertising", ["adsrvr.org"]),
    ("Criteo", "advertising", ["static.criteo.net"]),
    ("MNTN", "advertising", ["mountain.com"]),
    ("AdRoll", "advertising", ["d.adroll.com"]),
    ("Simpli.fi", "advertising", ["simpli.fi"]),
    ("MikMak", "advertising", ["mikmak.ai"]),
    ("Impact", "affiliates", ["impactcdn.com", "impactradius"]),
    ("ShareASale", "affiliates", ["shareasale.com"]),
    ("Rakuten Advertising", "affiliates", ["tag.rmp.rakuten.com"]),
    ("Awin", "affiliates", ["dwin1.com"]),
    # consent / accessibility / fraud / performance
    ("OneTrust", "privacy_consent", ["cdn.cookielaw.org", "onetrust.com"]),
    ("Pandectes GDPR", "privacy_consent", ["pandectes"]),
    ("Cookiebot", "privacy_consent", ["consent.cookiebot.com"]),
    ("Termly", "privacy_consent", ["app.termly.io"]),
    ("Osano", "privacy_consent", ["cmp.osano.com"]),
    ("Consentmo", "privacy_consent", ["consentmo"]),
    ("accessiBe", "accessibility", ["acsbapp.com", "accessibe.com"]),
    ("UserWay", "accessibility", ["cdn.userway.org"]),
    ("AudioEye", "accessibility", ["audioeye.com"]),
    ("Usablenet", "accessibility", ["usablenet.com"]),
    ("NoFraud", "fraud_prevention", ["services.nofraud.com"]),
    ("Signifyd", "fraud_prevention", ["signifyd.com"]),
    ("Riskified", "fraud_prevention", ["beacon.riskified.com"]),
    ("Yottaa", "performance", ["yottaa.com"]),
    ("Instant Page", "performance", ["instant.page"]),
    ("Sentry", "performance", ["sentry-cdn.com", "sentry.io"]),
    # page builders / merchandising / misc
    ("Shogun", "page_builder", ["getshogun.com"]),
    ("PageFly", "page_builder", ["pagefly.io"]),
    ("GemPages", "page_builder", ["gempages.net", "gemcommerce"]),
    ("Replo", "page_builder", ["replo.app", "replocdn.com"]),
    ("Zipify Pages", "page_builder", ["zipifypages"]),
    ("Instafeed", "social_feeds", ["instafeed"]),
    ("Fomo", "social_proof", ["usefomo.com"]),
    ("ShoppingGives", "donations", ["shoppinggives.com"]),
    ("Kiwi Size Chart", "size_guides", ["kiwisizing.com"]),
    ("True Fit", "size_guides", ["truefitcorp.com"]),
    ("Fit Analytics", "size_guides", ["fitanalytics.com"]),
    ("Bold Product Options", "product_options", ["option.boldapps.net"]),
    ("Infinite Options", "product_options", ["shopstorm.com", "infiniteoptions"]),
    ("Globo Product Options", "product_options", ["globosoftware.net"]),
    ("Weglot", "translation", ["cdn.weglot.com"]),
    ("Langify", "translation", ["langify"]),
    ("Shopify Translate & Adapt", "translation", ["translate-and-adapt"]),
    ("Stockist Store Locator", "store_locator", ["stockist.co"]),
    ("Storepoint Store Locator", "store_locator", ["storepoint.co"]),
    ("Amazon Buy Now Button", "sales_channels", ["buynowbuttons.com"]),
    ("Typekit Fonts", "fonts", ["use.typekit.net"]),
]

# App-embed handles -> (name, category). Unknown handles are still reported,
# with a title-cased name and category "other".
EMBED_APPS = {
    "klaviyo-email-marketing-sms": ("Klaviyo", "email_sms_marketing"),
    "attentive": ("Attentive", "email_sms_marketing"),
    "postscript-sms-marketing": ("Postscript", "email_sms_marketing"),
    "omnisend": ("Omnisend", "email_sms_marketing"),
    "privy": ("Privy", "email_sms_marketing"),
    "judge-me-reviews": ("Judge.me Product Reviews", "reviews"),
    "yotpo-product-reviews": ("Yotpo Reviews", "reviews"),
    "okendo": ("Okendo Reviews", "reviews"),
    "loox": ("Loox Reviews", "reviews"),
    "stamped": ("Stamped Reviews", "reviews"),
    "yotpo-loyalty-rewards": ("Yotpo Loyalty", "loyalty_referrals"),
    "smile-io": ("Smile Rewards", "loyalty_referrals"),
    "gorgias-live-chat-helpdesk": ("Gorgias", "customer_support"),
    "inbox": ("Shopify Inbox", "customer_support"),
    "intelligems-a-b-testing": ("Intelligems A/B Testing", "ab_testing"),
    "microsoft-clarity": ("Microsoft Clarity", "analytics"),
    "elevar-conversion-tracking": ("Elevar", "analytics"),
    "triplewhale": ("Triple Whale", "analytics"),
    "nosto": ("Nosto", "upsell_personalization"),
    "rebuy": ("Rebuy", "upsell_personalization"),
    "redo": ("Redo Returns", "returns_shipping"),
    "pandectes-gdpr": ("Pandectes GDPR", "privacy_consent"),
    "onetrust-consent-management": ("OneTrust", "privacy_consent"),
    "minmaxify-order-limits": ("MinMaxify Order Limits", "inventory_alerts"),
    "mntn": ("MNTN", "advertising"),
    "bnb-app-amazon-buy-now-button": ("Amazon Buy Now Button", "sales_channels"),
    "tolstoy-ads-image-video": ("Tolstoy Shoppable Video", "ugc"),
    "firework-shoppable-video-ugc": ("Firework Shoppable Video", "ugc"),
    "recharge-subscriptions": ("Recharge Subscriptions", "subscriptions"),
    "google-youtube": ("Google & YouTube", "sales_channels"),
    "facebook": ("Facebook & Instagram", "sales_channels"),
    "tiktok": ("TikTok", "sales_channels"),
    "pinterest": ("Pinterest", "sales_channels"),
    "search-discovery": ("Shopify Search & Discovery", "search"),
    "translate-and-adapt": ("Shopify Translate & Adapt", "translation"),
    "forms": ("Shopify Forms", "email_sms_marketing"),
    "swym-relay": ("Swym Wishlist Plus", "wishlist"),
    "checkmate": ("Checkmate", "upsell_personalization"),
    "eg-auto-add-to-cart": ("EG Auto Add to Cart", "upsell_personalization"),
}


def _pretty(handle):
    return " ".join(word.capitalize() for word in handle.split("-") if word)


def detect(html):
    """Homepage HTML -> the apps it runs."""
    if not html:
        return []
    out, seen = [], set()

    def add(name, category, handle, via):
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        out.append({"name": name, "category": category, "handle": handle, "detected_via": via})

    handles = []
    for handle, _block in _APP_BLOCK_RE.findall(html):
        if handle not in handles:
            handles.append(handle)
    for handle in handles:
        name, category = EMBED_APPS.get(handle, (_pretty(handle), "other"))
        add(name, category, handle, "app_embed")
    for name, category, needles in SIGNATURES:
        if any(needle in html for needle in needles):
            add(name, category, None, "script")
    return out
