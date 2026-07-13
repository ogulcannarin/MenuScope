# ─── Adim 1 arama parametreleri ─────────────────────────────────
# Aranacak bolge, yaricap ve mekan limiti buradan degistirilebilir.
# main.py, OSM aracini bu parametrelerle once dogrudan cagirip ham
# mekan listesini alir, sonra Agent 1'e kucuk gruplar (batch) halinde
# formatlatir - Agent 3'te oldugu gibi, tek seferde dev bir liste
# verildiginde model gorevi yarida birakip bir kismini atlayabiliyor.
AREA_NAME = "Alsancak, Izmir"
RADIUS_M = 4000
LIMIT = 300
