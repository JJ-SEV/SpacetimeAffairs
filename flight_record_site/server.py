from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse
import cgi
import hashlib
import hmac
import html
import json
import mimetypes
import os
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = APP_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
GENERATED_DIR = DATA_DIR / "generated"
PREVIEW_DIR = DATA_DIR / "previews"
DB_PATH = DATA_DIR / "flight_record.sqlite3"
ADMIN_SECRET_PATH = DATA_DIR / "admin_secret.txt"
ADMIN_PASSWORD_PATH = DATA_DIR / "admin_password.txt"
AMAP_KEY_PATH = DATA_DIR / "amap_key.txt"
STAMP_ANIMATION_TEMPLATE_PATH = APP_ROOT / "static" / "stamp-animation" / "index.html"
GALLERY_STATIC_DIR = APP_ROOT / "gallery_assets"
ADMIN_COOKIE = "flight_record_admin"
PLAYER_COOKIE = "flight_record_player"
_ADMIN_SECRET_CACHE: str | None = None
_ADMIN_PASSWORD_CACHE: str | None = None
_ADDRESS_SUGGEST_CACHE: dict[str, list[dict[str, object]]] = {}
_ADDRESS_GEOCODE_CACHE: dict[str, dict[str, object] | None] = {}
DOWNLOAD_UNLOCK_TZ = ZoneInfo("Asia/Shanghai")
DOWNLOAD_UNLOCK_AT = datetime(2026, 6, 13, 0, 0, 0, tzinfo=DOWNLOAD_UNLOCK_TZ)
DOWNLOAD_UNLOCK_ISO = DOWNLOAD_UNLOCK_AT.isoformat()
DOWNLOAD_UNLOCK_LABEL = "2026-06-13 00:00 中国北京时间"
LOCKED_PREVIEW_MAX_DIMENSION = 1400
LOCKED_PREVIEW_BADGE_VERSION = "v4"
ANIMATION_PREVIEW_MAX_DIMENSION = 1400
ANIMATION_PREVIEW_VERSION = "unstamped-v1"
RECORD_JPG_VERSION = "jpg-v1"
STATIC_GALLERY_ITEMS = (
    {"slug": "bantouming-qinzhan", "title": "半透明侵占", "file": "bantouming-qinzhan.jpg"},
    {"slug": "shuangying-jiaodieshi", "title": "双影交叠时", "file": "shuangying-jiaodieshi.jpg"},
    {"slug": "benyong-02", "title": "奔涌02", "file": "benyong-02.jpg"},
    {"slug": "benyong-01", "title": "奔涌01", "file": "benyong-01.jpg"},
    {"slug": "zunming-siyangguan-02", "title": "遵命饲养官02", "file": "zunming-siyangguan-02.jpg"},
    {"slug": "zunming-siyangguan-01", "title": "遵命饲养官01", "file": "zunming-siyangguan-01.jpg"},
)
STATIC_GALLERY_BY_SLUG = {item["slug"]: item for item in STATIC_GALLERY_ITEMS}
_ANIMATION_PREVIEW_LOCK = threading.Lock()
_ANIMATION_PREVIEW_WARMING: set[str] = set()
_ANIMATION_PREVIEW_WARMING_LOCK = threading.Lock()

sys.path.insert(0, str(ROOT / "scripts"))
import render_xia_yizhou_pilot_flight_record_v2 as flight_renderer  # noqa: E402


def admin_secret() -> str:
    global _ADMIN_SECRET_CACHE
    if _ADMIN_SECRET_CACHE:
        return _ADMIN_SECRET_CACHE
    if secret := os.environ.get("FLIGHT_RECORD_ADMIN_SECRET"):
        _ADMIN_SECRET_CACHE = secret
        return secret
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ADMIN_SECRET_PATH.exists():
        _ADMIN_SECRET_CACHE = ADMIN_SECRET_PATH.read_text(encoding="utf-8").strip()
        return _ADMIN_SECRET_CACHE
    secret = secrets.token_urlsafe(24)
    ADMIN_SECRET_PATH.write_text(secret + "\n", encoding="utf-8")
    _ADMIN_SECRET_CACHE = secret
    return secret


def admin_cookie_token() -> str:
    return hmac.new(admin_secret().encode("utf-8"), b"flight-record-admin", hashlib.sha256).hexdigest()


def player_cookie_token() -> str:
    return hmac.new(admin_secret().encode("utf-8"), b"flight-record-player", hashlib.sha256).hexdigest()


def admin_password() -> str:
    global _ADMIN_PASSWORD_CACHE
    if _ADMIN_PASSWORD_CACHE:
        return _ADMIN_PASSWORD_CACHE
    if password := os.environ.get("FLIGHT_RECORD_ADMIN_PASSWORD"):
        _ADMIN_PASSWORD_CACHE = password
        return password
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ADMIN_PASSWORD_PATH.exists():
        _ADMIN_PASSWORD_CACHE = ADMIN_PASSWORD_PATH.read_text(encoding="utf-8").strip()
        return _ADMIN_PASSWORD_CACHE
    password = secrets.token_urlsafe(9)
    ADMIN_PASSWORD_PATH.write_text(password + "\n", encoding="utf-8")
    _ADMIN_PASSWORD_CACHE = password
    return password


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def shanghai_now() -> datetime:
    return datetime.now(DOWNLOAD_UNLOCK_TZ)


def downloads_unlocked(now: datetime | None = None) -> bool:
    return (now or shanghai_now()) >= DOWNLOAD_UNLOCK_AT


