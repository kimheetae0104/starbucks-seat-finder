#!/usr/bin/env python3
"""
스타벅스 매장 가용성 데이터를 가져온다.
데이터 소스: Naver Map (영업 상태) + 시간대 패턴 + 날씨 + 공휴일

Usage: python execution/fetch_store_data.py
Output: JSON to stdout
Exit: 0=success, 1=error
"""

import sys
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime, date

BASE_DIR = Path(__file__).parent.parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://map.naver.com/",
}


# ── Naver Map 영업 상태 조회 ───────────────────────────────────────────────────

def _fetch_naver_all_stores(stores: list[dict]) -> dict[str, dict]:
    """Playwright로 Naver Map 검색 → 모든 매장 영업 상태 반환. {store_name: item}"""
    from playwright.sync_api import sync_playwright

    results = {}

    def _parse_all_search(response) -> None:
        try:
            data = response.json()
            items = (data.get("result") or {}).get("place") or {}
            for item in items.get("list", []):
                name = item.get("name", "")
                if item.get("id"):
                    results[name] = item
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ko-KR",
        )
        page = context.new_page()

        for store in stores:
            query = f"스타벅스 {store['name']}점"
            url = f"https://map.naver.com/v5/search/{requests.utils.quote(query)}"
            try:
                with page.expect_response(
                    lambda r: "allSearch" in r.url and r.status == 200,
                    timeout=8000,
                ) as resp_info:
                    page.goto(url, timeout=12000, wait_until="domcontentloaded")
                _parse_all_search(resp_info.value)
            except Exception as e:
                print(f"[WARN] Naver 검색 실패 ({store['name']}): {e}", file=sys.stderr)

        browser.close()

    return results


def _extract_business_status(item: dict) -> dict:
    """Naver 응답에서 영업 상태 추출."""
    bs = item.get("businessStatus", {})
    status = bs.get("status", {})
    code = status.get("code", -1)
    # code: 1=영업준비중, 2=영업중, 3=영업종료, 4=임시휴업
    is_open = code == 2
    text = status.get("text", "알수없음")
    detail = status.get("detailInfo", "")
    return {
        "is_open": is_open,
        "status_code": code,
        "status_text": text,
        "detail": detail,
    }


# ── 날씨 조회 (카카오 Map API) ────────────────────────────────────────────────

# 지역별 카카오 lcode (시/구 단위)
AREA_LCODE = {
    "강남구": "I10000202",
    "서초구": "I10000302",
    "도봉구": "I10090404",
    "노원구": "I10090200",
    "default": "I10000202",
}

def _fetch_weather(lcode: str = "I10000202") -> dict:
    """카카오 날씨 API로 현재 날씨 조회."""
    try:
        resp = requests.get(
            f"https://map.kakao.com/api/dapi/weather?extra=air&_caller1=ver_map_141&lcode={lcode}",
            headers={**HEADERS, "Referer": "https://map.kakao.com/"},
            timeout=5,
        )
        data = resp.json()
        forecast = data["result"]["delegateRegionWeather"]["shortTermForecast"]
        return {
            "temperature": float(forecast.get("temperature", 20)),
            "rainfall": float(forecast.get("rainfall") or 0),
            "snowfall": float(forecast.get("snowfall") or 0),
            "description": forecast.get("weatherDescription", ""),
            "thunder": forecast.get("thunderboltYn", "N") == "Y",
        }
    except Exception as e:
        print(f"[WARN] 날씨 조회 실패: {e}", file=sys.stderr)
        return {"temperature": 20, "rainfall": 0, "snowfall": 0, "description": "", "thunder": False}


def _weather_modifier(weather: dict) -> int:
    """날씨 기반 혼잡도 보정값. 비/눈/폭염/한파 → +1."""
    if weather["rainfall"] >= 1.0 or weather["snowfall"] >= 1.0:
        return 1  # 비/눈 오면 카페에 더 오래 있음
    if weather["temperature"] >= 33:
        return 1  # 폭염 → 에어컨 피서
    if weather["temperature"] <= -5:
        return 1  # 한파 → 난방 피서
    if weather["thunder"]:
        return 1
    return 0


