from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
from collections import defaultdict

UA   = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
HOME = "https://www.car-part.com"


# ── Public API ────────────────────────────────────────────────────────────────

def search_one_part(part_name, year, make, model, zipcode, radius=50):
    """Search car-part.com for a single part. Returns {part, results, error}."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        pg  = ctx.new_page()
        result = _search_one(pg, part_name, year, make, model, zipcode, radius)
        browser.close()
    return result


def aggregate_results(parts, part_results):
    """Combine a list of per-part results into ranked store lists."""
    return _aggregate(parts, part_results)


# ── Per-part search flow ──────────────────────────────────────────────────────

def _search_one(page, part_name, year, make, model, zipcode, radius):
    try:
        # domcontentloaded is fast; we wait for the specific element we need next
        page.goto(HOME, wait_until="domcontentloaded", timeout=30000)

        # Form is JS-rendered — wait for the year dropdown to appear.
        # If Cloudflare is blocking us, this will time out.
        try:
            page.wait_for_selector('select[name="userDate"]', state="attached", timeout=20000)
        except Exception:
            body = page.locator("body").inner_text()
            if "security" in body.lower() or "cloudflare" in body.lower() or "moment" in body.lower():
                raise RuntimeError(
                    "car-part.com is temporarily blocking automated requests. "
                    "Please wait 1–2 hours and try again."
                )
            raise

        # ── Year ──
        if year:
            page.select_option('select[name="userDate"]', year)
            page.wait_for_timeout(600)

        # ── Make / Model ──
        if make and model:
            opts = page.evaluate("""() => {
                const s = document.querySelector('select[name="userModel"]');
                return s ? Array.from(s.options).map(o => ({v:o.value, t:o.text})) : [];
            }""")
            match = _best_match(f"{make} {model}", opts)
            if match:
                page.select_option('select[name="userModel"]', value=match)
                page.wait_for_timeout(300)

        # ── Part (fuzzy match) ──
        part_opts = page.evaluate("""() => {
            const s = document.querySelector('select[name="userPart"]');
            return s ? Array.from(s.options).map(o => ({v:o.value, t:o.text})) : [];
        }""")
        part_val = _best_match(part_name, part_opts)
        if not part_val:
            return {"part": part_name, "results": [],
                    "error": f'Part not recognised: "{part_name}"'}
        page.select_option('select[name="userPart"]', value=part_val)

        # ── ZIP ──
        page.fill('input[name="userZip"]', zipcode)

        # ── Submit ──
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            page.click('input[type="image"]')

        # ── Interchange step (pick engine variant) ──
        if page.locator('input[name="dummyVar"]').count() > 0:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                page.click('input[type="image"]')

        html    = page.content()
        results = _parse_inventory(html)
        return {"part": part_name, "results": results, "error": None}

    except Exception as exc:
        return {"part": part_name, "results": [], "error": str(exc)}


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _parse_inventory(html):
    soup = BeautifulSoup(html, "html.parser")
    out  = []
    seen = set()

    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
        # Data rows: exactly 7 cols, col-0 starts with a 4-digit year
        if len(cells) != 7 or not re.match(r"\d{4}\b", cells[0]):
            continue

        price    = _parse_price(cells[4])
        store    = _parse_store(cells[5])
        distance = _parse_distance(cells[6])

        if not store:
            continue

        key = (store.lower(), round(price or 0, 2))
        if key in seen:
            continue
        seen.add(key)

        out.append({"store": store, "price": price, "distance": distance})

    return out


def _parse_price(text):
    m = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _parse_store(text):
    m = re.split(r"\s+(?:USA|Canada|Mexico)-", text)
    if len(m) > 1:
        return m[0].strip()
    m2 = re.split(r"\s+Request_", text)
    return m2[0].strip() if m2 else text.strip()


def _parse_distance(text):
    m = re.search(r"(\d+(?:\.\d+)?)", text.strip())
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


# ── Fuzzy option matching ─────────────────────────────────────────────────────

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _best_match(user_input, options):
    u = _norm(user_input)
    if not u:
        return None
    for o in options:                          # 1. exact
        if _norm(o["t"]) == u:
            return o["v"]
    for o in options:                          # 2. user text inside option
        if u in _norm(o["t"]):
            return o["v"]
    for o in options:                          # 3. option inside user text
        n = _norm(o["t"])
        if n and n in u:
            return o["v"]
    return None


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate(parts, part_results):
    store_map = defaultdict(lambda: {"parts": {}, "distances": [], "display": ""})

    for pr in part_results:
        if pr.get("error"):
            continue
        pname = pr["part"]
        for item in pr["results"]:
            key = item["store"].strip().lower()
            store_map[key]["display"] = item["store"]
            existing = store_map[key]["parts"].get(pname)
            p = item["price"]
            if existing is None or (p is not None and p < existing):
                store_map[key]["parts"][pname] = p
            if item["distance"] is not None:
                store_map[key]["distances"].append(item["distance"])

    all_parts = set(parts)
    stores_all, stores_partial = [], []

    for key, data in store_map.items():
        found   = set(data["parts"])
        missing = all_parts - found
        has_all = not missing
        distance = min(data["distances"]) if data["distances"] else None
        total    = sum(v for v in data["parts"].values() if v is not None)

        entry = {
            "store":         data["display"] or key,
            "has_all":       has_all,
            "parts_found":   dict(data["parts"]),
            "parts_missing": list(missing),
            "total_price":   round(total, 2),
            "distance":      distance,
        }
        (stores_all if has_all else stores_partial).append(entry)

    stores_all.sort(key=lambda x: (x["distance"] or 9999, x["total_price"]))
    stores_partial.sort(key=lambda x: (-len(x["parts_found"]), x["distance"] or 9999))

    errors = [{"part": r["part"], "error": r["error"]}
              for r in part_results if r.get("error")]

    return {
        "parts_searched":  parts,
        "stores_with_all": stores_all,
        "stores_partial":  stores_partial,
        "errors":          errors,
    }
