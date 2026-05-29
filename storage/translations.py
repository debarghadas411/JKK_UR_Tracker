"""
Translations for Japanese listing field values → English.

Covers:
  - All 23 Tokyo special wards + major Tokyo cities
  - Floor plan codes (間取り)
  - Priority type (優先種別)
  - Housing type (住宅種別)
  - Japanese era-based dates (元号) → Gregorian
"""

import re
import unicodedata
from typing import Optional

# ---------------------------------------------------------------------------
# Ward / Area (区市名)
# ---------------------------------------------------------------------------

WARD_JP_TO_EN: dict[str, str] = {
    # 23 Special Wards of Tokyo (東京23区)
    "千代田区": "Chiyoda Ward",
    "中央区":   "Chuo Ward",
    "港区":     "Minato Ward",
    "新宿区":   "Shinjuku Ward",
    "文京区":   "Bunkyo Ward",
    "台東区":   "Taito Ward",
    "墨田区":   "Sumida Ward",
    "江東区":   "Koto Ward",
    "品川区":   "Shinagawa Ward",
    "目黒区":   "Meguro Ward",
    "大田区":   "Ota Ward",
    "世田谷区": "Setagaya Ward",
    "渋谷区":   "Shibuya Ward",
    "中野区":   "Nakano Ward",
    "杉並区":   "Suginami Ward",
    "豊島区":   "Toshima Ward",
    "北区":     "Kita Ward",
    "荒川区":   "Arakawa Ward",
    "板橋区":   "Itabashi Ward",
    "練馬区":   "Nerima Ward",
    "足立区":   "Adachi Ward",
    "葛飾区":   "Katsushika Ward",
    "江戸川区": "Edogawa Ward",
    # Cities in Tokyo (市部)
    "八王子市": "Hachioji City",
    "立川市":   "Tachikawa City",
    "武蔵野市": "Musashino City",
    "三鷹市":   "Mitaka City",
    "青梅市":   "Ome City",
    "府中市":   "Fuchu City",
    "昭島市":   "Akishima City",
    "調布市":   "Chofu City",
    "町田市":   "Machida City",
    "小金井市": "Koganei City",
    "小平市":   "Kodaira City",
    "日野市":   "Hino City",
    "東村山市": "Higashimurayama City",
    "国分寺市": "Kokubunji City",
    "国立市":   "Kunitachi City",
    "福生市":   "Fussa City",
    "狛江市":   "Komae City",
    "東大和市": "Higashiyamato City",
    "清瀬市":   "Kiyose City",
    "東久留米市": "Higashikurume City",
    "武蔵村山市": "Musashimurayama City",
    "多摩市":   "Tama City",
    "稲城市":   "Inagi City",
    "羽村市":   "Hamura City",
    "あきる野市": "Akiruno City",
    "西東京市": "Nishitokyo City",
}


def translate_ward(ward: Optional[str]) -> str:
    """Return the English ward/city name, or the original if no mapping exists."""
    if not ward:
        return ""
    return WARD_JP_TO_EN.get(ward.strip(), ward)


# ---------------------------------------------------------------------------
# Floor plan (間取り)
# ---------------------------------------------------------------------------

# Reverse map: UR English long-form → standard code
_FLOOR_PLAN_EN_TO_CODE: dict[str, str] = {
    "Studio":                          "1R",
    "1 Room + Kitchen":                "1K",
    "1 Room + Dining-Kitchen":         "1DK",
    "1 Room + Living-Dining-Kitchen":  "1LDK",
    "2 Rooms + Kitchen":               "2K",
    "2 Rooms + Dining-Kitchen":        "2DK",
    "2 Rooms + Living-Dining-Kitchen": "2LDK",
    "3 Rooms + Kitchen":               "3K",
    "3 Rooms + Dining-Kitchen":        "3DK",
    "3 Rooms + Living-Dining-Kitchen": "3LDK",
    "4 Rooms + Kitchen":               "4K",
    "4 Rooms + Dining-Kitchen":        "4DK",
    "4 Rooms + Living-Dining-Kitchen": "4LDK",
    "5 Rooms + Kitchen":               "5K",
    "5 Rooms + Dining-Kitchen":        "5DK",
    "5 Rooms + Living-Dining-Kitchen": "5LDK",
}

_FLOOR_TYPE_ORDER = {"K": 0, "DK": 1, "LDK": 2}
_FLOOR_PLAN_RE = re.compile(r'^(\d+)(LDK|DK|K)$')


def normalize_floor_plan(floor_plan: Optional[str]) -> str:
    """
    Return a standardised ASCII floor plan code (e.g. 1LDK, 2DK).

    Handles:
      - Fullwidth Japanese chars: １ＬＤＫ  → 1LDK  (via NFKC)
      - UR English long-form:     3 Rooms + Living-Dining-Kitchen → 3LDK
      - Already-ASCII codes:      2DK → 2DK
    """
    if not floor_plan:
        return ""
    fp = floor_plan.strip()
    # Try reverse English long-form lookup first
    if fp in _FLOOR_PLAN_EN_TO_CODE:
        return _FLOOR_PLAN_EN_TO_CODE[fp]
    # Normalise fullwidth → ASCII then uppercase
    fp = unicodedata.normalize("NFKC", fp).upper().strip()
    return fp


