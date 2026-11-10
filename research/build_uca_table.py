"""
UCA(UCF-Crime Annotation) JSON 3개 + UCF-Crime 공식 split 목록을 합쳐
구간 단위 표(CSV)를 만든다.

실행 위치: ~/Videos  (UCF_Crime/ 과 Surveillance-Video-Understanding/ 가 있는 곳)
    python3 build_uca_table.py

출력: uca_segments.csv  (한 줄 = UCA 구간 하나)
"""
import json, re, csv
from pathlib import Path
from collections import Counter, defaultdict

UCA_DIR = Path("Surveillance-Video-Understanding/UCF Annotation/json")
UCF_DIR = Path("UCF_Crime")
OUT = Path("uca_segments.csv")

# ---------- 1. UCF-Crime 공식 split: 영상명 -> (split, 상대경로) ----------
split_of, path_of = {}, {}
for split in ("Train", "Test"):
    for line in (UCF_DIR / "Anomaly_Detection_splits" / f"Anomaly_{split}.txt").read_text().split():
        name = Path(line).stem                     # Abuse/Abuse001_x264.mp4 -> Abuse001_x264
        split_of[name] = split.lower()
        path_of[name] = line

# ---------- 2. UCA JSON 3개 합치기 ----------
uca = {}
uca_split_of = {}
for s in ("Train", "Val", "Test"):
    d = json.load(open(UCA_DIR / f"UCFCrime_{s}.json"))
    for k, v in d.items():
        if k in uca:
            print(f"[경고] UCA split 간 중복 키: {k}")
        uca[k] = v
        uca_split_of[k] = s.lower()

def category(name: str) -> str:
    """Abuse001_x264 -> Abuse, Normal_Videos001_x264 -> Normal"""
    if name.startswith("Normal"):
        return "Normal"
    return re.match(r"^([A-Za-z]+)", name).group(1)

# ---------- 3. 구간 단위로 펼치기 ----------
rows = []
for name, v in uca.items():
    cat = category(name)
    for i, ((st, en), sent) in enumerate(zip(v["timestamps"], v["sentences"])):
        rows.append({
            "video": name,
            "category": cat,
            "video_is_anomaly": 0 if cat == "Normal" else 1,
            "ucf_split": split_of.get(name, "none"),
            "uca_split": uca_split_of[name],
            "path": path_of.get(name, ""),
            "duration": v["duration"],
            "seg_idx": i,
            "start": st,
            "end": en,
            "seg_len": round(en - st, 2),
            "sentence": sent.strip(),
            "seg_is_anomaly": "",          # 다음 단계(문장 분류)에서 채움
        })

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)

# ---------- 4. 통계 ----------
vids = set(uca)
print(f"UCA 영상 수: {len(vids)}  /  구간 수: {len(rows)}")
print(f"UCF split에 없는 UCA 영상: {sum(1 for v in vids if v not in split_of)}")
print(f"UCA에 없는 UCF 영상: {sum(1 for v in split_of if v not in vids)}")
print()
print("유형별 영상 수 / 구간 수 (UCF train 기준):")
vc, sc = Counter(), Counter()
for r in rows:
    if r["ucf_split"] == "train":
        sc[r["category"]] += 1
for v in vids:
    if split_of.get(v) == "train":
        vc[category(v)] += 1
for c in sorted(vc):
    print(f"  {c:14s} 영상 {vc[c]:4d}  구간 {sc[c]:5d}  구간/영상 {sc[c]/vc[c]:.1f}")
print()
lens = [r["seg_len"] for r in rows]
print(f"구간 길이(초): 평균 {sum(lens)/len(lens):.1f}, 10초 이상 {sum(l>=10 for l in lens)}, 3초 미만 {sum(l<3 for l in lens)}")
print(f"저장: {OUT.resolve()}")