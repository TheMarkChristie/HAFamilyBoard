"""Does the card file survive being imported before Home Assistant's frontend starts?

Home Assistant's frontend replaces CustomElementRegistry.prototype.define/get with a scoped-registry polyfill that keeps
its own table, so an element defined natively before that is reported as missing afterwards (seen 12 Oct 2026 in Edge
155: every card "Configuration error"). This check imports a card file first, then installs a polyfill of the same shape,
then defines home-assistant through it, then asks the polyfilled registry for the cards. It is run against the current
file and against the v0.3.0 file to show the difference.

  python tests/registry_timing_check.py            (needs the Python playwright package and its Chromium)
"""
import os
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CARD = os.path.join(ROOT, "custom_components", "family_board", "www", "family-board-cards.js")

PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>
  // as in Home Assistant's index page: the card file and the frontend are imported together, and the small card
  // file wins the race. Only once it has run does the frontend start: it installs a registry polyfill with its own
  // table ...
  import("./card.js").then(() => {
    const native = { define: CustomElementRegistry.prototype.define, get: CustomElementRegistry.prototype.get };
    const table = new Map();
    CustomElementRegistry.prototype.define = function (tag, cls, opts) { table.set(tag, cls); return native.define.call(this, tag, cls, opts); };
    CustomElementRegistry.prototype.get = function (tag) { return table.get(tag); };
    // ... and then defines its own root element through it
    customElements.define("home-assistant", class extends HTMLElement {});
  });
</script>
</body></html>"""


def check(source: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "check.html")
        open(path, "w", encoding="utf-8").write(PAGE)
        open(os.path.join(tmp, "card.js"), "w", encoding="utf-8").write(source)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # a dynamic import needs a real origin (file:// pages may not import modules), so serve the folder on one
            def serve(route, request):
                name = request.url.split("/")[-1].split("?")[0] or "check.html"
                local = os.path.join(tmp, name)
                if os.path.exists(local):
                    route.fulfill(status=200, body=open(local, "rb").read(), content_type="text/javascript" if name.endswith(".js") else "text/html")
                else:
                    route.fulfill(status=404, body="")
            page.route("http://card.check/**", serve)
            page.goto("http://card.check/check.html")
            page.wait_for_timeout(2500)
            out = page.evaluate("""() => ({
                today: !!customElements.get("family-today-card"), lists: !!customElements.get("family-lists-card"),
                cards: (window.customCards || []).length })""")
            browser.close()
    return out


def main():
    current = open(CARD, encoding="utf-8").read()
    old = subprocess.run(["git", "-C", ROOT, "show", "v0.3.0:custom_components/family_board/www/family-board-cards.js"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    results = {"v0.3.0 (defines at import)": check(old), "current (defines once home-assistant exists)": check(current)}
    for name, r in results.items():
        print("%-48s cards defined for the frontend: today=%s lists=%s | customCards=%d" % (name, r["today"], r["lists"], r["cards"]))
    ok = results["current (defines once home-assistant exists)"]["today"] and results["current (defines once home-assistant exists)"]["lists"]
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
