import asyncio
import json
import re
import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
OUT = ROOT / "data/products.json"
IMAGE_DIR = ROOT / "images/products"

cfg = CONFIG["doppel"]
link_cfg = CONFIG["links"]

PROFILE_PREFIX = cfg["profile_prefix"].rstrip("/") + "/"
BLOCKED = {d.lower().removeprefix("www.") for d in link_cfg.get("blocked_domains", [])}


def compact(text):
    return re.sub(r"\s+", " ", text or "").strip()


def domain(url):
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def absolute(base, href):
    if not href:
        return ""
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return ""
    return urljoin(base, href)


def category_from_url(url):
    slug = urlparse(url).path.rstrip("/").split("/")[-1] or "Finds"
    return slug.replace("-", " ").replace("_", " ").title()


def safe_slug(value):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", compact(value).lower()).strip("-")
    return value[:70] or "product"


def ext_for(url, content_type=""):
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        return ".jpg" if ext == ".jpeg" else ext
    ctype = (content_type or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(ctype) or ".jpg"
    if guessed in {".jpe", ".jpeg"}:
        guessed = ".jpg"
    return guessed


def external_score(url, anchor_text=""):
    d = domain(url)
    if not d or d in BLOCKED:
        return -100
    score = 10
    t = (anchor_text or "").lower()
    score += sum(4 for k in ["buy", "shop", "item", "product", "view", "link", "order", "cop"] if k in t)
    if any(k in url.lower() for k in ["product", "item", "goods", "detail"]):
        score += 5
    return score


def looks_like_url(v):
    return isinstance(v, str) and v.startswith(("http://", "https://"))


def looks_like_image_url(v):
    if not looks_like_url(v):
        return False
    u = v.lower()
    return any(x in u for x in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", "image", "cdn"])


def iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_dicts(v)


def first_value(d, keys):
    for key in keys:
        if key in d and d[key] not in (None, "", [], {}):
            return d[key]
    return None


def normalize_brand(v):
    if isinstance(v, dict):
        return compact(str(v.get("name") or v.get("title") or ""))
    return compact(str(v or ""))


def normalize_image(v, base_url):
    if isinstance(v, list):
        for x in v:
            y = normalize_image(x, base_url)
            if y:
                return y
        return ""
    if isinstance(v, dict):
        for k in ["url", "src", "image", "imageUrl", "image_url", "original", "large", "medium"]:
            if k in v:
                y = normalize_image(v[k], base_url)
                if y:
                    return y
        return ""
    if isinstance(v, str):
        return absolute(base_url, v)
    return ""


def normalize_link(v, base_url):
    if isinstance(v, dict):
        for k in ["url", "href", "link", "productUrl", "product_url", "destinationUrl", "destination_url"]:
            if k in v:
                y = normalize_link(v[k], base_url)
                if y:
                    return y
        return ""
    if isinstance(v, str):
        return absolute(base_url, v)
    return ""


def candidate_from_dict(d, page_url, fallback_category):
    name = first_value(d, [
        "name", "title", "productName", "product_name",
        "displayName", "display_name", "label"
    ])
    if not isinstance(name, (str, int, float)):
        name = None
    name = compact(str(name or ""))

    image = normalize_image(first_value(d, [
        "image", "imageUrl", "image_url", "thumbnail", "thumbnailUrl",
        "thumbnail_url", "cover", "coverImage", "cover_image", "media", "images"
    ]), page_url)

    link = normalize_link(first_value(d, [
        "url", "href", "link", "productUrl", "product_url",
        "destinationUrl", "destination_url", "externalUrl", "external_url"
    ]), page_url)

    price = first_value(d, ["price", "displayPrice", "display_price", "formattedPrice", "formatted_price"])
    if isinstance(price, dict):
        price = first_value(price, ["formatted", "display", "amount", "value"])
    price = compact(str(price or ""))

    brand = normalize_brand(first_value(d, ["brand", "brandName", "brand_name", "vendor", "designer"]))

    category = first_value(d, ["category", "categoryName", "category_name", "collection", "section"])
    if isinstance(category, dict):
        category = first_value(category, ["name", "title", "label"])
    category = compact(str(category or fallback_category))

    # Require a decent name plus either image or link.
    if len(name) < 2 or not (image or link):
        return None

    # Avoid obvious navigation / non-product objects.
    low_name = name.lower()
    if low_name in {"home", "profile", "settings", "login", "sign up", "signup", "search"}:
        return None

    return {
        "name": name[:180],
        "brand": brand,
        "category": category or fallback_category,
        "price": price,
        "image": image,
        "link": link,
        "source_page": page_url,
    }


def extract_candidates_from_json(data, page_url, fallback_category):
    out = []
    for d in iter_dicts(data):
        c = candidate_from_dict(d, page_url, fallback_category)
        if c:
            out.append(c)
    return out


def parse_html_products(html, page_url, category):
    soup = BeautifulSoup(html, "html.parser")
    products = []

    # JSON-LD
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or tag.get_text())
            products.extend(extract_candidates_from_json(data, page_url, category))
        except Exception:
            pass

    # Next.js / hydration / generic JSON script blobs
    for tag in soup.select("script"):
        txt = tag.string or tag.get_text()
        if not txt:
            continue
        txt = txt.strip()
        if not txt or len(txt) < 20:
            continue
        # Direct JSON only; skip arbitrary JS.
        if txt[0] in "[{":
            try:
                data = json.loads(txt)
                products.extend(extract_candidates_from_json(data, page_url, category))
            except Exception:
                pass

    # Generic product cards
    selectors = [
        "[data-product]",
        "[data-testid*='product']",
        "[class*='product-card']",
        "[class*='ProductCard']",
        "[class*='product-item']",
        "[class*='ProductItem']"
    ]
    cards = []
    for sel in selectors:
        cards.extend(soup.select(sel))

    for card in cards:
        a = card.select_one("a[href]")
        img = card.select_one("img")
        if not a:
            continue
        name_el = card.select_one("h1,h2,h3,h4,[class*='title'],[class*='name']")
        name = compact(
            (name_el.get_text(" ", strip=True) if name_el else "")
            or (img.get("alt") if img else "")
            or a.get_text(" ", strip=True)
        )
        if not name:
            continue
        href = absolute(page_url, a.get("href"))
        src = ""
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        products.append({
            "name": name[:180],
            "brand": "",
            "category": category,
            "price": "",
            "image": absolute(page_url, src),
            "link": href,
            "source_page": page_url,
        })
    return products


def dedupe(items):
    seen = {}
    for p in items:
        if not p.get("name"):
            continue
        key = (
            compact(p.get("name", "")).lower(),
            p.get("link", ""),
            p.get("image", "")
        )
        if key not in seen:
            seen[key] = p
    return list(seen.values())


def choose_best_external_link(candidates):
    scored = []
    for url, txt in candidates:
        score = external_score(url, txt)
        if score > 0:
            scored.append((score, url))
    if not scored:
        return ""
    scored.sort(reverse=True)
    return scored[0][1]


async def resolve_detail_page(page, item):
    url = item.get("link", "")
    if domain(url) != "doppel.fit":
        return item

    try:
        outbound = []

        async def on_response(resp):
            try:
                ct = (resp.headers.get("content-type") or "").lower()
                if "json" in ct:
                    data = await resp.json()
                    # Search JSON for outbound URLs too.
                    for d in iter_dicts(data):
                        for k, v in d.items():
                            if isinstance(v, str) and looks_like_url(v):
                                outbound.append((v, k))
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await page.wait_for_timeout(1200)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        og = soup.select_one('meta[property="og:image"]')
        if og and og.get("content"):
            item["image"] = absolute(url, og["content"])

        for a in soup.select("a[href]"):
            outbound.append((absolute(url, a.get("href")), a.get_text(" ", strip=True)))

        best = choose_best_external_link(outbound)
        if best and link_cfg.get("prefer_external_destination", True):
            item["doppel_link"] = url
            item["link"] = best

    except Exception as e:
        print("Detail resolve failed:", url, e)

    return item


def download_image(url, name, index):
    if not url:
        return ""
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://doppel.fit/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
            timeout=30,
        )
        r.raise_for_status()
        ext = ext_for(url, r.headers.get("content-type", ""))
        digest = hashlib.sha1(url.encode()).hexdigest()[:10]
        filename = f"{safe_slug(name)}-{index:04d}-{digest}{ext}"
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        (IMAGE_DIR / filename).write_bytes(r.content)
        return f"images/products/{filename}"
    except Exception as e:
        print("Image download failed:", url, e)
        return ""


