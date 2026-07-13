import json
import os
import sys
import time

# Windows konsolu varsayilan olarak cp1254 (Turkce) kod sayfasi kullanir ve
# CrewAI'nin ilerleme ciktisindaki emoji/₺ gibi karakterleri yazdiramaz -
# UnicodeEncodeError ile crash olur. UTF-8'e zorla.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from crewai import Crew, Process, Task
from agents import agent_1, agent_2, agent_3, agent_4
from tasks import AREA_NAME, RADIUS_M, LIMIT
from tools import fetch_restaurants_osm

load_dotenv()

# Mekan formatlama (Agent 1) icin de ayni batch mantigi gecerli - tek seferde
# 250+ mekan verildiginde model isi yarida birakabiliyor. Fiyat taramasindan
# (Playwright, tool-cagrili) cok daha hafif bir gorev oldugu icin daha buyuk
# gruplar halinde islenebiliyor.
VENUE_BATCH_SIZE = 40

# Agent 3'e (ve buyuk hacimde Agent 4'e) tum listeyi tek seferde vermek yerine
# kucuk gruplar (batch) halinde veriyoruz. Sebep: onceki calistirmada Agent 3'e
# 59 gecerli menu linki tek Task icinde verildiginde, model gorevi "HER BIRI
# isle" talimatina ragmen yarida birakip sadece 6 tanesini tarayip bitirdi -
# uzun tekrarli bir checklist'i LLM'in sonuna kadar goturmesi guvenilir degil.
# 6'sarlik gruplar model icin "bitirilebilir" boyutta kalip her grubu
# tamamlama ihtimalini artiriyor.
BATCH_SIZE = 6

# Adim 2 (menu linki arama) daha once tum listeyi tek Task olarak isliyordu
# ("162 mekanin tamamini tek seferde basariyla islemisti" varsayimiyla), ama
# 250 mekanlik bir kosuda yarida (176/250) bir OpenAI baglanti hatasi tum
# Task'i - ve o ana kadarki ilerlemeyi - iptal etti. Diger adimlar gibi
# batch'e bolmek, bir hatanin butun adimi degil sadece bir grubu etkilemesini
# saglar.
MENU_BATCH_SIZE = 25

VENUES_CACHE_FILE = "venues_cache.json"
MENU_LINKS_CACHE_FILE = "menu_links_cache.json"


