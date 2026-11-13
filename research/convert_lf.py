"""
clips/teacher_logs.jsonl  →  LLaMA-Factory 학습 데이터
  lf/data/cctv_train.json, cctv_val.json  (train 영상의 10%를 영상 단위로 val)
  lf/data/cctv_test.json                  (UCF 공식 test, 평가 전용)
  lf/data/dataset_info.json

실행 위치: 데이터 루트      python3 convert_lf.py
"""
import json, random
from pathlib import Path
from collections import defaultdict, Counter

random.seed(0)
ROOT = Path.cwd()
FR   = ROOT / "clips/frames"
OUT  = ROOT / "lf/data"; OUT.mkdir(parents=True, exist_ok=True)

INSTRUCTION = """다음은 CCTV 영상에서 시간순으로 추출한 프레임 8장이다. 아래 JSON 형식으로 로그를 작성하라. 화면에 보이는 것만 기술하고, 의도나 감정은 추측하지 않는다.
{"scene": 장소 유형, "objects": [{"type": "사람|차량|동물|물건", "count": 정수, "appearance": 외형}], "action": 관찰 가능한 동작 1문장, "is_anomaly": "정상|이상", "anomaly_type": "Abuse|Arrest|Arson|Assault|Burglary|Explosion|Fighting|RoadAccidents|Robbery|Shooting|Shoplifting|Stealing|Vandalism|None", "summary": 1문장 요약}"""

recs = [json.loads(l) for l in open(ROOT / "clips/teacher_logs.jsonl", encoding="utf-8")]

def to_sample(r, frame_set="change"):
    imgs = [str(FR / r["clip_id"] / frame_set / f"f{k}.jpg") for k in range(8)]
    return {
        "messages": [
            {"role": "user", "content": "<image>" * 8 + "\n" + INSTRUCTION},
            {"role": "assistant", "content": json.dumps(r["target"], ensure_ascii=False)},
        ],
        "images": imgs,
    }

# 영상 단위 train / val 분리
train_videos = sorted({r["video"] for r in recs if r["split"] == "train"})
random.shuffle(train_videos)
n_val = len(train_videos) // 10
val_videos = set(train_videos[:n_val])

splits = defaultdict(list)
for r in recs:
    if r["split"] == "test":
        splits["test"].append(r)
    elif r["video"] in val_videos:
        splits["val"].append(r)
    else:
        splits["train"].append(r)

for name, rs in splits.items():
    json.dump([to_sample(r) for r in rs], open(OUT / f"cctv_{name}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # 비교군 C(균등 샘플링)용 test 도 만들어 둠
    if name == "test":
        json.dump([to_sample(r, "uniform") for r in rs], open(OUT / "cctv_test_uniform.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    c = Counter(r["target"]["is_anomaly"] for r in rs)
    print(f"{name:5s} {len(rs):5d}개  이상 {c['이상']:4d}  정상 {c['정상']:4d}  영상 {len({r['video'] for r in rs})}")

def entry(fn):
    return {"file_name": fn, "formatting": "sharegpt",
            "columns": {"messages": "messages", "images": "images"},
            "tags": {"role_tag": "role", "content_tag": "content", "user_tag": "user", "assistant_tag": "assistant"}}

json.dump({"cctv_train": entry("cctv_train.json"), "cctv_val": entry("cctv_val.json"),
           "cctv_test": entry("cctv_test.json"), "cctv_test_uniform": entry("cctv_test_uniform.json")},
          open(OUT / "dataset_info.json", "w"), indent=1)
print(f"\n저장: {OUT}/")