def ensure_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                contact TEXT,
                original_filename TEXT,
                stored_filename TEXT,
                review_note TEXT,
                reviewed_at TEXT,
                destination_name TEXT,
                address_hash TEXT,
                destination_coordinate TEXT,
                png_filename TEXT,
                pdf_filename TEXT,
                generated_at TEXT
            )
            """
        )
        submission_columns = {row[1] for row in db.execute("PRAGMA table_info(submissions)")}
        if "user_id" not in submission_columns:
            db.execute("ALTER TABLE submissions ADD COLUMN user_id TEXT")
        if "user_key" not in submission_columns:
            db.execute("ALTER TABLE submissions ADD COLUMN user_key TEXT")
        if "bond_original_filename" not in submission_columns:
            db.execute("ALTER TABLE submissions ADD COLUMN bond_original_filename TEXT")
        if "bond_stored_filename" not in submission_columns:
            db.execute("ALTER TABLE submissions ADD COLUMN bond_stored_filename TEXT")
        if "home_original_filename" not in submission_columns:
            db.execute("ALTER TABLE submissions ADD COLUMN home_original_filename TEXT")
        if "home_stored_filename" not in submission_columns:
            db.execute("ALTER TABLE submissions ADD COLUMN home_stored_filename TEXT")
        db.execute(
            """
            UPDATE submissions
            SET user_id = contact
            WHERE (user_id IS NULL OR TRIM(user_id) = '') AND contact IS NOT NULL
            """
        )
        db.execute(
            """
            UPDATE submissions
            SET user_key = LOWER(REPLACE(REPLACE(TRIM(contact), ' ', ''), char(9), ''))
            WHERE (user_key IS NULL OR TRIM(user_key) = '') AND contact IS NOT NULL
            """
        )
        db.execute(
            """
            UPDATE submissions
            SET bond_original_filename = original_filename
            WHERE (bond_original_filename IS NULL OR TRIM(bond_original_filename) = '')
              AND original_filename IS NOT NULL
            """
        )
        db.execute(
            """
            UPDATE submissions
            SET bond_stored_filename = stored_filename
            WHERE (bond_stored_filename IS NULL OR TRIM(bond_stored_filename) = '')
              AND stored_filename IS NOT NULL
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS download_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT NOT NULL,
                user_id TEXT,
                file_type TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                downloaded_at TEXT NOT NULL,
                client_ip TEXT,
                user_agent TEXT
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_user_key ON submissions(user_key)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_download_events_submission ON download_events(submission_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_download_events_user ON download_events(user_id)")


def db_row(query: str, params: tuple = ()) -> sqlite3.Row | None:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(query, params).fetchone()


def db_rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(query, params).fetchall()


def db_execute(query: str, params: tuple = ()) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(query, params)


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


LOCAL_PLACES: tuple[dict[str, object], ...] = (
    {"name": "上海市", "address": "上海市", "lat": 31.2304, "lon": 121.4737, "kind": "城市", "aliases": ("上海",)},
    {"name": "上海市黄浦区", "address": "上海市黄浦区", "lat": 31.2317, "lon": 121.4844, "kind": "行政区", "aliases": ("黄浦", "黄浦区")},
    {"name": "上海市徐汇区", "address": "上海市徐汇区", "lat": 31.1885, "lon": 121.4368, "kind": "行政区", "aliases": ("徐汇", "徐汇区")},
    {"name": "上海市长宁区", "address": "上海市长宁区", "lat": 31.2204, "lon": 121.4246, "kind": "行政区", "aliases": ("长宁", "长宁区")},
    {"name": "上海市静安区", "address": "上海市静安区", "lat": 31.2277, "lon": 121.4473, "kind": "行政区", "aliases": ("静安", "静安区")},
    {"name": "上海市普陀区", "address": "上海市普陀区", "lat": 31.2496, "lon": 121.3955, "kind": "行政区", "aliases": ("普陀", "普陀区")},
    {"name": "上海市虹口区", "address": "上海市虹口区", "lat": 31.2708, "lon": 121.5050, "kind": "行政区", "aliases": ("虹口", "虹口区")},
    {"name": "上海市杨浦区", "address": "上海市杨浦区", "lat": 31.2595, "lon": 121.5261, "kind": "行政区", "aliases": ("杨浦", "杨浦区")},
    {"name": "上海市浦东新区", "address": "上海市浦东新区", "lat": 31.2215, "lon": 121.5440, "kind": "行政区", "aliases": ("浦东", "浦东新区")},
    {"name": "上海市闵行区", "address": "上海市闵行区", "lat": 31.1128, "lon": 121.3817, "kind": "行政区", "aliases": ("闵行", "闵行区")},
    {"name": "上海市宝山区", "address": "上海市宝山区", "lat": 31.4053, "lon": 121.4899, "kind": "行政区", "aliases": ("宝山", "宝山区")},
    {"name": "上海市嘉定区", "address": "上海市嘉定区", "lat": 31.3835, "lon": 121.2653, "kind": "行政区", "aliases": ("嘉定", "嘉定区")},
    {"name": "上海市金山区", "address": "上海市金山区", "lat": 30.7419, "lon": 121.3419, "kind": "行政区", "aliases": ("金山", "金山区")},
    {"name": "上海市松江区", "address": "上海市松江区", "lat": 31.0322, "lon": 121.2277, "kind": "行政区", "aliases": ("松江", "松江区")},
    {"name": "上海市青浦区", "address": "上海市青浦区", "lat": 31.1512, "lon": 121.1242, "kind": "行政区", "aliases": ("青浦", "青浦区")},
    {"name": "上海市奉贤区", "address": "上海市奉贤区", "lat": 30.9178, "lon": 121.4740, "kind": "行政区", "aliases": ("奉贤", "奉贤区")},
    {"name": "上海市崇明区", "address": "上海市崇明区", "lat": 31.6229, "lon": 121.3975, "kind": "行政区", "aliases": ("崇明", "崇明区")},
    {"name": "云岭东路", "address": "上海市普陀区云岭东路", "lat": 31.2244, "lon": 121.3980, "kind": "道路", "aliases": ("上海普陀区云岭东路", "普陀云岭东路", "云岭东路")},
    {"name": "曹杨路", "address": "上海市普陀区曹杨路", "lat": 31.2412, "lon": 121.4175, "kind": "道路", "aliases": ("上海普陀区曹杨路", "普陀曹杨路")},
    {"name": "武宁路", "address": "上海市普陀区武宁路", "lat": 31.2418, "lon": 121.4211, "kind": "道路", "aliases": ("上海普陀区武宁路", "普陀武宁路")},
    {"name": "真如", "address": "上海市普陀区真如", "lat": 31.2526, "lon": 121.4025, "kind": "地点", "aliases": ("上海普陀真如", "真如镇")},
    {"name": "桃浦", "address": "上海市普陀区桃浦", "lat": 31.2794, "lon": 121.3713, "kind": "地点", "aliases": ("上海普陀桃浦",)},
    {"name": "中山北路", "address": "上海市普陀区中山北路", "lat": 31.2434, "lon": 121.4142, "kind": "道路", "aliases": ("上海普陀区中山北路", "普陀中山北路")},
    {"name": "长风公园", "address": "上海市普陀区大渡河路189号", "lat": 31.2269, "lon": 121.3958, "kind": "地点", "aliases": ("上海长风公园", "普陀长风公园")},
    {"name": "环球港", "address": "上海市普陀区中山北路3300号", "lat": 31.2313, "lon": 121.4139, "kind": "地点", "aliases": ("上海环球港", "月星环球港")},
    {"name": "外滩", "address": "上海市黄浦区中山东一路", "lat": 31.2404, "lon": 121.4903, "kind": "地点", "aliases": ("上海外滩", "中山东一路")},
    {"name": "陆家嘴", "address": "上海市浦东新区陆家嘴", "lat": 31.2381, "lon": 121.4998, "kind": "地点", "aliases": ("上海陆家嘴",)},
    {"name": "人民广场", "address": "上海市黄浦区人民广场", "lat": 31.2304, "lon": 121.4737, "kind": "地点", "aliases": ("上海人民广场",)},
    {"name": "南京东路", "address": "上海市黄浦区南京东路", "lat": 31.2362, "lon": 121.4849, "kind": "道路", "aliases": ("上海南京东路",)},
    {"name": "徐家汇", "address": "上海市徐汇区徐家汇", "lat": 31.1832, "lon": 121.4365, "kind": "地点", "aliases": ("上海徐家汇",)},
    {"name": "静安寺", "address": "上海市静安区静安寺", "lat": 31.2234, "lon": 121.4453, "kind": "地点", "aliases": ("上海静安寺",)},
    {"name": "武康路", "address": "上海市徐汇区武康路", "lat": 31.2105, "lon": 121.4382, "kind": "道路", "aliases": ("上海武康路",)},
    {"name": "上海迪士尼度假区", "address": "上海市浦东新区川沙新镇", "lat": 31.1434, "lon": 121.6579, "kind": "地点", "aliases": ("上海迪士尼", "迪士尼")},
    {"name": "上海虹桥站", "address": "上海市闵行区申贵路1500号", "lat": 31.1942, "lon": 121.3207, "kind": "交通枢纽", "aliases": ("虹桥站", "虹桥火车站", "上海虹桥火车站")},
    {"name": "北京市", "address": "北京市", "lat": 39.9042, "lon": 116.4074, "kind": "城市", "aliases": ("北京",)},
    {"name": "北京市东城区", "address": "北京市东城区", "lat": 39.9289, "lon": 116.4164, "kind": "行政区", "aliases": ("北京东城", "东城区")},
    {"name": "北京市西城区", "address": "北京市西城区", "lat": 39.9123, "lon": 116.3659, "kind": "行政区", "aliases": ("北京西城", "西城区")},
    {"name": "北京市朝阳区", "address": "北京市朝阳区", "lat": 39.9219, "lon": 116.4431, "kind": "行政区", "aliases": ("北京朝阳", "朝阳区")},
    {"name": "北京市海淀区", "address": "北京市海淀区", "lat": 39.9599, "lon": 116.2981, "kind": "行政区", "aliases": ("北京海淀", "海淀区")},
    {"name": "北京市丰台区", "address": "北京市丰台区", "lat": 39.8584, "lon": 116.2867, "kind": "行政区", "aliases": ("北京丰台", "丰台区")},
    {"name": "北京市石景山区", "address": "北京市石景山区", "lat": 39.9066, "lon": 116.2229, "kind": "行政区", "aliases": ("北京石景山", "石景山区")},
    {"name": "北京市通州区", "address": "北京市通州区", "lat": 39.9099, "lon": 116.6564, "kind": "行政区", "aliases": ("北京通州", "通州区")},
    {"name": "三里屯", "address": "北京市朝阳区三里屯", "lat": 39.9336, "lon": 116.4551, "kind": "地点", "aliases": ("北京三里屯", "朝阳三里屯")},
    {"name": "望京", "address": "北京市朝阳区望京", "lat": 39.9968, "lon": 116.4697, "kind": "地点", "aliases": ("北京望京", "朝阳望京")},
    {"name": "国贸", "address": "北京市朝阳区建国门外大街", "lat": 39.9097, "lon": 116.4600, "kind": "地点", "aliases": ("北京国贸", "中国国际贸易中心")},
    {"name": "五道口", "address": "北京市海淀区五道口", "lat": 39.9928, "lon": 116.3372, "kind": "地点", "aliases": ("北京五道口", "海淀五道口")},
    {"name": "中关村", "address": "北京市海淀区中关村", "lat": 39.9841, "lon": 116.3162, "kind": "地点", "aliases": ("北京中关村", "海淀中关村")},
    {"name": "天安门广场", "address": "北京市东城区天安门广场", "lat": 39.9056, "lon": 116.3976, "kind": "地点", "aliases": ("北京天安门", "天安门")},
    {"name": "故宫博物院", "address": "北京市东城区景山前街4号", "lat": 39.9163, "lon": 116.3972, "kind": "地点", "aliases": ("北京故宫", "故宫")},
    {"name": "北京南站", "address": "北京市丰台区北京南站", "lat": 39.8652, "lon": 116.3785, "kind": "交通枢纽", "aliases": ("北京南", "北京南站")},
    {"name": "广州市", "address": "广东省广州市", "lat": 23.1291, "lon": 113.2644, "kind": "城市", "aliases": ("广州",)},
    {"name": "深圳市", "address": "广东省深圳市", "lat": 22.5431, "lon": 114.0579, "kind": "城市", "aliases": ("深圳",)},
    {"name": "杭州市", "address": "浙江省杭州市", "lat": 30.2741, "lon": 120.1551, "kind": "城市", "aliases": ("杭州",)},
    {"name": "南京市", "address": "江苏省南京市", "lat": 32.0603, "lon": 118.7969, "kind": "城市", "aliases": ("南京",)},
    {"name": "苏州市", "address": "江苏省苏州市", "lat": 31.2989, "lon": 120.5853, "kind": "城市", "aliases": ("苏州",)},
    {"name": "成都市", "address": "四川省成都市", "lat": 30.5728, "lon": 104.0668, "kind": "城市", "aliases": ("成都",)},
    {"name": "重庆市", "address": "重庆市", "lat": 29.5630, "lon": 106.5516, "kind": "城市", "aliases": ("重庆",)},
    {"name": "武汉市", "address": "湖北省武汉市", "lat": 30.5928, "lon": 114.3055, "kind": "城市", "aliases": ("武汉",)},
    {"name": "西安市", "address": "陕西省西安市", "lat": 34.3416, "lon": 108.9398, "kind": "城市", "aliases": ("西安",)},
)


def amap_key() -> str:
    if key := os.environ.get("FLIGHT_RECORD_AMAP_KEY"):
        return key.strip()
    if AMAP_KEY_PATH.exists():
        return AMAP_KEY_PATH.read_text(encoding="utf-8").strip()
    return ""


def normalize_address(address: str) -> str:
    return " ".join(address.strip().split()).lower()


def normalize_place_query(value: str) -> str:
    return "".join(value.strip().lower().split())


def fuzzy_place_term(value: str) -> str:
    term = normalize_place_query(value)
    for token in ("省", "市", "区", "县", "自治州", "特别行政区"):
        term = term.replace(token, "")
    return term


def parse_location(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    if not value or value == "[]":
        return None
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        lon = float(parts[0])
        lat = float(parts[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def location_from_fields(lat_text: str, lon_text: str) -> tuple[float, float] | None:
    try:
        lat = float(lat_text)
        lon = float(lon_text)
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def place_aliases(place: dict[str, object]) -> set[str]:
    aliases = {str(place["name"]), str(place["address"])}
    aliases.update(str(alias) for alias in place.get("aliases", ()))
    return aliases


def place_match_terms(place: dict[str, object]) -> set[str]:
    terms: set[str] = set()
    for alias in place_aliases(place):
        terms.add(normalize_place_query(alias))
        terms.add(fuzzy_place_term(alias))
    return {term for term in terms if term}


def place_result(place: dict[str, object], source: str = "built-in") -> dict[str, object]:
    return {
        "name": place["name"],
        "address": place["address"],
        "kind": place["kind"],
        "lat": place["lat"],
        "lon": place["lon"],
        "source": source,
    }


def local_address_matches(query: str, limit: int = 6) -> list[dict[str, object]]:
    q = normalize_place_query(query)
    fuzzy_q = fuzzy_place_term(query)
    if len(q) < 2:
        return []
    matches: list[tuple[int, dict[str, object]]] = []
    for place in LOCAL_PLACES:
        score = 0
        for a in place_match_terms(place):
            if not a:
                continue
            if q == a:
                score = max(score, 130 + len(a))
            elif fuzzy_q and fuzzy_q == a:
                score = max(score, 124 + len(a))
            elif a in q:
                score = max(score, 105 + len(a))
            elif fuzzy_q and a in fuzzy_q:
                score = max(score, 100 + len(a))
            elif q in a:
                score = max(score, 80 + len(q))
            elif fuzzy_q and fuzzy_q in a:
                score = max(score, 74 + len(fuzzy_q))
        if score:
            matches.append((score, place_result(place)))
    matches.sort(key=lambda item: (-item[0], len(str(item[1]["address"]))))
    return [match for _, match in matches[:limit]]


def custom_address_result(query: str) -> dict[str, object]:
    cleaned = " ".join(query.strip().split())
    return {
        "name": f"按输入使用：{cleaned}",
        "address": cleaned,
        "kind": "自定义位置",
        "source": "custom",
    }


def fetch_json(url: str, timeout: float = 4.0) -> dict[str, object] | None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CalebFlightRecord/0.1",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def amap_inputtips(query: str, limit: int = 6) -> list[dict[str, object]]:
    key = amap_key()
    if not key:
        return []
    params = urllib.parse.urlencode(
        {
            "key": key,
            "keywords": query,
            "city": "全国",
            "datatype": "all",
        }
    )
    data = fetch_json(f"https://restapi.amap.com/v3/assistant/inputtips?{params}")
    if not data or data.get("status") != "1":
        return []
    results: list[dict[str, object]] = []
    for tip in data.get("tips", []):
        if not isinstance(tip, dict):
            continue
        name = str(tip.get("name") or "").strip()
        if not name:
            continue
        district = str(tip.get("district") or "").strip()
        address = str(tip.get("address") or "").strip()
        location = parse_location(tip.get("location"))
        full_address = " ".join(piece for piece in (district, address, name) if piece and piece != "[]")
        result: dict[str, object] = {
            "name": name,
            "address": full_address or name,
            "kind": "地图候选",
            "source": "amap",
        }
        if location:
            result["lat"], result["lon"] = location
        results.append(result)
        if len(results) >= limit:
            break
    return results


def amap_geocode(address: str) -> dict[str, object] | None:
    key = amap_key()
    if not key:
        return None
    cache_key = normalize_place_query(address)
    if cache_key in _ADDRESS_GEOCODE_CACHE:
        return _ADDRESS_GEOCODE_CACHE[cache_key]
    params = urllib.parse.urlencode({"key": key, "address": address})
    data = fetch_json(f"https://restapi.amap.com/v3/geocode/geo?{params}")
    if not data or data.get("status") != "1":
        _ADDRESS_GEOCODE_CACHE[cache_key] = None
        return None
    geocodes = data.get("geocodes", [])
    if not isinstance(geocodes, list) or not geocodes:
        _ADDRESS_GEOCODE_CACHE[cache_key] = None
        return None
    first = geocodes[0]
    if not isinstance(first, dict):
        _ADDRESS_GEOCODE_CACHE[cache_key] = None
        return None
    location = parse_location(first.get("location"))
    if not location:
        _ADDRESS_GEOCODE_CACHE[cache_key] = None
        return None
    lat, lon = location
    formatted = str(first.get("formatted_address") or address).strip()
    result = {"name": formatted, "address": formatted, "kind": "地图定位", "source": "amap", "lat": lat, "lon": lon}
    _ADDRESS_GEOCODE_CACHE[cache_key] = result
    return result


def address_suggestions(query: str, limit: int = 6) -> list[dict[str, object]]:
    cache_key = f"{bool(amap_key())}:{normalize_place_query(query)}"
    if cache_key in _ADDRESS_SUGGEST_CACHE:
        return _ADDRESS_SUGGEST_CACHE[cache_key]
    results: list[dict[str, object]] = []
    if normalize_place_query(query):
        results.append(custom_address_result(query))
    _ADDRESS_SUGGEST_CACHE[cache_key] = results
    return results


def resolve_address_location(address: str, lat_text: str = "", lon_text: str = "", label: str = "") -> dict[str, object] | None:
    selected = location_from_fields(lat_text, lon_text)
    if selected:
        lat, lon = selected
        display = label.strip() or address
        return {"name": display, "address": display, "kind": "已选候选", "source": "selected", "lat": lat, "lon": lon}
    remote = amap_geocode(address)
    if remote:
        return remote
    return None


def coordinate_from_location(lat: float, lon: float, label: str) -> str:
    digest = hashlib.sha256(f"{lat:.6f},{lon:.6f}:{label}".encode("utf-8")).hexdigest()
    a = int(abs(lon) * 10000) % 9000 + 1000
    b = int(abs(lat) * 1000) % 900 + 100
    c = 1 if lat >= 0 else 2
    d = 1 if lon >= 0 else 2
    e = int(digest[:4], 16) % 10000
    return f".{a:04d} {b:03d} {c} {d} [{e:04d}]"


def random_destination_coordinate() -> tuple[str, str]:
    while True:
        a = secrets.randbelow(9000) + 1000
        b = secrets.randbelow(900) + 100
        c = secrets.randbelow(9) + 1
        d = secrets.randbelow(9) + 1
        e = secrets.randbelow(10000)
        coord = f".{a:04d} {b:03d} {c} {d} [{e:04d}]"
        existing = db_row("SELECT id FROM submissions WHERE destination_coordinate = ? LIMIT 1", (coord,))
        if existing is None:
            token = secrets.token_urlsafe(18)
            return coord, hashlib.sha256(f"random:{coord}:{token}".encode("utf-8")).hexdigest()


def coordinate_from_address(address: str, lat_text: str = "", lon_text: str = "", label: str = "") -> tuple[str, str]:
    normalized = normalize_address(address)
    location = resolve_address_location(address, lat_text, lon_text, label)
    if location and "lat" in location and "lon" in location:
        lat = float(location["lat"])
        lon = float(location["lon"])
        location_label = str(location.get("address") or location.get("name") or address)
        coord = coordinate_from_location(lat, lon, location_label)
        address_key = f"geo:{normalized}:{lat:.6f}:{lon:.6f}:{location_label}"
        return coord, hashlib.sha256(address_key.encode("utf-8")).hexdigest()
    digest = hashlib.sha256(("caleb-destination-coordinate-v1:" + normalized).encode("utf-8")).hexdigest()
    a = int(digest[0:4], 16) % 9000 + 1000
    b = int(digest[4:8], 16) % 900 + 100
    c = int(digest[8:10], 16) % 9 + 1
    d = int(digest[10:12], 16) % 9 + 1
    e = int(digest[12:16], 16) % 10000
    coord = f".{a} {b} {c} {d} [{e:04d}]"
    return coord, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generated_record_names() -> tuple[str, str]:
    while True:
        archive_number = f"{secrets.randbelow(10000):04d}"
        stem = f"calebflightrecord-{archive_number}"
        png_name = f"{stem}.png"
        pdf_name = f"{stem}.pdf"
        existing = db_row(
            "SELECT id FROM submissions WHERE png_filename = ? OR pdf_filename = ?",
            (png_name, pdf_name),
        )
        if existing is None and not (GENERATED_DIR / png_name).exists() and not (GENERATED_DIR / pdf_name).exists():
            return png_name, pdf_name


def normalize_contact(contact: str) -> str:
    return "".join(contact.split()).lower()


def normalize_submission_id(value: str) -> str:
    return "".join(ch for ch in value.strip().upper() if ch.isalnum())[:12]


VALID_PILOT_IDS = {"CALEB", "XIAYIZHOU"}


def row_field(row: sqlite3.Row, name: str, default: str = "") -> str:
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else str(value)


def row_user_id(row: sqlite3.Row) -> str:
    return row_field(row, "user_id") or row_field(row, "contact")


def proof_filename(row: sqlite3.Row, kind: str) -> str:
    if kind == "home":
        return row_field(row, "home_original_filename")
    return row_field(row, "bond_original_filename") or row_field(row, "original_filename")


def proof_stored_filename(row: sqlite3.Row, kind: str) -> str:
    if kind == "home":
        return row_field(row, "home_stored_filename")
    return row_field(row, "bond_stored_filename") or row_field(row, "stored_filename")


def proof_summary_html(row: sqlite3.Row, linked: bool = False) -> str:
    items = []
    for kind, label in (("bond", "牵绊度页面"), ("home", "主页")):
        filename = proof_filename(row, kind)
        stored = proof_stored_filename(row, kind)
        if filename and stored:
            if linked:
                href = f"/proof?id={quote(row['id'])}&kind={kind}"
                content = f'<a href="{href}" target="_blank" rel="noopener">{esc(filename)}</a>'
            else:
                content = esc(filename)
        else:
            content = '<span class="muted">旧提交未上传</span>'
        items.append(f"<li><b>{label}</b><span>{content}</span></li>")
    return f'<ul class="proof-list">{"".join(items)}</ul>'


def uploaded_file_item(form: cgi.FieldStorage, field_name: str) -> cgi.FieldStorage | None:
    if field_name not in form:
        return None
    item = form[field_name]
    if isinstance(item, list):
        item = item[0] if item else None
    if item is None or not getattr(item, "filename", ""):
        return None
    return item


def save_uploaded_file(file_item: cgi.FieldStorage, submission_id: str, tag: str) -> tuple[str, str]:
    original = Path(str(file_item.filename)).name
    suffix = Path(original).suffix.lower()[:12]
    stored = f"{submission_id}-{tag}{suffix or '.bin'}"
    with (UPLOAD_DIR / stored).open("wb") as f:
        shutil.copyfileobj(file_item.file, f)
    return original, stored


def regenerate_record_files(row: sqlite3.Row, force: bool = False) -> bool:
    if not row["destination_name"] or not row["destination_coordinate"] or not row["png_filename"] or not row["pdf_filename"]:
        return False
    png_path = GENERATED_DIR / row["png_filename"]
    pdf_path = GENERATED_DIR / row["pdf_filename"]
    if not force and png_path.exists() and pdf_path.exists():
        return True
    try:
        flight_renderer.generate_record(
            destination_name=row["destination_name"],
            destination_coordinate=row["destination_coordinate"],
            out_path=png_path,
            pdf_path=pdf_path,
            show_callsign=True,
        )
    except Exception as exc:
        print(f"Failed to regenerate files for {row['id']}: {exc}", file=sys.stderr)
        return False
    return png_path.exists() and pdf_path.exists()


def locked_preview_path(original_path: Path) -> Path | None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview_path = PREVIEW_DIR / f"{original_path.stem}-locked-preview-{LOCKED_PREVIEW_BADGE_VERSION}.png"
    if preview_path.exists() and preview_path.stat().st_mtime >= original_path.stat().st_mtime:
        return preview_path
    try:
        with Image.open(original_path) as source:
            preview = source.convert("RGBA")
        preview.thumbnail(
            (LOCKED_PREVIEW_MAX_DIMENSION, LOCKED_PREVIEW_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        label = "PREVIEW ONLY"
        font_size = max(14, min(preview.size) // 52)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        pad = max(12, preview.width // 70)
        x = max(pad, preview.width - text_w - pad * 2)
        y = max(pad, preview.height - text_h - pad * 2)
        draw.rounded_rectangle(
            (x - pad, y - pad, x + text_w + pad, y + text_h + pad),
            radius=max(8, pad // 2),
            fill=(2, 8, 14, 156),
            outline=(103, 199, 239, 118),
            width=2,
        )
        draw.text((x, y), label, font=font, fill=(255, 255, 255, 218))
        Image.alpha_composite(preview, overlay).convert("RGB").save(preview_path, "PNG", optimize=True)
        return preview_path
    except Exception as exc:
        print(f"Failed to create locked preview for {original_path}: {exc}", file=sys.stderr)
        return None


def animation_preview_path(row: sqlite3.Row, original_path: Path) -> Path | None:
    with _ANIMATION_PREVIEW_LOCK:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        source_path = PREVIEW_DIR / f"{original_path.stem}-animation-source-{ANIMATION_PREVIEW_VERSION}.png"
        preview_path = PREVIEW_DIR / f"{original_path.stem}-animation-preview-{ANIMATION_PREVIEW_VERSION}.png"
        if preview_path.exists() and preview_path.stat().st_mtime >= original_path.stat().st_mtime:
            return preview_path
        try:
            flight_renderer.generate_record(
                destination_name=row["destination_name"],
                destination_coordinate=row["destination_coordinate"],
                out_path=source_path,
                pdf_path=None,
                show_callsign=True,
                show_stamp=False,
            )
            with Image.open(source_path) as source:
                preview = source.convert("RGB")
            preview.thumbnail(
                (ANIMATION_PREVIEW_MAX_DIMENSION, ANIMATION_PREVIEW_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            preview.save(preview_path, "PNG", optimize=True)
            return preview_path
        except Exception as exc:
            print(f"Failed to create animation preview for {row['id']}: {exc}", file=sys.stderr)
            return None


def warm_animation_preview(submission_id: str) -> None:
    submission_id = normalize_submission_id(submission_id)
    if not submission_id:
        return
    with _ANIMATION_PREVIEW_WARMING_LOCK:
        if submission_id in _ANIMATION_PREVIEW_WARMING:
            return
        _ANIMATION_PREVIEW_WARMING.add(submission_id)

    def worker() -> None:
        try:
            row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
            if row is None or not row["png_filename"]:
                return
            path = GENERATED_DIR / row["png_filename"]
            if not path.exists() and not regenerate_record_files(row):
                return
            animation_preview_path(row, path)
        finally:
            with _ANIMATION_PREVIEW_WARMING_LOCK:
                _ANIMATION_PREVIEW_WARMING.discard(submission_id)

    threading.Thread(target=worker, daemon=True).start()


def record_jpg_path(row: sqlite3.Row, force: bool = False) -> Path | None:
    if not row["png_filename"]:
        return None
    if not regenerate_record_files(row, force=force):
        return None
    source_path = GENERATED_DIR / row["png_filename"]
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    jpg_path = PREVIEW_DIR / f"{source_path.stem}-{RECORD_JPG_VERSION}.jpg"
    if jpg_path.exists() and jpg_path.stat().st_mtime >= source_path.stat().st_mtime:
        return jpg_path
    try:
        with Image.open(source_path) as source:
            source.convert("RGB").save(jpg_path, "JPEG", quality=92, optimize=True, progressive=True)
        return jpg_path
    except Exception as exc:
        print(f"Failed to create JPG record for {row['id']}: {exc}", file=sys.stderr)
        return None


def record_download(row: sqlite3.Row, file_type: str, actor_role: str, client_ip: str, user_agent: str) -> None:
    if file_type not in {"jpg", "pdf", "png"}:
        return
    db_execute(
        """
        INSERT INTO download_events (submission_id, user_id, file_type, actor_role, downloaded_at, client_ip, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row_user_id(row),
            file_type,
            actor_role,
            now_text(),
            client_ip[:120],
            user_agent[:260],
        ),
    )


def download_record_html(submission_id: str) -> str:
    summary = db_row(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN file_type = 'jpg' THEN 1 ELSE 0 END) AS jpg_count,
            SUM(CASE WHEN file_type = 'pdf' THEN 1 ELSE 0 END) AS pdf_count,
            SUM(CASE WHEN file_type = 'png' THEN 1 ELSE 0 END) AS png_count,
            MAX(downloaded_at) AS last_downloaded_at
        FROM download_events
        WHERE submission_id = ?
        """,
        (submission_id,),
    )
    total = int(summary["total"] or 0) if summary else 0
    if total == 0:
        return '<p class="download-record muted">下载纪录：暂无下载纪录</p>'
    recent = db_rows(
        """
        SELECT file_type, actor_role, downloaded_at
        FROM download_events
        WHERE submission_id = ?
        ORDER BY id DESC
        LIMIT 3
        """,
        (submission_id,),
    )
    recent_text = " · ".join(
        f"{esc(item['downloaded_at'])} {esc(str(item['file_type']).upper())}"
        for item in recent
    )
    detail = f'<span>{recent_text}</span>' if recent_text else ""
    return (
        f'<p class="download-record"><b>下载纪录：</b>共 {total} 次 · '
        f'JPG {int(summary["jpg_count"] or 0)} · PDF {int(summary["pdf_count"] or 0)} · PNG {int(summary["png_count"] or 0)} · '
        f'最近 {esc(summary["last_downloaded_at"])}</p>'
        f'<p class="download-record compact">{detail}</p>'
    )


def query_countdown_script() -> str:
    return """
<script>
(() => {
  const gate = document.querySelector("[data-query-unlock]");
  if (!gate) return;
  const target = Date.parse(gate.dataset.unlockAt || "");
  if (!Number.isFinite(target)) return;

  const units = {
    days: gate.querySelector('[data-countdown-unit="days"]'),
    hours: gate.querySelector('[data-countdown-unit="hours"]'),
    minutes: gate.querySelector('[data-countdown-unit="minutes"]'),
    seconds: gate.querySelector('[data-countdown-unit="seconds"]')
  };
  const button = gate.querySelector("[data-query-submit]");
  const copy = gate.querySelector("[data-query-copy]");
  const countdown = gate.querySelector("[data-query-countdown]");
  const pad = (value) => String(value).padStart(2, "0");

  function setOpen() {
    gate.classList.remove("locked");
    gate.classList.add("open");
    Object.values(units).forEach((unit) => {
      if (unit) unit.textContent = "00";
    });
    if (button) {
      button.disabled = false;
      button.textContent = "查看状态";
    }
    if (countdown) countdown.hidden = true;
    if (copy) copy.textContent = "查询已开放，可以查看审核状态并进入下载。";
  }

  function render() {
    const diff = target - Date.now();
    if (diff <= 0) {
      setOpen();
      return false;
    }
    const totalSeconds = Math.floor(diff / 1000);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (units.days) units.days.textContent = pad(days);
    if (units.hours) units.hours.textContent = pad(hours);
    if (units.minutes) units.minutes.textContent = pad(minutes);
    if (units.seconds) units.seconds.textContent = pad(seconds);
    return true;
  }

  let timer = null;
  if (render()) {
    timer = setInterval(() => {
      if (!render() && timer) clearInterval(timer);
    }, 1000);
  }
})();
</script>
"""


def gallery_download_html(href: str, download_name: str, force_unlocked: bool = False) -> str:
    if not force_unlocked and not downloads_unlocked():
        return f"""
  <div class="actions locked-actions">
    <button class="button disabled" type="button" disabled>JPG 下载将在 {DOWNLOAD_UNLOCK_LABEL} 开放</button>
  </div>
"""
    download_link = f'<a class="button download-button" href="{esc(href)}" download="{esc(download_name)}">下载 JPG</a>'
    return f"""
  <div class="download-ready">
    <p class="muted">下载窗口已开放，可以保存 JPG。</p>
  </div>
  <div class="actions download-actions">
    {download_link}
  </div>
"""


def record_jpg_download_html(row: sqlite3.Row, force_unlocked: bool = False, source: str = "player") -> str:
    if not row["png_filename"]:
        return ""
    jpg_name = Path(row["png_filename"]).with_suffix(".jpg").name
    href = f'/download?id={esc(row["id"])}&type=jpg&source={esc(source)}'
    return gallery_download_html(href, jpg_name, force_unlocked=force_unlocked)


def gallery_record_entry_html(row: sqlite3.Row, preview_token: str, frame_class: str, force_unlocked: bool, source: str) -> str:
    return f"""
    <details class="gallery-entry">
      <summary class="gallery-summary">
        <span class="gallery-thumb">
          <img src="/preview?id={esc(row['id'])}&v={preview_token}" alt="" loading="eager">
        </span>
        <span class="gallery-entry-copy">
          <b>返航飞行纪录图</b>
          <em>{esc(row['destination_name'])} · {esc(row['destination_coordinate'])}</em>
        </span>
        <span class="gallery-toggle" aria-hidden="true"></span>
      </summary>
      <div class="gallery-entry-panel">
        <figure class="{frame_class}">
          <img class="record-preview" src="/preview?id={esc(row['id'])}&v={preview_token}" alt="返航飞行纪录图" loading="lazy">
          <figcaption>返航飞行纪录图</figcaption>
        </figure>
        {record_jpg_download_html(row, force_unlocked=force_unlocked, source=source)}
      </div>
    </details>
"""


def gallery_static_entry_html(row: sqlite3.Row, item: dict[str, str], force_unlocked: bool, source: str) -> str:
    slug = item["slug"]
    title = item["title"]
    download_name = f"{title}.jpg"
    thumb_src = f"/gallery-image?id={esc(row['id'])}&asset={esc(slug)}&variant=thumb"
    full_src = f"/gallery-image?id={esc(row['id'])}&asset={esc(slug)}"
    download_href = f"/download?id={esc(row['id'])}&type=gallery-jpg&asset={esc(slug)}&source={esc(source)}"
    return f"""
    <details class="gallery-entry">
      <summary class="gallery-summary">
        <span class="gallery-thumb">
          <img src="{thumb_src}" alt="" loading="lazy">
        </span>
        <span class="gallery-entry-copy">
          <b>{esc(title)}</b>
          <em>JPG</em>
        </span>
        <span class="gallery-toggle" aria-hidden="true"></span>
      </summary>
      <div class="gallery-entry-panel">
        <figure class="record-preview-frame">
          <img class="record-preview" src="{full_src}" alt="{esc(title)}" loading="lazy">
          <figcaption>{esc(title)}</figcaption>
        </figure>
        {gallery_download_html(download_href, download_name, force_unlocked=force_unlocked)}
      </div>
    </details>
"""


def gallery_static_path(item: dict[str, str], variant: str = "full") -> Path:
    folder = "thumbs" if variant == "thumb" else "full"
    return GALLERY_STATIC_DIR / folder / item["file"]


def download_locked_page(submission_id: str) -> bytes:
    back_href = f"/history?id={esc(submission_id)}#query" if submission_id else "/history#query"
    body = f"""
<section class="panel wide">
  <div class="section-head">
    <span>LOCK</span>
    <h2>下载尚未开放</h2>
  </div>
  <p class="muted">查看状态和 JPG 下载入口将在 {DOWNLOAD_UNLOCK_LABEL} 开放。现在可以返回查询页查看倒计时。</p>
  <div class="actions status-actions">
    <a class="button ghost" href="{back_href}">返回查询页</a>
  </div>
</section>
"""
    return layout("下载尚未开放", body)


def address_picker_script() -> str:
    return """
<script>
(() => {
  const form = document.querySelector(".destination-form");
  if (!form) return;
  const targetInput = form.querySelector('[name="destination_name"]');
  const input = form.querySelector(".address-input");
  const lat = form.querySelector(".address-lat");
  const lon = form.querySelector(".address-lon");
  const label = form.querySelector(".address-label");
  const suggest = form.querySelector(".address-suggest");
  const hint = form.querySelector(".address-hint");
  let timer;
  let requestId = 0;

  function clearSelection() {
    lat.value = "";
    lon.value = "";
    label.value = "";
    input.classList.remove("has-location");
    if (hint) hint.textContent = "";
  }

  function hideSuggest() {
    suggest.hidden = true;
    suggest.innerHTML = "";
  }

  if (targetInput && input) {
    targetInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      input.focus();
      input.scrollIntoView({block: "center", behavior: "smooth"});
    });
  }

  function renderSuggest(items) {
    suggest.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "address-empty";
      empty.textContent = "没有匹配到候选；可以继续输入、直接使用这段文字，或清空地址自动搜索目标定位。";
      suggest.append(empty);
      suggest.hidden = false;
      return;
    }
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "address-option";
      button.dataset.lat = item.lat ?? "";
      button.dataset.lon = item.lon ?? "";
      button.dataset.label = item.address || item.name || "";

      const title = document.createElement("b");
      title.textContent = item.name || item.address || "地点候选";
      const detail = document.createElement("span");
      detail.textContent = item.address || "";
      const meta = document.createElement("em");
      meta.textContent = item.source === "amap" ? "MAP LINK" : (item.source === "custom" ? "CUSTOM" : "LOCAL INDEX");

      button.append(title, detail, meta);
      button.addEventListener("click", () => {
        input.value = item.address || item.name || input.value;
        lat.value = button.dataset.lat;
        lon.value = button.dataset.lon;
        label.value = button.dataset.label;
        input.classList.toggle("has-location", Boolean(lat.value && lon.value));
        if (hint) {
          hint.textContent = lat.value && lon.value
            ? `已锁定地图候选：${button.dataset.label}`
            : "已选择文字候选；生成时会继续尝试解析地图坐标。";
        }
        hideSuggest();
      });
      suggest.append(button);
    }
    suggest.hidden = false;
  }

  input.addEventListener("input", () => {
    clearSelection();
    const query = input.value.trim();
    clearTimeout(timer);
    if (!query) {
      hideSuggest();
      return;
    }
    const current = ++requestId;
    timer = setTimeout(async () => {
      try {
        const response = await fetch(`/address-suggest?q=${encodeURIComponent(query)}`, {headers: {"Accept": "application/json"}});
        if (!response.ok || current !== requestId) return;
        const data = await response.json();
        renderSuggest(Array.isArray(data.items) ? data.items : []);
      } catch (error) {
        if (current === requestId) hideSuggest();
      }
    }, 260);
  });
})();
</script>
"""


def archive_access_html(extra_class: str = "") -> str:
    class_name = f"quick-gallery {extra_class}".strip()
    return f"""
  <aside class="{class_name}">
    <p class="eyebrow">ARCHIVE ACCESS</p>
    <form class="inline-query" action="/gallery" method="get">
      <input name="id" maxlength="12" placeholder="输入编号" required>
      <button type="submit">编号登录</button>
    </form>
  </aside>"""


def preview_frame_class(force_unlocked: bool = False) -> str:
    classes = ["record-preview-frame"]
    if not force_unlocked and not downloads_unlocked():
        classes.append("preview-only")
    return " ".join(classes)


def destination_page(message: str = "") -> bytes:
    notice = f'<div class="notice">{esc(message)}</div>' if message else ""
    desktop_archive = archive_access_html("desktop-archive")
    mobile_archive = archive_access_html("mobile-archive")
    body = f"""
{notice}
<section class="command-deck destination-command">
  <div class="radar-scope" aria-hidden="true">
    <span></span>
  </div>
  <div class="mission-copy">
    <p class="eyebrow">TARGET CLEARANCE</p>
    <h2>规划飞行航道</h2>
  </div>
{desktop_archive}
</section>

<form class="panel wide destination-form" action="/flight/create" method="post">
  <div class="section-head">
    <span>01</span>
    <h2>输入目标和目的地</h2>
  </div>
  <label>目标
    <input name="destination_name" maxlength="24" placeholder="输入目标姓名" inputmode="text" lang="zh-CN" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="next" required>
  </label>
  <label class="address-field">目的地
    <input name="address" class="address-input" maxlength="160" placeholder="输入城市、区县、道路；不输入则自动搜索目标定位" inputmode="text" lang="zh-CN" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="go">
    <input type="hidden" name="address_lat" class="address-lat">
    <input type="hidden" name="address_lon" class="address-lon">
    <input type="hidden" name="address_label" class="address-label">
    <div class="address-suggest" hidden></div>
  </label>
  <div class="commit-row">
    <button type="submit">确认</button>
    <p class="commit-warning"><b>请确认信息</b><span>确认后将自动规划航道，无法撤回。</span></p>
  </div>
</form>
{mobile_archive}
{address_picker_script()}
"""
    return layout("规划飞行航道", body, body_class="home-body")


def flight_confirm_page(submission_id: str) -> bytes:
    row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if row is None or not row["png_filename"]:
        return destination_page("没找到这个飞行纪录。")
    warm_animation_preview(row["id"])
    preview_token = quote(str(row["generated_at"] or row["id"]))
    animation_src = f"/animation-preview?id={esc(row['id'])}&v={preview_token}"
    body = f"""
<section class="panel wide confirm-panel">
  <div class="section-head">
    <span>02</span>
    <h2>飞行纪录预览</h2>
  </div>
  <dl class="meta">
    <div><dt>编号</dt><dd>{esc(row['id'])}</dd></div>
    <div><dt>任务目标</dt><dd>{esc(row['destination_name'])}</dd></div>
    <div><dt>目的地坐标</dt><dd>{esc(row['destination_coordinate'])}</dd></div>
  </dl>
  <div class="screen-warning simple-warning">
    <span>请截图保存编号</span>
  </div>
  <form class="confirm-actions flight-confirm-actions" action="/flight/confirm" method="post">
    <input type="hidden" name="id" value="{esc(row['id'])}">
    <button class="confirm-button" type="submit">确认</button>
  </form>
  <img src="{animation_src}" alt="" width="1" height="1" loading="eager" decoding="async" aria-hidden="true" class="preload-probe">
</section>
"""
    return layout("飞行纪录预览", body, body_class="home-body")


def flight_loading_fallback_page(submission_id: str) -> bytes:
    redirect_to = f"/record?id={esc(submission_id)}"
    body = f"""
<main class="auth-shell loading-shell">
  <section class="loading-screen">
    <div class="loading-grid" aria-hidden="true">
      <span></span><span></span><span></span><span></span>
    </div>
    <div class="loading-core" aria-hidden="true">
      <span class="loading-ring ring-a"></span>
      <span class="loading-ring ring-b"></span>
      <span class="loading-axis axis-a"></span>
      <span class="loading-axis axis-b"></span>
      <span class="loading-dot"></span>
    </div>
    <p class="eyebrow">MISSION LOCKED</p>
    <h1>生成飞行纪录</h1>
    <div class="loading-bar" aria-hidden="true"><span></span></div>
    <p class="loading-copy">正在同步目标与目的地坐标</p>
    <a class="button ghost loading-fallback" href="{redirect_to}" data-loading-fallback hidden>查看预览</a>
  </section>
</main>
<script>
  const fallback = document.querySelector("[data-loading-fallback]");
  setTimeout(() => {{
    if (fallback) fallback.hidden = false;
  }}, 2200);
  setTimeout(() => {{
    window.location.replace("{redirect_to}");
  }}, 1500);
</script>
"""
    return auth_layout("生成飞行纪录", body)


def flight_loading_page(submission_id: str) -> bytes:
    row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if row is None or not row["png_filename"]:
        return destination_page("没找到这个飞行纪录。")
    warm_animation_preview(row["id"])
    if not STAMP_ANIMATION_TEMPLATE_PATH.exists():
        return flight_loading_fallback_page(submission_id)
    redirect_to = f"/record?id={esc(row['id'])}"
    preview_token = quote(str(row["generated_at"] or row["id"]))
    record_src = f"/animation-preview?id={esc(row['id'])}&v={preview_token}"
    page = STAMP_ANIMATION_TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace(
        '<title>Flight Record Scanner Seal Preview</title>',
        "<title>生成飞行纪录</title>",
    )
    page = page.replace(
        "<title>生成飞行纪录</title>",
        f'<title>生成飞行纪录</title>\n  <link rel="preload" as="image" href="{record_src}" fetchpriority="high">',
    )
    page = page.replace(
        'src="assets/flight-record-default-unstamped.png"',
        f'src="{record_src}"',
    )
    page = page.replace('src="assets/', 'src="/static/stamp-animation/assets/')
    page = page.replace('href="assets/', 'href="/static/stamp-animation/assets/')
    page = page.replace(
        'window.location.href = "download-placeholder.html";',
        f'window.location.href = "{redirect_to}";',
    )
    return page.encode("utf-8")


def record_preview_page(submission_id: str) -> bytes:
    row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if row is None or not row["png_filename"]:
        return destination_page("没找到这个飞行纪录。")
    preview_token = quote(str(row["generated_at"] or row["id"]))
    frame_class = preview_frame_class()
    body = f"""
<section class="panel wide success-panel">
  <div class="section-head">
    <span>02</span>
    <h2>飞行纪录预览</h2>
  </div>
  <dl class="meta">
    <div><dt>编号</dt><dd>{esc(row['id'])}</dd></div>
    <div><dt>任务目标</dt><dd>{esc(row['destination_name'])}</dd></div>
    <div><dt>目的地坐标</dt><dd>{esc(row['destination_coordinate'])}</dd></div>
  </dl>
  <figure class="{frame_class}" id="record-preview">
    <img class="record-preview" src="/preview?id={esc(row['id'])}&v={preview_token}" alt="飞行纪录预览" loading="eager" onerror="this.hidden=true; this.nextElementSibling.hidden=false;">
    <p class="preview-fallback" hidden>预览加载失败，请稍后再试。</p>
    <figcaption>飞行纪录预览</figcaption>
  </figure>
  <div class="preview-actions">
    <a class="button" href="/history?id={esc(row['id'])}">下载飞行纪录</a>
  </div>
</section>
"""
    return layout("飞行纪录预览", body, body_class="home-body")


def gallery_page(submission_id: str, admin_access: bool = False) -> bytes:
    if not admin_access and not downloads_unlocked():
        return history_page(f"查看状态和 JPG 下载入口将在 {DOWNLOAD_UNLOCK_LABEL} 开放。", submission_id)
    row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if row is None:
        return history_page("没找到这个编号。")
    if row["status"] != "approved":
        status_text = {
            "draft": "这个编号还没有提交自证。",
            "pending": "自证正在审核中。",
            "rejected": "自证审核未通过。",
        }.get(row["status"], "这个编号暂时不能进入图库。")
        note = f"<p class='muted'>{esc(row['review_note'])}</p>" if row["review_note"] else ""
        action = (
            f'<a class="button" href="/history?id={esc(row["id"])}">提交自证</a>'
            if row["status"] in {"draft", "rejected"}
            else '<a class="button ghost" href="/history#query">返回查询页</a>'
        )
        body = f"""
<section class="panel wide">
  <div class="section-head">
    <span>ID</span>
    <h2>{esc(row['id'])}</h2>
    {status_badge(row['status'])}
  </div>
  <p class="muted">{status_text}</p>
  {note}
  <div class="actions status-actions">
    {action}
  </div>
</section>
"""
        return layout("图库状态", body, body_class="home-body")
    if not row["png_filename"]:
        return status_page(row["id"])
    preview_token = quote(str(row["generated_at"] or row["id"]))
    frame_class = preview_frame_class(force_unlocked=admin_access)
    download_source = "admin" if admin_access else "player"
    gallery_entries = [gallery_record_entry_html(row, preview_token, frame_class, admin_access, download_source)]
    gallery_entries.extend(
        gallery_static_entry_html(row, item, admin_access, download_source)
        for item in STATIC_GALLERY_ITEMS
    )
    admin_note = (
        '<p class="muted gallery-note">ADMIN ACCESS：后台预览已绕过倒计时，仅用于提前检查图库布局。</p>'
        if admin_access
        else ""
    )
    body = f"""
<section class="panel wide success-panel gallery-library">
  <div class="section-head gallery-head">
    <span>LIB</span>
    <h2>{esc(row['id'])}</h2>
    {status_badge(row['status'])}
  </div>
  <div class="gallery-directory" aria-label="图库目录">
    <p class="gallery-directory-label">目录</p>
    {''.join(gallery_entries)}
  </div>
  {admin_note}
</section>
"""
    return layout("飞行纪录图库", body, body_class="home-body")


def layout(title: str, body: str, admin: bool = False, body_class: str = "") -> bytes:
    nav_links = ""
    if admin:
        nav_links = '<a href="/">玩家入口</a><a href="/admin">审核</a><a href="/admin/logout">退出审核</a>'
    elif body_class == "help-body":
        nav_links = '<a href="/">返回控制台</a>'
    elif body_class == "home-body":
        nav_links = '<a href="/help">帮助</a><a href="/logout">退出</a>'
    else:
        nav_links = '<a href="/help">帮助</a>'
    nav_block = f"<nav>{nav_links}</nav>" if nav_links else ""
    body_class_attr = f' class="{esc(body_class)}"' if body_class else ""
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body{body_class_attr}>
  <main class="shell">
    <header class="topbar">
      <div class="brand-lockup">
        <p class="eyebrow">PILOT FLIGHT RECORD</p>
        <h1>Flight Ops Console</h1>
      </div>
      {nav_block}
    </header>
    {body}
  </main>
</body>
</html>"""
    return page.encode("utf-8")


def auth_layout(title: str, body: str) -> bytes:
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body class="auth-body">
  {body}
</body>
</html>"""
    return page.encode("utf-8")


def history_page(message: str = "", submission_id: str = "") -> bytes:
    notice = f'<div class="notice">{esc(message)}</div>' if message else ""
    clean_id = normalize_submission_id(submission_id)
    hidden_id = f'<input type="hidden" name="id" value="{esc(clean_id)}">' if clean_id else ""
    query_unlocked = downloads_unlocked()
    query_state = "open" if query_unlocked else "locked"
    query_button_disabled = "" if query_unlocked else " disabled"
    query_button_text = "查看状态" if query_unlocked else "等待开放"
    query_copy = (
        "查询已开放，可以查看审核状态并进入 JPG 下载。"
        if query_unlocked
        else "6月13日 00:00 中国北京时间后开放查询，届时可查看审核状态并进入 JPG 下载。"
    )
    countdown_hidden = " hidden" if query_unlocked else ""
    current_code = f"""
    <div class="screen-warning compact-warning">
      <b>当前编号</b>
      <span>{esc(clean_id)}</span>
    </div>
""" if clean_id else ""
    body = f"""
{notice}
<section class="command-deck">
  <div class="radar-scope" aria-hidden="true">
    <span></span>
  </div>
  <div class="mission-copy">
    <p class="eyebrow">ARCHIVE CLEARANCE</p>
    <h2>历史飞行纪录下载</h2>
  </div>
  <div class="signal-grid">
    <div><b>VERIFY</b><span>MANUAL</span></div>
    <div><b>QUERY</b><span>CODE</span></div>
    <div><b>GALLERY</b><span>JPG</span></div>
  </div>
</section>
<section class="workspace two">
  <form class="panel" action="/submit" method="post" enctype="multipart/form-data">
    {hidden_id}
    <div class="section-head">
      <span>01</span>
      <h2>上传自证</h2>
    </div>
    {current_code}
    <label>用户ID（小红书号或邮箱）
      <input name="contact" maxlength="80" placeholder="请输入小红书号或邮箱" required>
    </label>
    <label>自证文件：牵绊度页面
      <input name="proof_bond" type="file" accept="image/*,.pdf" required>
    </label>
    <label>自证文件：主页
      <input name="proof_home" type="file" accept="image/*,.pdf" required>
    </label>
    <button type="submit">提交审核</button>
  </form>

  <form class="panel query-panel {query_state}" id="query" action="/gallery" method="get" data-query-unlock data-unlock-at="{DOWNLOAD_UNLOCK_ISO}">
    <div class="section-head">
      <span>02</span>
      <h2>查看进度</h2>
    </div>
    <label>编号
      <input name="id" value="{esc(clean_id)}" placeholder="请输入编号" required>
    </label>
    <div class="query-unlock" aria-live="polite">
      <p class="muted" data-query-copy>{esc(query_copy)}</p>
      <div class="countdown-grid query-countdown" data-query-countdown aria-label="距离查看状态开放"{countdown_hidden}>
        <span><b data-countdown-unit="days">00</b><em>天</em></span>
        <span><b data-countdown-unit="hours">00</b><em>时</em></span>
        <span><b data-countdown-unit="minutes">00</b><em>分</em></span>
        <span><b data-countdown-unit="seconds">00</b><em>秒</em></span>
      </div>
    </div>
    <button type="submit" data-query-submit{query_button_disabled}>{query_button_text}</button>
  </form>
</section>
{query_countdown_script()}
"""
    return layout("历史飞行纪录下载", body, body_class="home-body")


def public_page(message: str = "") -> bytes:
    return history_page(message)


def help_page() -> bytes:
    body = """
<section class="help-console">
  <div class="help-copy">
    <p class="eyebrow">SUPPORT CHANNEL</p>
    <dl class="contact-ledger">
      <div>
        <dt>CALLSIGN</dt>
        <dd>SEV（出逃版）</dd>
      </div>
      <div>
        <dt>REDNOTE ID</dt>
        <dd><code>7291792900</code></dd>
      </div>
    </dl>
    <button class="button ghost copy-contact" type="button" data-copy="7291792900">复制编号</button>
  </div>
  <figure class="qr-dock">
    <span class="qr-scanline" aria-hidden="true"></span>
    <img src="/static/assets/xhs-sev-qr.png" alt="SEV（出逃版）小红书二维码">
    <figcaption>SCAN REDNOTE CONTACT</figcaption>
  </figure>
</section>
<script>
  document.querySelector(".copy-contact")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(button.dataset.copy || "");
      button.textContent = "已复制";
      setTimeout(() => { button.textContent = "复制编号"; }, 1400);
    } catch (error) {
      button.textContent = "7291792900";
    }
  });
</script>
"""
    return layout("帮助", body, body_class="help-body")


def player_gate_page(message: str = "", password_hint_attempt: bool = False) -> bytes:
    notice = f'<div class="auth-alert">{esc(message)}</div>' if message else ""
    password_hint_attempt_js = "true" if password_hint_attempt else "false"
    body = f"""
<main class="auth-shell">
  <a class="auth-help" href="/help">帮助</a>
  <section class="auth-screen">
    <div class="auth-visual" aria-hidden="true">
      <span class="auth-image-layer"></span>
      <span class="auth-image-core"></span>
    </div>
    <div class="auth-copy">
      <p class="eyebrow">SECURE PILOT CHANNEL</p>
      <h1>Flight Gate</h1>
      {notice}
      <form class="auth-card" action="/gate" method="post">
        <div class="auth-state">SYNC 0/8</div>
        <label class="pilot-id-label">Pilot ID
          <input name="pilot_id" class="auth-input pilot-id-input" inputmode="email" pattern="[A-Za-z]*" maxlength="16" autocomplete="username" autocapitalize="characters" autocorrect="off" spellcheck="false" lang="en" required>
          <span class="pilot-id-hint" aria-live="polite"></span>
        </label>
        <label>密码
          <input name="password" class="auth-input code-input" type="password" inputmode="numeric" pattern="(19|20)[0-9]{{6}}" minlength="8" maxlength="8" autocomplete="current-password" required>
        </label>
        <div class="digit-rack" aria-hidden="true">
          <span></span><span></span><span></span><span></span>
          <span></span><span></span><span></span><span></span>
        </div>
        <button class="auth-submit" type="submit">登录</button>
      </form>
    </div>
  </section>
  <div class="password-hint-modal" data-password-hint-modal hidden>
    <div class="password-hint-scrim" data-password-hint-close></div>
    <section class="password-hint-dialog" role="dialog" aria-modal="true" aria-labelledby="password-hint-title">
      <p class="eyebrow">PILOT PASSWORD HINT</p>
      <h2 id="password-hint-title">是否解锁Pilot ID：XIAYIZHOU/CALEB 密码提示。</h2>
      <p class="password-hint-answer" data-password-hint-answer hidden>我最重要的人的生日</p>
      <div class="password-hint-actions">
        <button class="auth-submit password-hint-confirm" type="button" data-password-hint-confirm>确认</button>
        <button class="password-hint-cancel" type="button" data-password-hint-close>取消</button>
      </div>
    </section>
  </div>
</main>
<script>
    const pilotInput = document.querySelector(".pilot-id-input");
    const codeInput = document.querySelector(".code-input");
    const authForm = document.querySelector(".auth-card");
    const digitRack = document.querySelector(".digit-rack");
    const cells = Array.from(document.querySelectorAll(".digit-rack span"));
    const state = document.querySelector(".auth-state");
    const pilotHint = document.querySelector(".pilot-id-hint");
    const validPilots = new Set(["CALEB", "XIAYIZHOU"]);
    const passwordHintAttempt = {password_hint_attempt_js};
    const passwordFailKey = "flightGatePasswordFailCount";
    const passwordHintModal = document.querySelector("[data-password-hint-modal]");
    const passwordHintAnswer = document.querySelector("[data-password-hint-answer]");
    const passwordHintConfirm = document.querySelector("[data-password-hint-confirm]");
    const passwordHintCloseControls = Array.from(document.querySelectorAll("[data-password-hint-close]"));
    let invalidTimer;
    let passwordHintUnlocked = false;
  function cleanPilotId(value) {{
    return value.normalize("NFKC").replace(/[^A-Za-z]/g, "").toUpperCase();
  }}
  function syncPilot(showError = false) {{
    const clean = cleanPilotId(pilotInput.value);
    if (pilotInput.value !== clean) {{
      pilotInput.value = clean;
    }}
    const value = pilotInput.value;
    const invalid = showError && value.length > 0 && !validPilots.has(value);
    pilotInput.classList.toggle("invalid", invalid);
    pilotHint.textContent = invalid ? "飞行员ID不存在" : "";
    return value.length === 0 || validPilots.has(value);
  }}
  function flashInvalid() {{
    digitRack.classList.add("invalid");
    clearTimeout(invalidTimer);
    invalidTimer = setTimeout(() => {{
      digitRack.classList.remove("invalid");
      syncCode(false);
    }}, 760);
  }}
  function birthdayDigits(value) {{
    const digits = value.replace(/\\D/g, "");
    let clean = "";
    let rejected = digits !== value;
    for (const digit of digits) {{
      if (clean.length === 0) {{
        if (digit === "1" || digit === "2") {{
          clean += digit;
        }} else {{
          rejected = true;
        }}
      }} else if (clean.length === 1) {{
        if ((clean === "1" && digit === "9") || (clean === "2" && digit === "0")) {{
          clean += digit;
        }} else {{
          rejected = true;
        }}
      }} else if (clean.length < 8) {{
        clean += digit;
      }}
    }}
    return {{ clean, rejected }};
  }}
    function syncCode(showError = true) {{
      const result = birthdayDigits(codeInput.value);
      const clean = result.clean;
    if (clean !== codeInput.value) {{
      codeInput.value = clean;
    }}
    cells.forEach((cell, index) => {{
      cell.classList.toggle("filled", index < clean.length);
    }});
    state.textContent = clean.length === 8 ? "CLEARANCE READY" : `SYNC ${{clean.length}}/8`;
    if (result.rejected && showError) {{
      recordPasswordFailure(true);
      flashInvalid();
      return;
    }}
  }}
    function closePasswordHint() {{
      if (!passwordHintModal) return;
      passwordHintModal.hidden = true;
      passwordHintUnlocked = false;
      if (passwordHintAnswer) passwordHintAnswer.hidden = true;
      if (passwordHintConfirm) passwordHintConfirm.textContent = "确认";
    }}
    function showPasswordHint() {{
      if (!passwordHintModal) return;
      passwordHintUnlocked = false;
      if (passwordHintAnswer) passwordHintAnswer.hidden = true;
      if (passwordHintConfirm) passwordHintConfirm.textContent = "确认";
      passwordHintModal.hidden = false;
      requestAnimationFrame(() => passwordHintConfirm && passwordHintConfirm.focus());
    }}
    function recordPasswordFailure(requireValidPilot = true) {{
      if (requireValidPilot && !validPilots.has(cleanPilotId(pilotInput.value))) {{
        return;
      }}
      try {{
        const failCount = Number(localStorage.getItem(passwordFailKey) || "0") + 1;
        if (failCount >= 3) {{
          localStorage.setItem(passwordFailKey, "0");
          showPasswordHint();
        }} else {{
          localStorage.setItem(passwordFailKey, String(failCount));
        }}
      }} catch (error) {{
        showPasswordHint();
      }}
    }}
    if (passwordHintConfirm) {{
      passwordHintConfirm.addEventListener("click", () => {{
        if (!passwordHintUnlocked) {{
          passwordHintUnlocked = true;
          if (passwordHintAnswer) passwordHintAnswer.hidden = false;
          passwordHintConfirm.textContent = "关闭";
          return;
        }}
        closePasswordHint();
      }});
    }}
    passwordHintCloseControls.forEach((control) => control.addEventListener("click", closePasswordHint));
    document.addEventListener("keydown", (event) => {{
      if (event.key === "Escape" && passwordHintModal && !passwordHintModal.hidden) {{
        closePasswordHint();
      }}
    }});
    pilotInput.addEventListener("input", () => syncPilot(false));
    pilotInput.addEventListener("paste", (event) => {{
      event.preventDefault();
    const pasted = (event.clipboardData || window.clipboardData).getData("text");
    const start = pilotInput.selectionStart ?? pilotInput.value.length;
    const end = pilotInput.selectionEnd ?? pilotInput.value.length;
      pilotInput.value = cleanPilotId(pilotInput.value.slice(0, start) + pasted + pilotInput.value.slice(end));
      syncPilot(false);
    }});
    pilotInput.addEventListener("keydown", (event) => {{
      if (event.key !== "Enter") return;
      event.preventDefault();
      if (syncPilot(true)) {{
        codeInput.focus();
      }}
    }});
    codeInput.addEventListener("focus", () => syncPilot(true));
    codeInput.addEventListener("input", syncCode);
    codeInput.addEventListener("invalid", () => recordPasswordFailure(true));
    authForm.addEventListener("submit", (event) => {{
      if (!syncPilot(true)) {{
        event.preventDefault();
        pilotInput.focus();
        return;
      }}
      syncCode(false);
    }});
    syncPilot(false);
    syncCode();
    if (passwordHintAttempt) {{
      recordPasswordFailure(false);
    }}
  </script>
  """
    return auth_layout("Flight Gate", body)


def player_loading_page() -> bytes:
    body = """
<main class="auth-shell loading-shell">
  <section class="loading-screen">
    <div class="loading-grid" aria-hidden="true">
      <span></span><span></span><span></span><span></span>
    </div>
    <div class="loading-core" aria-hidden="true">
      <span class="loading-ring ring-a"></span>
      <span class="loading-ring ring-b"></span>
      <span class="loading-axis axis-a"></span>
      <span class="loading-axis axis-b"></span>
      <span class="loading-dot"></span>
    </div>
    <p class="eyebrow">ACCESS GRANTED</p>
    <h1>同步飞行通道</h1>
    <div class="loading-bar" aria-hidden="true"><span></span></div>
    <p class="loading-copy">正在建立任务目标链路</p>
    <a class="button ghost loading-fallback" href="/">进入控制台</a>
  </section>
</main>
<script>
  setTimeout(() => {
    window.location.replace("/");
  }, 1500);
</script>
"""
    return auth_layout("Flight Gate Loading", body)


def admin_login_page(message: str = "") -> bytes:
    notice = f'<div class="auth-alert">{esc(message)}</div>' if message else ""
    body = f"""
<main class="auth-shell loading-shell">
  <section class="loading-screen admin-auth-screen">
    <p class="eyebrow">ADMIN CHANNEL</p>
    <h1>Ops Access</h1>
    {notice}
    <form class="auth-card admin-auth-card" action="/admin/login" method="post">
      <label>管理员口令
        <input name="password" class="auth-input" type="password" autocomplete="current-password" required>
      </label>
      <button class="auth-submit" type="submit">进入审核队列</button>
    </form>
  </section>
</main>
"""
    return auth_layout("管理员验证", body)


def admin_loading_page() -> bytes:
    body = """
<main class="auth-shell loading-shell">
  <section class="loading-screen">
    <div class="loading-grid" aria-hidden="true">
      <span></span><span></span><span></span><span></span>
    </div>
    <div class="loading-core" aria-hidden="true">
      <span class="loading-ring ring-a"></span>
      <span class="loading-ring ring-b"></span>
      <span class="loading-axis axis-a"></span>
      <span class="loading-axis axis-b"></span>
      <span class="loading-dot"></span>
    </div>
    <p class="eyebrow">ADMIN ACCESS</p>
    <h1>同步审核航道</h1>
    <div class="loading-bar" aria-hidden="true"><span></span></div>
    <p class="loading-copy">正在建立审核通道</p>
    <a class="button ghost loading-fallback" href="/admin">进入审核主页</a>
  </section>
</main>
<script>
  setTimeout(() => {
    window.location.replace("/admin");
  }, 1500);
</script>
"""
    return auth_layout("审核通道", body)


def submitted_page(submission_id: str) -> bytes:
    row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if row is None:
        return public_page("没找到这个编号。")

    body = f"""
<section class="panel wide confirm-panel">
  <div class="section-head">
    <span>ID</span>
    <h2>编号已生成</h2>
    {status_badge(row['status'])}
  </div>
  <div class="confirm-grid">
    <div>
      <div class="id-chip">{esc(row['id'])}</div>
      <div class="screen-warning simple-warning">
        <span>请截图保存编号</span>
      </div>
    </div>
    <div class="confirm-copy">
      <dl class="meta compact">
        <div><dt>提交时间</dt><dd>{esc(row['created_at'])}</dd></div>
        <div><dt>用户ID</dt><dd>{esc(row_user_id(row))}</dd></div>
        <div><dt>自证文件</dt><dd>{proof_summary_html(row)}</dd></div>
      </dl>
      <div class="confirm-actions">
        <a class="button confirm-button" href="/gallery?id={esc(row['id'])}">我已截图，查看审核进度</a>
        <a class="button ghost confirm-button" href="/history#query">返回查询页</a>
      </div>
    </div>
  </div>
</section>
"""
    return layout("编号", body)


def status_badge(status: str) -> str:
    return f'<span class="status {esc(status)}">{esc(status.upper())}</span>'


def status_page(submission_id: str) -> bytes:
    if not downloads_unlocked():
        return history_page(f"查看状态和 JPG 下载入口将在 {DOWNLOAD_UNLOCK_LABEL} 开放。", submission_id)
    row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if row is None:
        return public_page("没找到这个编号。")

    downloads = ""
    customize = ""
    note = f"<p class='muted'>{esc(row['review_note'])}</p>" if row["review_note"] else ""
    if row["status"] == "approved" and not row["pdf_filename"]:
        customize = f"""
<form class="panel wide destination-form" action="/customize" method="post">
  <input type="hidden" name="id" value="{esc(row['id'])}">
  <div class="section-head">
    <span>03</span>
    <h2>规划飞行航道</h2>
  </div>
  <label>姓名
    <input name="destination_name" maxlength="24" required>
  </label>
  <label class="address-field">地址
    <input name="address" class="address-input" maxlength="160" placeholder="输入城市、区县、道路；不输入则自动搜索目标定位" autocomplete="off">
    <input type="hidden" name="address_lat" class="address-lat">
    <input type="hidden" name="address_lon" class="address-lon">
    <input type="hidden" name="address_label" class="address-label">
    <div class="address-suggest" hidden></div>
  </label>
  <div class="commit-row">
    <button type="submit">确认任务部署</button>
    <p class="commit-warning"><b>请确认信息</b><span>确认后将自动规划航道，无法撤回。</span></p>
  </div>
</form>
<script>
(() => {{
  const form = document.querySelector(".destination-form");
  if (!form) return;
  const input = form.querySelector(".address-input");
  const lat = form.querySelector(".address-lat");
  const lon = form.querySelector(".address-lon");
  const label = form.querySelector(".address-label");
  const suggest = form.querySelector(".address-suggest");
  const hint = form.querySelector(".address-hint");
  let timer;
  let requestId = 0;

  function clearSelection() {{
    lat.value = "";
    lon.value = "";
    label.value = "";
    input.classList.remove("has-location");
    if (hint) hint.textContent = "";
  }}

  function hideSuggest() {{
    suggest.hidden = true;
    suggest.innerHTML = "";
  }}

  function renderSuggest(items) {{
    suggest.innerHTML = "";
    if (!items.length) {{
      const empty = document.createElement("div");
      empty.className = "address-empty";
      empty.textContent = "没有匹配到候选；可以继续输入、直接使用这段文字，或清空地址自动搜索目标定位。";
      suggest.append(empty);
      suggest.hidden = false;
      return;
    }}
    for (const item of items) {{
      const button = document.createElement("button");
      button.type = "button";
      button.className = "address-option";
      button.dataset.lat = item.lat ?? "";
      button.dataset.lon = item.lon ?? "";
      button.dataset.label = item.address || item.name || "";

      const title = document.createElement("b");
      title.textContent = item.name || item.address || "地点候选";
      const detail = document.createElement("span");
      detail.textContent = item.address || "";
      const meta = document.createElement("em");
      meta.textContent = item.source === "amap" ? "MAP LINK" : (item.source === "custom" ? "CUSTOM" : "LOCAL INDEX");

      button.append(title, detail, meta);
      button.addEventListener("click", () => {{
        input.value = item.address || item.name || input.value;
        lat.value = button.dataset.lat;
        lon.value = button.dataset.lon;
        label.value = button.dataset.label;
        input.classList.toggle("has-location", Boolean(lat.value && lon.value));
        if (hint) {{
          hint.textContent = lat.value && lon.value
            ? `已锁定地图候选：${{button.dataset.label}}`
            : "已选择文字候选；生成时会继续尝试解析地图坐标。";
        }}
        hideSuggest();
      }});
      suggest.append(button);
    }}
    suggest.hidden = false;
  }}

  input.addEventListener("input", () => {{
    clearSelection();
    const query = input.value.trim();
    clearTimeout(timer);
    if (!query) {{
      hideSuggest();
      return;
    }}
    const current = ++requestId;
    timer = setTimeout(async () => {{
      try {{
        const response = await fetch(`/address-suggest?q=${{encodeURIComponent(query)}}`, {{headers: {{"Accept": "application/json"}}}});
        if (!response.ok || current !== requestId) return;
        const data = await response.json();
        renderSuggest(Array.isArray(data.items) ? data.items : []);
      }} catch (error) {{
        if (current === requestId) hideSuggest();
      }}
    }}, 260);
  }});
}})();
</script>
"""
    if row["pdf_filename"]:
        preview_token = quote(str(row["generated_at"] or row["id"]))
        frame_class = preview_frame_class()
        downloads = f"""
<div class="panel wide success-panel">
  <div class="section-head">
    <span>04</span>
    <h2>最终文件</h2>
  </div>
  <p><b>任务目标：</b>{esc(row['destination_name'])}</p>
  <p><b>目的地坐标：</b>{esc(row['destination_coordinate'])}</p>
  <figure class="{frame_class}" id="record-preview">
    <img class="record-preview" src="/preview?id={esc(row['id'])}&v={preview_token}" alt="飞行纪录预览" loading="eager" onerror="this.hidden=true; this.nextElementSibling.hidden=false;">
    <p class="preview-fallback" hidden>预览加载失败，请直接下载 JPG。</p>
    <figcaption>飞行纪录预览</figcaption>
  </figure>
  {record_jpg_download_html(row)}
</div>
"""

    body = f"""
<section class="panel wide">
  <div class="section-head">
    <span>ID</span>
    <h2>{esc(row['id'])}</h2>
    {status_badge(row['status'])}
  </div>
  <dl class="meta">
    <div><dt>提交时间</dt><dd>{esc(row['created_at'])}</dd></div>
    <div><dt>用户ID</dt><dd>{esc(row_user_id(row)) or "未填写"}</dd></div>
    <div><dt>自证文件</dt><dd>{proof_summary_html(row)}</dd></div>
  </dl>
  {note}
  <div class="actions status-actions">
    <a class="button ghost" href="/history#query">返回查询页</a>
  </div>
</section>
{customize}
{downloads}
"""
    return layout("提交状态", body)


def admin_page() -> bytes:
    rows = db_rows("SELECT * FROM submissions WHERE status != 'draft' ORDER BY created_at DESC")
    cards = []
    for row in rows:
        actions = ""
        if row["status"] == "pending":
            actions = f"""
<form class="inline" action="/admin/review" method="post">
  <input type="hidden" name="id" value="{esc(row['id'])}">
  <button name="action" value="approved">通过</button>
  <button class="danger" name="action" value="rejected">驳回</button>
</form>
"""
        generated = ""
        if row["pdf_filename"]:
            generated = (
                f'<span class="generated-links">文件：'
                f'<a href="/view?id={esc(row["id"])}&type=pdf" target="_blank" rel="noopener">PDF</a> '
                f'<a href="/view?id={esc(row["id"])}&type=png" target="_blank" rel="noopener">PNG</a>'
                f' <a href="/gallery?id={esc(row["id"])}">Gallery</a>'
                f' <em>后台预览不计入下载纪录</em>'
                f'</span>'
            )
        download_record = download_record_html(row["id"]) if row["pdf_filename"] else ""
        cards.append(
            f"""
<article class="submission">
  <div>
    <h3>{esc(row['id'])}</h3>
    {status_badge(row['status'])}
  </div>
  <p>{esc(row['created_at'])} · 用户ID：{esc(row_user_id(row)) or "未填写"}</p>
  <section class="proof-block"><span>自证文件</span>{proof_summary_html(row, linked=True)}</section>
  <p>{generated}</p>
  {download_record}
  {actions}
</article>
"""
        )
    body = f"""
<section class="panel wide">
  <div class="section-head">
    <span>ADMIN</span>
    <h2>审核队列</h2>
  </div>
  <form class="inline admin-gallery-access" action="/gallery" method="get">
    <input name="id" maxlength="12" placeholder="输入编号查看 Gallery" required>
    <button type="submit">进入 Gallery</button>
  </form>
  <div class="queue">{''.join(cards) or '<p class="muted">还没有提交。</p>'}</div>
</section>
"""
    return layout("审核队列", body, admin=True)


class FlightRecordHandler(BaseHTTPRequestHandler):
    server_version = "FlightRecordMVP/0.1"

    def send_html(self, content: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, path: str, headers: tuple[tuple[str, str], ...] = ()) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()

    def send_file_headers(self, path: Path, download_name: str | None = None) -> None:
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        if download_name:
            fallback_name = "".join(
                ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\", ";"} else "_"
                for ch in download_name
            ).strip() or "download"
            encoded_name = urllib.parse.quote(download_name, safe="")
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}",
            )
        else:
            self.send_header("Content-Disposition", "inline")
        self.end_headers()

    def is_admin(self) -> bool:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get(ADMIN_COOKIE)
        return bool(token and hmac.compare_digest(token.value, admin_cookie_token()))

    def is_player(self) -> bool:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get(PLAYER_COOKIE)
        return bool(token and hmac.compare_digest(token.value, player_cookie_token()))

    def require_admin(self) -> bool:
        if self.is_admin():
            return True
        self.redirect("/admin/login")
        return False

    def require_player(self) -> bool:
        if self.is_player():
            return True
        self.redirect("/")
        return False

    def require_player_or_admin(self) -> bool:
        if self.is_player() or self.is_admin():
            return True
        self.redirect("/")
        return False

    def client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return self.client_address[0] if self.client_address else ""

    def download_actor_role(self, source: str = "") -> str:
        if source == "player" and self.is_player():
            return "player"
        if source == "admin" and self.is_admin():
            return "admin"
        if self.is_player():
            return "player"
        return "admin" if self.is_admin() else "unknown"

    def serve_path(self, path: Path, download_name: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        self.send_file_headers(path, download_name)
        with path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def serve_path_head(self, path: Path, download_name: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        self.send_file_headers(path, download_name)

    def parse_urlencoded(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/":
            if self.is_player():
                self.send_html(destination_page())
            else:
                self.send_html(player_gate_page())
        elif parsed.path == "/help":
            self.send_html(help_page())
        elif parsed.path == "/gate/loading":
            if not self.require_player():
                return
            self.send_html(player_loading_page())
        elif parsed.path == "/flight/loading":
            if not self.require_player():
                return
            self.send_html(flight_loading_page(normalize_submission_id(qs.get("id", [""])[0])))
        elif parsed.path == "/flight/confirm":
            if not self.require_player():
                return
            self.send_html(flight_confirm_page(normalize_submission_id(qs.get("id", [""])[0])))
        elif parsed.path == "/record":
            if not self.require_player():
                return
            self.send_html(record_preview_page(normalize_submission_id(qs.get("id", [""])[0])))
        elif parsed.path == "/history":
            if not self.require_player():
                return
            self.send_html(history_page(submission_id=normalize_submission_id(qs.get("id", [""])[0])))
        elif parsed.path == "/gallery":
            if not self.require_player_or_admin():
                return
            self.send_html(gallery_page(normalize_submission_id(qs.get("id", [""])[0]), admin_access=self.is_admin()))
        elif parsed.path == "/logout":
            self.redirect(
                "/",
                (("Set-Cookie", f"{PLAYER_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"),),
            )
        elif parsed.path == "/submitted":
            if not self.require_player():
                return
            self.send_html(submitted_page(qs.get("id", [""])[0].strip().upper()))
        elif parsed.path == "/status":
            if not self.require_player():
                return
            self.send_html(status_page(normalize_submission_id(qs.get("id", [""])[0])))
        elif parsed.path == "/admin":
            if not self.require_admin():
                return
            self.send_html(admin_page())
        elif parsed.path == "/admin/login":
            if self.is_admin():
                self.redirect("/admin")
                return
            self.send_html(admin_login_page())
        elif parsed.path == "/admin/loading":
            if not self.require_admin():
                return
            self.send_html(admin_loading_page())
        elif parsed.path == "/admin/logout":
            self.redirect(
                "/",
                (("Set-Cookie", f"{ADMIN_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"),),
            )
        elif parsed.path == "/proof":
            if not self.require_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            if row is None:
                self.send_error(404)
                return
            kind = qs.get("kind", ["bond"])[0]
            if kind not in {"bond", "home"}:
                self.send_error(404)
                return
            stored = proof_stored_filename(row, kind)
            if not stored:
                self.send_error(404)
                return
            self.serve_path(UPLOAD_DIR / stored)
        elif parsed.path == "/animation-preview":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            if row is None or not row["png_filename"]:
                self.send_error(404)
                return
            path = GENERATED_DIR / row["png_filename"]
            if not regenerate_record_files(row):
                self.send_error(404)
                return
            animation_path = animation_preview_path(row, path)
            if animation_path is None:
                self.send_error(404)
                return
            self.serve_path(animation_path)
        elif parsed.path == "/preview":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            if row is None or not row["png_filename"]:
                self.send_error(404)
                return
            path = GENERATED_DIR / row["png_filename"]
            if not regenerate_record_files(row, force=True):
                self.send_error(404)
                return
            if not self.is_admin() and not downloads_unlocked():
                locked_path = locked_preview_path(path)
                if locked_path is None:
                    self.send_error(404)
                    return
                path = locked_path
            self.serve_path(path)
        elif parsed.path == "/gallery-image":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            item = STATIC_GALLERY_BY_SLUG.get(qs.get("asset", [""])[0])
            if row is None or item is None:
                self.send_error(404)
                return
            if row["status"] != "approved":
                self.send_error(403)
                return
            if not self.is_admin() and not downloads_unlocked():
                self.send_error(403)
                return
            variant = "thumb" if qs.get("variant", ["full"])[0] == "thumb" else "full"
            self.serve_path(gallery_static_path(item, variant))
        elif parsed.path == "/view":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            kind = qs.get("type", ["pdf"])[0]
            if row is None:
                self.send_error(404)
                return
            if not self.is_admin():
                if kind == "png":
                    self.send_error(404)
                    return
                if row["status"] != "approved":
                    self.send_error(403)
                    return
                if not downloads_unlocked():
                    self.send_html(download_locked_page(row["id"]), HTTPStatus.FORBIDDEN)
                    return
            if kind == "jpg" and row["png_filename"]:
                path = record_jpg_path(row, force=True)
                if path is None:
                    self.send_error(404)
                    return
                self.serve_path(path)
            elif kind == "png" and row["png_filename"]:
                path = GENERATED_DIR / row["png_filename"]
                if not regenerate_record_files(row, force=True):
                    self.send_error(404)
                    return
                self.serve_path(path)
            elif kind == "pdf" and row["pdf_filename"]:
                path = GENERATED_DIR / row["pdf_filename"]
                if not regenerate_record_files(row, force=True):
                    self.send_error(404)
                    return
                self.serve_path(path)
            else:
                self.send_error(404)
        elif parsed.path == "/download":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            kind = qs.get("type", ["pdf"])[0]
            if row is None:
                self.send_error(404)
                return
            if not self.is_admin():
                if kind in {"pdf", "png"}:
                    self.send_error(404)
                    return
                if row["status"] != "approved":
                    self.send_error(403)
                    return
                if not downloads_unlocked():
                    self.send_html(download_locked_page(row["id"]), HTTPStatus.FORBIDDEN)
                    return
            if kind == "jpg" and row["png_filename"]:
                path = record_jpg_path(row, force=True)
                if path is None:
                    self.send_error(404)
                    return
                role = self.download_actor_role(qs.get("source", [""])[0])
                record_download(row, "jpg", role, self.client_ip(), self.headers.get("User-Agent", ""))
                self.serve_path(path, Path(row["png_filename"]).with_suffix(".jpg").name)
            elif kind == "gallery-jpg":
                item = STATIC_GALLERY_BY_SLUG.get(qs.get("asset", [""])[0])
                if item is None:
                    self.send_error(404)
                    return
                path = gallery_static_path(item, "full")
                role = self.download_actor_role(qs.get("source", [""])[0])
                record_download(row, "jpg", role, self.client_ip(), self.headers.get("User-Agent", ""))
                self.serve_path(path, f"{item['title']}.jpg")
            elif kind == "png" and row["png_filename"]:
                path = GENERATED_DIR / row["png_filename"]
                if not regenerate_record_files(row, force=True):
                    self.send_error(404)
                    return
                role = self.download_actor_role(qs.get("source", [""])[0])
                record_download(row, "png", role, self.client_ip(), self.headers.get("User-Agent", ""))
                self.serve_path(path, Path(row["png_filename"]).name)
            elif kind == "pdf" and row["pdf_filename"]:
                path = GENERATED_DIR / row["pdf_filename"]
                if not regenerate_record_files(row, force=True):
                    self.send_error(404)
                    return
                role = self.download_actor_role(qs.get("source", [""])[0])
                record_download(row, "pdf", role, self.client_ip(), self.headers.get("User-Agent", ""))
                self.serve_path(path, Path(row["pdf_filename"]).name)
            else:
                self.send_error(404)
        elif parsed.path == "/address-suggest":
            if not self.require_player():
                return
            query = qs.get("q", [""])[0].strip()
            if not query:
                self.send_json({"items": []})
                return
            self.send_json({"items": address_suggestions(query[:80])})
        elif parsed.path.startswith("/static/"):
            rel = parsed.path.removeprefix("/static/")
            self.serve_path(APP_ROOT / "static" / rel)
        else:
            self.send_error(404)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/animation-preview":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            if row is None or not row["png_filename"]:
                self.send_error(404)
                return
            path = GENERATED_DIR / row["png_filename"]
            if not path.exists() and not regenerate_record_files(row):
                self.send_error(404)
                return
            animation_path = animation_preview_path(row, path)
            if animation_path is None:
                self.send_error(404)
                return
            self.serve_path_head(animation_path)
        elif parsed.path == "/preview":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            if row is None or not row["png_filename"]:
                self.send_error(404)
                return
            path = GENERATED_DIR / row["png_filename"]
            if not path.exists() and not regenerate_record_files(row):
                self.send_error(404)
                return
            if not self.is_admin() and not downloads_unlocked():
                locked_path = locked_preview_path(path)
                if locked_path is None:
                    self.send_error(404)
                    return
                path = locked_path
            self.serve_path_head(path)
        elif parsed.path == "/gallery-image":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            item = STATIC_GALLERY_BY_SLUG.get(qs.get("asset", [""])[0])
            if row is None or item is None:
                self.send_error(404)
                return
            if row["status"] != "approved":
                self.send_error(403)
                return
            if not self.is_admin() and not downloads_unlocked():
                self.send_error(403)
                return
            variant = "thumb" if qs.get("variant", ["full"])[0] == "thumb" else "full"
            self.serve_path_head(gallery_static_path(item, variant))
        elif parsed.path == "/view":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            kind = qs.get("type", ["pdf"])[0]
            if row is None:
                self.send_error(404)
                return
            if not self.is_admin():
                if kind == "png":
                    self.send_error(404)
                    return
                if row["status"] != "approved" or not downloads_unlocked():
                    self.send_error(403)
                    return
            if kind == "jpg" and row["png_filename"]:
                path = record_jpg_path(row)
                if path is None:
                    self.send_error(404)
                    return
                self.serve_path_head(path)
            elif kind == "png" and row["png_filename"]:
                path = GENERATED_DIR / row["png_filename"]
                if not path.exists() and not regenerate_record_files(row):
                    self.send_error(404)
                    return
                self.serve_path_head(path)
            elif kind == "pdf" and row["pdf_filename"]:
                path = GENERATED_DIR / row["pdf_filename"]
                if not path.exists() and not regenerate_record_files(row):
                    self.send_error(404)
                    return
                self.serve_path_head(path)
            else:
                self.send_error(404)
        elif parsed.path == "/download":
            if not self.require_player_or_admin():
                return
            row = db_row("SELECT * FROM submissions WHERE id = ?", (qs.get("id", [""])[0].strip().upper(),))
            kind = qs.get("type", ["pdf"])[0]
            if row is None:
                self.send_error(404)
                return
            if not self.is_admin():
                if kind in {"pdf", "png"}:
                    self.send_error(404)
                    return
                if row["status"] != "approved" or not downloads_unlocked():
                    self.send_error(403)
                    return
            if kind == "jpg" and row["png_filename"]:
                path = record_jpg_path(row)
                if path is None:
                    self.send_error(404)
                    return
                self.serve_path_head(path, Path(row["png_filename"]).with_suffix(".jpg").name)
            elif kind == "gallery-jpg":
                item = STATIC_GALLERY_BY_SLUG.get(qs.get("asset", [""])[0])
                if item is None:
                    self.send_error(404)
                    return
                self.serve_path_head(gallery_static_path(item, "full"), f"{item['title']}.jpg")
            elif kind == "png" and row["png_filename"]:
                path = GENERATED_DIR / row["png_filename"]
                if not path.exists() and not regenerate_record_files(row):
                    self.send_error(404)
                    return
                self.serve_path_head(path, Path(row["png_filename"]).name)
            elif kind == "pdf" and row["pdf_filename"]:
                path = GENERATED_DIR / row["pdf_filename"]
                if not path.exists() and not regenerate_record_files(row):
                    self.send_error(404)
                    return
                self.serve_path_head(path, Path(row["pdf_filename"]).name)
            else:
                self.send_error(404)
        elif parsed.path.startswith("/static/"):
            rel = parsed.path.removeprefix("/static/")
            self.serve_path_head(APP_ROOT / "static" / rel)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/gate":
            form = self.parse_urlencoded()
            pilot_id = form.get("pilot_id", "").strip().upper()
            password = form.get("password", form.get("birthday", "")).strip()
            if pilot_id not in VALID_PILOT_IDS:
                self.send_html(player_gate_page("Pilot ID不存在。"), 403)
                return
            if len(password) != 8 or not password.isdigit() or not password.startswith(("19", "20")):
                self.send_html(player_gate_page("密码不正确，密码为8位数字。", password_hint_attempt=True), 403)
                return
            self.redirect(
                "/",
                (("Set-Cookie", f"{PLAYER_COOKIE}={player_cookie_token()}; Path=/; HttpOnly; SameSite=Lax"),),
            )
        elif parsed.path == "/flight/create":
            if not self.require_player():
                return
            form = self.parse_urlencoded()
            destination_name = form.get("destination_name", "").strip()
            address = form.get("address", "").strip()
            address_lat = form.get("address_lat", "").strip()
            address_lon = form.get("address_lon", "").strip()
            address_label = form.get("address_label", "").strip()
            if not destination_name:
                self.send_html(destination_page("请先输入目标。"), 400)
                return
            if address:
                coord, address_hash = coordinate_from_address(address, address_lat, address_lon, address_label)
            else:
                coord, address_hash = random_destination_coordinate()
            submission_id = uuid.uuid4().hex[:8].upper()
            png_name, pdf_name = generated_record_names()
            flight_renderer.generate_record(
                destination_name=destination_name,
                destination_coordinate=coord,
                out_path=GENERATED_DIR / png_name,
                pdf_path=GENERATED_DIR / pdf_name,
                show_callsign=True,
            )
            db_execute(
                """
                INSERT INTO submissions (
                    id, created_at, status, destination_name, address_hash,
                    destination_coordinate, png_filename, pdf_filename, generated_at
                )
                VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?)
                """,
                (submission_id, now_text(), destination_name, address_hash, coord, png_name, pdf_name, now_text()),
            )
            warm_animation_preview(submission_id)
            self.redirect(f"/flight/confirm?id={submission_id}")
        elif parsed.path == "/flight/confirm":
            if not self.require_player():
                return
            form = self.parse_urlencoded()
            submission_id = normalize_submission_id(form.get("id", ""))
            row = db_row("SELECT id FROM submissions WHERE id = ?", (submission_id,))
            if row is None:
                self.send_html(destination_page("没找到这个飞行纪录。"), 404)
                return
            self.redirect(f"/flight/loading?id={submission_id}")
        elif parsed.path == "/submit":
            if not self.require_player():
                return
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
            proof_bond = uploaded_file_item(form, "proof_bond")
            proof_home = uploaded_file_item(form, "proof_home")
            if proof_bond is None or proof_home is None:
                self.send_html(public_page("请上传牵绊度页面和主页两张自证文件。"), 400)
                return
            contact = form.getfirst("contact", "").strip()
            if not contact:
                self.send_html(public_page("请填写小红书号或邮箱。"), 400)
                return
            contact_key = normalize_contact(contact)
            submission_id = normalize_submission_id(form.getfirst("id", ""))
            existing_row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,)) if submission_id else None
            if existing_row is not None and existing_row["status"] == "approved":
                self.redirect(f"/gallery?id={submission_id}")
                return
            duplicate = db_row(
                """
                SELECT id FROM submissions
                WHERE (user_key = ?
                   OR LOWER(REPLACE(REPLACE(TRIM(contact), ' ', ''), char(9), '')) = ?)
                   AND id != ?
                LIMIT 1
                """,
                (contact_key, contact_key, submission_id or ""),
            )
            if duplicate is not None:
                self.send_html(public_page("这个小红书号或邮箱已经提交过自证。请使用第一次保存的编号查询审核进度。"), 400)
                return
            if existing_row is not None:
                bond_original, bond_stored = save_uploaded_file(proof_bond, submission_id, "bond")
                home_original, home_stored = save_uploaded_file(proof_home, submission_id, "home")
                db_execute(
                    """
                    UPDATE submissions
                    SET status = 'pending',
                        contact = ?, user_id = ?, user_key = ?,
                        original_filename = ?, stored_filename = ?,
                        bond_original_filename = ?, bond_stored_filename = ?,
                        home_original_filename = ?, home_stored_filename = ?,
                        review_note = '自证已提交，等待审核。',
                        reviewed_at = NULL
                    WHERE id = ?
                    """,
                    (
                        contact,
                        contact,
                        contact_key,
                        bond_original,
                        bond_stored,
                        bond_original,
                        bond_stored,
                        home_original,
                        home_stored,
                        submission_id,
                    ),
                )
            else:
                submission_id = uuid.uuid4().hex[:8].upper()
                bond_original, bond_stored = save_uploaded_file(proof_bond, submission_id, "bond")
                home_original, home_stored = save_uploaded_file(proof_home, submission_id, "home")
                db_execute(
                    """
                    INSERT INTO submissions (
                        id, created_at, status, contact, user_id, user_key,
                        original_filename, stored_filename,
                        bond_original_filename, bond_stored_filename,
                        home_original_filename, home_stored_filename
                    )
                    VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        submission_id,
                        now_text(),
                        contact,
                        contact,
                        contact_key,
                        bond_original,
                        bond_stored,
                        bond_original,
                        bond_stored,
                        home_original,
                        home_stored,
                    ),
                )
            self.redirect(f"/submitted?id={submission_id}")
        elif parsed.path == "/admin/login":
            form = self.parse_urlencoded()
            password = form.get("password", "").strip()
            if not hmac.compare_digest(password, admin_password()):
                self.send_html(admin_login_page("管理员口令不正确。"), 403)
                return
            self.redirect(
                "/admin/loading",
                (("Set-Cookie", f"{ADMIN_COOKIE}={admin_cookie_token()}; Path=/; HttpOnly; SameSite=Lax"),),
            )
        elif parsed.path == "/admin/review":
            if not self.require_admin():
                return
            form = self.parse_urlencoded()
            submission_id = form.get("id", "").strip().upper()
            action = form.get("action", "")
            if action not in {"approved", "rejected"}:
                self.send_error(400)
                return
            db_execute(
                "UPDATE submissions SET status = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
                (action, now_text(), "审核已通过。" if action == "approved" else "审核未通过。", submission_id),
            )
            self.redirect("/admin")
        elif parsed.path == "/customize":
            if not self.require_player():
                return
            form = self.parse_urlencoded()
            submission_id = form.get("id", "").strip().upper()
            destination_name = form.get("destination_name", "").strip()
            address = form.get("address", "").strip()
            address_lat = form.get("address_lat", "").strip()
            address_lon = form.get("address_lon", "").strip()
            address_label = form.get("address_label", "").strip()
            row = db_row("SELECT * FROM submissions WHERE id = ?", (submission_id,))
            if row is None or row["status"] != "approved":
                self.send_error(403)
                return
            if row["pdf_filename"] or row["png_filename"]:
                self.redirect(f"/status?id={submission_id}")
                return
            if not destination_name:
                self.send_error(400)
                return
            if address:
                coord, address_hash = coordinate_from_address(address, address_lat, address_lon, address_label)
            else:
                coord, address_hash = random_destination_coordinate()
            png_name, pdf_name = generated_record_names()
            flight_renderer.generate_record(
                destination_name=destination_name,
                destination_coordinate=coord,
                out_path=GENERATED_DIR / png_name,
                pdf_path=GENERATED_DIR / pdf_name,
                show_callsign=True,
            )
            db_execute(
                """
                UPDATE submissions
                SET destination_name = ?, address_hash = ?, destination_coordinate = ?,
                    png_filename = ?, pdf_filename = ?, generated_at = ?
                WHERE id = ?
                """,
                (destination_name, address_hash, coord, png_name, pdf_name, now_text(), submission_id),
            )
            warm_animation_preview(submission_id)
            self.redirect(f"/status?id={submission_id}")
        else:
            self.send_error(404)


def main() -> None:
    ensure_db()
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    host = os.environ.get("FLIGHT_RECORD_HOST", default_host)
    port = int(os.environ.get("FLIGHT_RECORD_PORT") or os.environ.get("PORT") or "8787")
    server = ThreadingHTTPServer((host, port), FlightRecordHandler)
    print(f"Flight record site: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