def parse_json(raw) -> list:
    """
    Beklenen cikti her zaman bir JSON dizisi. Model bazen dizinin oncesine/
    sonrasina aciklama metni ekliyor (orn. "Iste sonuc: ```json [...] ``` Not:
    ...") - bu yuzden sadece bastaki/sondaki kod bloğunu kirpmak yetmiyor,
    ilk '[' ile son ']' arasindaki govdeyi metnin neresinde olursa olsun
    cikarmamiz gerekiyor.
    """
    text = str(raw).strip()
    start, end = text.find('['), text.rfind(']')
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def run_single_agent_task(agent, description: str, expected_output: str, retries: int = 3):
    """
    Tek bir agent'i tek bir Task ile calistirir, JSON parse edip dondurur.
    OpenAI/network gibi gecici baglanti hatalarinda (crew.kickoff() sirasinda
    olusabiliyor, orn. "ConnectionError: Failed to connect to OpenAI API")
    kisa bir bekleme ile tekrar dener - tek bir gecici hata yuzunden koca bir
    grubun (ya da tum adimin) sonucunu kaybetmemek icin.
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            task = Task(description=description, expected_output=expected_output, agent=agent)
            crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
            result = crew.kickoff()
            return parse_json(result)
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = 15 * attempt
                print(f"  [UYARI] Deneme {attempt}/{retries} basarisiz ({e}), {wait}s sonra tekrar denenecek...")
                time.sleep(wait)
    raise last_err


if __name__ == "__main__":
    print("=" * 60)
    print(" TAM CREWAI PIPELINE BASLIYOR (batch mimarisi)")
    print("  Agent 1 -> OSM Restoran Kesfedici")
    print("  Agent 2 -> QR Menu Link Bulucu")
    print("  Agent 3 -> Menu Sayfasi Tarayici (6'sarlik gruplar halinde)")
    print("  Agent 4 -> Urun Standardizasyon - GPT (her grup icin ayri)")
    print("=" * 60)

    # ── ADIM 1: Mekan kesfi (OSM aracini dogrudan cagir, Agent 1'e batch ──
    # halinde formatlat) ──────────────────────────────────────────────
    if os.path.exists(VENUES_CACHE_FILE):
        with open(VENUES_CACHE_FILE, encoding="utf-8") as f:
            venues = json.load(f)
        print(f"\n[ADIM 1] Onbellekten {len(venues)} mekan yuklendi ({VENUES_CACHE_FILE} bulundu, adim atlandi).")
    else:
        print("\n[ADIM 1] Mekan kesfi calisiyor...")
        osm_raw = json.loads(fetch_restaurants_osm.func(area_name=AREA_NAME, radius_m=RADIUS_M, limit=LIMIT))
        if "hata" in osm_raw or not osm_raw.get("mekanlar"):
            print(f">> HATA: OSM'den mekan alinamadi, pipeline durduruluyor: {osm_raw}")
            sys.exit(1)
        raw_mekanlar = osm_raw["mekanlar"]
        print(f">> OSM'den {len(raw_mekanlar)} ham mekan cekildi, {VENUE_BATCH_SIZE}'serlik gruplar halinde formatlanacak...")

        venues = []
        total_venue_batches = (len(raw_mekanlar) + VENUE_BATCH_SIZE - 1) // VENUE_BATCH_SIZE
        for batch_idx in range(total_venue_batches):
            batch = raw_mekanlar[batch_idx * VENUE_BATCH_SIZE: (batch_idx + 1) * VENUE_BATCH_SIZE]
            batch_json = json.dumps(batch, ensure_ascii=False)
            task1_desc = (
                'Hicbir arac kullanma, sadece asagida verilen ham veriyi isle. '
                'Ham OSM mekan listesindeki HER BIR mekan icin su alanlari '
                'cikar: isim, kategori, adres, website. Listede '
                f'{len(batch)} mekan var, HICBIRINI ATLAMA - hepsini isle.\n\n'
                f'Ham liste:\n{batch_json}\n\n'
                'Sadece JSON dondur, oncesinde veya sonrasinda aciklama yazma. '
                'Cikti formati: [{"isim": "...", "kategori": "...", "adres": '
                '"...", "website": "..."}]'
            )
            try:
                formatted = run_single_agent_task(
                    agent_1, task1_desc,
                    f'Bu {len(batch)} mekanin her biri icin isim, kategori, '
                    'adres, website iceren JSON listesi.'
                )
            except Exception as e:
                print(f"  HATA (Agent 1, grup {batch_idx + 1} atlandi): {e}")
                continue
            venues.extend(formatted)
            print(f"  -- Grup {batch_idx + 1}/{total_venue_batches}: {len(formatted)} mekan formatlandi (toplam: {len(venues)})")

        print(f">> {len(venues)} mekan bulundu")
        with open(VENUES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(venues, f, ensure_ascii=False, indent=2)

    # ── ADIM 2: Menu linki arama (Adim 3/4 gibi batch halinde - 250 mekanlik ──
    # bir kosuda tum listeyi tek Task olarak islerken 176/250'de bir OpenAI
    # baglanti hatasi tum adimin sonucunu iptal etmisti) ─────────────────
    if os.path.exists(MENU_LINKS_CACHE_FILE):
        with open(MENU_LINKS_CACHE_FILE, encoding="utf-8") as f:
            menu_links = json.load(f)
        print(f"\n[ADIM 2] Onbellekten {len(menu_links)} mekanin menu linki yuklendi ({MENU_LINKS_CACHE_FILE} bulundu, adim atlandi).")
    else:
        print(f"\n[ADIM 2] Menu linki aramasi calisiyor ({MENU_BATCH_SIZE}'serlik gruplar halinde)...")
        menu_links = []
        total_menu_batches = (len(venues) + MENU_BATCH_SIZE - 1) // MENU_BATCH_SIZE
        for batch_idx in range(total_menu_batches):
            batch = venues[batch_idx * MENU_BATCH_SIZE: (batch_idx + 1) * MENU_BATCH_SIZE]
            batch_json = json.dumps(batch, ensure_ascii=False)
            task2_desc = (
                'Asagidaki restoran listesindeki HER BIR mekan icin "Dijital '
                'Menü Arayıcı" aracini kullanarak dijital menu linki ara. Her '
                'mekan icin bir kez araci cagir. Bulamadiklarin icin '
                'menu_linki alani "Bulunamadi" olsun. Listede '
                f'{len(batch)} mekan var, HICBIRINI ATLAMA - hepsini isle.\n\n'
                f'Restoran listesi:\n{batch_json}\n\n'
                'Cikti formati: [{"isim": "...", "menu_linki": "...", "platform": "..."}]'
            )
            try:
                formatted = run_single_agent_task(
                    agent_2, task2_desc,
                    f'Bu {len(batch)} mekanin her biri icin isim ve menu '
                    'linki iceren JSON listesi. Bulunamayanlar icin '
                    'menu_linki = "Bulunamadi".'
                )
            except Exception as e:
                print(f"  HATA (Agent 2, grup {batch_idx + 1} atlandi): {e}")
                continue
            menu_links.extend(formatted)
            print(f"  -- Grup {batch_idx + 1}/{total_menu_batches}: {len(formatted)} mekan icin arama tamamlandi (toplam: {len(menu_links)})")

        print(f">> {len(menu_links)} mekan icin arama tamamlandi")
        with open(MENU_LINKS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(menu_links, f, ensure_ascii=False, indent=2)

    valid_links = [
        m for m in menu_links
        if m.get("menu_linki") and str(m["menu_linki"]).startswith(("http://", "https://"))
    ]
    print(f">> {len(valid_links)} gecerli menu linki bulundu")

    # ── ADIM 3+4: Fiyat tarama + standardizasyon (batch'ler halinde) ──
    print(f"\n[ADIM 3-4] {len(valid_links)} mekan, {BATCH_SIZE}'sarlik gruplar halinde taranacak...")
    final_products = []
    total_batches = (len(valid_links) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        batch = valid_links[batch_idx * BATCH_SIZE: (batch_idx + 1) * BATCH_SIZE]
        isimler = [b["isim"] for b in batch]
        print(f"\n  -- Grup {batch_idx + 1}/{total_batches}: {isimler}")

        batch_json = json.dumps(batch, ensure_ascii=False)
        task3_desc = (
            'Asagidaki restoran listesindeki HER BIR mekan icin "Menu '
            'Kategori ve Fiyat Tarayıcı" aracini, parametre olarak SADECE o '
            'mekanin menu_linki degeriyle bir kez cagir. Listede '
            f'{len(batch)} mekan var, HICBIRINI ATLAMA - hepsini isle.\n\n'
            f'Restoran listesi:\n{batch_json}\n\n'
            'Toplanan verileri su JSON formatinda dondur: '
            '[{"restoran": "...", "urunler": [{"urun": "...", "fiyat": "..."}]}] '
            'Urun bulunamadiysa "urunler": [] yaz.'
        )
        try:
            scraped = run_single_agent_task(
                agent_3, task3_desc,
                f'Bu {len(batch)} restoranin her biri icin urun/fiyat listesi iceren JSON.'
            )
        except Exception as e:
            print(f"  HATA (Agent 3, grup atlandi): {e}")
            continue

        scraped = [s for s in scraped if s.get("urunler")]
        if not scraped:
            print("  >> bu grupta urun bulunamadi, standardizasyona gerek yok")
            continue

        scraped_json = json.dumps(scraped, ensure_ascii=False)
        task4_desc = (
            'Asagidaki restoran/urun listesini al. Listedeki HER BIR urunu '
            'analiz et ve su formatta cikti ver: [{"restoran": "...", '
            '"orijinal_isim": "...", "standart_isim": "...", "kategori": "...", '
            '"fiyat": "..."}] "restoran" ve "fiyat" alanlarini oldugu gibi '
            'kopyala - degistirme veya uydurma. Kategori secenekleri: Sicak '
            'Icecek, Soguk Icecek, Sandvic, Burger, Ana Yemek, Tatli, '
            'Atistirmalik, Kahvalti, Diger. Ayni standart_isim farkli '
            'restoranlarda gecebilir (orn. "Kutu Kola" ile "Coca Cola" ikisi '
            'de "Cola" olur) - bu, urunlerin restoranlar arasi eslestirilmesini '
            'standart_isim uzerinden saglar.\n\n'
            f'Veri:\n{scraped_json}'
        )
        try:
            standardized = run_single_agent_task(
                agent_4, task4_desc,
                'Her urun icin restoran, orijinal_isim, standart_isim, kategori '
                've fiyat iceren JSON listesi.'
            )
        except Exception as e:
            print(f"  HATA (Agent 4, grup ham veriyle kaydedildi): {e}")
            standardized = [
                {
                    "restoran": s["restoran"],
                    "orijinal_isim": p["urun"],
                    "standart_isim": p["urun"],
                    "kategori": "Diger",
                    "fiyat": p["fiyat"],
                }
                for s in scraped for p in s["urunler"]
            ]

        final_products.extend(standardized)
        print(f"  >> {len(standardized)} urun eklendi (toplam: {len(final_products)})")

        # Her grup sonunda kaydet - bu adim en uzun ve en riskli (Playwright
        # ile onlarca dis site taramasi), boylece bir crash tum ilerlemeyi
        # degil sadece son yarim kalan grubu goturur.
        with open("crew_output.json", "w", encoding="utf-8") as f:
            json.dump(final_products, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"BITTI: {len(final_products)} urun, crew_output.json'a kaydedildi")
    print("=" * 60)
