import asyncio, json, re, hashlib, mimetypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/"config.json").read_text())
OUT=ROOT/"data/products.json"
IMAGE_DIR=ROOT/"images/products"
cfg=CONFIG["doppel"]; link_cfg=CONFIG["links"]
PROFILE_PREFIX=cfg["profile_prefix"].rstrip("/")+"/"
BLOCKED={d.lower().removeprefix("www.") for d in link_cfg.get("blocked_domains",[])}

def domain(url):
    try:return urlparse(url).netloc.lower().removeprefix("www.")
    except:return ""
def absolute(base,href):
    if not href or href.startswith(("mailto:","tel:","javascript:","#")):return ""
    return urljoin(base,href)
def compact(t):return re.sub(r"\s+"," ",t or "").strip()
def category_from_url(url):
    slug=urlparse(url).path.rstrip("/").split("/")[-1] or "Finds"
    return slug.replace("-"," ").replace("_"," ").title()
def safe_slug(v):
    v=re.sub(r"[^a-zA-Z0-9]+","-",compact(v).lower()).strip("-")
    return v[:70] or "product"
def ext_for(url,ctype=""):
    e=Path(urlparse(url).path).suffix.lower()
    if e in {".jpg",".jpeg",".png",".webp",".gif"}:return ".jpg" if e==".jpeg" else e
    m=mimetypes.guess_extension((ctype or "").split(";")[0].strip()) or ".jpg"
    return ".jpg" if m in {".jpe",".jpeg"} else m
def external_score(url,text=""):
    d=domain(url)
    if not d or d in BLOCKED:return -100
    s=10; t=text.lower()
    s+=sum(4 for k in ["buy","shop","item","product","view","link","order"] if k in t)
    if any(k in url.lower() for k in ["product","item","goods","detail"]):s+=5
    return s

async def rendered_html(page,url):
    await page.goto(url,wait_until="domcontentloaded",timeout=60000)
    try:await page.wait_for_load_state("networkidle",timeout=12000)
    except:pass
    await page.wait_for_timeout(1000)
    return await page.content()

def profile_links(html,base):
    s=BeautifulSoup(html,"html.parser"); out=set()
    for a in s.select("a[href]"):
        u=absolute(base,a.get("href"))
        if u.startswith(PROFILE_PREFIX):out.add(u.split("#")[0].split("?")[0].rstrip("/"))
    return out

def parse_products(html,page_url,category):
    s=BeautifulSoup(html,"html.parser"); out=[]
    for tag in s.select('script[type="application/ld+json"]'):
        try:data=json.loads(tag.string or tag.get_text())
        except:continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            obj=stack.pop()
            if isinstance(obj,list):stack.extend(obj);continue
            if not isinstance(obj,dict):continue
            if "@graph" in obj:stack.append(obj["@graph"])
            typ=obj.get("@type")
            if typ=="Product" or isinstance(typ,list) and "Product" in typ:
                offers=obj.get("offers") or {}
                if isinstance(offers,list):offers=offers[0] if offers else {}
                image=obj.get("image") or ""
                if isinstance(image,list):image=image[0] if image else ""
                out.append({"name":compact(obj.get("name")),"brand":"","category":category,
                            "price":str(offers.get("price","")) if isinstance(offers,dict) else "",
                            "image":absolute(page_url,image),
                            "link":absolute(page_url,(offers.get("url","") if isinstance(offers,dict) else obj.get("url",""))),
                            "source_page":page_url})
    selectors=["[data-product]","[data-testid*='product']","[class*='product-card']","[class*='ProductCard']","[class*='product-item']"]
    cards=[]
    for sel in selectors:cards.extend(s.select(sel))
    for card in cards:
        a=card.select_one("a[href]"); img=card.select_one("img")
        if not a or not img:continue
        nameel=card.select_one("h1,h2,h3,h4,[class*='title'],[class*='name']")
        name=compact(nameel.get_text(" ",strip=True) if nameel else img.get("alt") or a.get_text(" ",strip=True))
        href=absolute(page_url,a.get("href")); src=img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if name and href:out.append({"name":name[:180],"brand":"","category":category,"price":"","image":absolute(page_url,src),"link":href,"source_page":page_url})
    if not out:
        for a in s.select("a[href]"):
            img=a.select_one("img")
            if not img:continue
            name=compact(img.get("alt") or a.get_text(" ",strip=True)); href=absolute(page_url,a.get("href")); src=img.get("src") or img.get("data-src") or ""
            if name and href and src:out.append({"name":name[:180],"brand":"","category":category,"price":"","image":absolute(page_url,src),"link":href,"source_page":page_url})
    return out

