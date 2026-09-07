# Phase 6 baseline

- 기록일: 2026-09-06 (Asia/Seoul)
- 기존 테스트: 59개, 실패 0, 오류 0
- 테스트 파일: `test_advancement.py`, `test_school_collection.py`, `test_phase4_school_zone.py`, `test_phase5.py`
- school master: 502행
- Phase 5 apartment-school match: 11행
- manual_review: 11행
- UNRESOLVED: 1행

## 기존 processed 파일

| 파일 | 역할 |
|---|---|
| `schools.parquet` | 학교 master |
| `middle_school_advancement.parquet` | 중학교 진학정보 |
| `middle_school_scores.parquet` | Phase 3 중학교 점수 |
| `haeundae_apartment_elementary_match_2025.parquet` | Phase 5 검증 매칭 |
| `haeundae_school_apartments_500plus_2025.parquet` | Phase 5 500세대 이상 검증 view |

첫 실행에서 기존 지오코딩 캐시 테스트가 Windows 임시파일 잠금으로 한 차례 실패했다.
새 임시 디렉터리에서 동일한 전체 테스트를 재실행해 59개 통과를 확인했으며
`reports/phase6_baseline_pytest.xml`에 최종 결과를 저장했다.