def floor_plan_sort_key(floor_plan: Optional[str]) -> tuple:
    """Return a (room_count, type_order) tuple for sorting floor plans numerically."""
    fp = normalize_floor_plan(floor_plan)
    m = _FLOOR_PLAN_RE.match(fp)
    if m:
        return (int(m.group(1)), _FLOOR_TYPE_ORDER.get(m.group(2), 99))
    return (999, 99)


# ---------------------------------------------------------------------------
# Priority type (優先種別)
# ---------------------------------------------------------------------------

PRIORITY_TYPE_JP_TO_EN: dict[str, str] = {
    "一般":       "General",
    "優先":       "Priority",
    "結婚予定者":  "Prospective Married Couple",
    "結婚 予定者": "Prospective Married Couple",
    "応援":       "Support / Subsidised",
    "新婚":       "Newlywed",
    "子育て":     "Child-Rearing",
    "高齢者":     "Senior",
    "障害者":     "Person with Disability",
}


def translate_priority_type(priority_type: Optional[str]) -> str:
    """Return the English label for a JKK priority category."""
    if not priority_type:
        return ""
    return PRIORITY_TYPE_JP_TO_EN.get(priority_type.strip(), priority_type)


# ---------------------------------------------------------------------------
# Housing type (住宅種別)
# ---------------------------------------------------------------------------

HOUSING_TYPE_JP_TO_EN: dict[str, str] = {
    "一般賃貸住宅":          "General Rental",
    "一般賃貸住宅（期限付）":  "General Rental (Fixed Term)",
    "都民住宅":              "Tokyo Metropolitan Housing",
    "都民住宅（期限付）":     "Tokyo Metropolitan Housing (Fixed Term)",
    "特定公共賃貸住宅":       "Designated Public Rental",
    "特定公共賃貸住宅（期限付）": "Designated Public Rental (Fixed Term)",
    "UR賃貸住宅":            "UR Public Housing",
}


def translate_housing_type(housing_type: Optional[str]) -> str:
    """Return the English label for a JKK housing type."""
    if not housing_type:
        return ""
    return HOUSING_TYPE_JP_TO_EN.get(housing_type.strip(), housing_type)


# ---------------------------------------------------------------------------
# Available date — handle Japanese era dates (元号)
# Era offsets from year 1 of each era to Gregorian year
# ---------------------------------------------------------------------------

_ERA_OFFSETS: dict[str, int] = {
    "令和": 2018,   # Reiwa  starts 2019  → year 1 = 2019 → offset = 2018
    "平成": 1988,   # Heisei starts 1989  → offset = 1988
    "昭和": 1925,   # Showa  starts 1926  → offset = 1925
    "大正": 1911,   # Taisho starts 1912  → offset = 1911
    "明治": 1867,   # Meiji  starts 1868  → offset = 1867
}

# Pattern: era + year + 年 + optional month + 月 + optional day + 日
_ERA_DATE_RE = re.compile(
    r"(令和|平成|昭和|大正|明治)\s*(\d+)\s*年\s*(?:(\d+)\s*月\s*(?:(\d+)\s*日)?)?",
    re.UNICODE,
)

# Pattern: 元年 (first year) shorthand
_GANNEN_RE = re.compile(
    r"(令和|平成|昭和|大正|明治)\s*元年\s*(?:(\d+)\s*月\s*(?:(\d+)\s*日)?)?",
    re.UNICODE,
)


def translate_date(date_str: Optional[str]) -> str:
    """
    Convert a Japanese era date string to ISO-style Gregorian (YYYY-MM-DD or YYYY-MM or YYYY).
    If the date is already Gregorian or unrecognised, return it unchanged.
    """
    if not date_str:
        return ""

    text = date_str.strip()

    # Try 元年 (year 1) shorthand first
    m = _GANNEN_RE.search(text)
    if m:
        era, month, day = m.group(1), m.group(2), m.group(3)
        greg_year = _ERA_OFFSETS.get(era, 0) + 1
        return _format_date(greg_year, month, day)

    # Try normal era year
    m = _ERA_DATE_RE.search(text)
    if m:
        era, year_str, month, day = m.group(1), m.group(2), m.group(3), m.group(4)
        greg_year = _ERA_OFFSETS.get(era, 0) + int(year_str)
        return _format_date(greg_year, month, day)

    return text


def _format_date(year: int, month: Optional[str], day: Optional[str]) -> str:
    if month and day:
        return f"{year:04d}-{int(month):02d}-{int(day):02d}"
    if month:
        return f"{year:04d}-{int(month):02d}"
    return str(year)


# ---------------------------------------------------------------------------
# Available-from date (入居可能日) → English
# ---------------------------------------------------------------------------

_AVAILABLE_FROM_FIXED: dict[str, str] = {
    "即入居可": "Immediately Available",
    "随時":     "Anytime",
}

# Matches: 2026年5月30日以降
_GREGORIAN_FROM_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日以降")


def translate_available_from(date_str: Optional[str]) -> str:
    """Translate Japanese available-from strings to English."""
    if not date_str:
        return ""
    text = date_str.strip()
    if text in _AVAILABLE_FROM_FIXED:
        return _AVAILABLE_FROM_FIXED[text]
    m = _GREGORIAN_FROM_RE.search(text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"From {y}-{mo:02d}-{d:02d}"
    return text
