# 테트라워치 — 분석데이터 + 분석소스코드

- 학교 : 국립한국해양대학교 (인공지능공학부)
- 팀명 : 테트라워치 (팀장 정민혁, 팀원 권찬희, 팀원 길민혁)
- 과제명 : 데이터 기반 부산 해안 CCTV 위험 지역 판별

이 폴더는 데이터설명서의 Ⅰ. 원시 데이터 · Ⅱ. 가공 데이터 · Ⅲ. 결과 데이터와 이를 만든 소스코드를 한곳에 모은 것이다.
분석 작업 폴더(`DatoryLab_trackB_2`)의 구조를 그대로 두어 소스코드의 상대경로가 그대로 동작한다.
모든 공간 데이터의 좌표계는 EPSG:5186 (Korea 2000 / 중부원점)이다.

```
DatoryLab_trackB_2/
├── README_viewshed.md                  분석 과정·가정값·결과 요약 (작업 당시 기록)
├── trackB_viewshed_colab.ipynb         전체 실행 순서 노트북 (tools/*.py 를 순서대로 호출)
├── 부산전체_행정안전부_연안사고.csv       원시 9′ 행안부 해양사고 (부산 해역 추출본, 파일명만 "연안사고")
├── data/raw/                           원시 데이터 (Ⅰ)
├── trackA/                             트랙 A 위험지수 소스코드·산출물 (권찬희, 2026-10-14)
├── outputs/                            가공 데이터 (Ⅱ) · 결과 데이터 (Ⅲ)
└── tools/                              트랙 B 분석 소스코드 (Python)
```

## 실행 순서 (소스코드)

| 순서 | 파일                               | 하는 일                                                                                                   | 데이터설명서 |
| ---- | ---------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------ |
| 0′   | `tools/extract_busan_accidents.py` | 전국 해양사고 31,911건 → 부산 해역 2,138건 추출,`lon_exact`·`lat_exact` 추가                              | Ⅰ-자         |
| 0    | `trackA/track_a.py`                | 트랙 A: 관측소 배정, 파고 임계(P85), 해안유형별 사고율, 위험지수 R=√(T×W)·등급, 설치후보 63구간, 차트 4장 | Ⅱ-바         |
| 1    | `tools/reanalyze_cctv_coverage.py` | 4개 출처 CCTV 통합(20m 중복 제거), 500m 반경 커버율                                                       | Ⅱ-가, Ⅱ-나   |
| 2    | `tools/attach_cctv_fov.py`         | 촬영방면정보 → 화각 유형(`view_type`, `fov_deg_max`) 결합                                                 | Ⅱ-가         |
| 3    | `tools/fetch_dem_copernicus.py`    | Copernicus GLO-30 DSM 내려받기·EPSG:5186 30m 재투영                                                       | Ⅰ-사         |
| 4    | `tools/prepare_viewshed.py`        | 관측점 3,856 추출, 3분류(그룹1·2·3), 대상구역(±100m) 래스터화                                             | Ⅱ-다         |
| 5    | `tools/run_viewshed.py`            | 3D 가시권 계산, 구간·구군·관측점별 집계                                                                   | Ⅱ-라         |
| 6    | `tools/viewshed_sensitivity.py`    | 화각·방위각, 설치 높이·가시거리 민감도                                                                    | Ⅱ-마         |
| 7    | `tools/site_exclusions.py`         | 도서부 + 수동 제외 구간 → 설치 제외 마스크                                                                | Ⅱ-사         |
| 8    | `tools/build_trackD_dataset.py`    | 트랙 A 위험지수 + 트랙 B 가시권 결합 구간표, 가중치 파일(`--weights-only`)                                | Ⅱ-사, Ⅲ-다   |
| 9    | `tools/viewshed_new_sites.py`      | 신규 후보 격자점 생성, 레이지 그리디 배치 (`--n 200 [--weights]`)                                         | Ⅱ-아, Ⅲ-가   |
| 10   | `tools/trackA_reevaluate.py`       | 트랙 A 설치후보 63구간 3D 가시권 재평가                                                                   | Ⅲ-라         |
| 11   | `tools/trackA_compare_plans.py`    | 균등 vs 위험도 가중 배치 성과 비교, 핵심 사각 v4 34구간                                                   | Ⅲ-라         |
| 12   | `tools/export_segment_results.py`  | 구간별 결과 통합 CSV (한글판·영문판)                                                                      | Ⅲ-다         |
| 13   | `tools/plot_viewshed_maps.py`      | 지도 7종, 상위 50곳 촬영방향 3분류                                                                        | Ⅲ-나, Ⅲ-마   |
| –    | `tools/trackD_query.py`            | 구간표 조회용 보조 스크립트                                                                               | –            |

