"""
test 클립에 대해 VLM 서버(vLLM, OpenAI 호환)로 로그를 생성하고 지표를 계산한다.

  python3 eval_test.py --name B_lora_change  --port 8002 --frames change
  python3 eval_test.py --name C_lora_uniform --port 8002 --frames uniform
  python3 eval_test.py --name A_base_change  --port 8003 --frames change

출력: eval/<name>.jsonl (클립별 예측), eval/<name>_metrics.json, 콘솔 요약
지표: JSON 파싱 성공률, is_anomaly 정확도/정밀도/재현율/F1, anomaly_type 정확도(이상 클립 한정), 유형별 재현율
"""
import json, csv, base64, re, argparse, time, requests
from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True); ap.add_argument("--port", type=int, required=True)
ap.add_argument("--frames", default="change", choices=["change", "uniform"])
ap.add_argument("--workers", type=int, default=16)
a = ap.parse_args()

URL = f"http://localhost:{a.port}/v1/chat/completions"
MODEL = requests.get(f"http://localhost:{a.port}/v1/models").json()["data"][0]["id"]
FR = Path("clips/frames"); OUT = Path("eval"); OUT.mkdir(exist_ok=True)

INSTRUCTION = """다음은 CCTV 영상에서 시간순으로 추출한 프레임 8장이다. 아래 JSON 형식으로 로그를 작성하라. 화면에 보이는 것만 기술하고, 의도나 감정은 추측하지 않는다.
{"scene": 장소 유형, "objects": [{"type": "사람|차량|동물|물건", "count": 정수, "appearance": 외형}], "action": 관찰 가능한 동작 1문장, "is_anomaly": "정상|이상", "anomaly_type": "Abuse|Arrest|Arson|Assault|Burglary|Explosion|Fighting|RoadAccidents|Robbery|Shooting|Shoplifting|Stealing|Vandalism|None", "summary": 1문장 요약}"""

def b64(p): return "data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode()

def infer(c):
    content = [{"type": "image_url", "image_url": {"url": b64(FR / c["clip_id"] / a.frames / f"f{k}.jpg")}} for k in range(8)]
    content.append({"type": "text", "text": INSTRUCTION})
    body = {"model": MODEL, "max_tokens": 400, "temperature": 0,
            "messages": [{"role": "user", "content": content}]}
    try:
        r = requests.post(URL, json=body, timeout=180); r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return {"raw": f"error:{e}", "pred": None}
    try:
        m = re.search(r"\{.*\}", txt, re.S); d = json.loads(m.group(0))
        assert "is_anomaly" in d and "anomaly_type" in d
        return {"raw": txt, "pred": d}
    except Exception:
        return {"raw": txt, "pred": None}

test = [r for r in csv.DictReader(open("clips/manifest.csv", encoding="utf-8")) if r["split"] == "test"]
print(f"[{a.name}] 모델 {MODEL}, test 클립 {len(test)}개, 프레임 {a.frames}")

t0 = time.time(); results = []
with ThreadPoolExecutor(a.workers) as ex:
    futs = {ex.submit(infer, c): c for c in test}
    for i, f in enumerate(as_completed(futs), 1):
        c = futs[f]; o = f.result()
        results.append({"clip_id": c["clip_id"], "video": c["video"], "gt_anomaly": int(c["is_anomaly"]),
                        "gt_type": c["anomaly_type"], **o})
        if i % 100 == 0: print(f"  {i}/{len(test)}  {time.time()-t0:.0f}s")

with open(OUT / f"{a.name}.jsonl", "w", encoding="utf-8") as f:
    for r in results: f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---------------- 지표 ----------------
n = len(results); parsed = [r for r in results if r["pred"]]
tp = fp = fn = tn = 0
type_ok = type_n = 0
per_type = defaultdict(lambda: [0, 0])          # [맞춘 수, 전체] (이상여부 재현율)
for r in parsed:
    p = 1 if str(r["pred"].get("is_anomaly", "")).strip() == "이상" else 0
    g = r["gt_anomaly"]
    tp += p and g; fp += p and not g; fn += (not p) and g; tn += (not p) and (not g)
    if g:
        per_type[r["gt_type"]][1] += 1; per_type[r["gt_type"]][0] += p
        type_n += 1; type_ok += str(r["pred"].get("anomaly_type", "")).strip() == r["gt_type"]
prec = tp / (tp + fp) if tp + fp else 0; rec = tp / (tp + fn) if tp + fn else 0
f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
# 파싱 실패는 "틀림"으로 간주한 보수적 정확도도 같이
acc_parsed = (tp + tn) / len(parsed) if parsed else 0
acc_all = (tp + tn) / n

m = {"name": a.name, "model": MODEL, "frames": a.frames, "n": n,
     "parse_rate": len(parsed) / n, "acc_parsed": acc_parsed, "acc_all": acc_all,
     "precision": prec, "recall": rec, "f1": f1,
     "type_acc_on_anomaly": type_ok / type_n if type_n else 0,
     "recall_per_type": {k: v[0] / v[1] for k, v in sorted(per_type.items())},
     "runtime_s": time.time() - t0}
json.dump(m, open(OUT / f"{a.name}_metrics.json", "w"), indent=1, ensure_ascii=False)

print(f"\n== {a.name} ==")
print(f"파싱 성공률     {m['parse_rate']:.3f}")
print(f"이상여부 정확도 {acc_parsed:.3f} (파싱 성공분) / {acc_all:.3f} (실패=오답 포함)")
print(f"정밀도 {prec:.3f}  재현율 {rec:.3f}  F1 {f1:.3f}")
print(f"유형 정확도(이상 클립) {m['type_acc_on_anomaly']:.3f}")
print("유형별 이상 재현율:", {k: round(v, 2) for k, v in m["recall_per_type"].items()})
print(f"저장: {OUT}/{a.name}.jsonl, {OUT}/{a.name}_metrics.json")