# Restoran & Menü Keşif Ajanı (CrewAI)

Belirli bir bölgedeki (varsayılan: Alsancak, İzmir) restoran/kafe/fast-food mekanlarını otomatik olarak bulan, dijital menülerini tarayan ve ürünleri standardize edip kategorize eden 4 agent'lı bir [CrewAI](https://github.com/crewAIInc/crewAI) pipeline'ı.

## Mimari

| Agent | Görev | Kullandığı araç / kaynak |
|---|---|---|
| 1 — Lokal Restoran ve Kafe Keşif Uzmanı | Bölgedeki mekanları bulur, merkeze en yakın olanları sıralar | OpenStreetMap (Nominatim + Overpass API) |
| 2 — Dijital Menü Dedektifi | Her mekan için dijital/QR menü linki arar | Tavily Search API (ücretsiz kotalı), yoksa DuckDuckGo'ya düşer |
| 3 — Menü Veri Yapılandırma Uzmanı | Bulunan menü linkini tarar, ürün/fiyat listesi çıkarır | Playwright (headless Chromium) |
| 4 — Ürün Eşleştirme ve Anlamlandırma Uzmanı | Ürün isimlerini standardize eder, kategorize eder, restoranlar arası eşleştirmeyi `standart_isim` üzerinden sağlar | GPT-4o-mini |

Agent'lar `Process.sequential` ile sırayla çalışır; her agent bir önceki agent'ın çıktısını bağlam olarak alır.

## Kurulum

```bash
pip install -r requirements.txt
playwright install chromium
```

`.env.example` dosyasını `.env` olarak kopyalayıp kendi API anahtarlarını gir:

```
OPENAI_API_KEY=...      # zorunlu (agent'ların LLM'i)
TAVILY_API_KEY=...      # onerilir (menu linki aramasi icin, aylik 1000 ucretsiz sorgu)
GOOGLE_MAPS_API_KEY=...  # opsiyonel, su an hicbir agent'a bagli degil (yedek/manuel arac)
```

`TAVILY_API_KEY` tanımlı değilse arama otomatik olarak ücretsiz DuckDuckGo HTML aramasına düşer.

## Çalıştırma

```bash
python main.py
```

Aranacak bölge, yarıçap ve mekan limiti `tasks.py` içindeki `task_1` tanımından değiştirilebilir.

## Çıktı

Sonuç `crew_output.json` dosyasına yazılır:

```json
[
  {
    "restoran": "kokorecin alasi",
    "orijinal_isim": "Çeyrek",
    "standart_isim": "Kokoreç",
    "kategori": "Ana Yemek",
    "fiyat": "250 ₺"
  }
]
```

`pipeline_output.json` erken bir denemeden kalma örnek çıktıdır (referans amaçlı repoda tutuluyor).

## Bilinen sınırlamalar

- Bazı restoran siteleri fiyat bilgisini web'de hiç yayınlamıyor; bu durumda ürün ismi `"fiyat": "Belirtilmemis"` ile döner.
- Bazı zincir restoranların (örn. büyük fast-food markaları) menü sayfası sadece ürün kategorilerini listeler, fiyatlar ürün bazında ayrı sayfalardadır — bu sayfalar taranmaz.
- Arama sonuçları (Tavily/DuckDuckGo) zaman içinde değişebileceğinden aynı bölge için farklı çalıştırmalarda farklı mekan/menü linkleri bulunabilir.
