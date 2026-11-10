"""
uca_segments.csv  →  (1) 구간 병합·선별  →  (2) 구간마다 프레임 8장 추출
                                              - change/ : 변화량 기반 선택 (메인)
                                              - uniform/: 균등 샘플링 (비교군 C용)
출력:
  clips/manifest.csv        한 줄 = 클립 하나 (라벨, split, 프레임 폴더 경로)
  clips/frames/<clip_id>/change/f0..f7.jpg
  clips/frames/<clip_id>/uniform/f0..f7.jpg

실행 위치: ~/Videos      python3 make_clips.py
필요: pip install opencv-python-headless numpy
"""
import csv, random, os, sys
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np, cv2

random.seed(0)
UCF = Path("UCF_Crime")
OUT = Path("clips"); FR = OUT / "frames"
N_FRAMES   = 8
MIN_LEN, MAX_LEN = 3.0, 60.0      # 3초 미만 버림, 60초 초과는 앞 60초만
NORMAL_PER_VIDEO = 4              # 정상 영상 1편당 최대 정상 클립 수
HARD_NEG_TRAIN   = 1000            # 이상 영상 속 정상 구간(hard negative) 수

# ---------------- 1. 구간 병합·선별 ----------------
rows = list(csv.DictReader(open("uca_segments.csv", encoding="utf-8")))
by_video = defaultdict(list)
for r in rows:
    if r["ucf_split"] == "none" or r["seg_is_anomaly"] == "": continue
    by_video[r["video"]].append(r)

def merge(segs):
    """겹치는 구간 합치기. 라벨은 하나라도 1이면 1, 문장은 이어붙임."""
    segs = sorted(segs, key=lambda r: float(r["start"]))
    out = []
    for r in segs:
        s, e, lab = float(r["start"]), float(r["end"]), int(r["seg_is_anomaly"])
        if out and s <= out[-1]["end"]:
            out[-1]["end"] = max(out[-1]["end"], e)
            out[-1]["label"] |= lab
            out[-1]["sentences"].append(r["sentence"])
        else:
            out.append({"start": s, "end": e, "label": lab, "sentences": [r["sentence"]]})
    return out

clips = []
for video, segs in by_video.items():
    meta = segs[0]
    for m in merge(segs):
        length = m["end"] - m["start"]
        if length < MIN_LEN: continue
        end = min(m["end"], m["start"] + MAX_LEN)
        clips.append({
            "video": video, "category": meta["category"], "split": meta["ucf_split"],
            "path": meta["path"], "start": round(m["start"], 1), "end": round(end, 1),
            "is_anomaly": m["label"],
            "anomaly_type": meta["category"] if m["label"] else "None",
            "sentences": " || ".join(m["sentences"]),
        })

# 선별: 이상 구간 전부 / 정상 영상은 편당 N개 / 이상 영상 속 정상 구간은 train에서 일부
anom      = [c for c in clips if c["is_anomaly"] == 1]
norm_vid  = defaultdict(list); hard_neg = []
for c in clips:
    if c["is_anomaly"] == 0:
        (norm_vid[c["video"]] if c["category"] == "Normal" else hard_neg).append(c)
normals = []
for v, cs in norm_vid.items():
    normals += random.sample(cs, min(NORMAL_PER_VIDEO, len(cs)))
hn_train = [c for c in hard_neg if c["split"] == "train"]
hn_test  = [c for c in hard_neg if c["split"] == "test"]
selected = anom + normals + random.sample(hn_train, min(HARD_NEG_TRAIN, len(hn_train))) + hn_test
for c in selected:
    c["clip_id"] = f'{c["video"]}_{int(c["start"]*10):06d}'

from collections import Counter
print(f"병합 후 구간 {len(clips)} → 선별 {len(selected)}")
for sp in ("train", "test"):
    cc = Counter(c["is_anomaly"] for c in selected if c["split"] == sp)
    print(f"  {sp}: 이상 {cc[1]}  정상 {cc[0]}")
print("  유형별 이상(train):", dict(Counter(c["category"] for c in anom if c["split"] == "train")))

# ---------------- 2. 프레임 추출 ----------------
def extract(c):
    cap = cv2.VideoCapture(str(UCF / c["path"]))
    if not cap.isOpened(): return c["clip_id"], "open_fail"
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    f0, f1 = int(c["start"] * fps), int(c["end"] * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    frames, scores, prev = [], [], None
    for _ in range(f1 - f0):
        ok, fr = cap.read()
        if not ok: break
        g = cv2.cvtColor(cv2.resize(fr, (160, 120)), cv2.COLOR_BGR2GRAY)
        scores.append(0.0 if prev is None else float(np.mean(cv2.absdiff(g, prev))))
        prev = g; frames.append(fr)
    cap.release()
    n = len(frames)
    if n < N_FRAMES: return c["clip_id"], f"too_short({n})"
    bins = np.array_split(np.arange(n), N_FRAMES)
    change  = [int(b[np.argmax(np.array(scores)[b])]) for b in bins]   # 빈마다 변화 최대 프레임
    uniform = [int(b[len(b) // 2]) for b in bins]                      # 빈 중앙 프레임
    for name, idxs in (("change", change), ("uniform", uniform)):
        d = FR / c["clip_id"] / name; d.mkdir(parents=True, exist_ok=True)
        for k, i in enumerate(idxs):
            cv2.imwrite(str(d / f"f{k}.jpg"), frames[i], [cv2.IMWRITE_JPEG_QUALITY, 90])
    return c["clip_id"], "ok"

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    status = {}
    with ProcessPoolExecutor(max_workers=max(4, os.cpu_count() - 2)) as ex:
        futs = [ex.submit(extract, c) for c in selected]
        for i, f in enumerate(as_completed(futs), 1):
            cid, st = f.result(); status[cid] = st
            if i % 500 == 0: print(f"  {i}/{len(selected)}")
    ok = [c for c in selected if status[c["clip_id"]] == "ok"]
    bad = Counter(v for v in status.values() if v != "ok")
    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        fields = ["clip_id", "video", "category", "split", "start", "end", "is_anomaly", "anomaly_type", "sentences"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(ok)
    print(f"\n완료: {len(ok)} 클립 / 실패 {dict(bad)}")
    print(f"저장: {OUT/'manifest.csv'}, 프레임: {FR}/")