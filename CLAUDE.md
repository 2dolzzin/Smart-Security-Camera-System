# CCTV VLM 졸업작품 — 작업 기록 및 인계 문서

> 작성일: 2026-11-10. 서버 `hail-pro6000`에서 진행. 이 문서는 Claude Code 세션의 컨텍스트용이다.
> **연구 파트(데이터 → LoRA → 평가) 완료. 4단계 시스템 통합(6.1 서버 어댑터 + 6.2~6.4 클라이언트)도 코드·API 테스트까지 완료(2026-11-10, 서버에서). 남은 것: 노트북에서 실제 카메라로 UI 확인(6.6), 데모·보고서(5단계).**
> 이 파일은 서버 `~/Videos/CLAUDE.md`이고, 리포 루트 `CLAUDE.md`에 복사본을 커밋한다(노트북에서 Claude Code가 읽도록). 둘 중 하나 고치면 다른 쪽도 맞출 것.

---

## 0. 프로젝트 한 줄 요약

캡스톤 때 만든 지능형 CCTV 시스템(https://github.com/2dolzzin/Smart-Security-Camera-System)을 이어서,
VLM이 "한 문장 설명" 대신 **구조화된 한국어 JSON 로그**(장소·객체·행동·이상여부·이상유형·요약)를 출력하도록
Qwen3-VL-8B를 LoRA로 학습시킨 것. 학습 데이터는 UCF-Crime 영상 + UCA 주석에서 만들었고,
teacher(Qwen3-VL-32B)가 로그 본문을 쓰고 이상여부·유형은 데이터셋 라벨에서 코드로 삽입했다.

졸업작품이며 캡스톤의 연장이다. 연구 신규성은 주장하지 않는다. 심사용 메시지는
"LoRA로 스키마·유형 목록 준수와 재현율을 올렸고, 오탐의 출처와 한계를 분석했다".

---

## 1. 확정된 설계 결정 (바꾸지 말 것)

| 항목 | 결정 | 이유 |
|---|---|---|
| 베이스 모델 | `Qwen/Qwen3-VL-8B-Instruct` | 3×96GB GPU, 한국어 스키마 출력 안정성 |
| 학습 방식 | LoRA r=32, LLM만 학습, 비전 인코더·프로젝터 고정 | 5천 샘플 규모, 배우는 건 "본 것을 스키마로 쓰는 법" |
| 입력 | 클립당 프레임 **8장** | 구간 길이 무관하게 입력 크기 고정 |
| 프레임 선택 | 구간을 8등분, 각 등분에서 **프레임 차분이 최대인 1장** (="change") | 변화량 기준이면서 시간축을 고르게 덮음. 균등 샘플링("uniform")과 비교 결과 차이 없음 |
| 이상 판정 | VLM 출력 필드 `is_anomaly`/`anomaly_type`로 흡수 | 별도 모듈 없이 로그와 판정을 한 번에 |
| teacher 역할 | scene/objects/action/summary만 작성. **is_anomaly, anomaly_type은 라벨에서 코드로 삽입** | teacher 환각이 판정 라벨에 섞이는 것 방지 |
| 구간 라벨 정책 | 사건 자체 + 직후 결과(쓰러진 사람, 타는 불 등) = 이상. 사건 전 평범한 장면, 경찰 사후 도착, 흩어지는 사람들 = 정상 | CCTV 로그 용도에선 결과 장면도 표시 대상 |
| 최종 모델 | **B = 1차 학습 모델** (`lf/models/qwen3vl8b-cctv`) | 재현율 0.674 > B2 0.576. CCTV 용도에선 놓치는 게 오탐보다 비쌈 |
| split | UCF-Crime 공식 Anomaly_Train/Test. val은 train 영상의 10%를 **영상 단위**로 분리 | 같은 영상의 클립이 train/val에 갈리면 수치 왜곡 |
| 추론 창 길이 | **20초** (어댑터 `WINDOW_SEC`, 요청별 `window_sec`로 덮어쓰기 가능) | 학습 클립 평균 17초. 60초 창은 Robbery050·Fighting003·Shoplifting001 전부 정상으로 놓쳤고 20초 창은 전부 검출, 정상 2편 17창 오탐 0 (6.1 참고) |

### 출력 스키마 (v1, 길이 한도는 상향 조정됨)
```json
{"scene": "장소 유형 1~3단어 | 확인 불가",
 "objects": [{"type": "사람|차량|동물|물건", "count": 정수, "appearance": "15자 이내"}],
 "action": "관찰 가능한 동작 1문장 (~80자)",
 "is_anomaly": "정상|이상",
 "anomaly_type": "Abuse|Arrest|Arson|Assault|Burglary|Explosion|Fighting|RoadAccidents|Robbery|Shooting|Shoplifting|Stealing|Vandalism|None",
 "summary": "1문장 (~60자)"}
```
- 금지 표현: 의도·감정 추측("수상한", "훔치려고"), 외모 평가("뚱뚱한"), 인종 표현. teacher 출력에서 300개 중 2개 검출 → 허용 수준.
- 열거형 값은 영어(UCF 폴더명과 일치). UI에서만 한국어로 표시.

---

## 2. 환경

### 하드웨어
- GPU 3장: `NVIDIA RTX PRO 6000 Blackwell Max-Q`, 각 96 GB (index 0, 1, 2). compute capability (12,0).
- 디스크 `/dev/nvme0n1p2` 7.3 TB, 약 827 GB 여유 (2026-11-10 기준).

### conda 환경 (반드시 구분해서 쓸 것)
| env | python | 핵심 패키지 | 용도 | 주의 |
|---|---|---|---|---|
| `base` (anaconda3) | 3.13 | torch 2.13+cu130, vllm(깨짐) | **다른 프로젝트용. 건드리지 말 것** | `vllm` import 시 `_C.abi3.so undefined symbol` 에러 — 고치지 말 것 |
| `cctv` | 3.12 | vllm 0.33.0, torch 2.14+cu130, transformers 5.20, fastapi, uvicorn, python-multipart, requests, opencv-python-headless, numpy, huggingface_hub[cli] | 추론·서빙·데이터 스크립트·**어댑터 서버** | 한 번 llamafactory가 잘못 설치돼 transformers가 5.6으로 내려간 적 있음 → `pip uninstall llamafactory; pip install --force-reinstall --no-deps vllm==0.33.0; pip install vllm==0.33.0`로 복구함. **이 env에 llamafactory·sentence-transformers 설치 금지** |
| `train` | 3.12 | llamafactory 0.9.5, transformers 5.6.0, torch 2.15+cu132 | LoRA 학습·병합 | |

### tmux
세션 `vlm`: 창 0 `work`(작업), 창 1 `server`(vLLM 서버 :8002), 창 2 `bash`, 창 3 `adapter`(어댑터 :8010). prefix는 `Ctrl+B` 뗀 뒤 키.
서버는 반드시 tmux 안에서 띄운다.

### HuggingFace 캐시 (`~/.cache/huggingface/hub/`)
`Qwen/Qwen3-8B`, `Qwen/Qwen3-VL-32B-Instruct`, `Qwen/Qwen3-VL-8B-Instruct`, `BAAI/bge-m3`(어댑터 임베딩용, `pytorch_model.bin`만 존재 — safetensors 없음).
(그 외 `LaRA-VLA-libero`, `clip-vit-large-patch14-336`, `embodied_features_bridge`는 다른 프로젝트 것 — 건드리지 말 것)

### vLLM 서버 명령 (env `cctv`)
```bash
# 최종 모델 B (4단계 통합에 쓰는 것)
CUDA_VISIBLE_DEVICES=1 vllm serve ~/Videos/lf/models/qwen3vl8b-cctv --port 8002 --max-model-len 8192 --limit-mm-per-prompt '{"image":8}' --gpu-memory-utilization 0.8
# teacher (데이터 추가 생성할 때만)
CUDA_VISIBLE_DEVICES=1 vllm serve Qwen/Qwen3-VL-32B-Instruct --port 8001 --max-model-len 16384 --limit-mm-per-prompt '{"image":8}' --gpu-memory-utilization 0.9
# 텍스트 분류기 (UCA 구간 라벨링할 때만)
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen3-8B --port 8000 --max-model-len 4096 --gpu-memory-utilization 0.5
# 어댑터 (4단계, vLLM B가 떠 있어야 함; bge-m3를 같은 GPU 1에 올림 ~1.2 GB)
cd ~/Smart-Security-Camera-System/server && CUDA_VISIBLE_DEVICES=1 uvicorn app:app --host 0.0.0.0 --port 8010
```
`CUDA_VISIBLE_DEVICES`는 명령과 **같은 줄**에. 띄우기 전 `nvidia-smi`로 빈 GPU 확인 (유령 서버가 남아 있던 적 있음).

---

## 3. 데이터 — 파일 구조와 생성 경로

### 3.1 원본
```
~/Videos/UCF_Crime/                      # 1,900편, 약 28 GB (320x240 저해상도)
  Abuse/ Arrest/ Arson/ Assault/ Burglary/ Explosion/ Fighting/
  RoadAccidents/ Robbery/ Shooting/ Shoplifting/ Stealing/ Vandalism/   # 이상 950편
  Training_Normal_Videos_Anomaly/        # 정상 800편
  Testing_Normal_Videos_Anomaly/         # 정상 150편
  Anomaly_Detection_splits/
    Anomaly_Train.txt                    # 1,610줄 (배포본은 0바이트라 Dropbox의 교정본으로 덮어씀)
    Anomaly_Test.txt                     # 290줄
  Action_Regnition_splits/               # 미사용 (원본 오타 그대로)
~/Videos/UCF_Crime_raw/                  # zip 원본 (삭제 가능), Anomaly_Train.txt 교정본
~/Videos/Surveillance-Video-Understanding/   # UCA 리포 (git clone)
  UCF Annotation/json/UCFCrime_{Train,Val,Test}.json   # 사용
  UCF Annotation/json/revised_en_UCFCrime_Train.json   # 0바이트, 미사용
  UCF Annotation/txt*, Experimental Files/              # 미사용
```
- UCA JSON: 키 = UCF 파일명(확장자 없음, 예 `Robbery050_x264`), 값 = `{duration, timestamps[[s,e],...], sentences[...]}`, 단위 초.
- UCA 1,854편 / 23,542 구간. UCF 1,900편 중 46편은 UCA 주석 없음(저품질로 제외됨).
- **UCA 구간은 "이상 구간"이 아니라 "뭐든 일어난 구간"** — 이상 영상 안에도 정상 구간 다수. 그래서 3.3의 문장 분류가 필요했다.
- UCA의 Train/Val/Test 분할은 UCF 공식 분할과 다르다. UCA는 주석 사전으로만 쓰고 split은 UCF를 따른다.
- 테스트 영상의 프레임 단위 시간 주석(Temporal Annotation for Testing Videos)은 **아직 안 받음**. 공식 페이지(crcv.ucf.edu/projects/real-world)에 별도 링크. 프레임 AUC 계산하려면 필요하나 현재 평가는 클립 단위라 미사용.

### 3.2 `build_uca_table.py` → `uca_segments.csv`
UCA 3개 JSON 합치기 + 영상명에서 유형 추출 + UCF split·경로 붙이기. 구간 단위 한 줄.
열: video, category, video_is_anomaly, ucf_split, uca_split, path, duration, seg_idx, start, end, seg_len, sentence, seg_is_anomaly(빈칸→3.3에서 채움), seg_label_raw.
- 구간 길이 평균 16.9초, 10초 이상 13,098개, 3초 미만 1,768개.
- **CSV를 `cut -d,`로 자르면 안 됨** — sentence에 쉼표 있음. python csv 모듈 사용.

### 3.3 `classify_segments.py` → `uca_segments.csv`의 `seg_is_anomaly` 채움
- 정상 영상 구간은 전부 0. 이상 영상 구간 8,347개만 Qwen3-8B(텍스트, thinking off)에 "이 문장이 [유형] 사건 자체인가, 전후의 평범한 장면인가"를 물어 anomaly/normal.
- 33초 소요, 파싱 실패 0. 유형별 이상 비율 0.20(Explosion/Stealing)~0.51(Assault/Robbery).
- 검수: `review_sample.csv`(312개, 유형별 24개) — **사용자 검수는 안 함**. Claude가 읽은 2차 의견이 `review_sample_claude.csv`(동의 269 / 애매 36 / 불일치 7). 불일치 패턴: (a) 같은 영상의 앞 구간 맥락을 알아야 판정 가능한 경우(예: 앞에서 키 꽂던 오토바이를 끌고 감), (b) 범행이 평범한 단어로 쓰인 경우(캐비닛을 뒤짐, 전단지를 붙임). Burglary·Stealing·Shoplifting에 애매가 몰림.
- 개선 여지(안 함): 영상 하나의 문장 전부를 순서대로 주고 한 번에 라벨링하면 (a)가 해결됨. 사용자가 "빠르게 진행"을 택해 현재 라벨로 진행.

### 3.4 `make_clips.py` → `clips/manifest.csv`, `clips/frames/<clip_id>/{change,uniform}/f0..f7.jpg`
- 겹치는 구간 병합(하나라도 1이면 1, 문장 ` || `로 연결). 3초 미만 버림, 60초 초과는 앞 60초만.
- 선별: 이상 구간 전부 + 정상 영상 편당 최대 4개 + 이상 영상 속 정상 구간(hard negative). `HARD_NEG_TRAIN`은 **1차 600 → 2차 10000(=전부, 실제 약 1,000개)**. 현재 파일은 10000 상태.
- 프레임: OpenCV로 구간 디코드 → 160×120 그레이 absdiff → 8등분 각 빈의 최대 변화 프레임(change) / 빈 중앙(uniform) → JPEG q90.
- clip_id = `{video}_{int(start*10):06d}`.
- **현재 manifest: 5,405 클립** (train 이상 1,696 / 정상 2,911, test 이상 231 / 정상 567). 1차 때는 5,005였음.
- 영상 클립 mp4는 만들지 않는다(프레임만). UI 데모용 클립은 필요할 때 자른다.

### 3.5 `teacher_logs.py` → `clips/teacher_logs.jsonl` (5,405줄)
- Qwen3-VL-32B-Instruct(vLLM :8001)에 change 프레임 8장 + 해당 구간 UCA 영어 문장(참고용) → scene/objects/action/summary JSON. is_anomaly/anomaly_type은 manifest에서 삽입.
- 이미 있는 clip_id는 건너뜀(재실행 안전). `--n 300`은 파일럿 모드.
- 5,004개 92분, 추가 401개 8분. 실패 1개.
- 한 줄 형식: `{clip_id, video, split, start, end, target:{scene,objects,action,is_anomaly,anomaly_type,summary}, uca_sentences}`.
- 길이 통계(300개 파일럿): action 60자 초과 23%, summary 40자 초과 41% → 한도를 80/60으로 상향 조정하고 재생성 안 함(teacher 프롬프트는 전체 5,405개에 동일하게 적용되어 분포 일관).

### 3.6 `convert_lf.py` → `lf/data/`
- `cctv_train.json`(4,154) / `cctv_val.json`(453, train 영상의 10%를 영상 단위로) / `cctv_test.json`(798) / `cctv_test_uniform.json`(798, uniform 프레임) / `dataset_info.json`.
- LLaMA-Factory sharegpt 멀티모달 형식: user = `<image>`×8 + INSTRUCTION, assistant = target JSON 문자열, images = 절대경로 8개.
- INSTRUCTION 전문은 `convert_lf.py`, `eval_test.py`, 그리고 어댑터 `~/Smart-Security-Camera-System/server/app.py`에 동일하게 있음. **추론 시에도 이 INSTRUCTION을 그대로 써야 한다** (학습 프롬프트와 동일해야 함).
- 1차 학습 데이터는 3,776 / 430 / 798이었음(hard neg 600일 때).

---

## 4. 학습

### 설정 `lf/train_lora.yaml`
Qwen3-VL-8B-Instruct, template `qwen3_vl`, LoRA r32 α64 dropout0.05 target all, `freeze_vision_tower: true`, `freeze_multi_modal_projector: true`,
cutoff_len 6144, image_max_pixels 262144, bs 4 × grad_accum 4 (=16), lr 1e-4, 3 epoch, cosine, warmup 0.05, bf16, eval every 200 step.
현재 파일의 `output_dir`은 `saves/qwen3vl8b-lora-r32-hn`(2차). 1차는 `saves/qwen3vl8b-lora-r32`.

### 실행
```bash
conda activate train; cd ~/Videos/lf
CUDA_VISIBLE_DEVICES=<빈GPU> llamafactory-cli train train_lora.yaml
```

### 결과
| | 데이터 | train_loss | eval_loss | 시간 | 어댑터 | 병합 모델 |
|---|---|---|---|---|---|---|
| 1차 (B) | 3,776 / 430 | 0.338 | 0.3655 | 84분 | `saves/qwen3vl8b-lora-r32` | `models/qwen3vl8b-cctv` **← 최종** |
| 2차 (B2) | 4,154 / 453 | – | 0.3596 | ~95분 | `saves/qwen3vl8b-lora-r32-hn` | `models/qwen3vl8b-cctv-hn` |

loss는 1·2차 차이 없음. loss 토큰 대부분이 묘사 필드라 판정 성능은 loss로 안 보인다.

### 병합 `lf/merge_lora.yaml`
`llamafactory-cli export merge_lora.yaml`. 현재 파일은 `-hn` 경로로 설정돼 있음. B를 다시 병합할 일은 없음(이미 있음).

---

## 5. 평가 — `eval_test.py` → `eval/`

```bash
conda activate cctv; cd ~/Videos
python3 eval_test.py --name <이름> --port <서버포트> --frames change|uniform
```
test 798 클립에 로그 생성 → `eval/<이름>.jsonl`(클립별 예측·raw), `eval/<이름>_metrics.json`.
지표: 파싱 성공률, is_anomaly 정확도/정밀도/재현율/F1, anomaly_type 정확도(이상 클립 한정), 유형별 재현율.

### 비교군
- **A** `A_base_change`: 베이스 Qwen3-VL-8B + 같은 INSTRUCTION 프롬프트, change 프레임
- **B** `B_lora_change`: 1차 LoRA, change 프레임 **← 최종 모델**
- **C** `C_lora_uniform`: B와 같은 모델, uniform 프레임 (샘플링 비교용)
- **B2** `B2_lora_hn`: 2차 LoRA(hard neg 증량), change 프레임

### 결과 (test 798: 이상 231 / 정상 567)
| | 파싱 | 정확도 | 정밀도 | 재현율 | F1 | 유형 정확도 |
|---|---|---|---|---|---|---|
| A 베이스 | 0.932 | 0.713 | 0.610 | 0.516 | 0.559 | 0.177 |
| **B LoRA** | 0.999 | 0.736 | 0.534 | **0.674** | **0.596** | 0.274 |
| C LoRA+균등 | 1.000 | 0.738 | 0.540 | 0.645 | 0.588 | 0.277 |
| B2 LoRA+hardneg↑ | 0.999 | 0.751 | 0.571 | 0.576 | 0.573 | 0.260 |

### 오탐 분해 (정상 클립을 이상으로 찍은 비율)
| | Normal 영상 클립 (n≈313) | 이상 영상 속 정상 클립 (n≈254) |
|---|---|---|
| A | 0.03 | 0.26 |
| B | 0.06 | **0.46** |
| C | 0.05 | 0.44 |
| B2 | (미산출 — 아래 명령으로 계산 필요) | |

### 결론 (보고서에 쓸 것)
1. LoRA → 스키마 파싱 0.93→1.00, 유형 열거형 준수(A는 `Fire` 같은 목록 외 값 출력), 유형 정확도 0.18→0.27.
2. 재현율 0.52→0.67. 단 정밀도는 0.61→0.53으로 하락.
3. 오탐은 거의 전부 **사건 영상 속 정상 구간**(강도 직전 편의점 등)에서 발생. 순수 정상 영상 오탐 6%. → 모델이 행동보다 **장면 맥락**에 의존하는 비중이 큼.
4. hard negative 증량(B2) → 정밀도↑ 재현율↓, F1 소폭↓. 판별력이 아니라 판정 문턱이 이동. 용도상 재현율 우선이므로 B 채택.
5. 프레임 샘플링(변화량 vs 균등) → 차이 없음(노이즈 범위).
6. 유형 혼동은 의미 인접 쌍에 집중: Shoplifting→Robbery, Explosion→Arson, Burglary→Robbery, Shooting→Assault. 소수 유형(Explosion 37, Shooting 39, Vandalism 57 train 클립)은 데이터 한계.
7. A의 낮은 오탐(0.26)은 과소 판정의 결과(이상 클립도 None으로 많이 찍음).
8. (통합 단계에서 발견, 보고서 "한계"에 쓸 것) **창 길이 민감도**: 같은 영상을 60초 창으로 넣으면 사건이 묻혀 정상으로 판정, 20초 창이면 검출. 학습 클립 길이 분포(평균 17초) 밖으로 나가면 성능이 떨어진다. 6.1 참고.

### 미완 평가 작업
- B2 오탐 분해: 기존 분해 스니펫(`eval/*.jsonl` 읽어 video명이 `Normal`로 시작하는지로 출처 구분)의 이름 리스트에 `'B2_lora_hn'` 추가해서 실행.
- (선택) 로그 품질 평가: UCA 캡션 대비 BERTScore 또는 32B를 심판으로 한 LLM-judge 100개. 안 해도 됨.
- (선택) 프레임 AUC: 테스트 시간 주석을 받아 클립 점수를 프레임에 펼치면 기존 논문과 비교 가능. 안 해도 됨.

---

## 6. 남은 일 — 4단계 시스템 통합

대상 리포: https://github.com/2dolzzin/Smart-Security-Camera-System.
구조: `client/backend`(FastAPI: 움직임 감지·세션 녹화·360p/4fps 전처리·`ai_describer.py`가 `POST {VLM_SERVER_URL}/describe`로 mp4 업로드·SQLite `motion_logs.description`), `client/frontend`(React: /live /playback /logs /settings), `server/app.py`(원래 AWS A10G에 Qwen2.5-VL-3B transformers 서버 → **어댑터로 교체 완료**).

### 6.0 배치 원칙 — 서버와 클라이언트는 **분리**한다 (캡스톤 설계 유지)

| 위치 | 돌아가는 것 | 포트 |
|---|---|---|
| **서버 `hail-pro6000`** (GPU) | vLLM B 모델 | 8002 (서버 내부 전용, 외부 노출 안 함) |
| | 어댑터 `server/app.py` — `/describe`, `/embed`, `/health` | **8010** (8001은 teacher와 겹치므로 피함) |
| **클라이언트 노트북/데모 PC** (카메라) | `client/backend` (FastAPI) | 8800 |
| | `client/frontend` (React/Vite) | 5173 |

- GPU가 필요한 것(VLM 추론, bge-m3 임베딩)은 전부 서버. 클라이언트는 카메라·감지·녹화·DB·UI만.
- 리포는 **양쪽에 clone**: 서버에는 `server/`만 필요(`~/Smart-Security-Camera-System`, clone 완료), 노트북에는 `client/`.
- AWS는 더 이상 쓰지 않는다. README의 AWS 부분은 네트워크 절로 교체함.

**네트워크 (노트북 → 서버 8010)**
1. 같은 LAN이면 서버 내부 IP로 직접: `VLM_SERVER_URL=http://<서버IP>:8010`. 서버 IP는 `ip addr`로 확인 (2026-11-10: `172.29.55.2`).
2. 다른 망(학교 NAT 등)이거나 확실치 않으면 **SSH 터널** (권장, 방화벽 설정 불필요):
   노트북에서 `ssh -N -L 8010:localhost:8010 hail@<서버>`를 열어두고 `VLM_SERVER_URL=http://localhost:8010`.
   어댑터는 `--host 127.0.0.1`로 띄워도 된다(터널이 로컬로 들어오므로). LAN 직접 접속이면 `--host 0.0.0.0`.
3. 어댑터 서버는 tmux 안에서 실행. 확인: 노트북에서 `curl http://localhost:8010/health`.

### 6.1 `server/app.py` → 얇은 어댑터로 교체 — **완료 (2026-11-10)**
- 리포는 서버에 `~/Smart-Security-Camera-System`로 clone 됨. `server/app.py`, `server/requirements.txt`, `README.md`(서버 절·API 표·트러블슈팅) 수정. **아직 commit/push 안 함** — 노트북에서 이어 쓰려면 먼저 서버에서 commit·push.
- env `cctv`에서 실행. 추가 설치 없음(fastapi·uvicorn·python-multipart·cv2·requests 이미 있었음). bge-m3는 **sentence-transformers 없이 transformers `AutoModel`로 직접**(CLS 토큰 + L2 정규화 = 공식 dense 임베딩, 1024차원). env 보호 목적.
- `POST /describe`: mp4 → 순차 디코드하며 `WINDOW_SEC`(기본 **20초**) 창으로 분할 → 창마다 make_clips.py와 같은 규칙(160×120 gray absdiff, 8등분 빈별 최대 변화 프레임, 프레임 8장 미만이면 반복으로 채움) → vLLM :8002에 convert_lf.py의 INSTRUCTION 그대로(temperature 0, max_tokens 400) → `re.search(r"\{.*\}")` 파싱 + 열거형 정규화 → `summary + " " + action` bge-m3 임베딩. 3초 미만 꼬리 창은 앞 창에 합침. `question`은 받기만 하고 무시(학습 프롬프트 고정). 선택 `window_sec`(3~120)로 창 길이 덮어쓰기.
- 반환: `{"description": 첫 로그 summary, "logs": [{"window_start","window_end","log":{…}|null,"raw","embedding":[1024]|null}], "duration_sec","n_windows","window_sec","elapsed_sec"}`.
- `POST /embed` `{"text"}` → `{"embedding"}`. `GET /health` → `status ok|degraded`, `vllm` bool, `model`, `embed_ready`.
- 실측: 창당 약 2초(창을 순차 처리). 57초 영상 20초 창 3개 = 5.9초, 164초 영상 60초 창 3개 = 10.7초. 2초짜리(8프레임) 영상도 정상 동작. 깨진 파일은 400, vLLM 다운은 502. 360p·4fps 다운샘플본도 원본과 같은 결과.
- **창 길이 발견**: 60초 창으로 넣으면 Robbery050(사건 14~56초)·Fighting003(64~102초)·Shoplifting001(25~46, 58~74초) 모두 **정상**으로 놓침. 20초 창에서는 셋 다 해당 구간에서 검출(Robbery / Fighting / Robbery→Shoplifting). 정상 영상 2편(Normal_027, 246) 20초 창 17개 오탐 0. RoadAccidents001은 60초(45초 영상 1창)에서도 검출되나 20초 창에선 유형이 Arson/Assault/Arrest로 흔들림(이상 판정은 유지). → 기본 20초 채택. 클라이언트 녹화가 길면 창 수만큼 시간 걸리므로 `VLM_TIMEOUT` 상향 필요(창당 2초).
- 어댑터 로그는 tmux 창 `adapter`. 테스트용 다운샘플 클립은 세션 scratchpad에만 있음(임시).

### 6.2 `client/backend/database.py`, `ai_describer.py` — **완료 (2026-11-10, 서버에서 구현·테스트)**
- `motion_logs`에 열 추가: `window_start`, `window_end`(녹화 내 초), `is_anomaly`(0/1), `anomaly_type`, `scene`, `action`, `objects_json`, `summary`, `embedding`(BLOB float32×1024). `description`에는 `summary`(기존 UI 호환). 기존 DB는 `init_db()`가 `PRAGMA table_info`로 보고 없는 열만 `ALTER TABLE ADD COLUMN` → 노트북의 옛 `cctv.db` 그대로 써도 됨.
- 흐름: 세션 종료 시 만들어 둔 로그 행 1개 → `describe_recording()`이 어댑터 응답 `logs[]`를 받아 **첫 창은 그 행을 update**(`timestamp_offset_sec`도 창 시작으로), **2번째 창부터 insert**(`detected_at` = 녹화 시작 + 창 시작). 파싱 실패한 창(log null)은 건너뜀. 서버 미설정/실패면 기존 폴백 `"움직임 감지됨"` 단일 로그.
- `VLM_TIMEOUT` 기본 60 → **300**. 새 env `VLM_WINDOW_SEC`(선택). `embed_text()` 추가(검색용 `/embed` 호출). API 응답에서 `embedding`은 빼고 `objects_json`은 `objects` 리스트로 파싱해 내려줌(`_row_to_log`).
- `requirements.txt`에 numpy 추가.
- **`preprocess.py` 두 가지 수정**(6.5의 "안 건드려도 됨"과 달리 필요했음): (a) 결과 mp4의 fps를 명목 4가 아니라 실제값(원본fps/round(원본fps/4), 15fps면 3.75)으로 기록 — 안 그러면 재생 시간이 6% 줄어 `window_start`가 원본 시각과 어긋남(57초 영상이 53.2초로 나왔었음). (b) 축소 후 높이가 240 미만이면 축소 안 함(`MIN_HEIGHT`) — 320×240 테스트 영상이 160×120으로 들어가 결과가 흔들림.

### 6.3 `client/backend/routers/logs.py` — **완료**
- `GET /api/logs?period=&anomaly=1&type=Robbery` (유형 목록 외 값은 400). 응답에 `anomaly_total`.
- `GET /api/logs/search?q=&period=month&anomaly=1&top_k=20`: `/embed`로 질의 벡터 → `database.search_motion_logs()`가 numpy 내적(bge-m3는 L2 정규화돼 있어 내적=코사인) → `score` 포함 상위 N. `VLM_SERVER_URL` 없으면 503, 임베딩 실패 502. `/search` 라우트는 `/{log_id}`보다 **앞에** 선언해야 함(안 그러면 "search"를 int로 파싱하려다 422).
- `routers/recordings.py`의 `GET /api/recordings/{id}`도 `motion_logs`를 `_row_to_log`로 내려줌(창 순 정렬).
- 테스트(서버, Robbery050·Normal_027을 녹화로 가장해 삽입): 로그 12개(3창+9창) 생성, `anomaly=1`·`type=` 필터, 검색 3질의 모두 의미 맞는 창이 1위(예: "가방을 들고 나감" → 해당 창 0.663), 녹화 상세에 창 9개, 비디오 Range 206 정상.

### 6.4 `client/frontend` — **완료 (빌드 통과, 브라우저 확인은 노트북에서)**
- `src/anomaly.js`: 유형 영문→한국어(`ANOMALY_LABELS`), `fmtWindow`.
- `MotionLogList.jsx`: 자연어 검색창(→ `/api/logs/search`, 유사도순 + `score` 배지), "이상만 보기" 토글(빨강, 건수 표시), 이상 로그 빨간 배지 `이상 · 강도` + 왼쪽 빨간 테두리 + **상단 고정**(검색 결과는 유사도순 그대로), 정상은 초록 배지, `scene` 배지, `summary` 아래 `action` 한 줄, 시각 아래 `+m:ss` 창 오프셋. 클릭 → `/playback`으로 `window_start` seek.
- `VideoPlayer.jsx`: 타임라인 마커를 창 길이만큼 막대로, 이상=빨강 / 정상=파랑, 툴팁에 `[이상 · 유형] summary`.
- `PlaybackPage.jsx`: "구간 로그" 목록에 배지 + 창 시각(`m:ss–m:ss`), 클릭하면 해당 창으로 seek. `api/index.js`: `getLogs(period, anomalyOnly, type)`, `searchLogs(q, period, anomalyOnly, topK)`.
- `index.css` 끝에 스타일 추가. `npm run build` 통과. **실제 화면은 아직 아무도 안 봄** — 노트북에서 `npm run dev`로 확인하고 어색한 곳 손볼 것.

### 6.6 노트북에서 할 일 (남음)
1. `git pull` → `client/backend`: `pip install -r requirements.txt`(numpy 추가됨) → `VLM_SERVER_URL=http://localhost:8010`(터널) 또는 `http://172.29.55.2:8010`(LAN)으로 `uvicorn main:app --port 8800` → `client/frontend`: `npm run dev`.
2. 웹캠 앞에서 움직여 세션 1개 만들고 `/logs`에 창 로그가 뜨는지, 클릭 시 해당 창으로 seek 되는지, 검색이 되는지 확인. 백엔드 콘솔 `[VLM] 응답: 창 N개, 이상 M개` 로그 확인.
3. 실내 고정 카메라에서 모델 결과(도메인 갭) 관찰 → 5단계.

### 6.5 전처리
360p·4fps `_vlm.mp4`에서 8장 뽑으면 됨. 학습 데이터가 320×240이라 해상도 적합. 단 6.2의 두 가지 수정(실제 fps 기록, 최소 높이 240)은 필요했음. 관찰: 같은 Robbery050이라도 입력이 480×360·4fps(ffmpeg)면 20~40초 창이 Robbery로 검출됐고, 320×240·3.75fps(preprocess 경유)면 정상으로 나옴 — 저해상도·저fps에 민감. 노트북 녹화는 1280×720→640×360이라 전자에 가까움.

---

## 7. 남은 일 — 5단계 데모·보고서

- 사용자 카메라/휴대폰으로 정상 30분 + 연출 이상 상황 5개 촬영 → `CAMERA_SOURCE`로 넣어 end-to-end.
- **도메인 갭 예상**: UCF-Crime(다양한 공개 영상) vs 고정 실내 카메라. 품질 저하가 나오면 "한계 및 향후 과제"로 기술. 시간이 남으면 자체 영상 50개에 teacher 로그를 만들어 추가 LoRA(가장 효과 큰 보완).
- 보고서 표: (1) A/B/C/B2 지표 표, (2) 오탐 분해 표, (3) 유형 혼동 상위, (4) 5절 결론 1~8.
- UCF-Crime SOTA(프레임 AUC ~94%)와 나란히 놓지 말 것. 비교 대상은 "같은 베이스, 프롬프트만(A) vs LoRA(B)".

---

## 8. 삽질 기록 (같은 실수 방지)

- Dropbox 폴더 내부 파일 링크는 고정 URL(`?rlkey=...`), `dl=0→dl=1`로 다운로드. 8개 병렬 연결하면 403 차단됨 → `-x 4` 이하. 이어받기 마지막 조각에서 403이 나면 `-c` 없이 새 파일명으로 처음부터 받는 게 빠름(95 MiB/s 환경).
- UCF-Crime 배포본 `Anomaly_Train.txt`는 0바이트. Dropbox 폴더의 별도 `Anomaly_Train.txt`로 덮어쓸 것.
- UCA `revised_en_UCFCrime_Train.json`은 0바이트. 원본 Train.json 사용.
- 폴더명에 공백(`UCF Annotation`) → `xargs` 깨짐. 따옴표 필수.
- `conda create` 후 `conda activate` 확인 안 하고 pip install → 엉뚱한 env에 설치됨(실제 발생). 프롬프트 괄호 확인.
- vLLM 서버 `Ctrl+C` 안 하고 다른 창에서 새로 띄우다 OOM(실제 발생). 띄우기 전 `nvidia-smi`.
- `CUDA_VISIBLE_DEVICES=N`은 명령과 같은 줄에.
- 학습 전 `grep output_dir train_lora.yaml`로 덮어쓰기 방지.
- make_clips 재실행 후 teacher_logs → convert_lf 순서를 건너뛰면 convert가 옛 데이터로 돌아감(실제 발생). `wc -l clips/teacher_logs.jsonl`과 `wc -l clips/manifest.csv`(헤더 +1)가 맞는지 확인.
- `hf download BAAI/bge-m3 --include ...`는 model.safetensors가 없어서(이 리포는 `pytorch_model.bin`만 배포) 조용히 아무것도 안 받음. 파일명을 직접 지정해 `pytorch_model.bin`을 받을 것. transformers 5.20에서 .bin 로딩 정상.
- 디스크: 1.2 TB → 914 GB로 예상보다 150 GB 더 줄었음. 원인 미확인(`du -sh ~/.cache/vllm ~/anaconda3/envs/* ~/Videos/*` 로 확인 가능). 급하지 않음.

---

## 9. 파일 목록 (~/Videos/)
```
CLAUDE.md               이 문서
build_uca_table.py      UCA → uca_segments.csv
classify_segments.py    구간 문장 분류 (Qwen3-8B :8000)
make_clips.py           병합·선별·8프레임 추출 → clips/
teacher_logs.py         teacher 로그 생성 (Qwen3-VL-32B :8001) → clips/teacher_logs.jsonl
convert_lf.py           → lf/data/*.json
eval_test.py            test 평가 → eval/
uca_segments.csv        23,542 구간 + 라벨
review_sample.csv       검수 샘플 312 (미검수)
review_sample_claude.csv  Claude 2차 의견
clips/manifest.csv      5,405 클립
clips/frames/           클립별 change/uniform 8장
clips/teacher_logs.jsonl
lf/train_lora.yaml, lf/merge_lora.yaml, lf/data/, lf/saves/, lf/models/
eval/*.jsonl, eval/*_metrics.json
UCF_Crime/, UCF_Crime_raw/, Surveillance-Video-Understanding/
~/Smart-Security-Camera-System/   캡스톤 리포 clone. server/ 어댑터 + client/ 6.2~6.4 구현. client/backend/venv, cctv.db, recordings/(테스트용 UCF 2편)는 gitignore
```
