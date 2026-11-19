# 해양기상 지도통합 시각화

작성 2026-10-28 · 원본(`통합완료 데이터 관련/`)은 읽기만 하고 수정하지 않음

## 무엇을 보여주나

트랙 D(`DatoryLab_trackB_2/tools/build_trackD_dataset.py`)가 해안선 1,832구간에 붙인 해양기상 속성을 실제 해안선 형상 위에 그린 지도입니다.

- 배정 부이(기장·오륙도·다대포), 유의파고 임계(P85), 파랑노출 W
- 위험지수 R·위험등급(트랙 A), 기존 CCTV 3D 가시율(트랙 B, 보수적)
- 연안사고 2,138건(사고 당시 기상상태), 신규 CCTV 상위 50곳(위험도 가중)

## 파일

| 파일 | 내용 |
|---|---|
| `해양기상_지도통합_시각화.html` | 결과 지도 (단일 파일, 브라우저로 열기) |
| `build_marine_weather_map.py` | 데이터 변환 + HTML 생성 스크립트 |
| `map_template.html` | 지도 페이지 템플릿 (데이터 자리표시자 포함) |
| `vendor/leaflet-1.9.4.css` | 인라인용 Leaflet CSS |
| `data/segments_weather.geojson` | 해안선 구간(WGS84) + 기상·위험 속성 |
| `data/accidents.geojson` | 연안사고 + 기상상태 + 1km 이내 최근접 구간의 배정 부이 |
| `data/top50_sites.geojson` | 신규 상위 50곳 + 배정 부이 |
| `data/station_summary.csv` | 부이 권역별 요약 |

## 다시 만들기

```bash
pip install geopandas pyogrio pyproj shapely
python build_marine_weather_map.py
```

## 해석 시 주의

- W는 배정 부이 값을 그대로 받은 것이라 값이 세 가지(1.000 / 0.941 / 0.249)뿐입니다.
- 풍속 임계 16.9m/s는 오륙도 등표 한 곳 값으로 전 구간 동일합니다.
- 부이 시간대 관측 자료(`station_hourly.csv`)와 부이 좌표는 원본에 없습니다. 지도 위 권역 이름은 배정 구간의 중심이며 부이 위치가 아닙니다.
- 사고 → 권역 배정은 1km 이내 최근접 구간 기준입니다(2,138건 중 1,285건 배정).
