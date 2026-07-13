from crewai import Agent, LLM
from tools import search_digital_menu, scrape_menu_page

# Agent 2/3 her mekan icin araci ayri ayri cagiriyor - OpenAI'nin tool-calling
# API'si tek bir mesajda en fazla 128 arac cagrisina izin veriyor. 162 mekanlik
# bir listede model hepsini tek turda paralel cagirmaya calisirsa
# "array_above_max_length" hatasi aliyoruz. parallel_tool_calls=False ile
# modeli ayni akista ama tek tek (sirali) cagirmaya zorluyoruz.
sequential_tool_llm = LLM(model="gpt-4o-mini", parallel_tool_calls=False)

# Agent 1'in artik bir araci yok - main.py OSM aracini dogrudan cagirip ham
# veriyi kucuk gruplar (batch) halinde bu agent'a veriyor, is sadece bu ham
# veriyi filtreleyip istenen alanlara (isim/kategori/adres/website) indirgemek.
# Daha once tools=[fetch_restaurants_osm] tanimliyken model bazen zaten elinde
# olan veri icin gereksiz yere araci tekrar cagirmaya calisip gercek bir
# Overpass rate-limit hatasina takiliyor ve JSON ciktisinin oncesine/sonrasina
# bunu aciklayan metin ekliyordu - arac erisimini tamamen kaldirmak bunu onler.
agent_1 = Agent(
    role='Mekan Verisi Formatlama Uzmani',
    goal='Verilen ham OSM mekan listesini filtreleyip JSON formatinda yapilandirmak.',
    backstory='Ham konum verisini hizli ve eksiksiz bicimde istenen JSON semasina donusturen bir veri isleme uzmanisin. Hicbir arac kullanmazsin, sadece sana verilen veriyi isleyip donersin.',
    verbose=True,
    allow_delegation=False,
    llm="gpt-4o-mini"
)

agent_2 = Agent(
    role='Dijital Menü Dedektifi',
    goal='Verilen restoran listesindeki her bir mekan için internette dijital menü linklerini bulmak.',
    backstory='Sen bir araştırma uzmanısın. İşletmelerin dijital menü bağlantılarını bulmakta ustasın. Bulamadıkların için link kısmına "Bulunamadı" yazarsın.',
    verbose=True,
    allow_delegation=False,
    tools=[search_digital_menu],
    llm=sequential_tool_llm,
    # Varsayilan max_iter=25 - 300 mekani tek tek (sirali) tarayabilmek icin
    # en az 300 dongu gerekiyor, yoksa "max iterations exceeded" fallback'ine
    # dusuyor ve bu fallback parallel_tool_calls ile cakisip hata veriyor.
    max_iter=320
)

agent_3 = Agent(
    role='Menü Veri Yapılandırma Uzmanı',
    goal='Restoranların menü sayfalarındaki karmaşık metinleri okuyup, içecek ve yiyecekleri belirli bir JSON formatında çıkarmak.',
    backstory='Sen bir veri madencisisin. Karmaşık menü metinlerinin içinden ürün isimlerini ve fiyatlarını ustalıkla bulup, {"urun":"...", "fiyat":"..."} formatında yapılandırılmış veriye dönüştürürsün.',
    verbose=True,
    allow_delegation=False,
    tools=[scrape_menu_page],
    llm=sequential_tool_llm,
    max_iter=320
)
agent_4 = Agent(
    role='Ürün Eşleştirme ve Anlamlandırma Uzmanı',
    goal='Farklı restoranlardan gelen ürün isimlerinin (örn: "Kutu Kola" ile "Coca Cola") aynı ürünü ifade edip etmediğini anlamak ve eşleştirmek.',
    backstory='Sen bir veri temizleme ve anlamsal eşleştirme (entity resolution) uzmanısın. Yazım hataları, kısaltmalar veya farklı isimlendirmeler kullanılsa bile iki ürünün aslında aynı şey olup olmadığını mükemmel bir şekilde anlarsın.',
    verbose=True,
    allow_delegation=False,
    llm="gpt-4o-mini"
)