필요 패키지: `geopandas>=1.0`, `pyogrio>=0.10`, `rasterio>=1.3`, `shapely`, `pandas`, `numpy`, `folium>=0.18`, `matplotlib>=3.8` (노트북 0번 셀 참조)

### 트랙 A (`trackA/`) 입력 파일

`track_a.py`는 아래 파일을 읽으며, 입력 파일이 모두 `trackA/data/`에 있다. 해양기상 3종은 권찬희 해양기상데이터 아카이브, `integrated/`는 정민혁이 만든 통합 데이터(코드상 `integrated.zip`)에서 가져왔다. 산출 CSV 5종은 `data/raw/trackA/track_a_csvs_20261014/`와 동일 파일이다.

| 입력 (코드 경로)                                               | 내용                                                                                                                  | 이 폴더                                                     |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `integrated/tables/coastline_monitoring_segments.csv` (zip 안) | 해안 구간 1,832 (=`coastal_safety_busan.gpkg` 레이어 `coastline_monitoring_segments`와 속성 동일)                     | `trackA/data/integrated/tables/`                            |
| `integrated/tables/accidents_busan_2017_2023.csv` (zip 안)     | 해경 연안사고 부산 397건 (2017–2023, 장소유형만 있고 좌표 없음) → T 유형위험                                          | `trackA/data/integrated/tables/`                            |
| `data/파고부이_일별_2024_2026.csv`                             | 기장(22511)·오륙도(22459)·다대포(22460) 파고부이 일별 유의파고, 2024-01-01~2026-06-30, 2,736행 → W 파랑노출, P85 임계 | `trackA/data/`                                              |
| `data/등표_일별_2024_2026.csv`                                 | 오륙도 등표(984) 일별 최대순간풍속, 2024-01-01~2026-06-30, 884행 → 풍속 임계                                          | `trackA/data/`                                              |
| `data/시간별_영도근처_2026Q2.csv`                              | 위 4개 지점 시간별 파고·풍속, 2026-04-01~06-30, 8,724행 (경보 시연용)                                                 | `trackA/data/`                                              |
| `트랙B/input_trackB_segments.csv`                              | 트랙 B 가시 커버율 (설치후보 판정용)                                                                                  | `outputs/input_trackB_segments.csv`                         |
| – (코드에서 읽지 않음)                                         | 관측소 4곳의 ID·위경도·유형 (`nearby_stations_official.csv`)                                                          | `trackA/data/` (참고용)                                     |
| – (코드에서 읽지 않음)                                         | 397건의 원본: 전국 연안사고 4,721건 (2017–2023).`발생지역_표준 == "부산광역시"`로 거르면 397건과 완전히 같다          | `trackA/data/integrated/tables/accidents_all_2017_2023.csv` |
| – (코드에서 읽지 않음)                                         | 통합 데이터 생성 기록 (`integration_report.md`)                                                                       | `trackA/data/integrated/`                                   |

