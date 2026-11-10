# research/ — 데이터 파이프라인·학습·평가 (졸업작품 연구 파트)

서버 `~/Videos/`에 있던 스크립트와 결과물을 백업용으로 옮긴 것. 전체 맥락은 루트 `CLAUDE.md` 3~5절.

| 파일 | 역할 |
|---|---|
| `build_uca_table.py` | UCA 주석 JSON 3개 → `uca_segments.csv` (구간 단위) |
| `classify_segments.py` | 구간 문장을 Qwen3-8B로 이상/정상 분류 → `seg_is_anomaly` 채움 |
| `make_clips.py` | 구간 병합·선별·8프레임 추출 → `clips/manifest.csv`, `clips/frames/` |
| `teacher_logs.py` | Qwen3-VL-32B teacher로 로그 본문 생성 → `clips/teacher_logs.jsonl` |
| `convert_lf.py` | LLaMA-Factory sharegpt 형식으로 변환 → `lf/data/` |
| `eval_test.py` | test 798 클립 평가 → `eval/*_metrics.json` |
| `lf/train_lora.yaml`, `lf/merge_lora.yaml`, `lf/dataset_info.json` | LoRA 학습·병합 설정, 데이터셋 등록 |
| `uca_segments.csv` | 23,542 구간 + 라벨 |
| `review_sample.csv` | 라벨 검수 샘플 312개 (미검수) |
| `clips/manifest.csv`, `clips/teacher_logs.jsonl` | 5,405 클립 메타 + teacher 로그 (**재생성에 100분 걸리는 핵심 산출물**) |
| `eval/*_metrics.json` | A/B/C/B2 비교군 지표 |

포함 안 된 것(크기 때문): `clips/frames/`(2.1GB, `make_clips.py`로 재생성), `eval/*.jsonl`(클립별 예측), `lf/data/*.json`(`convert_lf.py`로 재생성), UCF-Crime 영상, 가중치(HuggingFace에 별도 업로드).

스크립트 안의 경로는 서버 기준(`~/Videos/...`). 다른 곳에서 돌리려면 상단 상수만 고치면 됨.
