"""Start the Shopify Scraper API.

    python run.py            # http://localhost:8000
    PORT=9000 python run.py  # another port

Then:  curl "http://localhost:8000/products/details?product=https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow"
"""
import bottle
from cheroot import wsgi

import config
import routes  # noqa: F401  (mounts the routes on bottle's default app)

EXAMPLE = "/products/details?product=https://fentybeauty.com/products/gloss-bomb-universal-lip-luminizer-fenty-glow"


def main():
    app = bottle.default_app()
    print(f"Shopify Scraper listening on http://localhost:{config.PORT}/")
    print(f"Try:  curl \"http://localhost:{config.PORT}{EXAMPLE}\"")
    server = wsgi.Server(("0.0.0.0", config.PORT), app, server_name="shopify-scraper", numthreads=16)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