- `track_a.py`는 작성 당시 폴더 구조(`../권찬희_해양기상분석_20260820/data/`, `jung data/integrated.zip` 등)를 경로로 쓰므로 그대로는 실행되지 않는다. 팀원 원본 코드라 고치지 않았다. 다시 실행하려면 코드 위쪽 `ZIP`, `DATA`, `TRACK_B` 세 경로를 위 표의 위치로 바꾸면 된다(`ZIP`은 `trackA/data/integrated/`를 zip으로 묶어 지정).
- **재실행 검증** (경로만 바꾼 사본으로 실행): `1_관측소배정`, `2_관측소별임계`, `3_해안유형별사고율`은 제출본과 바이트 단위로 같다. `4_구간별위험지수`는 위험지수·등급·T·W 등 트랙 A 계산값이 1,832구간 모두 같고, 트랙 B에서 받아 붙이는 `view_coverage_pct_conservative` 한 칼럼만 791구간에서 다르다. 트랙 A 산출(10/14) 뒤 트랙 B 가시권이 버퍼 보정으로 다시 계산되었기 때문이며(`README_viewshed.md` "2026-10-15 재계산"), 10/14 시점 트랙 B 파일은 남아 있지 않다. 그 영향으로 `5_CCTV설치후보`도 63구간 중 1구간이 바뀐다(제출본 `SEG_001571` ↔ 재실행 `SEG_000342`). 제출 폴더에는 실제 분석에 쓰인 10/14 산출본을 그대로 두었다.
- 제외한 파일: 아카이브의 순별 집계 2종, `integrated/coastal_safety_busan.gpkg`(= `data/raw/cctv_reanalysis/coastal_safety_busan.gpkg`, MD5 동일), `integrated/tables/`의 나머지 4종(`accident_coastguard_aggregate_all`, `accident_location_2017_2020_all`, `accident_summary_busan`, `cctv_coordinate_exclusions`) — 모두 어떤 코드에서도 읽지 않는다.

산출: `1_관측소배정.csv`, `2_관측소별임계.csv`, `3_해안유형별사고율.csv`, `4_구간별위험지수.csv`, `5_CCTV설치후보.csv`, `charts/A1~A4.png`. 방법 설명은 `trackA/트랙A_결과보고_권찬희.md`, 트랙 B 전달 메모는 `trackA/트랙A_트랙B전달_권찬희.md`.

## Ⅰ. 원시 데이터 ↔ 파일

| 연번 | 데이터 명                                                                                                         | 파일 경로                                                                                            | 건수                             |
| ---- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------- |
| 1    | 행정안전부 CCTV 표준데이터 (부산)                                                                                 | `data/raw/cctv_reanalysis/cctv_mois_busan.csv`                                                       | 18,074                           |
| 2    | 부산 ITS 교통 CCTV                                                                                                | `data/raw/cctv_reanalysis/its_cctv_2026/tl_tracffic_cctv_info_2026.shp` (+ .dbf .shx .prj .cpg)      | 315                              |
| 3    | 부산광역시 교통 CCTV 공개 API                                                                                     | `data/raw/cctv_reanalysis/coastal_safety_busan.gpkg` · 레이어 `cctv_busan`                           | 238                              |
| 4    | 행정안전부 재난예경보시설                                                                                         | `data/raw/cctv_reanalysis/disaster_warning_facilities.csv`                                           | 4,866 (부산 546, CCTV 81)        |
| 5    | 국립해양조사원 해안선                                                                                             | `data/raw/cctv_reanalysis/coastal_safety_busan.gpkg` · 레이어 `coastline_busan`                      | 1,361                            |
| 6    | 해양경찰청 연안 출입통제구역                                                                                      | `data/raw/cctv_reanalysis/coastal_safety_busan.gpkg` · 레이어 `restricted_areas_busan`               | 1                                |
| 7    | ESA Copernicus GLO-30 DSM                                                                                         | `data/raw/dem/busan_copernicus_dsm30_5186.tif`                                                       | 1,828 × 1,849 격자               |
| 8    | 기상청 파고부이·등표 관측자료 (기장·오륙도·다대포 파고부이, 오륙도 등표; 2024.01.01–2026.06.30)                   | `trackA/data/파고부이_일별_2024_2026.csv` · `등표_일별_2024_2026.csv` · `시간별_영도근처_2026Q2.csv` | 2,736 / 884 / 8,724              |
| 9    | 행정안전부 생활안전지도 해양사고발생현황 (전국 원본, 선박 사고 위주) → 촬영방향 분류                              | `data/raw/accidents/행정안전부_생활안전지도 해양사고발생현황.csv`                                    | 31,911 (2015.01.02 ~ 2024.12.31) |
| 9′   | 위 원본에서 부산 해역만 추출한 분석 입력                                                                          | `부산전체_행정안전부_연안사고.csv`                                                                   | 2,138                            |
| 10   | 해양경찰청 연안 장소별 사고발생이력 — 부산 (accidents_busan_2017_2023; 2017–2023, 좌표 없음) → 트랙 A 유형위험 T | `trackA/data/integrated/tables/accidents_busan_2017_2023.csv`                                        | 397                              |
| 10′  | 위 자료의 전국 원본 (accidents_all_2017_2023)                                                                     | `trackA/data/integrated/tables/accidents_all_2017_2023.csv`                                          | 4,721                            |