# ── 공휴일 체크 ───────────────────────────────────────────────────────────────

# 한국 공휴일 (월/일 기준 고정 공휴일)
FIXED_HOLIDAYS = {
    (1, 1), (3, 1), (5, 5), (6, 6), (8, 15),
    (10, 3), (10, 9), (12, 25),
}

def _is_holiday(dt: date | None = None) -> bool:
    """공휴일 여부. 고정 공휴일만 체크 (설/추석 등 음력은 미포함)."""
    d = dt or date.today()
    return (d.month, d.day) in FIXED_HOLIDAYS


# ── 시간대별 혼잡도 패턴 ──────────────────────────────────────────────────────

# 매장 타입별 패턴 (0=여유, 1=보통, 2=혼잡)
PEAK_HOURS = {
    "office":  {  # 오피스가 (역삼, 강남대로 등)
        6: 0, 7: 1, 8: 2, 9: 2,
        10: 1, 11: 1,
        12: 2, 13: 2,
        14: 1, 15: 1, 16: 1,
        17: 2, 18: 2, 19: 1,
        20: 1, 21: 0, 22: 0,
    },
    "station": {  # 역사/유동인구 많은 곳 (강남역, 신분당역 등)
        6: 0, 7: 1, 8: 2, 9: 2,
        10: 1, 11: 2,
        12: 2, 13: 2,
        14: 2, 15: 2, 16: 2,
        17: 2, 18: 2, 19: 2,
        20: 1, 21: 1, 22: 0,
    },
    "residential": {  # 주택가/동네 (주말에 더 붐빔)
        8: 0, 9: 0, 10: 1, 11: 1,
        12: 1, 13: 1,
        14: 0, 15: 0, 16: 0,
        17: 0, 18: 0, 19: 0,
        20: 0, 21: 0,
    },
    "weekend": {  # 공통 주말 패턴
        9: 0, 10: 1, 11: 2, 12: 2,
        13: 2, 14: 2, 15: 1, 16: 1,
        17: 1, 18: 1, 19: 0, 20: 0,
    },
}

# 매장별 타입 분류
STORE_TYPE = {
    "강남R":          "office",
    "역삼포스코":      "office",
    "강남대로":        "office",
    "역삼초교사거리":  "office",
    "강남역신분당역사": "station",
    "강남역7번출구":   "station",
    "케이스퀘어강남":  "station",
    # 창동 지역
    "창동역":         "station",
    "쌍문도봉로":     "residential",
    "쌍문":           "residential",
    "창동이마트":     "station",
}

CONGESTION_LABELS = {0: "여유", 1: "보통", 2: "혼잡"}

# 이름 키워드 기반 자동 분류
_STATION_KW    = ("역", "터미널", "공항", "출구", "역사", "환승")
_COMMERCIAL_KW = ("백화점", "쇼핑", "몰", "마트", "아울렛", "롯데", "이마트", "홈플")
_RESIDENT_KW   = ("아파트", "주택", "마을", "단지", "빌라")


def _classify_store(store_name: str, address: str = "") -> str:
    """매장 이름/주소 키워드로 타입 자동 분류. 하드코딩 우선."""
    if store_name in STORE_TYPE:
        return STORE_TYPE[store_name]
    combined = store_name + address
    if any(k in store_name for k in _STATION_KW):
        return "station"
    if any(k in combined for k in _COMMERCIAL_KW):
        return "station"
    if any(k in combined for k in _RESIDENT_KW):
        return "residential"
    return "office"


def _estimate_congestion(store_name: str, weather_mod: int = 0,
                         address: str = "") -> tuple[str, str]:
    """매장 타입 + 시간대 + 날씨 보정으로 혼잡도 추정."""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()
    is_weekend = weekday >= 5 or _is_holiday()

    store_type = _classify_store(store_name, address)

    if is_weekend:
        table = PEAK_HOURS["weekend"]
    else:
        table = PEAK_HOURS.get(store_type, PEAK_HOURS["office"])

    base_score = table.get(hour, 0)
    score = min(2, base_score + weather_mod)
    return CONGESTION_LABELS[score], str(score)


