import json
import math
import time
import requests
from crewai.tools import tool
from playwright.sync_api import sync_playwright


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Iki koordinat arasi kus ucusu mesafe (metre)."""
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ─────────────────────────────────────────────────────────────
# AGENT 1 ARACI: Nominatim Geocoding + Overpass API
# ─────────────────────────────────────────────────────────────

@tool("OpenStreetMap Restoran Bulucu")
def fetch_restaurants_osm(area_name: str, radius_m: int = 2000, limit: int = 50) -> str:
    """
    Verilen bölge adını (örn: 'Konak, İzmir') koordinata çevirip,
    o noktanın çevresindeki belirtilen yarıçapta (varsayılan 2 km) tüm
    restoran, kafe, fast-food ve benzeri yeme-içme mekanlarını bulur.
    
    Args:
        area_name: Aranacak bölge adı (örn: 'Alsancak, İzmir', 'Bornova, İzmir')
        radius_m: Arama yarıçapı metre cinsinden (varsayılan: 2000)
        limit: Maksimum döndürülecek mekan sayısı (varsayılan: 50)
    
    Returns:
        JSON formatında mekan listesi (isim, adres, koordinat, kategori, website)
    """
    HEADERS = {"User-Agent": "RestaurantFinderBot/1.0 (educational project)"}

    # ── ADIM 1: Bölge adını koordinata çevir (Nominatim Geocoding) ──
    try:
        geo_url = "https://nominatim.openstreetmap.org/search"
        geo_params = {"q": area_name, "format": "json", "limit": 1}
        geo_resp = requests.get(geo_url, params=geo_params, headers=HEADERS, timeout=10)
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()

        if not geo_data:
            return json.dumps(
                {"hata": f"'{area_name}' için koordinat bulunamadı. Daha spesifik bir yer adı deneyin."},
                ensure_ascii=False
            )

        lat = float(geo_data[0]["lat"])
        lon = float(geo_data[0]["lon"])
    except Exception as e:
        return json.dumps({"hata": f"Geocoding hatası: {str(e)}"}, ensure_ascii=False)

    # Nominatim rate limit kuralı: istekler arası en az 1 saniye bekleme
    time.sleep(1)

    # ── ADIM 2: Overpass API ile tüm yeme-içme mekanlarını sorgula ──
    # Kapsanan kategoriler: restoran, kafe, fast-food, bar, pub, yiyecek dükkanı,
    # dondurma, pasta, içecek, food_court, büfe
    amenity_types = [
        "restaurant", "cafe", "fast_food", "bar", "pub",
        "food_court", "ice_cream", "bakery", "confectionery",
        "juice_bar", "biergarten", "bbq"
    ]

    # Overpass QL sorgusu — her kategori için around filtresi
    union_queries = "\n".join([
        f'  node["amenity"="{a}"](around:{radius_m},{lat},{lon});'
        f'\n  way["amenity"="{a}"](around:{radius_m},{lat},{lon});'
        for a in amenity_types
    ])

    overpass_query = f"""