- 3·5·6번은 과제 초기에 제공된 `coastal_safety_busan.gpkg` 한 파일에 레이어로 들어 있다 (설명서의 "shp → gpkg"). 이 gpkg에는 해안선을 500m 단위로 나눈 `coastline_monitoring_segments`(1,832) 레이어도 함께 있다.
- 10번 397건은 10′ 전국 4,721건 중 `발생지역_표준`이 "부산광역시"인 행이다(원래 발생지역 표기 "부산광역시" 358 · "부산시" 33 · "부산" 6을 표준화한 값). 관할 해경서는 부산 304 · 울산 57 · 창원 36건이다.
- 9번 전국 원본은 `objt_id`가 고유하지 않다(31,911행 중 고유값 20,663). 9′ 부산 추출본 2,138행은 전국 원본의 `x`,`y`(EPSG:3857)를 WGS84로 변환해 부산 해역 좌표 범위(동경 128.7465~129.402°, 북위 34.861~35.337°)로 거른 것이며, 변환 좌표를 `lon_exact`,`lat_exact` 칼럼으로 덧붙였다. 원래 추출 코드는 남아 있지 않아 `tools/extract_busan_accidents.py`로 재현했다. 이 스크립트의 결과는 기존 2,138행과 행 순서·모든 칼럼 값이 같다(`lon_exact`,`lat_exact`는 PROJ 버전 차이로 소수 14번째 자리만 다를 수 있음). 출력 파일이 이미 있으면 덮어쓰지 않고 비교 결과만 출력한다(`--overwrite`로 다시 쓰기).

## Ⅱ. 가공 데이터 ↔ 파일

| 연번 | 데이터 명                                                 | 파일 경로                                                                                                                | 건수                       |
| ---- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------- |
| 1    | cctv_integrated_locations                                 | `outputs/cctv_reanalysis/cctv_integrated_locations.csv` · gpkg 레이어 동명                                               | 12,808                     |
| 2    | cctv_integrated_locations_fov                             | `outputs/cctv_reanalysis/cctv_integrated_locations_fov.csv`                                                              | 12,808                     |
| 3    | cctv_deduplication_report                                 | `outputs/cctv_reanalysis/cctv_deduplication_report.csv`                                                                  | 3                          |
| 4    | cctv_reanalysis_summary                                   | `outputs/cctv_reanalysis/cctv_reanalysis_summary.csv`                                                                    | 18                         |
| 5    | coastal_safety_busan_cctv_updated                         | `outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg` (9개 레이어)                                            | 1,832 (구간)               |
| 6    | cctv_coverage_by_district                                 | `outputs/cctv_reanalysis/cctv_coverage_by_district.csv`                                                                  | 10                         |
| 7    | 트랙 A 산출 CSV 5종                                       | `data/raw/trackA/track_a_csvs_20261014/1_관측소배정.csv` … `5_CCTV설치후보.csv`                                          | 1,832 / 3 / 4 / 1,832 / 63 |
| 8    | manual_site_exclusions                                    | `data/raw/manual_site_exclusions.csv`                                                                                    | 45                         |
| 9    | viewshed_inputs · viewshed_observers · viewshed_params    | `outputs/viewshed/viewshed_inputs.gpkg` (observers, target_zone) · `viewshed_observers.csv` · `viewshed_params.json`     | 3,856 / 1,832              |
| 10   | target_zone_mask · target_zone_index                      | `outputs/viewshed/target_zone_mask.tif` · `target_zone_index.tif`                                                        | 1,828 × 1,849              |
| 11   | viewshed_count_current · viewshed_count_omni              | `outputs/viewshed/viewshed_count_current.tif` · `viewshed_count_omni.tif`                                                | 1,828 × 1,849              |
| 12   | viewshed_by_segment · segment_coverage                    | `outputs/viewshed/viewshed_by_segment.csv` · `viewshed_results.gpkg` 레이어 `segment_coverage`                           | 1,832                      |
| 13   | viewshed_by_observer                                      | `outputs/viewshed/viewshed_by_observer.csv`                                                                              | 1,782                      |
| 14   | viewshed_by_district                                      | `outputs/viewshed/viewshed_by_district.csv`                                                                              | 11                         |
| 15   | sensitivity_fov_azimuth · sensitivity_height_range        | `outputs/viewshed/sensitivity_fov_azimuth.csv` · `sensitivity_height_range.csv`                                          | 3 / 5                      |
| 16   | trackB_weights · station_thresholds · risk_weights_trackA | `outputs/trackD/trackB_weights.csv` · `outputs/trackD/station_thresholds.csv` · `outputs/trackA/risk_weights_trackA.csv` | 1,832 / 3 / 63             |
| 17   | new_site_candidates                                       | `outputs/viewshed/viewshed_results.gpkg` 레이어 `new_site_candidates`                                                    | 1,775                      |