def _get_lcode_for_store(store: dict) -> str:
    """매장 주소에서 카카오 lcode 추출."""
    addr = store.get("address", "")
    for gu, lcode in AREA_LCODE.items():
        if gu in addr:
            return lcode
    return AREA_LCODE["default"]


# ── Mock 데이터 ───────────────────────────────────────────────────────────────

def _fetch_mock(stores: list[dict]) -> list[dict]:
    import random
    levels = ["여유", "보통", "혼잡"]
    results = []
    for store in stores:
        level = random.choice(levels)
        code = {"여유": "0", "보통": "1", "혼잡": "2"}[level]
        results.append({
            "store_id": str(store["id"]),
            "name": store.get("name", ""),
            "address": store.get("address", ""),
            "congestion_code": code,
            "congestion_level": level,
            "is_open": True,
            "status_text": "영업 중",
            "status_detail": "",
            "source": "mock",
        })
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_all(stores: list[dict], use_mock: bool = False) -> list[dict]:
    if use_mock:
        return _fetch_mock(stores)

    # 날씨 조회 (대표 지역 1회)
    lcode = _get_lcode_for_store(stores[0]) if stores else AREA_LCODE["default"]
    weather = _fetch_weather(lcode)
    weather_mod = _weather_modifier(weather)

    weather_note = ""
    if weather_mod:
        if weather["rainfall"] >= 1:
            weather_note = f"🌧 비({weather['rainfall']}mm)"
        elif weather["snowfall"] >= 1:
            weather_note = f"❄️ 눈"
        elif weather["temperature"] >= 33:
            weather_note = f"🥵 폭염({weather['temperature']}°C)"
        elif weather["temperature"] <= -5:
            weather_note = f"🥶 한파({weather['temperature']}°C)"

    # Playwright로 Naver Map에서 영업 상태 조회
    naver_map = _fetch_naver_all_stores(stores)

    results = []
    for store in stores:
        store_name = store.get("name", "")

        # 이름 매칭
        naver_item = None
        for key, item in naver_map.items():
            item_short = key.replace("스타벅스 ", "").replace("스타벅스", "").replace("점", "").replace(" ", "")
            store_short = store_name.replace(" ", "")
            if store_short in item_short or item_short in store_short:
                naver_item = item
                break

        if naver_item:
            biz = _extract_business_status(naver_item)
            naver_id = naver_item.get("id", "")
            address = naver_item.get("roadAddress") or naver_item.get("address") or store.get("address", "")
        else:
            biz = {"is_open": True, "status_code": -1, "status_text": "알수없음", "detail": ""}
            naver_id = ""
            address = store.get("address", "")

        if biz["is_open"]:
            congestion_level, congestion_code = _estimate_congestion(store_name, weather_mod)
        else:
            congestion_level, congestion_code = "영업 외", "-1"

        results.append({
            "store_id": str(store["id"]),
            "naver_id": naver_id,
            "name": store_name,
            "address": address,
            "is_open": biz["is_open"],
            "status_text": biz["status_text"],
            "status_detail": biz["detail"],
            "congestion_level": congestion_level,
            "congestion_code": congestion_code,
            "weather": weather["description"],
            "weather_note": weather_note,
            "source": "naver_map+heuristic+weather",
        })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-id", help="단일 매장 ID")
    parser.add_argument("--config", default="config/stores.json")
    parser.add_argument("--mock", action="store_true", help="Mock 데이터 사용")
    args = parser.parse_args()

    try:
        with open(BASE_DIR / args.config, encoding="utf-8") as f:
            stores = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] {args.config} not found", file=sys.stderr)
        sys.exit(1)

    if args.store_id:
        stores = [s for s in stores if str(s["id"]) == args.store_id]
        if not stores:
            stores = [{"id": args.store_id, "name": args.store_id, "address": ""}]

    results = fetch_all(stores, use_mock=args.mock)

    if not results:
        print("[ERROR] 데이터 수집 실패", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
