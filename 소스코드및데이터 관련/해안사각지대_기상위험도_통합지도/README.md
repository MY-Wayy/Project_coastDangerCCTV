# 해안 사각지대 · 기상·위험도 통합지도

작성 2026-10-29 · 원본(`통합완료 데이터 관련/`)은 읽기만 하고 수정하지 않음

`trackB_2_results/maps/busan_blind_and_new_sites.html`(사각지대·신규 후보지 지도)에 해양기상·위험도 정보를 더한 버전입니다.

## 원본 지도 대비 바뀐 점

- 해안선 색 기준 전환 버튼(왼쪽 위): 가시 커버율(기본, 원본과 같은 색) / 위험등급(파랑 → 빨강) / 배정 부이 / 파랑노출 W
- 해안선 툴팁: 원본 4개 항목(구간·구군·커버율·사각면적)에 해안유형, 섬·설치 제외 여부, 500m 내 CCTV 수, 배정 부이(외해/내만), 파고·풍속 임계, W, T, 위험지수 R, 위험등급 추가
- 연안사고: 사고 당시 기상상태로 "기상 양호 / 악기상" 두 레이어로 나누고 색 구분, 툴팁에 기상상태 추가
- 신규 후보지 50곳 툴팁: 배정 부이, 파고 임계, W, R, 위험등급 추가
- 왼쪽 아래 범례의 해안선 부분이 선택한 색 기준에 맞춰 바뀜
- 배경지도, 기존 CCTV 레이어, 촬영방향 3분류 번호 마커는 원본과 같음

## 파일

| 파일 | 내용 |
|---|---|
| `outputs/busan_blind_and_new_sites_기상위험도.html` | 결과 지도 (브라우저로 열기) |
| `outputs/top50_sites_direction_classified.csv` | 상위 50곳 촬영방향 3분류 (원본과 동일함을 확인) |
| `tools/plot_blind_map_weather.py` | 원본 `plot_viewshed_maps.py` 복제본. 지도 함수만 확장, 출력 경로를 이 폴더로 변경, 정적 PNG 생성은 제외 |
| `tools/site_exclusions.py` | 원본 복제본. 수동 제외 목록은 원본 경로에서 읽음 |

## 다시 만들기

```bash
pip install geopandas pyogrio folium pandas
PYTHONDONTWRITEBYTECODE=1 python tools/plot_blind_map_weather.py
```