- 7번 트랙 A CSV는 `trackA/track_a.py`의 산출물이다. 트랙 B가 입력으로 받은 사본이 `data/raw/trackA/track_a_csvs_20261014/`에 있으며 `trackA/`의 파일과 내용이 같다(MD5 일치). `data/raw/trackA/5_CCTV설치후보.csv`도 같은 파일의 복사본이다.
- 17번 후보지 수 1,775건은 보고서·포스터 표기와 일치한다(2026-11-02에 2,081곳 → 1,775곳으로 수정).

## Ⅲ. 결과 데이터 ↔ 파일

| 연번 | 데이터 명                                        | 파일 경로                                                                                                                                                                                          | 건수          |
| ---- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| 1    | new_sites_ranked_trackB_weights                  | `outputs/viewshed/new_sites_ranked_trackB_weights.csv` · `viewshed_results.gpkg` 레이어 동명                                                                                                       | 400           |
| 2    | new_sites_ranked                                 | `outputs/viewshed/new_sites_ranked.csv` · `viewshed_results.gpkg` 레이어 동명                                                                                                                      | 400           |
| 3    | new_sites_curve_trackB_weights · new_sites_curve | `outputs/viewshed/new_sites_curve_trackB_weights.csv` · `new_sites_curve.csv`                                                                                                                      | 18 / 18       |
| 4    | new_sites_top50_by_district(\_trackB_weights)    | `outputs/viewshed/new_sites_top50_by_district_trackB_weights.csv` · `new_sites_top50_by_district.csv`                                                                                              | 9 / 9         |
| 5    | top50_sites_direction_classified                 | `outputs/viewshed/top50_sites_direction_classified.csv`                                                                                                                                            | 50            |
| 6    | trackD/segments                                  | `outputs/trackD/segments.csv`                                                                                                                                                                      | 1,832         |
| 7    | trackD/cctv_candidates_v4                        | `outputs/trackD/cctv_candidates_v4.csv`                                                                                                                                                            | 34            |
| 8    | trackD/plan_comparison                           | `outputs/trackD/plan_comparison.csv`                                                                                                                                                               | 6             |
| 9    | trackA/trackA_candidates_reevaluated             | `outputs/trackA/trackA_candidates_reevaluated.csv`                                                                                                                                                 | 63            |
| 10   | segment_results_busan · input_trackB_segments    | `outputs/segment_results_busan.csv` · `outputs/input_trackB_segments.csv`                                                                                                                          | 1,832 / 1,832 |
| 11   | trackD/validation                                | `outputs/trackD/validation.json`                                                                                                                                                                   | 1             |
| 12   | 지도 7종                                         | `outputs/viewshed/maps/` (busan*blind_and_new_sites.html/.png, zoom*강서*사하.png, zoom*기장.png, new_sites_curve.png, trackA_candidates_and_risk_sites.png, busan_top50_direction_classified.png) | 7             |

최종 보고서의 신규 CCTV 상위 50곳은 Ⅲ-1 파일의 `baseline = original_360` 행 중 `rank` 1~50이다.