def cleanup_images(used):
    keep = {Path(x).name for x in used}
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for p in IMAGE_DIR.iterdir():
        if p.is_file() and p.name != ".gitkeep" and p.name not in keep:
            try:
                p.unlink()
            except Exception:
                pass


async def scrape_category(page, url):
    category = category_from_url(url)
    network_candidates = []

    async def on_response(resp):
        try:
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            data = await resp.json()
            found = extract_candidates_from_json(data, url, category)
            if found:
                print(f"JSON response {resp.url}: {len(found)} candidate(s)")
                network_candidates.extend(found)
        except Exception:
            pass

    page.on("response", on_response)

    print("Opening:", url)
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Give SPA requests time to fire.
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(2500)

    # Try to trigger lazy-loading.
    for _ in range(8):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(300)

    html = await page.content()
    html_candidates = parse_html_products(html, url, category)

    print(f"{category}: network={len(network_candidates)} html={len(html_candidates)}")
    return dedupe(network_candidates + html_candidates)


async def main():
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1440, "height": 1100},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
        )

        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        raw = []
        for url in cfg["seed_urls"]:
            try:
                raw.extend(await scrape_category(page, url.rstrip("/")))
            except Exception as e:
                print("Category scrape failed:", url, e)

        raw = dedupe(raw)[:cfg.get("max_product_pages", 1000)]
        print("Raw candidates:", len(raw))

        final = []
        used_images = []

        for i, item in enumerate(raw, 1):
            item = await resolve_detail_page(page, item)

            # Skip obviously bad / internal nav rows
            if not item.get("name"):
                continue
            if not item.get("link"):
                # Keep Doppel detail if that is all we found.
                item["link"] = item.get("source_page", "")

            remote_image = item.get("image", "")
            local_image = download_image(remote_image, item["name"], i)
            if local_image:
                item["remote_image"] = remote_image
                item["image"] = local_image
                used_images.append(local_image)

            item["source"] = "doppel"
            item["imported_at"] = stamp
            item.setdefault("featured", 0)
            final.append(item)

        final = dedupe(final)
        final.sort(key=lambda x: (x.get("category", ""), x.get("name", "").lower()))
        cleanup_images(used_images)

        OUT.write_text(json.dumps(final, ensure_ascii=False, indent=2))
        print(f"Wrote {len(final)} products")
        print(f"Saved {len(used_images)} local images")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
