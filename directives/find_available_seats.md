# Directive: 현재 자리 있는 매장 찾기

## Goal
지금 당장 자리가 있는 매장을 조회해서 목록을 반환한다.

## Script
```bash
python execution/fetch_store_data.py | python execution/check_availability.py --current -
```

## Output
JSON 배열 (자리 있는 매장 목록), stdout

## 판단 기준
- `여유`: 자리 있음 ✅
- `보통`: 조건부 (NOTIFY_ON_MODERATE=true 시 포함)
- `혼잡` / `매우혼잡`: 자리 없음 ❌

## 특정 매장만 확인
```bash
python execution/fetch_store_data.py --store-id 1077
```
