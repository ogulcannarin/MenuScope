import json
import re
from dotenv import load_dotenv
from crewai import Crew, Process
from agents import agent_1, agent_2, agent_3, agent_4
from tasks import task_1, task_2, task_3, task_4

load_dotenv()

crew = Crew(
    agents=[agent_1, agent_2, agent_3, agent_4],
    tasks=[task_1, task_2, task_3, task_4],
    process=Process.sequential,
    verbose=True,
)

if __name__ == "__main__":
    print("=" * 60)
    print(" TAM CREWAI PIPELINE BASLIYOR")
    print("  Agent 1 -> OSM Restoran Kesfedici")
    print("  Agent 2 -> QR Menu Link Bulucu")
    print("  Agent 3 -> Menu Sayfasi Tarayici")
    print("  Agent 4 -> Urun Standardizasyon (GPT)")
    print("=" * 60)

    result = crew.kickoff()

    print("\n" + "=" * 60)
    print("TAM SISTEM CIKTISI:")
    print("=" * 60)
    print(result)

    # Sonucu dosyaya kaydet
    # LLM ciktisi genelde ```json ... ``` fence'i ile geliyor, json.loads
    # bunu direkt parse edemiyor - once fence'leri temizle.
    raw = str(result).strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.IGNORECASE)

    with open("crew_output.json", "w", encoding="utf-8") as f:
        try:
            parsed = json.loads(raw)
            json.dump(parsed, f, ensure_ascii=False, indent=2)
        except Exception:
            json.dump({"raw_output": str(result)}, f, ensure_ascii=False, indent=2)

    print("\n>> crew_output.json kaydedildi")