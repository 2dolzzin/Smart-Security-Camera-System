# research

데이터 구축, 학습, 평가에 사용한 스크립트와 산출물이다. 절차 설명은 [개발 문서 6장](../docs/DEVELOPMENT.md#6-연구-파이프라인)에 있다.

| 파일 | 역할 |
|---|---|
| `build_uca_table.py` | UCA 주석 JSON 3개를 구간 단위 표 `uca_segments.csv` 로 통합 |
| `classify_segments.py` | 이상 영상의 구간 문장을 Qwen3-8B로 이상/정상 분류해 `seg_is_anomaly` 열을 채움 |
| `make_clips.py` | 구간 병합, 선별, 클립당 8프레임 추출. `clips/manifest.csv`, `clips/frames/` 생성 |
| `teacher_logs.py` | Qwen3-VL-32B로 로그 본문 생성. `clips/teacher_logs.jsonl` 생성 |
| `convert_lf.py` | LLaMA-Factory sharegpt 형식으로 변환. `lf/data/` 생성 |
| `eval_test.py` | 테스트 798 클립 평가. `eval/<이름>_metrics.json` 생성 |
| `lf/train_lora.yaml`, `lf/merge_lora.yaml`, `lf/dataset_info.json` | LoRA 학습, 병합 설정과 데이터셋 등록 |
| `uca_segments.csv` | 구간 23,542개와 라벨 |
| `review_sample.csv` | 라벨 검수용 표본 312개 |
| `clips/manifest.csv` | 클립 5,405개의 메타데이터 |
| `clips/teacher_logs.jsonl` | 클립별 학습 목표 로그 |
| `eval/*_metrics.json` | 조건 A, B, C, B2의 지표 |

## 저장소에 포함하지 않은 것

| 항목 | 이유와 재생성 방법 |
|---|---|
| `clips/frames/` | 2.1 GB. `make_clips.py` 로 재생성 |
| `lf/data/*.json` | `convert_lf.py` 로 재생성 |
| `eval/*.jsonl` | 클립별 예측. `eval_test.py` 로 재생성 |
| UCF-Crime 영상, UCA 주석 | 각 배포처에서 내려받음 |
| 모델 가중치 | 용량 |

## 실행 순서

스크립트는 `UCF_Crime/` 과 `Surveillance-Video-Understanding/` 이 있는 디렉토리에서 실행한다. 경로는 각 스크립트 상단의 상수로 지정한다.

```
build_uca_table.py → classify_segments.py → make_clips.py → teacher_logs.py → convert_lf.py
→ llamafactory-cli train lf/train_lora.yaml → llamafactory-cli export lf/merge_lora.yaml
→ eval_test.py
```

`lf/train_lora.yaml` 과 `lf/merge_lora.yaml` 은 2차 학습(B2) 때의 설정이다. 1차 학습(B)은 `output_dir`, `adapter_name_or_path`, `export_dir` 의 접미사 `-hn` 이 없고 `make_clips.py` 의 `HARD_NEG_TRAIN` 이 600이었다.