async def resolve_final(page,item):
    if domain(item.get("link",""))!="doppel.fit":return item
    url=item["link"]
    try:html=await rendered_html(page,url)
    except:return item
    s=BeautifulSoup(html,"html.parser")
    og=s.select_one('meta[property="og:image"]')
    if og and og.get("content"):item["image"]=absolute(url,og["content"])
    c=[]
    for a in s.select("a[href]"):
        u=absolute(url,a.get("href")); score=external_score(u,a.get_text(" ",strip=True))
        if score>0:c.append((score,u))
    if c and link_cfg.get("prefer_external_destination",True):
        c.sort(reverse=True); item["doppel_link"]=url; item["link"]=c[0][1]
    return item

def download_image(url,name,index):
    if not url:return ""
    try:
        r=requests.get(url,headers={"User-Agent":"Mozilla/5.0","Referer":"https://doppel.fit/"},timeout=30)
        r.raise_for_status()
        ext=ext_for(url,r.headers.get("content-type",""))
        h=hashlib.sha1(url.encode()).hexdigest()[:10]
        filename=f"{safe_slug(name)}-{index:04d}-{h}{ext}"
        IMAGE_DIR.mkdir(parents=True,exist_ok=True)
        (IMAGE_DIR/filename).write_bytes(r.content)
        return f"images/products/{filename}"
    except Exception as e:
        print("Image download failed:",url,e); return ""

def dedupe(items):
    d={}
    for p in items:
        k=p.get("link") or (p.get("name","").lower(),p.get("image",""))
        if k and k not in d:d[k]=p
    return list(d.values())

def cleanup(used):
    keep={Path(x).name for x in used}
    for p in IMAGE_DIR.glob("*"):
        if p.is_file() and p.name!=".gitkeep" and p.name not in keep:p.unlink()

async def main():
    stamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":1400,"height":1000},user_agent="Mozilla/5.0 Chrome/124 Safari/537.36")
        seeds=[u.rstrip("/") for u in cfg["seed_urls"]]; cats=set(seeds)
        if cfg.get("discover_categories",True):
            for seed in seeds:
                try:cats|=profile_links(await rendered_html(page,seed),seed)
                except Exception as e:print("Discovery failed",e)
        cats=sorted(cats,key=len)[:cfg.get("max_category_pages",30)]
        raw=[]
        for url in cats:
            try:
                items=parse_products(await rendered_html(page,url),url,category_from_url(url))
                print(url,len(items)); raw.extend(items)
            except Exception as e:print("Category failed",url,e)
        raw=dedupe(raw)[:cfg.get("max_product_pages",1000)]
        final=[]; used=[]
        for i,item in enumerate(raw,1):
            item=await resolve_final(page,item)
            if not item.get("name") or not item.get("link"):continue
            remote=item.get("image","")
            local=download_image(remote,item["name"],i)
            if local:
                item["remote_image"]=remote
                item["image"]=local
                used.append(local)
            item["source"]="doppel"; item["imported_at"]=stamp; item.setdefault("featured",0)
            final.append(item)
        final=dedupe(final)
        cleanup(used)
        final.sort(key=lambda x:(x.get("category",""),x.get("name","").lower()))
        OUT.write_text(json.dumps(final,ensure_ascii=False,indent=2))
        print(f"Wrote {len(final)} products and {len(used)} local images")
        await browser.close()

if __name__=="__main__": asyncio.run(main())
