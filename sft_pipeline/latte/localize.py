"""MS-LaTTE 파싱 시드 → 한국어 라벨 현지화(결정론적, API 불필요).

영어 task_title 번역과 대화 작문은 하류 LLM 합성 단계의 책임이다.
이 단계는 위치/시간 라벨만 한국어로 결정론적 매핑한다(테스트 가능).
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

SEED_COLUMNS = ["id", "task_title", "broad_ko", "place_ko", "times_ko"]

_DAY_KO = {"WE": "주말", "WD": "평일"}
_SLOT_KO = {
    "morning": "아침",
    "afternoon": "오후",
    "evening": "저녁",
    "night": "밤",
    "anytime": "아무때나",
}

_BROAD_KO = {"home": "집", "work": "회사", "public": "외부"}

# MS-LaTTE 세부 public 카테고리(59종) → 한국 일상 장소.
_PUBLIC_KO = {
    "grocery": "마트",
    "ethnicgrocery": "식료품점",
    "electronics": "전자제품 매장",
    "autorepair": "자동차 정비소",
    "autoparts": "자동차 부품점",
    "home+garden": "홈·가든 매장",
    "clothing": "옷가게",
    "footwear": "신발가게",
    "hardware": "철물점",
    "bank": "은행",
    "atm": "ATM",
    "pharmacy": "약국",
    "officesupply": "문구점",
    "doctor": "병원",
    "hospital": "병원",
    "dentist": "치과",
    "vet": "동물병원",
    "optician": "안경점",
    "sportinggoods": "스포츠용품점",
    "gym": "헬스장",
    "pool": "수영장",
    "park": "공원",
    "hairsalon": "미용실",
    "beautysalon": "뷰티샵",
    "courier": "택배 영업점",
    "taxservice": "세무 사무소",
    "drycleaning": "세탁소",
    "laundromat": "빨래방",
    "library": "도서관",
    "bookstore": "서점",
    "petsupply": "반려동물용품점",
    "petadoption": "동물 입양센터",
    "adoptionservice": "입양 기관",
    "lawyer": "법률사무소",
    "carwash": "세차장",
    "cardealer": "자동차 대리점",
    "postoffice": "우체국",
    "govtoffice": "관공서",
    "court": "법원",
    "dmv": "차량등록소",
    "gasstation": "주유소",
    "musicstore": "악기점",
    "jewelry": "귀금속점",
    "airport": "공항",
    "hotel": "호텔",
    "partysupply": "파티용품점",
    "giftshop": "선물가게",
    "insurance": "보험사",
    "farm": "농장",
    "restaurant": "식당",
    "bakery": "빵집",
    "recycling": "재활용 센터",
    "telecom": "통신사 대리점",
    "movtheater": "영화관",
    "gunstore": "총포상",
}


def decode_time(code: str) -> str:
    """'WE-morning' → '주말 아침'. 매핑 실패 시 빈 문자열."""
    parts = code.split("-", 1)
    if len(parts) != 2:
        return ""
    day, slot = _DAY_KO.get(parts[0]), _SLOT_KO.get(parts[1])
    if not day or not slot:
        return ""
    return f"{day} {slot}"


def _map_compound(value: str, table: dict) -> str:
    """콤마구분 복합값을 각각 매핑 후 중복 제거하고 '/'로 합친다(순서 보존)."""
    out: list[str] = []
    for part in value.split(","):
        part = part.strip()
        ko = table.get(part)
        if ko and ko not in out:
            out.append(ko)
    return "/".join(out)


def localize_broad(broad: str) -> str:
    return _map_compound(broad, _BROAD_KO)


def localize_public(public: str) -> str:
    return _map_compound(public, _PUBLIC_KO)


def localize_place(broad: str, public: str) -> str:
    """세부 public 장소가 매핑되면 우선, 아니면 broad 라벨."""
    if public:
        place = localize_public(public)
        if place:
            return place
    return localize_broad(broad)


def localize_seed(seed: dict) -> dict | None:
    times_ko = [t for t in (decode_time(c) for c in seed.get("top_times", [])) if t]
    place_ko = localize_place(seed.get("broad_location", ""), seed.get("public_location", ""))
    if not place_ko or not times_ko:
        return None
    return {
        "id": seed.get("id", ""),
        "task_title": seed.get("task_title", ""),
        "broad_ko": localize_broad(seed.get("broad_location", "")),
        "place_ko": place_ko,
        "times_ko": times_ko,
    }


def localize_seeds(seeds: list[dict]) -> list[dict]:
    return [out for out in (localize_seed(s) for s in seeds) if out is not None]


def load_parsed(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["top_times"] = [t for t in str(row.get("top_times", "")).split(";") if t]
    return rows


def write_csv(seeds: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SEED_COLUMNS)
        writer.writeheader()
        for seed in seeds:
            row = dict(seed)
            row["times_ko"] = ";".join(seed["times_ko"])
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="latte_parsed.csv → daily_seeds.csv (한국어 라벨)")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    parsed = load_parsed(args.in_path)
    seeds = localize_seeds(parsed)
    write_csv(seeds, args.out_path)
    print(f"localized {len(seeds)}/{len(parsed)} seeds -> {args.out_path}")


if __name__ == "__main__":
    main()