[out:json][timeout:30];
(
{union_queries}
);
out center tags;
"""

    try:
        ov_resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=overpass_query,
            headers=HEADERS,
            timeout=35
        )
        ov_resp.raise_for_status()
        ov_data = ov_resp.json()
    except Exception as e:
        return json.dumps({"hata": f"Overpass API hatası: {str(e)}"}, ensure_ascii=False)

    # ── ADIM 3: Gelen veriyi temizle ve yapılandır ──
    results = []
    for element in ov_data.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name", "").strip()

        # İsmi olmayan mekanları atla
        if not name:
            continue

        # Koordinatı al (node için direkt, way için center kullan)
        if element["type"] == "node":
            el_lat = element.get("lat")
            el_lon = element.get("lon")
        else:
            center = element.get("center", {})
            el_lat = center.get("lat")
            el_lon = center.get("lon")

        # Adres bilgisini birleştir
        adres_parcalari = filter(None, [
            tags.get("addr:street", ""),
            tags.get("addr:housenumber", ""),
            tags.get("addr:district", ""),
            tags.get("addr:city", ""),
        ])
        adres = ", ".join(adres_parcalari) or "Adres bilgisi yok"

        mesafe_m = (
            round(_haversine_m(lat, lon, el_lat, el_lon))
            if el_lat is not None and el_lon is not None else None
        )

        results.append({
            "isim": name,
            "kategori": tags.get("amenity", "bilinmiyor"),
            "adres": adres,
            "koordinat": {"lat": el_lat, "lon": el_lon},
            "mesafe_m": mesafe_m,
            "telefon": tags.get("phone", tags.get("contact:phone", "")),
            "website": tags.get("website", tags.get("contact:website", "")),
            "aciklama": tags.get("cuisine", ""),
        })

    # Overpass sonuclari mesafeye gore sirali gelmiyor (OSM ID sirasinda) -
    # limit uygulanmadan once merkeze en yakindan en uzaga sirala, yoksa
    # "en yakin N yer" yerine rastgele N yer donebiliyor.
    results.sort(key=lambda r: r["mesafe_m"] if r["mesafe_m"] is not None else float("inf"))
    results = results[:limit]

    if not results:
        return json.dumps(
            {
                "bilgi": f"'{area_name}' çevresinde ({radius_m}m) kayıtlı mekan bulunamadı.",
                "koordinat": {"lat": lat, "lon": lon},
                "ipucu": "Daha geniş bir yarıçap (radius_m) veya farklı bölge adı deneyin."
            },
            ensure_ascii=False
        )

    return json.dumps(
        {
            "aranan_bolge": area_name,
            "merkez_koordinat": {"lat": lat, "lon": lon},
            "arama_yaricapi_m": radius_m,
            "bulunan_mekan_sayisi": len(results),
            "mekanlar": results
        },
        ensure_ascii=False,
        indent=2
    )


# ─────────────────────────────────────────────────────────────
# AGENT 2 ARACI (birincil, ücretsiz): DuckDuckGo tabanlı QR Menü Arayıcı
# ─────────────────────────────────────────────────────────────

@tool("Dijital Menü Arayıcı")
def search_digital_menu(restaurant_name: str, location: str = "İzmir") -> str:
    """
    Restoranin dijital/QR menu linkini arar. .env'de TAVILY_API_KEY tanimliysa
    Tavily Search API kullanilir (ayda 1000 ucretsiz sorgu, AI agent'lar icin
    optimize edilmis resmi API); tanimli degilse veya hata verirse DuckDuckGo
    ucretsiz HTML aramasina düser.
    Menulux, FineDine, QrMenu, Karekod Menü, Orderific, Menu.com.tr ve diger
    bilinen QR menü platformlarini, ayrica restoranin kendi websitesindeki
    /menu path'ini onceliklendirir.

    Args:
        restaurant_name: Aranacak restoran/kafe ismi
        location: Konum bilgisi (varsayılan: 'İzmir')

    Returns:
        JSON formatında {"restoran", "menu_linki", "platform", "durum"}
    """
    import os
    import re as _re
    from urllib.parse import urlparse, parse_qs, unquote

    # Bilinen QR menü platformları: domain anahtar kelimesi -> platform adı
    KNOWN_MENU_DOMAINS = {
        "menulux.com": "menulux.com",
        "finedinemenu.com": "finedinemenu.com",
        "qrmenu": "qrmenu",
        "karekod": "karekodmenu",
        "orderific.com": "orderific.com",
        "menu.com.tr": "menu.com.tr",
        "menugo": "menugo",
        "adisyonum.com": "adisyonum.com",
        "vokopro.com": "vokopro.com",
        "qrdos.tr": "qrdos",
        "menustar.com.tr": "menustar",
        "getmenu.io": "getmenu",
        "kolaymenü.com": "kolaymenu",
        "kolaymenu.com": "kolaymenu",
    }

    # Domain eşleşse bile bunlar genelde tek bir restorana değil, genel bir
    # dizin/listeleme/blog sayfasına işaret eder - yanlış pozitif kaynağı.
    GENERIC_LISTING_PATTERNS = [
        "/sehir/", "/city/", "/kategori/", "/category/", "/liste/", "/list/",
        "/blog/", "/restoranlar/", "/restaurants/", "/sirala/", "/firmalar/",
        "/companies/", "/tum-", "/all-", "/hakkimizda", "/iletisim",
        "/fiyat", "/pricing", "/demo",
    ]

    # Bilinen işletme dizini / sosyal medya / harita siteleri - bunlar
    # restoranin KENDI menu sayfasi degil, ucuncu parti bir profil/liste
    # sayfasidir (orn. wheree.com bir Google Business aynasi). Bu domainler
    # asla "menu_linki" olarak kabul edilmemeli, tarasak bile gercek fiyat
    # verisi cikmaz.
    NON_MENU_DOMAINS = [
        "wheree.com", "tripadvisor.", "yelp.", "foursquare.", "zomato.",
        "facebook.com", "instagram.com", "happycow.", "restaurantguru.",
        "google.com/maps", "goo.gl/maps", "maps.app.goo.gl", "g.page",
        "yellowpages.", "sahibinden.com", "wikipedia.org", "youtube.com",
        "twitter.com", "x.com", "linkedin.com", "cybo.com", "nicelocal.",
        # Turkiye'ye ozgu mekan rehberi / yemek siparis platformlari -
        # restoranin kendi sitesi degil, ucuncu parti liste/siparis sayfasi.
        "mekanlar.com", "yemeksepeti.com", "getir.com", "trendyolyemek.com",
        "migrosyemek.com", "banabi.com", "restorantr.com",
    ]

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }

    def _is_generic_listing(url: str) -> bool:
        low = url.lower()
        if any(d in low for d in NON_MENU_DOMAINS):
            return True
        return any(p in low for p in GENERIC_LISTING_PATTERNS)

    def _verify_page_matches_restaurant(url: str, name: str) -> bool:
        """
        Bulunan linkin gercekten bu restorana ait oldugunu dogrular: sayfayi
        ceker, restoran adindan turetilen anlamli kelimelerin sayfa
        icerisinde gecip gecmedigine bakar. Sayfaya erisilemezse (JS render,
        bot koruması vb.) supheden yararlanip reddetmez - kabul eder.

        Isim tek jenerik kelimeden olusuyorsa (orn. "Sunset", "Blue", "Like" -
        OSM'de cok yaygin) tek kelime eslesmesi neredeyse her sayfada
        tutabildigi icin yanlis pozitif riski yuksek: bu durumda sayfada
        konum (location parametresinden turetilen sehir/ilce) da gecmeli.
        """
        STOPWORDS = {"cafe", "kafe", "restaurant", "restoran", "bar", "usta",
                     "the", "ve", "ile", "izmir", "alsancak"}
        tokens = [
            t for t in _re.findall(r"[a-zçğıöşü0-9]+", name.lower())
            if len(t) > 2 and t not in STOPWORDS
        ]
        if not tokens:
            return True
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            page_text = r.text.lower()
        except Exception:
            return True
        hits = sum(1 for t in tokens if t in page_text)
        if hits < max(1, len(tokens) // 2):
            return False
        if len(tokens) <= 1:
            loc_tokens = [
                t for t in _re.findall(r"[a-zçğıöşü0-9]+", location.lower())
                if len(t) > 2
            ]
            if loc_tokens and not any(lt in page_text for lt in loc_tokens):
                return False
        return True

    def _extract_real_url(href: str) -> str:
        # DuckDuckGo html sonuclari bazen /l/?uddg=ENCODED_URL redirect linki donduruyor
        if "uddg=" in href:
            try:
                qs = parse_qs(urlparse(href).query)
                if "uddg" in qs:
                    return unquote(qs["uddg"][0])
            except Exception:
                pass
        return href

    def _tavily_search(q: str):
        """Tavily Search API - TAVILY_API_KEY .env'de tanimliysa kullanilir.
        Ayda 1000 ucretsiz arama, AI agent'lar icin optimize edilmis resmi API.
        Basarisiz olursa None doner (DDG'ye duser)."""
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return None
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": q, "max_results": 10},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"  [DEBUG] Tavily basarisiz ({q[:40]}): HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
        except Exception as e:
            print(f"  [DEBUG] Tavily exception ({q[:40]}): {type(e).__name__}: {e}")
            return None
        return [r["url"] for r in data.get("results", []) if r.get("url")]

    def _ddg_search(q: str):
        """Ucretsiz DuckDuckGo HTML arama - yedek/varsayilan yontem."""
        try:
            resp = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": q},
                headers=HEADERS,
                timeout=12,
            )
            resp.raise_for_status()
        except Exception:
            return None
        # Sonuc linklerini cek: <a ... class="result__a" href="...">
        raw_links = _re.findall(r'class="result__a"[^>]*href="([^"]+)"', resp.text)
        return [_extract_real_url(l) for l in raw_links]

    query1 = f"{restaurant_name} {location} dijital menü"
    query2 = f"{restaurant_name} {location} qr menü online menu"

    arama_kaynagi = "tavily"
    links = _tavily_search(query1)
    if not links:
        links = _tavily_search(query2)
    if links is None:
        arama_kaynagi = "duckduckgo"
        links = _ddg_search(query1)

    if links is None:
        return json.dumps(
            {
                "restoran": restaurant_name,
                "menu_linki": "Bulunamadi",
                "platform": None,
                "durum": "arama_hatasi",
            },
            ensure_ascii=False,
        )

    # 1) Once bilinen QR menu platformlarini ara (genel dizin sayfalarini atla,
    #    sayfanin gercekten bu restorana ait oldugunu dogrula)
    for link in links:
        low = link.lower()
        if _is_generic_listing(low):
            continue
        for domain_key, platform_name in KNOWN_MENU_DOMAINS.items():
            if domain_key in low:
                if _verify_page_matches_restaurant(link, restaurant_name):
                    return json.dumps(
                        {
                            "restoran": restaurant_name,
                            "menu_linki": link,
                            "platform": platform_name,
                            "durum": "bulundu",
                            "arama_kaynagi": arama_kaynagi,
                        },
                        ensure_ascii=False,
                    )
                break  # bu link dogrulanamadi, diger domain'leri bu link icin tekrar deneme

    # 2) Bilinen platform yoksa: URL'de /menu veya /menü path'i olan restoran
    #    websiteleri de gecerli kabul edilir (kendi sitesinde menusu olan restoranlar)
    MENU_PATH_KEYWORDS = ["/menu", "/menü", "/meniu", "/card", "/kaart", "/speisekarte"]
    for link in links:
        low = link.lower()
        if _is_generic_listing(low):
            continue
        parsed_path = urlparse(low).path
        if any(kw in parsed_path for kw in MENU_PATH_KEYWORDS):
            if _verify_page_matches_restaurant(link, restaurant_name):
                return json.dumps(
                    {
                        "restoran": restaurant_name,
                        "menu_linki": link,
                        "platform": "restoran_websitesi",
                        "durum": "bulundu",
                        "arama_kaynagi": arama_kaynagi,
                    },
                    ensure_ascii=False,
                )

    # 3) Hicbir eslesme yoksa bulunamadi don, ipucu olarak ilk sonucu ekle
    if links:
        return json.dumps(
            {
                "restoran": restaurant_name,
                "menu_linki": "Bulunamadi",
                "platform": None,
                "durum": "bulunamadi",
                "ipucu_ilk_sonuc": links[0],
                "arama_kaynagi": arama_kaynagi,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "restoran": restaurant_name,
            "menu_linki": "Bulunamadi",
            "platform": None,
            "durum": "bulunamadi",
            "arama_kaynagi": arama_kaynagi,
        },
        ensure_ascii=False,
    )


# ─────────────────────────────────────────────────────────────
# AGENT 2 ARACI (yedek, ücretli): Google Places API tabanlı Restoran Website Bulucu
# ─────────────────────────────────────────────────────────────

@tool("Google Maps Restoran Website Bulucu")
def find_restaurant_website(restaurant_name: str, location: str = "Alsancak, İzmir") -> str:
    """
    Google Places API kullanarak restoran adını ve konumunu eşleştirip
    restoranın gerçek web sitesini döndürür. İki adımlı çalışır:
    1) Text Search → doğru Place ID bulunur
    2) Place Details → website ve Google Maps linki alınır

    Args:
        restaurant_name: Aranacak restoran ya da kafe ismi
        location: Arama yapılacak konum (varsayılan: 'Alsancak, İzmir')

    Returns:
        JSON formatında restoran ismi, website linki ve platform bilgisi
    """
    import os

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return json.dumps(
            {"hata": "GOOGLE_MAPS_API_KEY .env dosyasında bulunamadı. Lütfen ekleyin."},
            ensure_ascii=False
        )

    BASE_URL = "https://maps.googleapis.com/maps/api/place"

    # ── ADIM 1: Text Search — restoran adı + konum ile Place ID bul ──
    try:
        search_query = f"{restaurant_name} {location}"
        text_search_resp = requests.get(
            f"{BASE_URL}/textsearch/json",
            params={
                "query": search_query,
                "key": api_key,
                "language": "tr",
            },
            timeout=10
        )
        text_search_resp.raise_for_status()
        search_data = text_search_resp.json()

        status = search_data.get("status")
        if status != "OK" or not search_data.get("results"):
            return json.dumps(
                {
                    "restoran": restaurant_name,
                    "menu_linki": "Bulunamadi",
                    "platform": None,
                    "durum": "bulunamadi",
                    "google_status": status,
                },
                ensure_ascii=False
            )

        place_id = search_data["results"][0]["place_id"]
        found_name = search_data["results"][0].get("name", restaurant_name)

    except Exception as e:
        return json.dumps(
            {"hata": f"Google Text Search hatası: {str(e)}"},
            ensure_ascii=False
        )

    # ── ADIM 2: Place Details — website ve harita linki al ──
    try:
        details_resp = requests.get(
            f"{BASE_URL}/details/json",
            params={
                "place_id": place_id,
                "fields": "name,website,formatted_phone_number,url",
                "key": api_key,
                "language": "tr",
            },
            timeout=10
        )
        details_resp.raise_for_status()
        details_data = details_resp.json()

        result = details_data.get("result", {})
        website = result.get("website", "")
        google_maps_url = result.get("url", "")
        phone = result.get("formatted_phone_number", "")

        if website:
            # Restoranın kendi web sitesi bulundu
            return json.dumps(
                {
                    "restoran": restaurant_name,
                    "bulunan_isim": found_name,
                    "menu_linki": website,
                    "platform": "website",
                    "google_maps": google_maps_url,
                    "telefon": phone,
                    "durum": "bulundu",
                },
                ensure_ascii=False
            )
        elif google_maps_url:
            # Web sitesi yok ama Google Maps linki var
            return json.dumps(
                {
                    "restoran": restaurant_name,
                    "bulunan_isim": found_name,
                    "menu_linki": google_maps_url,
                    "platform": "google_maps",
                    "telefon": phone,
                    "durum": "bulundu_maps_linki",
                },
                ensure_ascii=False
            )
        else:
            return json.dumps(
                {
                    "restoran": restaurant_name,
                    "menu_linki": "Bulunamadi",
                    "platform": None,
                    "durum": "bulunamadi",
                },
                ensure_ascii=False
            )

    except Exception as e:
        return json.dumps(
            {"hata": f"Google Place Details hatası: {str(e)}"},
            ensure_ascii=False
        )


# ─────────────────────────────────────────────────────────────
# AGENT 3 ARACI: Playwright ile Menü Sayfası Tarayıcı
# ─────────────────────────────────────────────────────────────

@tool("Menü Kategori ve Fiyat Tarayıcı")
def scrape_menu_page(base_url: str) -> str:
    """
    Verilen QR menü linkine gider, cookie popup'ı kapatır,
    kategori butonlarına tıklar ve ürün/fiyat listesini çeker.
    FineDine ve Menulux için özel mantık; Karekod Menü, Orderific,
    Menu.com.tr, QrMenu ve diğer platformlar için genelleştirilmiş
    sekme/scroll taraması kullanır.

    Args:
        base_url: Taranacak menü sayfasının URL'i (http/https ile başlamalı)

    Returns:
        JSON formatında ürün ve fiyat listesi [{urun, fiyat}]
    """
    import re as _re

    if not base_url or not base_url.startswith(("http://", "https://")):
        return json.dumps(
            {"hata": f"Gecersiz URL: '{base_url}'. http:// veya https:// ile baslamali."},
            ensure_ascii=False
        )

    # Fiyat regex: ₺70.00 | ₺70,00 | 70.00 TL | €15.00 | 125₺ | 1150 TL (ondalıksız)
    # Ondalik kismi opsiyonel - Turkiye'deki QR menulerde "125₺" gibi tam sayi +
    # bitisik para birimi sembolu cok yaygin bir format, bunu da yakalamamiz gerekiyor.
    PRICE_RE = _re.compile(
        r'(?:[₺€$£]\s*\d{1,6}(?:[.,]\d{1,2})?|\d{1,6}(?:[.,]\d{1,2})?\s*(?:TL|₺|tl|lira))',
        _re.IGNORECASE
    )
    SKIP_WORDS = {"menu", "siparis", "ekle", "ara", "sepet", "toplam",
                  "kvkk", "cerez", "cookie", "gizlilik", "kisisel",
                  "anasayfa", "hakkimizda", "iletisim", "giris",
                  # Turkce kucuk harfe cevirmede İ -> i̇ oldugu ve s/ş
                  # farkli oldugu icin ASCII formlar eslesmiyor, aksanli
                  "iletişim", "hakkımızda", "girişi",
                  # Site navigasyonu / sayfa iskeleti - urun degil
                  "haberler", "kurumsal", "menüler", "menümüz", "ürünler",
                  "overview", "photos", "reviews", "suggest an edit",
                  "tıkla gelsin", "ara gelsin", "üye ol", "kayıt ol",
                  "sepetim", "favoriler", "bize ulaşın", "şubelerimiz",
                  "kampanyalar", "kariyer", "galeri"}

    def dismiss_cookie(page):
        for sel in [
            "button:has-text('Hepsini kabul et')",
            "button:has-text('Kabul et')",
            "button:has-text('Accept All')",
            "button:has-text('Accept')",
            "[id*='cookie'] button",
            "[class*='cookie'] button",
        ]:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0:
                    btn.click(timeout=2000)
                    page.wait_for_timeout(400)
                    return
            except Exception:
                pass

    def click_menu_entry(page) -> bool:
        """
        Menulux, FineDine gibi platformlar QR linkine gidince once bir
        karsilama ekrani gosterir ('Menüye Git', 'MENÜYÜ KEŞFET' vb.) -
        urun/fiyat verisi sadece bu tiklamadan sonra render edilir. Buton
        genelde CSS animasyonlu (scale/transition) oldugu icin normal click
        Playwright'ta "element is not stable" diye timeout verir; force=True
        ile bu kontrolu atlariz.
        """
        for sel in [
            "text=Menüye Git", "text=Menuye Git",
            "text=MENÜYÜ KEŞFET", "text=MENUYU KESFET",
            "text=Menüyü Görüntüle", "text=Menüyü Gör",
            "text=View Menu",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=3000, force=True)
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                pass
        return False

    def interactive_scrape(page) -> list:
        """
        Kategori sekmelerine/butonlarina tiklayarak urun/fiyat toplar, hicbir
        sekme bulunamazsa scroll ile lazy-load tetikler. Cogu QR menu SaaS
        sablonu (FineDine, Karekod Menu, Orderific, QrMenu, Menu.com.tr vb.)
        benzer sekme/buton yapilari kullandigi icin bu yontem platforma ozel
        kod yazmadan genel bir kapsama saglar.
        """
        collected = []
        base_page_url = page.url

        # Once hicbir sekmeye tiklamadan mevcut sayfanin icerigini oku -
        # bircok site (orn. kokoreco.com/menu) butun urun/fiyat listesini
        # tek sayfada, sekmesiz gosteriyor. Bunu atlayip direkt tiklamaya
        # geçmek, o veriyi hic gormeden kaybetmek anlamina gelir.
        text = page.inner_text("body")
        collected.extend(extract_items(text))

        cat_buttons = []
        for sel in [
            "button[class*='category']", "button[class*='Category']",
            "[class*='category-tab']", "[role='tab']",
            "[class*='tab-item']", "nav button", "nav a",
            "[class*='menu-tab']", "[class*='kategori']",
        ]:
            try:
                btns = page.locator(sel).all()
                if btns:
                    cat_buttons = btns
                    break
            except Exception:
                pass

        for btn in cat_buttons[:8]:
            try:
                # "nav a" / "nav button" gibi genis secicilerle bazen kategori
                # sekmesi degil, sitenin ana navigasyonu (Anasayfa, Hakkimizda,
                # Blog, Iletisim) yakalaniyor. Bunlara tiklamak menuden tamamen
                # uzaklasip yanlis sayfayi taramamiza yol acar - gercek bir
                # sayfaya giden href'i olan elemanlari atla.
                href = btn.get_attribute("href")
                is_real_link = href and href.strip() and not href.strip().lower().startswith(("#", "javascript:"))
                if is_real_link:
                    continue
                btn.click(timeout=2000)
                page.wait_for_timeout(1200)
                if page.url != base_page_url:
                    # Beklenmedik sekilde farkli bir sayfaya gecildi - geri don
                    page.go_back(wait_until="domcontentloaded", timeout=10000)
                    page.wait_for_timeout(500)
                    continue
                text = page.inner_text("body")
                collected.extend(extract_items(text))
            except Exception:
                pass

        # Hicbir sey toplanamadiysa scroll + body text dene (lazy-load ihtimali)
        if not collected:
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
            except Exception:
                pass
            text = page.inner_text("body")
            collected.extend(extract_items(text))

        return collected

    # Urun adinin en az 2 harf icermesi sarti - sadece sayi/fiyat olan
    # satirlarin (orn. "0.00") yanlislikla urun adi sayilmasini engeller.
    LETTER_RE = _re.compile(r'[A-Za-zÇĞİÖŞÜçğıöşü]{2,}')

    def extract_items(text: str) -> list:
        items = []
        lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 1]
        for i, line in enumerate(lines):
            m = PRICE_RE.search(line)
            if m:
                fiyat = m.group(0).strip()
                urun = PRICE_RE.sub("", line).strip().strip(":-.,|/ ")
                if len(urun) < 2:
                    prev = lines[i - 1] if i > 0 else ""
                    # Onceki satir da fiyat iceriyorsa kullanma (orn. "650 TL ₺")
                    if prev and not PRICE_RE.search(prev):
                        urun = prev
                    else:
                        continue
                if not urun or any(w in urun.lower() for w in SKIP_WORDS):
                    continue
                if not LETTER_RE.search(urun):
                    # Hala sayisal/sembolik bir deger ise (orn. baska bir fiyat,
                    # "0.00" gibi stok/placeholder degeri) urun olarak kabul etme.
                    continue
                # Urun adi rakamla basliyor ve anlamli harf icermiyorsa atla
                # (orn. "650 TL ₺" gibi yanlis yakalanmis fiyat satirlari)
                urun_harf = PRICE_RE.sub("", urun).strip()
                if len(urun_harf) < 2 or not LETTER_RE.search(urun_harf):
                    continue
                if urun and len(urun) > 2:
                    items.append({"urun": urun[:60], "fiyat": fiyat})
        # Tekrar kaldir
        seen, unique = set(), []
        for item in items:
            key = (item["urun"].lower(), item["fiyat"])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:30]

    def extract_items_name_only(text: str) -> list:
        """
        Bazi restoran siteleri fiyati web sitesinde hic yayinlamiyor (menu
        sadece urun/icerik listesi). Boyle durumda extract_items hicbir sey
        bulamaz ve sonuc tamamen bos doner. Bu fonksiyon fiyat aramadan,
        aciklama/malzeme satirlarini (virgullu, uzun) ve navigasyon/baslik
        kelimelerini eleyerek en azindan urun isimlerini yakalar - fiyat
        yerine "Belirtilmemis" doner ki agent 4 en azindan urun ismini
        standardize edebilsin.
        """
        items = []
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for line in lines:
            low = line.lower()
            if len(line) < 3 or len(line) > 45:
                continue
            if line.count(",") >= 2:
                continue
            if PRICE_RE.search(line):
                continue
            if any(w in low for w in SKIP_WORDS):
                continue
            if not LETTER_RE.search(line):
                continue
            items.append({"urun": line[:60], "fiyat": "Belirtilmemis"})
        seen, unique = set(), []
        for item in items:
            key = item["urun"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:40]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/16.0 Mobile/15E148 Safari/604.1"
                ),
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                locale="tr-TR",
                # Bazı küçük işletme siteleri süresi geçmiş/geçersiz SSL sertifikası
                # kullanıyor (örn. ERR_CERT_DATE_INVALID) - bunlari da tarayabilelim.
                ignore_https_errors=True,
            )
            page = context.new_page()

            page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
            # networkidle: SPA API cagrisi bitmeden render etmez (burgerking vb.)
            # Timeout olursa (analytics/heartbeat olan siteler) manual beklemeye duser
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                page.wait_for_timeout(4000)
            dismiss_cookie(page)
            page.wait_for_timeout(600)
            click_menu_entry(page)
            # Ek scroll: lazy-load / infinite scroll tetikle
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(1000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
            except Exception:
                pass

            all_items = []

            if "finedinemenu.com" in base_url:
                # FineDine: ?table=sample parametresi urunu listesini yukluyor
                finedine_url = base_url
                if "?" not in finedine_url:
                    finedine_url = finedine_url + "?table=sample"
                elif "table=" not in finedine_url:
                    finedine_url = finedine_url + "&table=sample"

                if finedine_url != base_url:
                    page.goto(finedine_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                    dismiss_cookie(page)
                    page.wait_for_timeout(500)

                click_menu_entry(page)
                all_items = interactive_scrape(page)

            elif "menulux.com" in base_url:
                # Menulux: KVKK sayfasını atla, kategori linklerini gez
                text = page.inner_text("body")
                if "kvkk" in text.lower() or "kisisel veri" in text.lower():
                    browser.close()
                    return json.dumps(
                        {"hata": "KVKK sayfasi - gercek menu degil", "url": base_url},
                        ensure_ascii=False
                    )

                cat_links = []
                try:
                    links = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
                    cat_links = list(set([
                        l for l in links
                        if any(p in l for p in ["/category/", "#!/category/", "/kategori/"])
                        and l.startswith("http")
                    ]))[:5]
                except Exception:
                    pass

                pages_to_check = cat_links if cat_links else [base_url]
                for link in pages_to_check:
                    try:
                        if link != base_url:
                            page.goto(link, wait_until="domcontentloaded", timeout=20000)
                            page.wait_for_timeout(1500)
                        text = page.inner_text("body")
                        if "kvkk" not in text.lower():
                            all_items.extend(extract_items(text))
                    except Exception:
                        pass

            else:
                # Genel: once Next.js __NEXT_DATA__ dene (burgerking.com.tr vb. icin
                # hizli yol - tum veri HTML'e gomulur, JS gerekmez), basarisizsa
                # Karekod Menü / Orderific / QrMenu vb. icin sekme/scroll taramasi yap

                def extract_nextjs_data(pg) -> list:
                    """Next.js __NEXT_DATA__ tag'inden urun/fiyat ceker."""
                    try:
                        next_str = pg.evaluate(
                            "() => { const e=document.getElementById('__NEXT_DATA__');"
                            " return e?e.textContent:null; }"
                        )
                        if not next_str:
                            return []
                        nd = json.loads(next_str)
                    except Exception:
                        return []

                    nd_items = []
                    price_keys = ('price', 'fiyat', 'amount', 'calPrice', 'basePrice',
                                  'originalPrice', 'discountedPrice', 'unitPrice', 'salePrice')
                    name_keys  = ('name', 'title', 'productName', 'itemName', 'isim',
                                  'baslik', 'label', 'description')

                    def scan(obj, depth=0):
                        if depth > 14 or len(nd_items) >= 50:
                            return
                        if isinstance(obj, dict):
                            pval = next(
                                (str(obj[k]) for k in price_keys
                                 if k in obj and obj[k] is not None
                                 and str(obj[k]).replace('.','',1).replace(',','',1).isdigit()),
                                None
                            )
                            nval = next(
                                (obj[k] for k in name_keys
                                 if k in obj and isinstance(obj.get(k), str)
                                 and len(obj[k]) > 1 and LETTER_RE.search(obj[k])),
                                None
                            )
                            if pval and nval:
                                nd_items.append({"urun": nval[:60], "fiyat": f"{pval} TL"})
                            for v in obj.values():
                                scan(v, depth + 1)
                        elif isinstance(obj, list):
                            for it in obj[:100]:
                                scan(it, depth + 1)

                    scan(nd)
                    seen_nd, unique_nd = set(), []
                    for it in nd_items:
                        key = (it["urun"].lower(), it["fiyat"])
                        if key not in seen_nd:
                            seen_nd.add(key)
                            unique_nd.append(it)
                    return unique_nd

                all_items = extract_nextjs_data(page)
                if not all_items:
                    all_items = interactive_scrape(page)

            # Fiyat hic bulunamadiysa (bazi siteler fiyat yayinlamiyor),
            # en azindan urun isimlerini fiyatsiz olarak yakalamayi dene.
            if not all_items:
                all_items = extract_items_name_only(page.inner_text("body"))

            browser.close()

            # Tekrarlari kaldir
            seen, unique = set(), []
            for item in all_items:
                key = item["urun"].lower()
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            all_items = unique[:50]

            if not all_items:
                return json.dumps(
                    {"bilgi": "Sayfada fiyat/urun verisi bulunamadi", "url": base_url},
                    ensure_ascii=False
                )

            return json.dumps(all_items, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"hata": f"Tarama hatasi: {str(e)[:200]}"}, ensure_ascii=False)