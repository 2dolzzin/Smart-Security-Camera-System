"""
clips/manifest.csv 의 각 클립에 대해 teacher(Qwen3-VL-32B, vLLM :8001)로 로그 생성.
 - teacher 는 scene / objects / action / summary 만 작성
 - is_anomaly / anomaly_type 은 manifest 라벨을 코드로 삽입 (teacher 판정 금지)
 - 입력: change/ 프레임 8장 + UCA 문장(참고용) 
출력: clips/teacher_logs.jsonl  (한 줄 = 클립 하나, 최종 학습 target 포함)

사용:  python3 teacher_logs.py --n 300          # 파일럿 (무작위 300개, 이상/정상 반반)
       python3 teacher_logs.py                  # 전체 (이미 처리된 clip_id 는 건너뜀)
"""
import csv, json, base64, random, time, argparse, re, requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

URL, MODEL = "http://localhost:8001/v1/chat/completions", "Qwen/Qwen3-VL-32B-Instruct"
FR, OUT = Path("clips/frames"), Path("clips/teacher_logs.jsonl")
WORKERS = 8

SYSTEM = """당신은 CCTV 영상 로그를 작성하는 기록관이다. 프레임 8장(시간순)과, 같은 구간을 사람이 영어로 묘사한 참고 문장이 주어진다.
규칙:
1. 화면에 보이는 것만 쓴다. 참고 문장은 사람 수·복장·동작을 확인하는 데만 쓰고, 프레임에 없는 내용은 쓰지 않는다.
2. 의도·감정·원인을 추측하지 않는다. "훔치려고", "화가 나서", "수상하게" 같은 표현 금지. 보이는 동작만 쓴다.
3. 외모 평가(뚱뚱한, 예쁜 등)와 인종 표현은 쓰지 않는다. 복장·색·소지품만 쓴다.
4. 아래 JSON 형식 한 덩어리만 출력한다. 설명·마크다운·코드블록 금지.
{"scene": "장소 유형 1~3단어 또는 '확인 불가'",
 "objects": [{"type": "사람|차량|동물|물건", "count": 정수, "appearance": "15자 이내"}],
 "action": "관찰 가능한 동작 1문장, 60자 이내",
 "summary": "1문장 40자 이내"}"""

def img_b64(p):
    return "data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode()

def ask(c):
    frames = sorted((FR / c["clip_id"] / "change").glob("f*.jpg"))
    content = [{"type": "image_url", "image_url": {"url": img_b64(p)}} for p in frames]
    content.append({"type": "text", "text": f"참고 문장(영어): {c['sentences'][:800]}\n\n위 8장의 프레임을 보고 JSON 로그를 작성하라."})
    body = {"model": MODEL, "max_tokens": 400, "temperature": 0.2,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]}
    for attempt in range(2):
        try:
            r = requests.post(URL, json=body, timeout=180); r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", txt, re.S)
            d = json.loads(m.group(0))
            assert all(k in d for k in ("scene", "objects", "action", "summary"))
            return d, txt
        except Exception as e:
            err = str(e)
    return None, err

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=0); a = ap.parse_args()
    rows = list(csv.DictReader(open("clips/manifest.csv", encoding="utf-8")))
    done = {json.loads(l)["clip_id"] for l in open(OUT, encoding="utf-8")} if OUT.exists() else set()
    todo = [r for r in rows if r["clip_id"] not in done]
    if a.n:
        random.seed(0)
        tr = [r for r in todo if r["split"] == "train"]
        A = [r for r in tr if r["is_anomaly"] == "1"]; N = [r for r in tr if r["is_anomaly"] == "0"]
        todo = random.sample(A, a.n // 2) + random.sample(N, a.n // 2)
    print(f"대상 {len(todo)}개 (기존 완료 {len(done)})")

    ok = fail = 0; t0 = time.time()
    with open(OUT, "a", encoding="utf-8") as f, ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(ask, c): c for c in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            c = futs[fu]; d, raw = fu.result()
            if d is None:
                fail += 1; print(f"  [실패] {c['clip_id']}: {raw[:80]}"); continue
            rec = {"clip_id": c["clip_id"], "video": c["video"], "split": c["split"],
                   "start": c["start"], "end": c["end"],
                   "target": {"scene": d["scene"], "objects": d["objects"], "action": d["action"],
                              "is_anomaly": "이상" if c["is_anomaly"] == "1" else "정상",
                              "anomaly_type": c["anomaly_type"], "summary": d["summary"]},
                   "uca_sentences": c["sentences"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush(); ok += 1
            if i % 50 == 0: print(f"  {i}/{len(todo)}  성공 {ok} 실패 {fail}  {time.time()-t0:.0f}s")
    print(f"\n완료: 성공 {ok} 실패 {fail}  {time.time()-t0:.0f}s  → {OUT}")