"""
uca_segments.csv 의 seg_is_anomaly 열을 채운다.
 - 정상 영상(category == Normal) 구간: 전부 0 (UCF-Crime 라벨상 범죄 없음)
 - 이상 영상 구간: 문장을 Qwen3-8B(vLLM, localhost:8000)에 보내 anomaly / normal 판정

실행 위치: 데이터 루트   (vLLM 서버가 먼저 떠 있어야 함)
    python3 classify_segments.py
출력: uca_segments.csv 를 덮어쓰고, seg_is_anomaly / seg_label_raw 열이 채워짐
"""
import csv, json, sys, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

CSV = "uca_segments.csv"
URL = "http://localhost:8000/v1/chat/completions"
MODEL = "Qwen/Qwen3-8B"
WORKERS = 32            # vLLM 이 서버 쪽에서 배치로 묶으므로 동시 요청 수

# UCF-Crime 공식 페이지의 유형 정의 (요약)
DEF = {
 "Abuse":        "cruel or violent behavior against children, elderly people, animals, or women",
 "Arrest":       "police arresting or detaining individuals",
 "Arson":        "people deliberately setting fire to property",
 "Assault":      "a sudden violent physical attack on someone who does not fight back",
 "Burglary":     "thieves entering a building or house to commit theft, without force against people",
 "Explosion":    "a destructive event of something blowing apart",
 "Fighting":     "two or more people attacking one another",
 "RoadAccidents":"traffic accidents involving vehicles, pedestrians, or cyclists",
 "Robbery":      "thieves taking money or property by force or threat of force",
 "Shooting":     "the act of shooting someone with a gun",
 "Shoplifting":  "stealing goods from a shop while posing as a shopper",
 "Stealing":     "taking property or money without permission (not shoplifting)",
 "Vandalism":    "deliberate destruction of or damage to property",
}

SYSTEM = (
 "You label surveillance-video segment descriptions. Each video is known to contain "
 "exactly one type of anomalous event somewhere in it. Given the event type and a "
 "sentence describing one segment, decide whether that segment shows the anomalous "
 "event itself (including the act in progress, e.g. the attack, the theft, the fire, "
 "the crash) or an ordinary scene before/after it (people walking, talking, waiting, "
 "shopping normally, police arriving after the fact, etc.). "
 "Answer with exactly one word: anomaly or normal."
)

def ask(cat, sentence):
    user = f"Event type: {cat} ({DEF[cat]}).\nSegment description: {sentence}\nAnswer:"
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "max_tokens": 4, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    for attempt in range(3):
        try:
            r = requests.post(URL, json=body, timeout=60)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip().lower()
        except Exception as e:
            if attempt == 2:
                return f"error:{e}"
            time.sleep(2)

def to_label(raw):
    if raw.startswith("anomaly"): return 1
    if raw.startswith("normal"):  return 0
    return ""                      # 파싱 실패 → 비워두고 나중에 검수

rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
for r in rows:
    r.setdefault("seg_label_raw", "")

todo = [i for i, r in enumerate(rows) if r["category"] != "Normal" and r["seg_is_anomaly"] == ""]
for i, r in enumerate(rows):
    if r["category"] == "Normal":
        r["seg_is_anomaly"] = "0"
print(f"분류 대상 구간: {len(todo)}")

done = 0; t0 = time.time()
with ThreadPoolExecutor(WORKERS) as ex:
    futs = {ex.submit(ask, rows[i]["category"], rows[i]["sentence"]): i for i in todo}
    for f in as_completed(futs):
        i = futs[f]; raw = f.result()
        rows[i]["seg_label_raw"] = raw
        rows[i]["seg_is_anomaly"] = str(to_label(raw))
        done += 1
        if done % 500 == 0:
            print(f"  {done}/{len(todo)}  {time.time()-t0:.0f}s")

fields = list(rows[0].keys())
with open(CSV, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

# 통계
from collections import Counter
c = Counter(); fail = 0
for r in rows:
    if r["category"] == "Normal": continue
    if r["seg_is_anomaly"] == "": fail += 1
    else: c[(r["category"], r["seg_is_anomaly"])] += 1
print(f"\n파싱 실패: {fail}")
print(f"{'유형':14s} {'이상':>6s} {'정상':>6s} {'이상비율':>8s}")
for cat in DEF:
    a, n = c[(cat, "1")], c[(cat, "0")]
    print(f"{cat:14s} {a:6d} {n:6d} {a/(a+n):8.2f}" if a+n else f"{cat:14s}      -")
print(f"\n저장: {CSV}  ({time.time()-t0:.0f}s)")