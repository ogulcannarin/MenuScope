from crewai import Task
from agents import agent_1, agent_2, agent_3, agent_4

# ─── Task 1: Mekanları Keşfet ───────────────────────────────────
task_1 = Task(
    description=(
        'Alsancak, Izmir bolgesindeki yeme-icme mekanlarini bul. '
        '"OpenStreetMap Restoran Bulucu" aracini kullan. '
        'Parametreler: area_name="Alsancak, Izmir", radius_m=1500, limit=5. '
        'Sonucu su JSON formatinda dondur: '
        '[{"isim": "...", "kategori": "...", "adres": "...", "website": "..."}]'
    ),
    expected_output=(
        'En fazla 5 mekanin isim, kategori, adres ve website bilgisini '
        'iceren JSON listesi.'
    ),
    agent=agent_1
)

# ─── Task 2: Menü Linklerini Bul ────────────────────────────────
task_2 = Task(
    description=(
        'Agent 1 tarafindan olusturulan restoran listesindeki HER BIR '
        'mekan icin "Dijital Menü Arayıcı" aracini kullanarak dijital menu linki ara. '
        'Her mekan icin bir kez araci cagir. '
        'Bulamadiklarin icin menu_linki alani "Bulunamadi" olsun. '
        'Cikti formati: '
        '[{"isim": "...", "menu_linki": "...", "platform": "..."}]'
    ),
    expected_output=(
        'Her mekan icin isim ve menu linki iceren JSON listesi. '
        'Bulunamayanlar icin menu_linki = "Bulunamadi".'
    ),
    agent=agent_2
)

# ─── Task 3: Menü Sayfalarını Tara ──────────────────────────────
task_3 = Task(
    description=(
        'Agent 2 tarafindan saglanan restoran listesini al. '
        'SADECE Agent 2 ciktisindaki "menu_linki" alanini kullan - baska hicbir '
        'kaynaktan (Agent 1 ciktisindaki "website" alani, kendi tahminin, vb.) '
        'URL turetme veya kullanma, KESINLIKLE YASAK. '
        '"menu_linki" gecerli bir URL (http veya https ile baslayan) olan '
        'HER BIR restoran icin "Menu Kategori ve Fiyat Tarayici" aracini, '
        'parametre olarak SADECE o menu_linki degeriyle bir kez cagir. '
        'menu_linki "Bulunamadi" olan restoranlari tamamen atla - bu restoranlar '
        'icin arac ASLA cagirma, direkt "urunler": [] yaz ve gec. '
        'Toplanan verileri su JSON formatinda dondur: '
        '[{"restoran": "...", "urunler": [{"urun": "...", "fiyat": "..."}]}] '
        'Urun bulunamadiysa "urunler": [] yaz.'
    ),
    expected_output=(
        'Her restoran icin urun ve fiyat listesi iceren JSON. '
        'Menu linki olmayanlari atla. Sadece menu_linki kullanildi, '
        'baska URL turetilmedi.'
    ),
    agent=agent_3
)

# ─── Task 4: Ürünleri Standardize Et ────────────────────────────
task_4 = Task(
    description=(
        'Agent 3 tarafindan saglanan urun listesini al. '
        'Urun listesi bos olan restoranlari atla. '
        'Urun listesi dolu olan her restoran icin, '
        'listedeki HER BIR urunu analiz et ve su formatta cikti ver: '
        '[{"restoran": "...", "orijinal_isim": "...", "standart_isim": "...", '
        '"kategori": "...", "fiyat": "..."}] '
        '"restoran" ve "fiyat" alanlarini Agent 3 ciktisindan oldugu gibi kopyala - '
        'degistirme veya uydurma. Kategori secenekleri: Sicak Icecek, Soguk Icecek, '
        'Sandvic, Burger, Ana Yemek, Tatli, Atistirmalik, Kahvalti, Diger. '
        'Her urunun hangi restorandan geldigini, orijinal adini, anlasilan standart '
        'adini, kategorisini ve fiyatini yaz. Ayni standart_isim farkli restoranlarda '
        'gecebilir (orn. "Kutu Kola" ile "Coca Cola" ikisi de "Cola" olur) - bu, '
        'urunlerin restoranlar arasi eslestirilmesini standart_isim uzerinden saglar.'
    ),
    expected_output=(
        'Her urun icin restoran, orijinal_isim, standart_isim, kategori ve fiyat '
        'iceren JSON listesi.'
    ),
    agent=agent_4
)