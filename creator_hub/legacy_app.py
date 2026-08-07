import base64
import hashlib
import hmac
import io
import json
import math
import os
import re
import requests
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from html import escape
from urllib.parse import quote, urlparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from flask import (
    Flask, flash, jsonify, redirect, render_template, render_template_string,
    request, send_from_directory, session, url_for
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from markupsafe import Markup
from openai import OpenAI
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build


BASE_DIR = Path(__file__).resolve().parent

# Codespace/로컬 개발 환경에서는 터미널에 export로 매번 키를 넣지 않아도,
# BASE_DIR/.env 파일에 OPENAI_API_KEY=... 형태로 한 번만 적어두면
# 서버가 시작할 때 자동으로 읽어옵니다. (python-dotenv가 없으면 조용히
# 건너뛰고 기존처럼 실제 환경변수만 사용합니다. Render 등 실제 배포
# 환경에서는 이미 대시보드에 등록한 값을 그대로 쓰므로 영향이 없습니다.)
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

MEDIA_DIR = BASE_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
APP_VERSION = "V33 ULTIMATE"
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Render는 실제로는 https로 요청을 받지만, 내부적으로는 http로 우리
# 서버에 전달하면서 "원래는 https였다"는 정보를 X-Forwarded-Proto라는
# 헤더에 담아 보내줍니다. ProxyFix가 이 헤더를 읽어서, url_for(...,
# _external=True)가 http가 아니라 https 링크를 만들도록 고쳐줍니다.
# (이게 없으면 인스타그램 같은 외부 API에 http 링크를 보내게 되어
# 이미지를 못 가져가는 문제가 생겼습니다.)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["PREFERRED_URL_SCHEME"] = "https"

database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'creator.db'}")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

db = SQLAlchemy(app)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/blogger"]

# 인스타그램 자동 게시 (Instagram API with Instagram Login, Standard Access —
# 본인 계정에만 게시하는 용도라 메타 앱 심사 없이 바로 사용 가능합니다).
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com/v25.0"
KST = ZoneInfo("Asia/Seoul")

# 쿠팡파트너스 오픈API. 파트너스 사이트에서 API 키를 발급받은 뒤
# 이 두 값을 환경변수로 등록하면 상품명 검색만으로 제휴 링크를 바로
# 가져올 수 있습니다. 키가 없으면 이 기능은 자동으로 꺼진 채로
# 동작하고(에러를 내지 않고 "설정되지 않음" 상태로만 표시), 지금처럼
# 손으로 링크를 붙여넣는 방식은 그대로 계속 쓸 수 있습니다.
COUPANG_ACCESS_KEY = os.getenv("COUPANG_ACCESS_KEY", "")
COUPANG_SECRET_KEY = os.getenv("COUPANG_SECRET_KEY", "")
COUPANG_API_DOMAIN = "https://api-gateway.coupang.com"


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(200), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    meta_description = db.Column(db.Text, default="")
    body_html = db.Column(db.Text, default="")
    brand_style = db.Column(db.String(100), default="육아·생활")
    article_type = db.Column(db.String(100), default="정보형")
    audience = db.Column(db.String(300), default="")
    notes = db.Column(db.Text, default="")
    tags = db.Column(db.Text, default="")
    seo_score = db.Column(db.Integer, default=0)
    seo_report = db.Column(db.Text, default="{}")
    thumbnail_path = db.Column(db.String(500), nullable=True)
    fortune_card_path = db.Column(db.String(500), nullable=True)
    fortune_card_paths = db.Column(db.Text, default="")  # JSON 리스트, 카드뉴스 여러 장
    fortune_reel_path = db.Column(db.String(500), nullable=True)
    thumbnail_text = db.Column(db.String(300), nullable=True)
    blogger_post_id = db.Column(db.String(200), nullable=True)
    blogger_blog_id = db.Column(db.String(200), nullable=True)
    blogger_url = db.Column(db.String(1000), nullable=True)
    blogger_status = db.Column(db.String(50), nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    instagram_caption = db.Column(db.Text, default="")
    threads_text = db.Column(db.Text, default="")
    shorts_script = db.Column(db.Text, default="")
    youtube_title = db.Column(db.String(300), default="")
    youtube_description = db.Column(db.Text, default="")
    youtube_tags = db.Column(db.String(500), default="")
    tiktok_caption = db.Column(db.Text, default="")
    instatoon_images = db.Column(db.Text, default="{}")
    instatoon_captioned_images = db.Column(db.Text, default="{}")
    instatoon_character_profile = db.Column(db.Text, default="{}")
    instatoon_character_sheet = db.Column(db.String(500), nullable=True)
    instatoon_reference_image = db.Column(db.String(500), nullable=True)
    reels_path = db.Column(db.String(500), nullable=True)
    reels_settings = db.Column(db.Text, default="{}")
    instatoon_audio = db.Column(db.Text, default="{}")
    instatoon_audio_settings = db.Column(db.Text, default="{}")
    reels_voice_path = db.Column(db.String(500), nullable=True)
    reels_voice_settings = db.Column(db.Text, default="{}")
    reels_bgm_path = db.Column(db.String(500), nullable=True)
    reels_final_path = db.Column(db.String(500), nullable=True)
    reels_final_settings = db.Column(db.Text, default="{}")
    export_package_path = db.Column(db.String(500), nullable=True)
    export_package_settings = db.Column(db.Text, default="{}")
    director_report = db.Column(db.Text, default="{}")
    director_revised_instatoon = db.Column(db.Text, default="")
    production_queue_state = db.Column(db.Text, default="{}")
    coupang_product_name = db.Column(db.String(300), default="")
    coupang_link = db.Column(db.String(1000), default="")
    atomy_product_name = db.Column(db.String(300), default="")
    atomy_link = db.Column(db.String(1000), default="")
    toss_product_name = db.Column(db.String(300), default="")
    toss_link = db.Column(db.String(1000), default="")
    affiliate_html = db.Column(db.Text, default="")
    affiliate_enabled = db.Column(db.Boolean, default=False)
    blog_done = db.Column(db.Boolean, default=False)
    instagram_done = db.Column(db.Boolean, default=False)
    threads_done = db.Column(db.Boolean, default=False)
    shorts_done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PublishLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    message = db.Column(db.Text, default="")
    blogger_url = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    article = db.relationship("Article", backref=db.backref("publish_logs", lazy=True, cascade="all, delete-orphan"))




class InstatoonPreset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, default="")
    profile_json = db.Column(db.Text, default="{}")
    reference_image = db.Column(db.String(500), nullable=True)
    character_sheet = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )



class ContentIdea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(200), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    hook = db.Column(db.Text, default="")
    format_type = db.Column(db.String(80), default="블로그")
    status = db.Column(db.String(30), default="대기")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text, default="")


def ensure_schema():
    """Create tables and add V6 columns to an existing database safely."""
    db.create_all()
    inspector = inspect(db.engine)
    if "article" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("article")}
    dialect = db.engine.dialect.name
    column_sql = {
        "blogger_blog_id": "VARCHAR(200)",
        "blogger_url": "VARCHAR(1000)",
        "scheduled_at": "TIMESTAMP" if dialect == "postgresql" else "DATETIME",
        "instagram_caption": "TEXT",
        "threads_text": "TEXT",
        "shorts_script": "TEXT",
        "youtube_title": "VARCHAR(300)",
        "fortune_card_path": "VARCHAR(500)",
        "fortune_card_paths": "TEXT",
        "fortune_reel_path": "VARCHAR(500)",
        "youtube_description": "TEXT",
        "youtube_tags": "VARCHAR(500)",
        "tiktok_caption": "TEXT",
        "instatoon_images": "TEXT DEFAULT '{}'",
        "instatoon_captioned_images": "TEXT DEFAULT '{}'",
        "instatoon_character_profile": "TEXT DEFAULT '{}'",
        "instatoon_character_sheet": "VARCHAR(500)",
        "instatoon_reference_image": "VARCHAR(500)",
        "reels_path": "VARCHAR(500)",
        "reels_settings": "TEXT DEFAULT '{}'",
        "instatoon_audio": "TEXT DEFAULT '{}'",
        "instatoon_audio_settings": "TEXT DEFAULT '{}'",
        "reels_voice_path": "VARCHAR(500)",
        "reels_voice_settings": "TEXT DEFAULT '{}'",
        "reels_bgm_path": "VARCHAR(500)",
        "reels_final_path": "VARCHAR(500)",
        "reels_final_settings": "TEXT DEFAULT '{}'",
        "export_package_path": "VARCHAR(500)",
        "export_package_settings": "TEXT DEFAULT '{}'",
        "director_report": "TEXT DEFAULT '{}'",
        "director_revised_instatoon": "TEXT",
        "production_queue_state": "TEXT DEFAULT '{}'",
        "coupang_product_name": "VARCHAR(300)",
        "coupang_link": "VARCHAR(1000)",
        "atomy_product_name": "VARCHAR(300)",
        "atomy_link": "VARCHAR(1000)",
        "toss_product_name": "VARCHAR(300)",
        "toss_link": "VARCHAR(1000)",
        "affiliate_html": "TEXT",
        "affiliate_enabled": "BOOLEAN DEFAULT FALSE" if dialect == "postgresql" else "INTEGER DEFAULT 0",
        "blog_done": "BOOLEAN DEFAULT FALSE" if dialect == "postgresql" else "INTEGER DEFAULT 0",
        "instagram_done": "BOOLEAN DEFAULT FALSE" if dialect == "postgresql" else "INTEGER DEFAULT 0",
        "threads_done": "BOOLEAN DEFAULT FALSE" if dialect == "postgresql" else "INTEGER DEFAULT 0",
        "shorts_done": "BOOLEAN DEFAULT FALSE" if dialect == "postgresql" else "INTEGER DEFAULT 0",
    }

    with db.engine.begin() as conn:
        for name, sql_type in column_sql.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE article ADD COLUMN {name} {sql_type}"))


with app.app_context():
    ensure_schema()


def get_setting(key, default=""):
    row = AppSetting.query.filter_by(setting_key=key).first()
    return row.setting_value if row else default


def set_setting(key, value):
    row = AppSetting.query.filter_by(setting_key=key).first()
    if not row:
        row = AppSetting(setting_key=key)
        db.session.add(row)
    row.setting_value = value
    db.session.commit()


def log_ai_usage(category):
    """OpenAI를 호출할 때마다 이번 달 사용 횟수를 자동으로 1 늘립니다.
    정확한 달러 비용은 모델별 가격이 자주 바뀌어 여기서 추정하지 않고,
    "몇 번 썼는지"만 정확하게 기록합니다. 실제 청구 금액은 OpenAI
    사용량 페이지(platform.openai.com/usage)에서 확인해 수익 대시보드에
    직접 입력하는 방식은 그대로 유지합니다. 기록 실패는 조용히 무시합니다
    (콘텐츠 생성 자체가 이 기록 때문에 실패하면 안 되므로).
    """
    try:
        month_key = f"ai_usage_{datetime.utcnow().strftime('%Y-%m')}"
        raw = get_setting(month_key, "{}")
        try:
            counts = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            counts = {}
        if not isinstance(counts, dict):
            counts = {}
        counts[category] = int(counts.get(category, 0)) + 1
        set_setting(month_key, json.dumps(counts, ensure_ascii=False))
    except Exception:
        pass


def get_ai_usage_this_month():
    """이번 달 AI 사용 횟수를 {"text": n, "image": n, "audio": n} 형태로 돌려줍니다."""
    month_key = f"ai_usage_{datetime.utcnow().strftime('%Y-%m')}"
    raw = get_setting(month_key, "{}")
    try:
        counts = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        counts = {}
    return counts if isinstance(counts, dict) else {}


def openai_client():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("Render 환경변수에 OPENAI_API_KEY가 없습니다.")

    return OpenAI(api_key=api_key)


def strip_code_fence(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json|html)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_article(keyword, brand_style, article_type, length, audience, notes):
    prompt = f"""
당신은 한국어 SEO 블로그 전문 작가입니다.
아래 조건으로 사실을 꾸며내지 않는 실용적인 블로그 글을 작성하세요.

키워드: {keyword}
브랜드 스타일: {brand_style}
글 유형: {article_type}
분량: {length}
독자: {audience or '일반 독자'}
직접 경험 또는 반드시 포함할 내용: {notes or '없음'}

작성 규칙:
1. 제목은 자연스럽고 핵심 키워드를 포함합니다.
2. 메타 설명은 80~150자 정도로 작성합니다.
3. 본문은 HTML만 사용합니다. h2, h3, p, ul, ol, li, strong 태그를 중심으로 구성합니다.
4. 서론, 핵심 설명, 실용 팁, FAQ 3개, 결론을 포함합니다.
5. 확인하지 않은 가격, 통계, 인증, 효능은 단정하지 않습니다.
6. 과장 광고나 의료적 확정 표현을 사용하지 않습니다.
7. 태그는 # 없이 한국어 중심으로 5~8개 작성합니다.

반드시 아래 JSON 형식 하나만 출력하세요.
{{
  "title": "제목",
  "meta_description": "메타 설명",
  "body_html": "<h2>...</h2>",
  "tags": ["태그1", "태그2"]
}}
"""
    response = openai_client().responses.create(
        model=OPENAI_MODEL,
        input=prompt
    )
    log_ai_usage("text")
    raw = strip_code_fence(response.output_text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise RuntimeError("AI 응답을 JSON으로 읽지 못했습니다. 다시 생성해 주세요.")
        data = json.loads(match.group(0))
    return data


def plain_text_from_html(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def analyze_seo(article):
    html = article.body_html or ""
    text = plain_text_from_html(html)
    keyword = (article.keyword or "").strip()
    title = article.title or ""
    meta = article.meta_description or ""

    checks = []
    score = 0

    def add(name, passed, points, advice):
        nonlocal score
        if passed:
            score += points
        checks.append({
            "name": name,
            "passed": passed,
            "points": points,
            "advice": advice
        })

    add("제목에 핵심 키워드", keyword.lower() in title.lower(), 20,
        "제목에 핵심 키워드를 자연스럽게 넣으세요.")
    add("제목 길이", 15 <= len(title) <= 45, 10,
        "제목은 약 15~45자로 다듬어 보세요.")
    add("메타 설명 길이", 70 <= len(meta) <= 160, 15,
        "메타 설명은 약 70~160자로 작성하세요.")
    add("H2 소제목", len(re.findall(r"<h2\b", html, re.I)) >= 3, 15,
        "H2 소제목을 3개 이상 구성하세요.")
    add("FAQ 포함", "FAQ" in text.upper() or "자주 묻" in text, 10,
        "FAQ 또는 자주 묻는 질문을 추가하세요.")
    add("본문 분량", len(text) >= 1200, 15,
        "본문을 1,200자 이상으로 보강하세요.")
    add("목록 활용", bool(re.search(r"<(ul|ol)\b", html, re.I)), 5,
        "핵심 내용을 목록으로 정리하세요.")
    add("키워드 자연 반복", 2 <= text.lower().count(keyword.lower()) <= 15 if keyword else False, 10,
        "핵심 키워드를 본문에 2~15회 정도 자연스럽게 사용하세요.")

    return min(score, 100), {"checks": checks, "text_length": len(text)}


def image_prompt(article, style, thumbnail_text):
    body_summary = plain_text_from_html(article.body_html)[:700]
    return f"""
Create a polished horizontal Korean blog hero image.
Topic: {article.keyword}
Article summary: {body_summary}
Visual style: {style}
Composition: 3:2 landscape, clear central subject, generous clean space for a headline overlay.
Mood: trustworthy, warm, modern, family-friendly.
Do not include logos, watermarks, brand marks, prices, statistics, or tiny unreadable text.
Do not render the Korean headline inside the image. The web app overlays this text separately:
{thumbnail_text}
"""


def generate_thumbnail(article, style, thumbnail_text):
    
    result = openai_client().images.generate(
        model=IMAGE_MODEL,
        prompt=image_prompt(article, style, thumbnail_text),
        size="1536x1024",
        quality="medium"
    )
    log_ai_usage("image")
    image_b64 = result.data[0].b64_json
    if not image_b64:
        raise RuntimeError("이미지 데이터가 반환되지 않았습니다.")
    filename = f"article_{article.id}_{int(datetime.utcnow().timestamp())}.png"
    (MEDIA_DIR / filename).write_bytes(base64.b64decode(image_b64))
    return filename


ZODIAC_ANIMALS = ["쥐", "소", "범", "토끼", "용", "뱀", "말", "양", "원숭이", "닭", "개", "돼지"]
ZODIAC_ANIMALS_EN = {
    "쥐": "rat", "소": "ox", "범": "tiger", "토끼": "rabbit", "용": "dragon",
    "뱀": "snake", "말": "horse", "양": "goat", "원숭이": "monkey",
    "닭": "rooster", "개": "dog", "돼지": "pig",
}
ZODIAC_BOX_COLORS = [(70, 140, 255), (170, 110, 255), (235, 80, 80)]


def zodiac_birth_years(animal, count=4, reference_year=None):
    """해당 띠에 해당하는 최근 출생연도 4개를 계산합니다(1900년=쥐띠 기준
    12년 주기). 올해는 제외하고 그 이전 연도들로 계산합니다."""
    reference_year = (reference_year or datetime.utcnow().year) - 1
    idx = ZODIAC_ANIMALS.index(animal)
    years = []
    year = reference_year
    while len(years) < count:
        if (year - 1900) % 12 == idx:
            years.append(year)
        year -= 1
    return years


def get_zodiac_icon(animal):
    """12띠 아이콘은 매일 내용이 바뀌지 않는 그림이라, 한 번만 만들고
    계속 재사용합니다(파일이 이미 있으면 새로 안 만듭니다)."""
    filename = f"zodiac_icon_{animal}.png"
    path = MEDIA_DIR / filename
    if path.exists():
        return filename

    animal_en = ZODIAC_ANIMALS_EN.get(animal, animal)
    prompt = f"""
A cute, clean circular badge illustration of a {animal_en}, for a
Korean 12-zodiac (십이지신) fortune card series. Friendly, semi-flat
illustration style, centered, filling most of the frame. Warm gold
and deep-navy color accents. No text, no letters, no numbers, no
watermark. Square 1:1 image.
"""
    result = openai_client().images.generate(
        model=IMAGE_MODEL, prompt=prompt, size="1024x1024", quality="medium"
    )
    log_ai_usage("image")
    image_b64 = result.data[0].b64_json
    if not image_b64:
        raise RuntimeError(f"{animal}띠 아이콘 생성에 실패했습니다.")
    path.write_bytes(base64.b64decode(image_b64))
    return filename


def generate_zodiac_fortune_texts(article):
    """12간지 전부에 대해 오늘의 운세를 4줄씩 만듭니다(한 번의 AI
    요청으로 12개를 다 만들어서 비용을 아낍니다)."""
    prompt = f"""
다음은 오늘의 띠별 운세 콘텐츠 글입니다. 이 글의 전체적인 톤을
참고해서, 12간지 각 띠에 대해 오늘의 운세를 4줄씩 새로 작성하세요.

제목: {article.title}
본문: {plain_text_from_html(article.body_html)[:2000]}

규칙:
- 12간지: 쥐, 소, 범, 토끼, 용, 뱀, 말, 양, 원숭이, 닭, 개, 돼지 (이
  순서 그대로 12개 전부 빠짐없이 작성)
- 각 띠마다 정확히 4줄. 각 줄은 "~습니다/~하세요"로 끝나는 자연스럽고
  완결된 문장으로 씁니다. 대략 20~30자 정도가 읽기 좋지만, **글자수를
  맞추려고 문장을 중간에 끊지 마세요. 절대 "~하세요", "~합니다"처럼
  끝까지 완성된 형태로만 씁니다.** 글자수보다 문장을 끝까지 완성하는
  것이 훨씬 더 중요합니다. 키워드만 나열하지 말고 실제 조언이 되는
  문장으로 씁니다.
  예시 톤: "오전 일정은 머리로 기억하지 말고 알림을 하나 더 맞추세요"
- 확정적 표현("무조건", "100%")은 쓰지 않고, 불안을 조장하는 표현도
  자제합니다.

반드시 아래 JSON 형식으로만 답하세요. 다른 설명은 쓰지 마세요.
{{"쥐": ["...", "...", "...", "..."], "소": ["...", "...", "...", "..."]}}
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    log_ai_usage("text")
    raw = strip_code_fence(response.output_text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(match.group(0)) if match else {}
    if not isinstance(data, dict):
        data = {}

    fallback = [
        "오늘은 평온한 하루가 예상됩니다",
        "무리하지 않는 선에서 진행하세요",
        "작은 배려가 좋은 인연을 만듭니다",
        "여유를 갖고 하루를 마무리해보세요",
    ]
    sentence_endings = (
        "세요", "니다", "봐요", "해요", "돼요", "구요", "라요", "네요",
        "어요", "아요", "죠", "함", "임", "다.", "요.",
    )

    def looks_complete(text):
        text = text.strip()
        return bool(text) and text.endswith(sentence_endings)

    for animal in ZODIAC_ANIMALS:
        lines = data.get(animal)
        if not isinstance(lines, list) or not lines:
            data[animal] = list(fallback)
        else:
            cleaned = []
            for x in lines[:4]:
                text = str(x).strip()
                # 22자로 강제로 자르던 부분을 없앴습니다(문장이 잘리던
                # 진짜 원인이었어요). 대신 문장이 끝까지 완성됐는지만
                # 확인하고, 중간에 끊긴 것 같으면 안전한 문장으로
                # 바꿉니다.
                if text and looks_complete(text):
                    cleaned.append(text)
                elif text:
                    cleaned.append(fallback[len(cleaned) % len(fallback)])
            while len(cleaned) < 4:
                cleaned.append(fallback[len(cleaned) % len(fallback)])
            data[animal] = cleaned
    return data


def generate_fortune_shared_background():
    """카드 7장이 전부 같은 배경을 씁니다. AI 이미지 대신 흰색 배경을
    직접 그려서 만듭니다 — 이러면 100% 확실하게 밝고, 위에 올리는
    글씨도 항상 잘 보이고, AI 이미지 호출을 하나 줄여서 더 빨라져요."""
    width, height = 1024, 1536
    image = Image.new("RGB", (width, height), (255, 253, 248))
    draw = ImageDraw.Draw(image, "RGBA")
    # 은은한 느낌을 주기 위한 아주 옅은 점 패턴(장식용, 글씨랑 안 겹치게 연하게)
    import random
    rnd = random.Random(42)
    for _ in range(90):
        x, y = rnd.randint(0, width), rnd.randint(0, height)
        r = rnd.randint(1, 2)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(230, 220, 200, 140))
    return image


def _centered_text(draw, text, font, y, width, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (width - (bbox[2] - bbox[0])) // 2
    draw.text((x, y), text, font=font, fill=fill)


INK = (34, 31, 43, 255)
MUTED = (110, 100, 130, 255)
GOLD = (184, 146, 90, 255)


def compose_fortune_cover(background, article, today, article_id):
    image = background.copy()
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    cx, cy = width // 2, int(height * 0.42)
    r = int(width * 0.40)
    diamond = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r)]
    draw.line(diamond, fill=GOLD, width=6)
    r2 = r - 20
    diamond2 = [(cx, cy - r2), (cx + r2, cy), (cx, cy + r2), (cx - r2, cy), (cx, cy - r2)]
    draw.line(diamond2, fill=(184, 146, 90, 130), width=2)

    date_font = get_korean_font(42, bold=True)
    title_font = get_korean_font(70, bold=True)
    sub_font = get_korean_font(34, bold=True)

    _centered_text(draw, today.strftime("%m월 %d일"), date_font, cy - 150, width, GOLD)
    _centered_text(draw, "오늘의 운세", title_font, cy - 80, width, INK)
    _centered_text(draw, "十二支", sub_font, cy + 6, width, MUTED)

    icon_size = int(r * 0.9)
    today_animal = ZODIAC_ANIMALS[(today.year - 1900) % 12]
    try:
        icon = Image.open(MEDIA_DIR / get_zodiac_icon(today_animal)).convert("RGBA")
        icon = icon.resize((icon_size, icon_size))
        image.paste(icon, (cx - icon_size // 2, cy + 60), icon)
    except Exception:
        pass

    footer_font = get_korean_font(30, bold=True)
    _centered_text(draw, "매일 아침 새로운 하루를 위한 오늘의 운세", footer_font, height - 90, width, MUTED)

    filename = f"fortune_cover_{article_id}_{int(datetime.utcnow().timestamp())}.png"
    image.save(MEDIA_DIR / filename, "PNG")
    return filename


def compose_zodiac_slide(background, today, animals_subset, texts, slide_index, article_id):
    image = background.copy()
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    margin = 40

    title_font = get_korean_font(46, bold=True)
    _centered_text(draw, f"{today.strftime('%m월 %d일')} 오늘의 띠별 운세", title_font, 44, width, INK)

    box_top = 130
    box_gap = 26
    box_height = (height - box_top - margin - box_gap * 2) // 3

    for i, animal in enumerate(animals_subset):
        color = ZODIAC_BOX_COLORS[i % len(ZODIAC_BOX_COLORS)]
        box_y = box_top + i * (box_height + box_gap)
        draw.rounded_rectangle(
            (margin, box_y, width - margin, box_y + box_height),
            radius=26, outline=color + (255,), width=4, fill=(255, 255, 255, 255),
        )

        icon_size = box_height - 150
        label_font = get_korean_font(34, bold=True)
        label_text = f"{animal}띠"
        label_gap = 12
        icon_block_h = icon_size + label_gap + 42
        icon_block_y = box_y + (box_height - icon_block_h) // 2

        try:
            icon = Image.open(MEDIA_DIR / get_zodiac_icon(animal)).convert("RGBA").resize((icon_size, icon_size))
            mask = Image.new("L", (icon_size, icon_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, icon_size, icon_size), fill=255)
            image.paste(icon, (margin + 17, icon_block_y), mask)
            draw.ellipse(
                (margin + 17, icon_block_y, margin + 17 + icon_size, icon_block_y + icon_size),
                outline=color + (255,), width=3,
            )
        except Exception:
            pass

        bbox = draw.textbbox((0, 0), label_text, font=label_font)
        draw.text(
            (margin + 17 + (icon_size - (bbox[2] - bbox[0])) // 2, icon_block_y + icon_size + label_gap),
            label_text, font=label_font, fill=INK,
        )

        years = zodiac_birth_years(animal, reference_year=today.year)
        lines = texts.get(animal, [])
        year_font = get_korean_font(29, bold=True)
        line_font = get_korean_font(29, bold=False)
        text_x = margin + 17 + icon_size + 16
        text_w = width - margin - text_x - 20
        row_h = box_height / 4
        for row in range(4):
            row_top = box_y + row * row_h
            year_label = str(years[row]) if row < len(years) else ""
            draw.text((text_x, row_top + 14), year_label, font=year_font, fill=color + (255,))
            line_text = lines[row] if row < len(lines) else ""
            wrapped = wrap_text_by_words(draw, line_text, line_font, text_w - 80)
            line_y = row_top + 10
            for wline in wrapped:
                draw.text((text_x + 80, line_y), wline, font=line_font, fill=INK)
                line_y += 34

    filename = f"fortune_slide{slide_index}_{article_id}_{int(datetime.utcnow().timestamp())}.png"
    image.save(MEDIA_DIR / filename, "PNG")
    return filename


def compose_fortune_closing(background, today, article_id):
    image = background.copy()
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    title_font = get_korean_font(54, bold=True)
    body_font = get_korean_font(32, bold=False)

    title_lines = ["날마다 새로운 마음으로,", "오늘 하루도 힘내봐요"]
    line_h = 68
    pad_top = 56
    pad_between = 30
    pad_bottom = 50

    box_content_h = pad_top + line_h * len(title_lines) + pad_between + 40 + pad_bottom
    box_w = int(width * 0.8)
    box_x = (width - box_w) // 2
    box_y = (height - box_content_h) // 2

    # 허전해 보이지 않게, 아이콘 대신 은은한 테두리의 예쁜 글씨 박스를 넣습니다.
    draw.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_content_h),
        radius=32, outline=GOLD, width=3, fill=(250, 246, 236, 255),
    )
    accent_w = 60
    draw.rounded_rectangle(
        (width // 2 - accent_w // 2, box_y + 22, width // 2 + accent_w // 2, box_y + 26),
        radius=2, fill=GOLD,
    )

    y = box_y + pad_top
    for line in title_lines:
        _centered_text(draw, line, title_font, y, width, INK)
        y += line_h

    _centered_text(draw, "오늘 나의 다짐을 댓글로 남겨보세요", body_font, y + pad_between, width, MUTED)

    filename = f"fortune_closing_{article_id}_{int(datetime.utcnow().timestamp())}.png"
    image.save(MEDIA_DIR / filename, "PNG")
    return filename


def compose_fortune_promo(background, today, article_id):
    image = background.copy()
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    title_font = get_korean_font(48, bold=True)
    price_font = get_korean_font(62, bold=True)
    body_font = get_korean_font(30, bold=False)
    url_font = get_korean_font(34, bold=True)

    fortune_url = os.getenv("FORTUNE_URL", "https://ai-blog-factory.onrender.com/fortune/")
    title_lines = ["나만의 자세한 운세가", "궁금하다면?"]

    icon_size = int(width * 0.26)
    icon_gap = 30
    title_line_h = 62
    price_gap = 50
    price_h = 70
    url_gap = 60
    url_h = 40
    body_gap = 20
    body_h = 34
    total_h = (
        icon_size + icon_gap
        + title_line_h * len(title_lines) + price_gap + price_h
        + url_gap + url_h + body_gap + body_h
    )

    y = (height - total_h) // 2
    today_animal = ZODIAC_ANIMALS[(today.year - 1900) % 12]
    try:
        icon = Image.open(MEDIA_DIR / get_zodiac_icon(today_animal)).convert("RGBA").resize((icon_size, icon_size))
        image.paste(icon, ((width - icon_size) // 2, y), icon)
    except Exception:
        pass
    y += icon_size + icon_gap

    for line in title_lines:
        _centered_text(draw, line, title_font, y, width, INK)
        y += title_line_h

    y += price_gap
    _centered_text(draw, "3,000원", price_font, y, width, GOLD)
    y += price_h

    y += url_gap
    # 사진 안에는 실제로 눌리는 링크를 넣을 수 없어서(인스타그램 등은
    # 프로필 링크만 클릭 가능), 주소 글자를 눈에 보이게 그대로 넣습니다.
    draw.rounded_rectangle(
        (width * 0.12, y - 14, width * 0.88, y + url_h + 6),
        radius=16, outline=GOLD, width=3, fill=(250, 243, 230, 255),
    )
    _centered_text(draw, fortune_url.replace("https://", ""), url_font, y, width, GOLD)
    y += url_h + body_gap

    _centered_text(draw, "위 주소를 눌러(또는 검색해서) 생년월일을 넣어보세요", body_font, y, width, MUTED)

    filename = f"fortune_promo_{article_id}_{int(datetime.utcnow().timestamp())}.png"
    image.save(MEDIA_DIR / filename, "PNG")
    return filename


def generate_fortune_carousel(article):
    """표지+띠별 운세 4장+마무리+홍보 카드까지 총 7장짜리 카드뉴스
    세트를 만듭니다. 배경은 흰색 고정이라 AI 이미지 호출 없이 빠르게
    만들어집니다."""
    today = datetime.utcnow().date()
    background = generate_fortune_shared_background()
    texts = generate_zodiac_fortune_texts(article)

    filenames = [compose_fortune_cover(background, article, today, article.id)]
    for i in range(4):
        subset = ZODIAC_ANIMALS[i * 3:(i + 1) * 3]
        filenames.append(compose_zodiac_slide(background, today, subset, texts, i + 1, article.id))
    filenames.append(compose_fortune_closing(background, today, article.id))
    filenames.append(compose_fortune_promo(background, today, article.id))
    return filenames


# ── TOP3 훅 릴스 전용 카드뉴스 (강렬한 빨강·블랙 쇼츠 스타일) ──────────
# 사장님이 미리 써둔 "훅 / N위 OO띠 - 이유 / ... / CTA" 형식의 대본을
# 붙여넣었을 때, 기존의 "12지신 전부 보여주는" 카드 대신 훅과 TOP N
# 순위만 크게 보여주는 임팩트 있는 카드로 만듭니다.

TOP3_RANK_COLORS = {1: (255, 205, 60), 2: (210, 210, 215), 3: (205, 140, 80)}
TOP3_RANK_FALLBACK_COLOR = (226, 40, 40)


def parse_top3_brief(text):
    """'훅 문구 / 1위 OO띠 - 이유 / 2위 ... / CTA 문구' 형식(슬래시나
    줄바꿈으로 구분)의 대본을 파싱합니다. 'N위 OO띠 - 이유' 패턴이
    2개 이상 없으면(=TOP N 형식이 아니면) None을 돌려줘서, 호출하는
    쪽이 기존 12지신 전체 카드 방식으로 자연스럽게 넘어가게 합니다."""
    text = (text or "").strip()
    if not text:
        return None

    segments = [s.strip() for s in re.split(r"/|\n", text) if s.strip()]
    rank_pattern = re.compile(r"^(\d)\s*위\s*([가-힣]{1,3})\s*띠\s*[-–—:]\s*(.+)$")

    items = []
    before, after = [], []
    for seg in segments:
        match = rank_pattern.match(seg)
        if match:
            animal = match.group(2)
            if animal in ZODIAC_ANIMALS:
                items.append({
                    "rank": int(match.group(1)),
                    "animal": animal,
                    "reason": match.group(3).strip(),
                })
                continue
        (after if items else before).append(seg)

    if len(items) < 2:
        return None

    items.sort(key=lambda x: x["rank"])
    items = items[:5]
    hook = before[0] if before else f"오늘 {items[0]['animal']}띠 등 TOP{len(items)} 확인하세요"
    cta = after[-1] if after else "저장하고 다음 운세도 받아가세요"
    return {"hook": hook, "items": items, "cta": cta}


def generate_top3_fortune_shared_background():
    """검정에서 진한 레드로 은은하게 퍼지는 배경(쇼츠에서 자주 보이는
    강렬한 느낌). 카드마다 다시 그리지 않도록 한 번만 만들어 재사용."""
    width, height = 1024, 1536
    # 세로 1픽셀짜리 그라데이션만 계산한 뒤 가로로 늘려서 만듭니다
    # (가로세로 전체를 픽셀 단위로 채우면 느려서, 계산량을 height번으로 줄입니다).
    gradient = Image.new("RGB", (1, height))
    for y in range(height):
        t = (y / height) ** 2
        r = int(12 + (70 - 12) * t)
        g = int(10 + (8 - 10) * t)
        b = int(14 - 4 * t)
        gradient.putpixel((0, y), (r, g, b))
    image = gradient.resize((width, height))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((22, 22, width - 22, height - 22), outline=(226, 40, 40, 220), width=4)
    return image


def compose_top3_cover(background, hook_text, rank_count, today, article_id):
    image = background.copy()
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    badge_font = get_korean_font(40, bold=True)
    hook_font = get_korean_font(62, bold=True)
    date_font = get_korean_font(30, bold=True)

    badge_text = f"TOP{rank_count}"
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_pad_x, badge_pad_y = 34, 18
    badge_w = (bbox[2] - bbox[0]) + badge_pad_x * 2
    badge_h = (bbox[3] - bbox[1]) + badge_pad_y * 2
    badge_x = (width - badge_w) // 2
    badge_y = int(height * 0.16)
    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=badge_h // 2, fill=(226, 40, 40, 255),
    )
    draw.text((badge_x + badge_pad_x, badge_y + badge_pad_y - 6), badge_text, font=badge_font, fill=(255, 255, 255, 255))

    max_w = int(width * 0.82)
    lines = wrap_text_by_words(draw, hook_text, hook_font, max_w)
    y = badge_y + badge_h + 70
    for line in lines:
        _centered_text(draw, line, hook_font, y, width, (255, 255, 255, 255))
        y += 82

    _centered_text(draw, today.strftime("%m월 %d일 오늘의 운세"), date_font, height - 90, width, (226, 40, 40, 255))

    filename = f"top3_cover_{article_id}_{int(datetime.utcnow().timestamp())}.png"
    image.save(MEDIA_DIR / filename, "PNG")
    return filename


def compose_top3_rank_card(background, rank, animal, reason, article_id):
    image = background.copy()
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    color = TOP3_RANK_COLORS.get(rank, TOP3_RANK_FALLBACK_COLOR) + (255,)

    rank_font = get_korean_font(90, bold=True)
    label_font = get_korean_font(30, bold=True)
    animal_font = get_korean_font(72, bold=True)
    reason_font = get_korean_font(38, bold=True)

    badge_r = 90
    badge_cx, badge_cy = width // 2, int(height * 0.16)
    draw.ellipse((badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r), fill=color)
    rank_text = str(rank)
    bbox = draw.textbbox((0, 0), rank_text, font=rank_font)
    draw.text(
        (badge_cx - (bbox[2] - bbox[0]) // 2, badge_cy - (bbox[3] - bbox[1]) // 2 - 10),
        rank_text, font=rank_font, fill=(15, 15, 18, 255),
    )
    _centered_text(draw, "위", label_font, badge_cy + badge_r + 14, width, color)

    icon_size = int(width * 0.42)
    icon_y = badge_cy + badge_r + 70
    try:
        icon = Image.open(MEDIA_DIR / get_zodiac_icon(animal)).convert("RGBA").resize((icon_size, icon_size))
        image.paste(icon, ((width - icon_size) // 2, icon_y), icon)
    except Exception:
        pass

    name_y = icon_y + icon_size + 24
    _centered_text(draw, f"{animal}띠", animal_font, name_y, width, (255, 255, 255, 255))

    reason_y = name_y + 100
    max_w = int(width * 0.82)
    for line in wrap_text_by_words(draw, reason, reason_font, max_w)[:3]:
        _centered_text(draw, line, reason_font, reason_y, width, color)
        reason_y += 52

    filename = f"top3_rank{rank}_{article_id}_{int(datetime.utcnow().timestamp())}.png"
    image.save(MEDIA_DIR / filename, "PNG")
    return filename


def compose_top3_cta(background, cta_text, article_id):
    image = background.copy()
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    cta_font = get_korean_font(56, bold=True)
    sub_font = get_korean_font(30, bold=True)

    max_w = int(width * 0.8)
    lines = wrap_text_by_words(draw, cta_text, cta_font, max_w)
    y = (height - len(lines) * 72) // 2 - 40
    for line in lines:
        _centered_text(draw, line, cta_font, y, width, (255, 255, 255, 255))
        y += 72

    _centered_text(draw, "매일 아침 확인하세요", sub_font, y + 30, width, (226, 40, 40, 255))

    filename = f"top3_cta_{article_id}_{int(datetime.utcnow().timestamp())}.png"
    image.save(MEDIA_DIR / filename, "PNG")
    return filename


def generate_top3_fortune_carousel(article, parsed):
    """훅 표지 + 순위 카드(2~5장) + CTA 카드로, 12지신 전부가 아니라
    대본에서 지정한 띠만 크게 보여주는 임팩트형 카드뉴스를 만듭니다."""
    today = datetime.utcnow().date()
    background = generate_top3_fortune_shared_background()

    filenames = [compose_top3_cover(background, parsed["hook"], len(parsed["items"]), today, article.id)]
    for item in parsed["items"]:
        filenames.append(compose_top3_rank_card(background, item["rank"], item["animal"], item["reason"], article.id))
    filenames.append(compose_top3_cta(background, parsed["cta"], article.id))
    return filenames


def generate_fortune_reel_video(article, filenames):
    """카드뉴스 이미지 7장을 순서대로 보여주는 슬라이드쇼 영상(mp4)을
    만듭니다. imageio-ffmpeg는 ffmpeg 실행 파일을 패키지 안에 이미
    내장하고 있어서, 서버(Render)에 ffmpeg가 따로 설치되어 있지 않아도
    항상 작동합니다.

    Render 서버 메모리 한도가 512MB로 꽤 빠듯해서(실제로 이전 방식은
    메모리 초과로 서버가 다운됐습니다), 파이썬이 프레임을 하나하나
    만들어서 들고 있는 대신, ffmpeg한테 "이 사진들을 몇 초씩 순서대로
    보여줘"라고 통째로 맡깁니다. 이러면 파이썬은 이미지 하나씩만
    잠깐 다루고 바로 놓아주기 때문에 메모리를 훨씬 적게 씁니다."""
    import subprocess
    import tempfile
    import imageio_ffmpeg

    target_size = (720, 1280)
    seconds_per_image = 3.5

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        resized_paths = []
        for index, filename in enumerate(filenames):
            with Image.open(MEDIA_DIR / filename) as img:
                small = img.convert("RGB").resize(target_size)
                resized_path = tmp_path / f"frame_{index:02d}.png"
                small.save(resized_path, "PNG")
            resized_paths.append(resized_path)

        # ffmpeg의 concat 방식은 마지막 파일을 한 번 더(길이 지정 없이)
        # 적어줘야 마지막 장면이 온전히 보입니다(ffmpeg 자체 동작 방식).
        list_path = tmp_path / "list.txt"
        with open(list_path, "w") as f:
            for p in resized_paths:
                f.write(f"file '{p.name}'\n")
                f.write(f"duration {seconds_per_image}\n")
            f.write(f"file '{resized_paths[-1].name}'\n")

        output_filename = f"fortune_reel_{article.id}_{int(datetime.utcnow().timestamp())}.mp4"
        output_path = MEDIA_DIR / output_filename

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [
                ffmpeg_exe, "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-vsync", "cfr", "-r", "24",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-c:a", "aac", "-shortest",
                "-movflags", "+faststart",
                "-threads", "1",
                str(output_path),
            ],
            check=True, capture_output=True, timeout=60,
        )

    return output_filename

    return output_filename



def copy_media_file(source_filename, prefix):
    if not source_filename:
        return None

    source_path = MEDIA_DIR / source_filename

    if not source_path.exists():
        return None

    extension = source_path.suffix.lower() or ".png"
    target_filename = (
        f"{prefix}_{int(datetime.utcnow().timestamp())}"
        f"_{secrets.token_hex(3)}{extension}"
    )
    target_path = MEDIA_DIR / target_filename
    shutil.copy2(source_path, target_path)
    return target_filename


def delete_media_if_exists(filename):
    if not filename:
        return

    path = MEDIA_DIR / filename

    if path.exists():
        path.unlink()


def preset_profile(preset):
    try:
        data = json.loads(preset.profile_json or "{}")
    except json.JSONDecodeError:
        return default_instatoon_character_profile()

    if not isinstance(data, dict):
        return default_instatoon_character_profile()

    default_profile = default_instatoon_character_profile()

    for key, value in default_profile.items():
        if not str(data.get(key, "")).strip():
            data[key] = value

    return data


def extract_latest_instatoon_text(article):
    notes = article.notes or ""
    marker = "🎨 인스타툰 8컷"
    if marker not in notes:
        return ""
    return notes.rsplit(marker, 1)[1].strip()


def normalize_instatoon_cuts(instatoon_text):
    """최신 인스타툰에서 컷 번호 1~8만 한 번씩 반환합니다."""
    numbered = {}

    for chunk in (instatoon_text or "").split("[CUT]"):
        chunk = chunk.strip()
        if not chunk:
            continue

        match = re.search(r"컷\s*번호\s*:\s*(\d+)", chunk)
        if not match:
            continue

        number = int(match.group(1))
        if 1 <= number <= 8:
            numbered[number] = re.sub(
                r"컷\s*번호\s*:\s*\d+",
                f"컷 번호: {number}",
                chunk,
                count=1,
            )

    return [numbered[n] for n in range(1, 9) if n in numbered]


def canonical_instatoon_text(article):
    cuts = normalize_instatoon_cuts(extract_latest_instatoon_text(article))
    return "\n\n".join(f"[CUT]\n{cut}" for cut in cuts)


def default_instatoon_character_profile():
    return {
        "project_name": "말썽쟁이 딸랑구",
        "mother_name": "엄마",
        "mother_appearance": (
            "한국인 30대 후반 여성, 부드러운 둥근 얼굴, "
            "따뜻한 갈색 단발 보브컷과 옆가르마, 주황색 니트, 크림색 바지"
        ),
        "daughter_name": "딸",
        "daughter_appearance": (
            "한국인 초등학생 여자아이, 둥근 어린이 얼굴, "
            "진한 갈색 양 갈래 낮은 묶음머리, 노란 긴팔 상의, 주황색 치마"
        ),
        "art_style": (
            "따뜻한 한국 웹툰 일러스트, 부드러운 베이지·주황 팔레트, "
            "둥글고 깔끔한 선, 은은한 종이 질감"
        ),
        "location_style": "아늑하고 단순한 한국 가정집 실내",
        "negative_rules": (
            "글자, 숫자, 말풍선, 자막, 로고, 워터마크, 간판, UI, "
            "사진풍, 3D 렌더 금지"
        ),
        "caption_style": "큰 말풍선+하단자막",
        "caption_font_size": "58",
        "subtitle_font_size": "62",
        "reference_priority": "업로드 이미지 최우선",
    }


def get_instatoon_character_profile(article):
    default_profile = default_instatoon_character_profile()

    try:
        saved = json.loads(article.instatoon_character_profile or "{}")
    except json.JSONDecodeError:
        saved = {}

    if not isinstance(saved, dict):
        saved = {}

    for key, value in default_profile.items():
        if not str(saved.get(key, "")).strip():
            saved[key] = value

    return saved


def instatoon_scene_only(cut_text):
    """이미지 모델에는 장면 설명만 전달하고 대사·자막은 제외합니다."""
    lines = []

    for raw_line in (cut_text or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith(("대사:", "자막:", "컷 번호:")):
            continue

        if line.startswith("장면:"):
            line = line.split(":", 1)[1].strip()

        if line:
            lines.append(line)

    return " ".join(lines)[:1200] or "엄마와 딸이 자연스럽게 상호작용하는 장면"



def parse_instatoon_cut_fields(cut_text):
    fields = {
        "cut_number": "",
        "scene": "",
        "dialogue": "",
        "caption": "",
    }

    current_key = None
    key_map = {
        "컷 번호": "cut_number",
        "장면": "scene",
        "대사": "dialogue",
        "자막": "caption",
    }
    # 위 4개 라벨 외에, AI가 오타/변형된 라벨(예: '자작:', '설명:')을 출력해도
    # 이전 필드(특히 대사)에 그대로 이어붙지 않도록 걸러내는 패턴입니다.
    unknown_label_pattern = re.compile(r"^[가-힣A-Za-z][가-힣A-Za-z0-9\s]{0,9}:\s*")

    for raw_line in (cut_text or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        matched = False

        for label, key in key_map.items():
            prefix = f"{label}:"

            if line.startswith(prefix):
                fields[key] = line.split(":", 1)[1].strip()
                current_key = key
                matched = True
                break

        if matched:
            continue

        if unknown_label_pattern.match(line):
            # 알려진 4개 라벨이 아닌 "무언가: 내용" 형태는 오염된 필드명일 가능성이
            # 높으므로, 직전 필드에 붙이지 않고 통째로 버립니다.
            continue

        if current_key:
            fields[current_key] = (
                f"{fields[current_key]} {line}".strip()
            )

    return fields


KOREAN_FONT_DOWNLOAD_URLS = {
    "NanumGothic-Bold.ttf": "https://github.com/google/fonts/raw/refs/heads/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
    "NanumGothic-Regular.ttf": "https://github.com/google/fonts/raw/refs/heads/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
}
_korean_font_download_attempted = False


def ensure_bundled_korean_font():
    """Render는 재배포될 때마다 서버를 완전히 새로 만들어서, 터미널에서
    설치했던 폰트는 다음 배포에는 남아있지 않습니다. 그래서 프로젝트
    폴더(static/fonts) 안에 폰트 파일이 없으면, 구글의 공식 폰트
    저장소에서 한 번 받아와 저장해둡니다. 한 번 받아두면 그다음부터는
    다시 안 받고 그대로 사용합니다."""
    global _korean_font_download_attempted
    if _korean_font_download_attempted:
        return
    _korean_font_download_attempted = True

    fonts_dir = BASE_DIR / "static" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in KOREAN_FONT_DOWNLOAD_URLS.items():
        target = fonts_dir / filename
        if target.exists() and target.stat().st_size > 1000:
            continue
        try:
            response = requests.get(url, timeout=20)
            if response.status_code == 200 and len(response.content) > 1000:
                target.write_bytes(response.content)
        except Exception:
            pass  # 다운로드 실패해도 조용히 넘어가고, 시스템 폰트 검색으로 넘어갑니다.


def get_korean_font(size, bold=True):
    """한글이 이미지에 안 보이는 문제의 대부분은 서버(컨테이너)에 한글 폰트가
    아예 설치되어 있지 않아서 발생합니다. Pillow의 기본 폰트(load_default)는
    아주 작은 영문 비트맵 폰트라 한글 자체를 그리지 못해 글씨가 안 보이거나
    네모(tofu)만 보이게 됩니다. 그래서 정확한 파일명 몇 개만 보는 대신,
    폰트 폴더 전체를 뒤져서 한글 폰트로 보이는 파일을 최대한 찾아봅니다.
    """
    ensure_bundled_korean_font()

    exact_candidates = [
        str(BASE_DIR / "static" / "fonts" / ("NanumGothic-Bold.ttf" if bold else "NanumGothic-Regular.ttf")),
        (
            "/usr/share/fonts/truetype/nanum/"
            + ("NanumBarunGothicBold.ttf" if bold else "NanumBarunGothic.ttf")
        ),
        (
            "/usr/share/fonts/opentype/noto/"
            + ("NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc")
        ),
        "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
        # 프로젝트에 폰트 파일을 직접 넣어두는 경우(운영 환경에 가장 안전한 방식)
        str(BASE_DIR / "static" / "fonts" / "NanumBarunGothicBold.ttf"),
        str(BASE_DIR / "static" / "fonts" / "NotoSansKR-Bold.ttf"),
    ]

    for font_path in exact_candidates:
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(str(font_path), size=size)

    # 정확한 파일명을 못 찾았으면, 시스템에 설치된 폰트를 하나씩 실제로
    # 테스트해봅니다. 이름만 보고 판단하면("gothic"처럼 흔한 단어) 한글을
    # 지원 안 하는 영어 전용 폰트를 잘못 고를 수도, 진짜 한글 폰트를
    # 놓칠 수도 있어서, 실제로 한글 글자("한")를 그려서 확인합니다.
    def supports_hangul(font_path):
        try:
            test_font = ImageFont.truetype(str(font_path), size=20)
            # 폰트가 "한"을 실제로 그릴 수 있는지 확인합니다. 없는
            # 글자를 그리면 폰트들이 보통 빈 사각형(notdef) 대체
            # 글리프를 보여주는데, bbox만 보면 그 대체 글리프도
            # 크기가 있어서 "있다"고 착각할 수 있습니다. 그래서
            # 절대 존재할 리 없는 사용자 영역 코드(U+E000)를 그린
            # 결과와 비교해서, 완전히 똑같으면(=둘 다 대체 글리프)
            # 한글 지원이 없는 것으로 판단합니다.
            hangul_mask = bytes(test_font.getmask("한"))
            missing_mask = bytes(test_font.getmask("\ue000"))
            return hangul_mask != missing_mask
        except Exception:
            return False

    korean_tags = (
        "nanum", "noto", "cjk", "malgun", "unfont", "batang",
        "dotum", "gulim", "gungsuh", "gothic", "pretendard", "spoqa",
        "source han", "sourcehan", "wqy", "droid sans fallback",
    )
    keyword = "bold" if bold else "regular"
    named_matches = []
    for fonts_root in ("/usr/share/fonts", "/usr/local/share/fonts"):
        root = Path(fonts_root)
        if not root.exists():
            continue
        for font_file in root.rglob("*"):
            if font_file.suffix.lower() not in (".ttf", ".ttc", ".otf"):
                continue
            name = font_file.name.lower()
            if any(tag in name for tag in korean_tags):
                named_matches.append(font_file)

    # 이름에 keyword(bold/regular)까지 일치하는 것을 먼저 시도하고,
    # 그다음 나머지 이름-일치 후보들을 시도합니다. 각 후보는 실제로
    # 한글을 그릴 수 있는지 확인한 뒤에만 사용합니다.
    named_matches.sort(key=lambda p: (keyword not in p.name.lower()))
    for font_file in named_matches:
        if supports_hangul(font_file):
            return ImageFont.truetype(str(font_file), size=size)

    # 이름으로 못 찾았으면, 폰트 폴더 전체를 다시 훑으면서 이번엔
    # 이름 상관없이 전부 실제로 한글이 그려지는지 테스트합니다
    # (최후의 수단이라 시간이 조금 더 걸릴 수 있습니다).
    for fonts_root in ("/usr/share/fonts", "/usr/local/share/fonts"):
        root = Path(fonts_root)
        if not root.exists():
            continue
        for font_file in root.rglob("*"):
            if font_file.suffix.lower() not in (".ttf", ".ttc", ".otf"):
                continue
            if supports_hangul(font_file):
                return ImageFont.truetype(str(font_file), size=size)

    # 한글 폰트를 정말 하나도 못 찾은 경우: 여기서 조용히 영문 기본 폰트로
    # 넘어가면 이미지에 글씨가 안 보이는 채로 계속 나오니, 원인을 바로
    # 알 수 있도록 명확한 에러로 알려줍니다.
    raise RuntimeError(
        "서버에 한글 폰트가 설치되어 있지 않아 이미지에 글씨를 넣을 수 없습니다. "
        "터미널에서 `sudo apt-get update && sudo apt-get install -y fonts-nanum` "
        "실행 후 다시 이미지를 생성해 주세요. (Codespace를 새로 만들면 다시 설치해야 "
        "할 수 있으니, 가능하면 폰트 파일을 static/fonts/ 폴더에 직접 넣어두는 것을 "
        "추천합니다.)"
    )


def wrap_text_by_words(draw, text, font, max_width):
    """글자 하나씩이 아니라 띄어쓰기(단어) 단위로 줄바꿈합니다.
    글자 단위로 자르면 "신중하세" + "요." 처럼 단어 중간이 끊겨
    어색해 보일 수 있어서, 운세 카드처럼 자연스러운 문장이 중요한
    곳에서는 이 함수를 씁니다."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []

    words = text.split(" ")
    lines = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            # 단어 하나가 그 자체로도 너무 길면(줄 폭보다 크면), 어쩔 수
            # 없이 그 단어만 글자 단위로 다시 쪼갭니다.
            word_bbox = draw.textbbox((0, 0), word, font=font)
            if word_bbox[2] - word_bbox[0] > max_width:
                lines.extend(wrap_text_pixels(draw, word, font, max_width))
                current = ""
            else:
                current = word

    if current:
        lines.append(current)

    return lines


def wrap_text_pixels(draw, text, font, max_width):
    text = re.sub(r"\s+", " ", (text or "")).strip()

    if not text:
        return []

    lines = []
    current = ""

    for char in text:
        candidate = current + char
        bbox = draw.textbbox((0, 0), candidate, font=font)

        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char

    if current:
        lines.append(current)

    return lines


def compose_instatoon_text_overlay(
    article,
    cut_number,
    source_filename,
    cut_text,
):
    profile = get_instatoon_character_profile(article)
    fields = parse_instatoon_cut_fields(cut_text)
    source_path = MEDIA_DIR / source_filename

    if not source_path.exists():
        raise FileNotFoundError(
            f"원본 인스타툰 이미지를 찾을 수 없습니다: {source_filename}"
        )

    image = Image.open(source_path).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    margin = max(28, width // 30)

    try:
        dialogue_size = max(54, min(int(profile.get("caption_font_size", "64")), 82))
    except (TypeError, ValueError):
        dialogue_size = 64

    try:
        subtitle_size = max(58, min(int(profile.get("subtitle_font_size", "68")), 88))
    except (TypeError, ValueError):
        subtitle_size = 68

    dialogue_font = get_korean_font(dialogue_size, bold=True)
    subtitle_font = get_korean_font(subtitle_size, bold=True)

    turns = parse_dialogue_turns(fields.get("dialogue", ""))[:2]
    caption = str(fields.get("caption", "") or "").strip()
    caption = re.split(
        r"(?:장면|대사|설명|컷\s*번호)\s*:",
        caption,
        maxsplit=1,
    )[0].strip()

    # 말풍선 꼬리가 배경(곰인형 등)을 잘못 가리키는 문제가 있어,
    # AI 얼굴 위치 감지는 더 이상 사용하지 않습니다. 대신 왼쪽/오른쪽
    # 위치 구분만으로 누가 말하는지 표시합니다.
    bubble_y = margin
    max_bubble_width = width - margin * 2

    for index, turn in enumerate(turns):
        lines = wrap_text_pixels(
            draw,
            turn.get("text", ""),
            dialogue_font,
            width - margin * 5,
        )[:3]

        if not lines:
            continue

        box = draw.textbbox((0, 0), "가나다ABC", font=dialogue_font)
        line_height = box[3] - box[1] + 14
        # 말하는 사람 이름(엄마/딸) 텍스트를 더는 표시하지 않으므로,
        # 말풍선 위아래 여백을 대칭으로 맞춰 더 아담하게 만듭니다.
        bubble_height = 30 + len(lines) * line_height + 26

        # 글씨 실제 폭에 맞춰 말풍선 가로 크기를 정합니다. (예전에는 항상
        # 화면 폭 가득 채운 큰 박스라 짧은 대사도 얼굴을 가렸습니다.)
        text_widths = [
            draw.textbbox((0, 0), line, font=dialogue_font)[2]
            for line in lines
        ]
        content_width = max(text_widths, default=0)
        bubble_width = min(max_bubble_width, content_width + 60)
        bubble_width = max(bubble_width, 140)  # 너무 작아지지 않도록 최소 폭 보장

        speaker = turn.get("speaker", "")
        # 순서(index)가 아니라 "누가 말하는지"로 방향을 고정합니다.
        # 엄마는 항상 왼쪽, 딸은 항상 오른쪽으로 말풍선이 펼쳐지고,
        # 그 외 캐릭터(나레이션 등)는 순서대로 번갈아 배치합니다.
        if speaker == "mother":
            side_left = True
        elif speaker == "daughter":
            side_left = False
        else:
            side_left = (index % 2 == 0)

        if not side_left:
            right = width - margin - (width // 14)
            left = max(margin, right - bubble_width)
        else:
            left = margin
            right = min(width - margin, left + bubble_width)

        # 매끈한(대화용) 구름 모양 말풍선을 그립니다. wobble_amplitude를
        # 0보다 크게 주면 톱니처럼 삐죽삐죽한(생각용) 모양이 됩니다 —
        # 지금은 "생각" 대사를 구분할 표시가 따로 없어서 항상 매끈한
        # 모양(대화)을 사용합니다.
        wobble_amplitude = 0.0
        cx = (left + right) / 2
        cy = bubble_y + bubble_height / 2
        rx = (right - left) / 2 * 1.16
        ry = bubble_height / 2 * 1.32
        bump_count = max(10, min(20, int((bubble_width + bubble_height) / 34)))
        bubble_points = []
        steps_per_bump = 8
        total_steps = bump_count * steps_per_bump
        for step in range(total_steps):
            angle = 2 * math.pi * step / total_steps
            wobble = 1 + wobble_amplitude * math.sin(bump_count * angle)
            bubble_points.append(
                (cx + rx * wobble * math.cos(angle), cy + ry * wobble * math.sin(angle))
            )

        draw.polygon(
            bubble_points,
            fill=(255, 255, 255, 208),
            outline=(32, 32, 32, 230),
            width=4,
        )

        text_y = bubble_y + 27
        for line in lines:
            draw.text(
                (left + 26, text_y),
                line,
                font=dialogue_font,
                fill=(20, 20, 20, 255),
            )
            text_y += line_height

        bubble_y += bubble_height + int(ry * 0.7) + 26

    if caption:
        lines = wrap_text_pixels(
            draw,
            caption,
            subtitle_font,
            width - margin * 4,
        )[:2]
        box = draw.textbbox((0, 0), "가나다ABC", font=subtitle_font)
        line_height = box[3] - box[1] + 16
        band_height = max(150, len(lines) * line_height + 58)

        # 자막을 그림 위에 겹쳐 그리지 않고, 그림 아래에 새로운 공간을
        # 만들어서 그 안에 넣습니다. 그림에는 글씨가 전혀 겹치지 않습니다.
        extended = Image.new(
            "RGB", (width, height + band_height), (24, 21, 20)
        )
        extended.paste(image, (0, 0))
        image = extended
        extended_draw = ImageDraw.Draw(image, "RGBA")

        band_top = height  # 원본 그림이 끝나는 지점부터 자막 공간 시작

        text_y = band_top + (band_height - len(lines) * line_height) // 2
        for line in lines:
            bbox = extended_draw.textbbox((0, 0), line, font=subtitle_font)
            text_x = (width - (bbox[2] - bbox[0])) // 2
            extended_draw.text(
                (text_x, text_y),
                line,
                font=subtitle_font,
                fill=(255, 255, 255, 255),
            )
            text_y += line_height

    filename = (
        f"instatoon_{article.id}_cut_{cut_number}_captioned_"
        f"{int(datetime.utcnow().timestamp())}.png"
    )
    image.save(MEDIA_DIR / filename, format="PNG", optimize=True)
    return filename


def load_json_map(value):
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def save_instatoon_image_versions(
    article,
    cut_number,
    raw_filename,
    cut_text,
):
    raw_map = load_json_map(article.instatoon_images)
    captioned_map = load_json_map(article.instatoon_captioned_images)

    old_raw = raw_map.get(str(cut_number))
    old_captioned = captioned_map.get(str(cut_number))

    captioned_filename = compose_instatoon_text_overlay(
        article=article,
        cut_number=cut_number,
        source_filename=raw_filename,
        cut_text=cut_text,
    )

    raw_map[str(cut_number)] = raw_filename
    captioned_map[str(cut_number)] = captioned_filename

    article.instatoon_images = json.dumps(
        raw_map,
        ensure_ascii=False,
    )
    article.instatoon_captioned_images = json.dumps(
        captioned_map,
        ensure_ascii=False,
    )

    return {
        "old_raw": old_raw,
        "old_captioned": old_captioned,
        "raw_filename": raw_filename,
        "captioned_filename": captioned_filename,
    }


def delete_replaced_media(*filenames):
    for filename in filenames:
        if not filename:
            continue

        file_path = MEDIA_DIR / filename

        if file_path.exists():
            file_path.unlink()



ALLOWED_REFERENCE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024


def allowed_reference_image(filename):
    return (
        "." in (filename or "")
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_REFERENCE_EXTENSIONS
    )


def save_reference_image_upload(file_storage, article_id):
    if not file_storage or not file_storage.filename:
        raise ValueError("업로드할 이미지를 선택해 주세요.")

    if not allowed_reference_image(file_storage.filename):
        raise ValueError("PNG, JPG, JPEG, WEBP 이미지만 업로드할 수 있습니다.")

    safe_name = secure_filename(file_storage.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    raw_bytes = file_storage.read()

    if not raw_bytes:
        raise ValueError("업로드한 이미지가 비어 있습니다.")

    if len(raw_bytes) > MAX_REFERENCE_IMAGE_BYTES:
        raise ValueError("참조 이미지는 10MB 이하만 업로드할 수 있습니다.")

    temp_filename = (
        f"instatoon_{article_id}_reference_upload_"
        f"{int(datetime.utcnow().timestamp())}.{extension}"
    )
    temp_path = MEDIA_DIR / temp_filename
    temp_path.write_bytes(raw_bytes)

    try:
        with Image.open(temp_path) as uploaded:
            uploaded.verify()

        with Image.open(temp_path) as uploaded:
            image = uploaded.convert("RGB")
            image.thumbnail((1536, 1536))

            final_filename = (
                f"instatoon_{article_id}_reference_"
                f"{int(datetime.utcnow().timestamp())}.png"
            )
            final_path = MEDIA_DIR / final_filename
            image.save(final_path, format="PNG", optimize=True)

    except Exception as error:
        if temp_path.exists():
            temp_path.unlink()
        raise ValueError("정상적인 이미지 파일을 업로드해 주세요.") from error

    if temp_path.exists():
        temp_path.unlink()

    return final_filename


def generate_instatoon_character_sheet(article, profile, style):
    reference_filename = article.instatoon_reference_image
    has_reference = bool(
        reference_filename and (MEDIA_DIR / reference_filename).exists()
    )

    if has_reference:
        prompt = f"""
Create a clean square production model sheet using the exact recurring cast
from the uploaded reference image.

PROJECT:
{profile.get("project_name", "인스타툰 프로젝트")}

STYLE:
{style}
{profile.get("art_style", "")}

STRICT RULES:
- The uploaded image is the canonical source of identity.
- Preserve the exact visible species and number of main characters.
- Preserve face, eyes, ears, muzzle or nose, fur or skin color,
  hairstyle, body proportions, clothing, accessories, and palette.
- Never turn animals into humans.
- Show front, three-quarter, side, and full-body views.
- Plain warm light background.
- No text, labels, numbers, logos, or watermarks.
- Square 1:1 composition.
"""
        with open(MEDIA_DIR / reference_filename, "rb") as reference_file:
            result = openai_client().images.edit(
                model=IMAGE_MODEL,
                image=reference_file,
                prompt=prompt,
                size="1024x1024",
                quality="medium",
                input_fidelity="high",
            )
    else:
        prompt = f"""
Create a clean square Korean webtoon character model sheet.

MOTHER:
{profile.get("mother_name", "엄마")}
{profile.get("mother_appearance", "")}

DAUGHTER:
{profile.get("daughter_name", "딸")}
{profile.get("daughter_appearance", "")}

STYLE:
{style}
{profile.get("art_style", "")}

Show front, three-quarter, side, and full-body views.
No text, labels, numbers, logos, or watermarks.
Square 1:1 composition.
"""
        result = openai_client().images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size="1024x1024",
            quality="medium",
        )

    log_ai_usage("image")
    image_b64 = result.data[0].b64_json
    if not image_b64:
        raise RuntimeError("캐릭터 시트 이미지 데이터가 반환되지 않았습니다.")

    filename = (
        f"instatoon_{article.id}_character_sheet_"
        f"{int(datetime.utcnow().timestamp())}.png"
    )
    (MEDIA_DIR / filename).write_bytes(base64.b64decode(image_b64))
    return filename


def generate_instatoon_image(
    article,
    cut_number,
    cut_text,
    style,
    expression_hint="",
):
    profile = get_instatoon_character_profile(article)
    scene_description = instatoon_scene_only(cut_text)
    expression_hint = (expression_hint or "").strip()
    reference_filename = article.instatoon_reference_image
    has_reference = bool(
        reference_filename and (MEDIA_DIR / reference_filename).exists()
    )

    prompt = f"""
Create panel {cut_number} of one continuous 8-panel Instagram webtoon.

SCENE:
{scene_description}

EXPRESSION:
{expression_hint or "Follow the emotion in the scene."}

STYLE:
{style}
{profile.get("art_style", "")}
Location mood: {profile.get("location_style", "")}

ZERO-TEXT RULE:
- No text, letters, numbers, captions, signs, logos, watermarks,
  speech bubbles, or title cards.
- Tell the story only through pose, expression, props, framing, and setting.
- Leave the top 30 percent visually calm and uncluttered (plain background,
  sky, wall, etc.) — dialogue bubbles are added there afterward and must
  not cover any character's face.
- Keep character faces centered in the middle band of the frame, not at
  the very top edge.
- Leave the lower 22 percent visually calm for captions.
- Portrait 2:3 composition (close to the 9:16 Instagram Reels/Story frame).
- {profile.get("negative_rules", "")}
"""

    if has_reference:
        prompt += """
UPLOADED IMAGE IS THE ONLY CANONICAL CAST:
- Preserve the exact species and number of recurring characters.
- Preserve face, eye shape, ears, muzzle or nose, fur or skin color,
  hairstyle, body proportions, clothing, accessories, and palette.
- Never turn animals into humans.
- Never replace the uploaded cast with generic people.
- Change only pose, expression, camera angle, props, and setting.
"""
        with open(MEDIA_DIR / reference_filename, "rb") as reference_file:
            result = openai_client().images.edit(
                model=IMAGE_MODEL,
                image=reference_file,
                prompt=prompt,
                size="1024x1536",
                quality="medium",
                input_fidelity="high",
            )
    else:
        prompt += f"""
LOCKED WRITTEN CAST:
Mother: {profile.get("mother_name", "엄마")},
{profile.get("mother_appearance", "")}
Daughter: {profile.get("daughter_name", "딸")},
{profile.get("daughter_appearance", "")}
Keep faces, hair, outfits, palette, and proportions identical in all panels.
"""
        result = openai_client().images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size="1024x1536",
            quality="medium",
        )

    log_ai_usage("image")
    image_b64 = result.data[0].b64_json
    if not image_b64:
        raise RuntimeError("인스타툰 이미지 데이터가 반환되지 않았습니다.")

    filename = (
        f"instatoon_{article.id}_cut_{cut_number}_"
        f"{int(datetime.utcnow().timestamp())}.png"
    )
    (MEDIA_DIR / filename).write_bytes(base64.b64decode(image_b64))
    return filename


TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICES = {
    "mother": "coral",
    "daughter": "nova",
    "narration": "sage",
}


def clean_dialogue_text(value):
    text_value = str(value or "")
    text_value = re.split(r"(?:장면|자막|설명|컷\s*번호)\s*:", text_value, maxsplit=1)[0]
    text_value = re.sub(r'["“”‘’]', "", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value[:1000]


def parse_dialogue_turns(dialogue):
    """명시된 화자 뒤의 대사만 추출합니다."""
    raw = str(dialogue or "").strip()
    if not raw:
        return []

    raw = re.split(
        r"(?:장면|자막|설명|컷\s*번호)\s*:",
        raw,
        maxsplit=1,
    )[0].strip()

    pattern = re.compile(
        r"(엄마|어머니|딸|아이|딸아이|친구|아빠|아버지|"
        r"여우|곰|토끼|고양이|강아지|나레이션|내레이션)"
        r"\s*:\s*"
    )
    matches = list(pattern.finditer(raw))
    if not matches:
        return []

    turns = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        label = match.group(1)
        text_value = raw[start:end]
        text_value = re.split(
            r"(?:장면|자막|설명|컷\s*번호)\s*:",
            text_value,
            maxsplit=1,
        )[0]
        # 위 4개 라벨 외에도 AI가 오타/변형된 라벨(예: '자작:')을 이어붙이는 경우가
        # 있어, "짧은 텍스트 + 콜론" 패턴이 다시 나오면 그 지점에서 대사를 끊습니다.
        text_value = re.split(
            r"[가-힣A-Za-z][가-힣A-Za-z0-9\s]{0,9}:\s*", text_value, maxsplit=1
        )[0]
        text_value = re.sub(r'["“”‘’]', "", text_value)
        text_value = re.sub(r"\s+", " ", text_value).strip(" ,./")

        if not text_value:
            continue

        if label in {"엄마", "어머니"}:
            speaker, display = "mother", "엄마"
        elif label in {"딸", "아이", "딸아이"}:
            speaker, display = "daughter", "딸"
        elif label in {"나레이션", "내레이션"}:
            speaker, display = "narration", "나레이션"
        else:
            speaker, display = "narration", label

        turns.append({
            "speaker": speaker,
            "label": display,
            "text": text_value[:700],
        })

    return turns


def tts_instructions_for(speaker, mood="자연스럽게"):
    mood = clean_dialogue_text(mood) or "자연스럽게"

    if speaker == "mother":
        return (
            "Speak in Korean as a warm, natural mother in her late thirties. "
            "Use clear diction, conversational pacing, gentle emotional acting, "
            f"and this mood: {mood}. Do not sound like an announcer."
        )

    if speaker == "daughter":
        return (
            "Speak in Korean as a bright elementary-school girl character. "
            "Use lively but understandable delivery, youthful energy, "
            f"and this mood: {mood}. Avoid exaggerated baby talk."
        )

    return (
        "Speak in Korean as a friendly webtoon narrator. "
        "Use clear, warm storytelling delivery and natural pacing. "
        f"Mood: {mood}."
    )


def generate_tts_mp3(text_value, speaker, article_id, cut_number, turn_number, mood):
    text_value = clean_dialogue_text(text_value)

    if not text_value:
        raise ValueError("음성으로 만들 대사가 없습니다.")

    voice = TTS_VOICES.get(speaker, TTS_VOICES["narration"])
    filename = (
        f"article_{article_id}_cut_{cut_number}_"
        f"{speaker}_{turn_number}_{int(datetime.utcnow().timestamp())}.mp3"
    )
    output_path = MEDIA_DIR / filename

    with openai_client().audio.speech.with_streaming_response.create(
        model=TTS_MODEL,
        voice=voice,
        input=text_value,
        instructions=tts_instructions_for(speaker, mood),
        response_format="mp3",
        speed=1.0,
    ) as response:
        response.stream_to_file(output_path)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("음성 파일 생성에 실패했습니다.")

    log_ai_usage("audio")
    return filename


def get_instatoon_cuts(article):
    return normalize_instatoon_cuts(extract_latest_instatoon_text(article))


def generate_cut_audio(article, cut_number, mother_mood, daughter_mood, narration_mood):
    cuts = get_instatoon_cuts(article)

    if cut_number < 1 or cut_number > len(cuts):
        raise ValueError("선택한 인스타툰 컷을 찾을 수 없습니다.")

    fields = parse_instatoon_cut_fields(cuts[cut_number - 1])
    turns = parse_dialogue_turns(fields.get("dialogue", ""))

    if not turns:
        raise ValueError("이 컷에는 엄마: 또는 딸: 형식의 대사가 없습니다.")

    audio_map = load_json_map(article.instatoon_audio)
    old_entries = audio_map.get(str(cut_number), [])
    new_entries = []

    moods = {
        "mother": mother_mood,
        "daughter": daughter_mood,
        "narration": narration_mood,
    }

    for turn_number, turn in enumerate(turns, start=1):
        filename = generate_tts_mp3(
            text_value=turn["text"],
            speaker=turn["speaker"],
            article_id=article.id,
            cut_number=cut_number,
            turn_number=turn_number,
            mood=moods.get(turn["speaker"], "자연스럽게"),
        )

        new_entries.append({
            "turn_number": turn_number,
            "speaker": turn["speaker"],
            "label": turn["label"],
            "text": turn["text"],
            "filename": filename,
        })

    audio_map[str(cut_number)] = new_entries
    article.instatoon_audio = json.dumps(
        audio_map,
        ensure_ascii=False,
    )

    return old_entries, new_entries


def delete_audio_entries(entries):
    for entry in entries or []:
        filename = entry.get("filename") if isinstance(entry, dict) else None

        if not filename:
            continue

        file_path = MEDIA_DIR / filename

        if file_path.exists():
            file_path.unlink()




ALLOWED_BGM_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "ogg"}
MAX_BGM_BYTES = 25 * 1024 * 1024



def safe_zip_name(value, fallback="content"):
    value = re.sub(r"[^\w가-힣\-]+", "_", (value or "").strip())
    value = value.strip("_")
    return value[:80] or fallback


def write_text_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")


def build_export_manifest(article):
    audio_map = load_json_map(article.instatoon_audio)
    captioned_map = load_json_map(article.instatoon_captioned_images)
    raw_map = load_json_map(article.instatoon_images)

    return {
        "article_id": article.id,
        "title": article.title,
        "keyword": article.keyword,
        "created_at": (
            article.created_at.isoformat()
            if article.created_at else None
        ),
        "files": {
            "thumbnail": article.thumbnail_path,
            "character_sheet": article.instatoon_character_sheet,
            "reference_image": article.instatoon_reference_image,
            "captioned_images": captioned_map,
            "raw_images": raw_map,
            "audio": audio_map,
            "reels": article.reels_path,
            "reels_voice": article.reels_voice_path,
            "reels_final": article.reels_final_path,
            "bgm": article.reels_bgm_path,
        },
        "settings": {
            "character_profile": load_json_map(
                article.instatoon_character_profile
            ),
            "audio_settings": load_json_map(
                article.instatoon_audio_settings
            ),
            "reels_settings": load_json_map(article.reels_settings),
            "reels_voice_settings": load_json_map(
                article.reels_voice_settings
            ),
            "reels_final_settings": load_json_map(
                article.reels_final_settings
            ),
        },
    }


def create_export_package(article, include_raw=True, include_audio=True):
    timestamp = int(datetime.utcnow().timestamp())
    slug = safe_zip_name(article.title, fallback=f"article_{article.id}")
    filename = f"{slug}_content_package_{timestamp}.zip"
    output_path = MEDIA_DIR / filename

    manifest = build_export_manifest(article)

    with tempfile.TemporaryDirectory(prefix="mi_export_") as temp_dir:
        root = Path(temp_dir) / slug
        root.mkdir(parents=True, exist_ok=True)

        # 기본 텍스트 콘텐츠
        write_text_file(root / "01_blog" / "title.txt", article.title)
        write_text_file(
            root / "01_blog" / "meta_description.txt",
            article.meta_description,
        )
        write_text_file(root / "01_blog" / "body.html", article.body_html)
        write_text_file(root / "01_blog" / "tags.txt", article.tags)

        write_text_file(
            root / "02_sns" / "instagram_caption.txt",
            article.instagram_caption,
        )
        write_text_file(
            root / "02_sns" / "threads.txt",
            article.threads_text,
        )
        write_text_file(
            root / "02_sns" / "shorts_script.txt",
            article.shorts_script,
        )

        # 인스타툰 원문
        instatoon_text = ""
        if "🎨 인스타툰 8컷" in (article.notes or ""):
            instatoon_text = (
                article.notes
                .split("🎨 인스타툰 8컷", 1)[1]
                .strip()
            )

        write_text_file(
            root / "03_instatoon" / "instatoon_script.txt",
            instatoon_text,
        )

        # 이미지
        captioned_map = load_json_map(article.instatoon_captioned_images)
        raw_map = load_json_map(article.instatoon_images)

        for cut_number in range(1, 9):
            captioned = captioned_map.get(str(cut_number))
            if captioned and (MEDIA_DIR / captioned).exists():
                destination=root / "03_instatoon" / "final_images" / f"cut_{cut_number:02d}.png"
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(MEDIA_DIR / captioned,destination)

            raw = raw_map.get(str(cut_number))
            if (
                include_raw
                and raw
                and (MEDIA_DIR / raw).exists()
            ):
                destination=root / "03_instatoon" / "raw_images" / f"cut_{cut_number:02d}.png"
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(MEDIA_DIR / raw,destination)

        # 대표 이미지와 참조 이미지
        media_items = [
            (
                article.thumbnail_path,
                root / "04_assets" / "thumbnail.png",
            ),
            (
                article.instatoon_character_sheet,
                root / "04_assets" / "character_sheet.png",
            ),
            (
                article.instatoon_reference_image,
                root / "04_assets" / "reference_image.png",
            ),
        ]

        for source_filename, destination in media_items:
            if (
                source_filename
                and (MEDIA_DIR / source_filename).exists()
            ):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(MEDIA_DIR / source_filename, destination)

        # 오디오
        if include_audio:
            audio_map = load_json_map(article.instatoon_audio)

            for cut_number, entries in audio_map.items():
                for entry in entries or []:
                    source_filename = entry.get("filename")
                    turn_number = entry.get("turn_number", 1)
                    speaker = safe_zip_name(
                        entry.get("label", "voice"),
                        fallback="voice",
                    )

                    if (
                        source_filename
                        and (MEDIA_DIR / source_filename).exists()
                    ):
                        destination = (
                            root / "05_audio"
                            / f"cut_{int(cut_number):02d}"
                            / f"{int(turn_number):02d}_{speaker}.mp3"
                        )
                        destination.parent.mkdir(
                            parents=True,
                            exist_ok=True,
                        )
                        shutil.copy2(
                            MEDIA_DIR / source_filename,
                            destination,
                        )

        # 영상
        video_items = [
            (
                article.reels_path,
                root / "06_video" / "reels_basic.mp4",
            ),
            (
                article.reels_voice_path,
                root / "06_video" / "reels_with_voice.mp4",
            ),
            (
                article.reels_final_path,
                root / "06_video" / "reels_final.mp4",
            ),
        ]

        for source_filename, destination in video_items:
            if (
                source_filename
                and (MEDIA_DIR / source_filename).exists()
            ):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(MEDIA_DIR / source_filename, destination)

        # 매니페스트와 사용 안내
        write_text_file(
            root / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

        readme = f"""MI Creator OS 콘텐츠 패키지

제목: {article.title}
키워드: {article.keyword}

폴더 구성
01_blog      블로그 제목, 메타 설명, 본문 HTML, 태그
02_sns       인스타그램, Threads, 쇼츠 대본
03_instatoon 인스타툰 원문, 최종 이미지, 글씨 없는 원본
04_assets    썸네일, 캐릭터 시트, 참조 이미지
05_audio     컷별 엄마·딸·나레이션 MP3
06_video     기본 릴스, 음성 릴스, 최종 릴스

주의
- 업로드 전 문구와 이미지 내용을 직접 확인하세요.
- BGM과 참조 이미지는 사용 권한이 있는 파일만 사용하세요.
"""
        write_text_file(root / "README.txt", readme)

        with zipfile.ZipFile(
            output_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for file_path in root.rglob("*"):
                if file_path.is_file():
                    archive.write(
                        file_path,
                        file_path.relative_to(root.parent),
                    )

    return filename, {
        "include_raw": bool(include_raw),
        "include_audio": bool(include_audio),
        "title": article.title,
        "created_at": datetime.utcnow().isoformat(),
    }


def allowed_bgm_file(filename):
    return (
        "." in (filename or "")
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_BGM_EXTENSIONS
    )


def save_bgm_upload(file_storage, article_id):
    if not file_storage or not file_storage.filename:
        raise ValueError("업로드할 BGM 파일을 선택해 주세요.")

    if not allowed_bgm_file(file_storage.filename):
        raise ValueError("MP3, WAV, M4A, AAC, OGG 파일만 업로드할 수 있습니다.")

    safe_name = secure_filename(file_storage.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    raw_bytes = file_storage.read()

    if not raw_bytes:
        raise ValueError("업로드한 BGM 파일이 비어 있습니다.")

    if len(raw_bytes) > MAX_BGM_BYTES:
        raise ValueError("BGM 파일은 25MB 이하만 업로드할 수 있습니다.")

    filename = (
        f"article_{article_id}_bgm_"
        f"{int(datetime.utcnow().timestamp())}.{extension}"
    )
    path = MEDIA_DIR / filename
    path.write_bytes(raw_bytes)

    # ffprobe가 읽을 수 있는 정상 오디오인지 확인
    media_duration_seconds(path)
    return filename


def make_final_reels_with_bgm(
    article,
    bgm_volume=0.16,
    voice_volume=1.0,
    bgm_start_seconds=0.0,
):
    ffmpeg = ffmpeg_binary()

    source_filename = article.reels_voice_path or article.reels_path

    if not source_filename:
        raise ValueError(
            "기본 릴스 영상이 없습니다. 먼저 릴스 영상을 만들어 주세요."
        )

    if not article.reels_bgm_path:
        raise ValueError("업로드된 BGM이 없습니다.")

    source_path = MEDIA_DIR / source_filename
    bgm_path = MEDIA_DIR / article.reels_bgm_path

    if not source_path.exists():
        raise FileNotFoundError("릴스 영상 파일을 찾을 수 없습니다.")

    if not bgm_path.exists():
        raise FileNotFoundError("BGM 파일을 찾을 수 없습니다.")

    bgm_volume = safe_float(
        bgm_volume,
        default=0.16,
        minimum=0.02,
        maximum=1.0,
    )
    voice_volume = safe_float(
        voice_volume,
        default=1.0,
        minimum=0.2,
        maximum=2.0,
    )
    bgm_start_seconds = safe_float(
        bgm_start_seconds,
        default=0.0,
        minimum=0.0,
        maximum=600.0,
    )

    timestamp = int(datetime.utcnow().timestamp())
    output_filename = (
        f"article_{article.id}_reels_final_{timestamp}.mp4"
    )
    output_path = MEDIA_DIR / output_filename

    # 영상에 음성이 있는지 확인
    probe = ffprobe_binary()
    audio_probe = subprocess.run(
        [
            probe,
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(source_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    source_has_audio = bool(audio_probe.stdout.strip())

    if source_has_audio:
        filter_complex = (
            f"[0:a]volume={voice_volume:.3f},"
            "aresample=44100,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo[voice];"
            f"[1:a]volume={bgm_volume:.3f},"
            "aresample=44100,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo[bgm];"
            "[voice][bgm]amix=inputs=2:duration=first:"
            "dropout_transition=2,alimiter=limit=0.95[outa]"
        )

        cmd = [
            ffmpeg,
            "-y",
            "-i", str(source_path),
            "-ss", f"{bgm_start_seconds:.3f}",
            "-stream_loop", "-1",
            "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            ffmpeg,
            "-y",
            "-i", str(source_path),
            "-ss", f"{bgm_start_seconds:.3f}",
            "-stream_loop", "-1",
            "-i", str(bgm_path),
            "-filter_complex",
            (
                f"[1:a]volume={bgm_volume:.3f},"
                "aresample=44100,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                "alimiter=limit=0.95[outa]"
            ),
            "-map", "0:v:0",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=420,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "최종 릴스 BGM 합성 실패: "
            + result.stderr[-1800:]
        )

    return output_filename, {
        "source_reels": source_filename,
        "bgm_path": article.reels_bgm_path,
        "bgm_volume": bgm_volume,
        "voice_volume": voice_volume,
        "bgm_start_seconds": bgm_start_seconds,
        "source_has_audio": source_has_audio,
    }


def ffprobe_binary():
    path = shutil.which("ffprobe")

    if not path:
        raise RuntimeError(
            "FFprobe가 설치되어 있지 않습니다. "
            "FFmpeg 패키지를 설치해 주세요."
        )

    return path


def media_duration_seconds(file_path):
    probe = ffprobe_binary()
    result = subprocess.run(
        [
            probe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "미디어 길이를 읽지 못했습니다: "
            + result.stderr[-800:]
        )

    try:
        return float(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError("미디어 길이 값이 올바르지 않습니다.") from error


def build_cut_voice_track(
    ffmpeg,
    entries,
    output_path,
    cut_duration,
    gap_seconds=0.18,
):
    valid_files = []

    for entry in entries or []:
        if not isinstance(entry, dict):
            continue

        filename = entry.get("filename")

        if not filename:
            continue

        file_path = MEDIA_DIR / filename

        if file_path.exists():
            valid_files.append(file_path)

    if not valid_files:
        silence_result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{cut_duration:.3f}",
                "-c:a", "pcm_s16le",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )

        if silence_result.returncode != 0:
            raise RuntimeError(
                "무음 오디오 생성 실패: "
                + silence_result.stderr[-1000:]
            )

        return

    input_args = []
    filter_parts = []
    concat_labels = []

    for index, file_path in enumerate(valid_files):
        input_args.extend(["-i", str(file_path)])
        label = f"a{index}"
        filter_parts.append(
            f"[{index}:a]"
            "aresample=44100,"
            "aformat=sample_fmts=s16:channel_layouts=stereo,"
            f"asetpts=N/SR/TB[{label}]"
        )
        concat_labels.append(f"[{label}]")

    if len(valid_files) == 1:
        filter_parts.append(
            f"{concat_labels[0]}"
            f"apad=pad_dur={cut_duration:.3f},"
            f"atrim=duration={cut_duration:.3f}[outa]"
        )
    else:
        joined = "".join(concat_labels)
        filter_parts.append(
            f"{joined}concat=n={len(valid_files)}:v=0:a=1[joined]"
        )
        filter_parts.append(
            f"[joined]"
            f"apad=pad_dur={cut_duration:.3f},"
            f"atrim=duration={cut_duration:.3f}[outa]"
        )

    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            *input_args,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[outa]",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "컷 음성 트랙 생성 실패: "
            + result.stderr[-1400:]
        )


def make_voice_reels_video(
    article,
    voice_volume=1.0,
    cut_duration_override=None,
):
    ffmpeg = ffmpeg_binary()

    if not article.reels_path:
        raise ValueError(
            "기본 릴스 영상이 없습니다. 먼저 ‘릴스 만들기’를 실행해 주세요."
        )

    base_video_path = MEDIA_DIR / article.reels_path

    if not base_video_path.exists():
        raise FileNotFoundError("기본 릴스 영상 파일을 찾을 수 없습니다.")

    audio_map = load_json_map(article.instatoon_audio)

    if not audio_map:
        raise ValueError(
            "생성된 인스타툰 음성이 없습니다. 먼저 8컷 음성을 만들어 주세요."
        )

    reels_settings = load_json_map(article.reels_settings)
    default_cut_duration = safe_float(
        reels_settings.get("seconds_per_cut", 3.0),
        default=3.0,
        minimum=1.5,
        maximum=8.0,
    )

    if cut_duration_override not in (None, ""):
        cut_duration = safe_float(
            cut_duration_override,
            default=default_cut_duration,
            minimum=1.5,
            maximum=8.0,
        )
    else:
        cut_duration = default_cut_duration

    voice_volume = safe_float(
        voice_volume,
        default=1.0,
        minimum=0.2,
        maximum=2.0,
    )

    video_duration = media_duration_seconds(base_video_path)
    cut_count = max(
        1,
        min(
            8,
            int(round(video_duration / cut_duration))
            if cut_duration > 0
            else 8,
        ),
    )

    timestamp = int(datetime.utcnow().timestamp())
    output_filename = (
        f"article_{article.id}_reels_voice_{timestamp}.mp4"
    )
    output_path = MEDIA_DIR / output_filename

    with tempfile.TemporaryDirectory(prefix="mi_voice_reels_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        cut_audio_paths = []

        for cut_number in range(1, cut_count + 1):
            cut_audio_path = (
                temp_dir_path / f"cut_audio_{cut_number:02d}.wav"
            )

            build_cut_voice_track(
                ffmpeg=ffmpeg,
                entries=audio_map.get(str(cut_number), []),
                output_path=cut_audio_path,
                cut_duration=cut_duration,
            )
            cut_audio_paths.append(cut_audio_path)

        concat_list = temp_dir_path / "audio_list.txt"
        concat_list.write_text(
            "\n".join(
                f"file '{path.as_posix()}'"
                for path in cut_audio_paths
            ),
            encoding="utf-8",
        )

        full_audio_path = temp_dir_path / "full_voice.wav"
        concat_result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "pcm_s16le",
                str(full_audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=240,
        )

        if concat_result.returncode != 0:
            raise RuntimeError(
                "전체 음성 트랙 합치기 실패: "
                + concat_result.stderr[-1400:]
            )

        mux_result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i", str(base_video_path),
                "-i", str(full_audio_path),
                "-filter:a", f"volume={voice_volume:.3f}",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if mux_result.returncode != 0:
            raise RuntimeError(
                "음성 포함 릴스 생성 실패: "
                + mux_result.stderr[-1600:]
            )

    return output_filename, {
        "voice_volume": voice_volume,
        "cut_duration": cut_duration,
        "cut_count": cut_count,
        "base_reels_path": article.reels_path,
        "audio_model": TTS_MODEL,
    }


def ffmpeg_binary():
    path = shutil.which("ffmpeg")
    if path:
        return path

    # Render 서버에는 시스템 ffmpeg가 기본으로 설치되어 있지 않을 수
    # 있습니다(오늘 한글 폰트가 없었던 것과 같은 이유입니다). 그래서
    # imageio-ffmpeg 패키지 안에 이미 들어있는 ffmpeg 실행 파일을
    # 대신 사용합니다 - 이건 pip로 설치되기 때문에 항상 존재합니다.
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    raise RuntimeError(
        "FFmpeg를 찾을 수 없습니다. requirements.txt에 imageio-ffmpeg가 "
        "포함되어 있는지 확인해 주세요."
    )


def safe_float(value, default, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default

    return max(minimum, min(number, maximum))


def safe_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default

    return max(minimum, min(number, maximum))


def reels_image_sequence(article):
    captioned = load_json_map(article.instatoon_captioned_images)
    raw = load_json_map(article.instatoon_images)
    sequence = []

    for cut_number in range(1, 9):
        filename = captioned.get(str(cut_number)) or raw.get(str(cut_number))

        if not filename:
            continue

        file_path = MEDIA_DIR / filename

        if file_path.exists():
            sequence.append((cut_number, file_path))

    return sequence


def make_reels_video(
    article,
    seconds_per_cut=3.0,
    fps=30,
    transition_seconds=0.35,
    motion_style="교차 줌",
):
    ffmpeg = ffmpeg_binary()
    sequence = reels_image_sequence(article)

    if not sequence:
        raise ValueError(
            "릴스로 만들 인스타툰 이미지가 없습니다. "
            "먼저 인스타툰 이미지를 생성해 주세요."
        )

    seconds_per_cut = safe_float(
        seconds_per_cut,
        default=3.0,
        minimum=1.5,
        maximum=8.0,
    )
    fps = safe_int(fps, default=30, minimum=24, maximum=60)
    transition_seconds = safe_float(
        transition_seconds,
        default=0.35,
        minimum=0.0,
        maximum=1.0,
    )

    timestamp = int(datetime.utcnow().timestamp())
    output_filename = f"article_{article.id}_reels_{timestamp}.mp4"
    output_path = MEDIA_DIR / output_filename

    with tempfile.TemporaryDirectory(prefix="mi_reels_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        clip_paths = []

        for index, (cut_number, source_path) in enumerate(sequence):
            clip_path = temp_dir_path / f"clip_{index:02d}.mp4"
            total_frames = max(1, int(seconds_per_cut * fps))

            selected_motion=motion_style
            if motion_style in {"다양한 움직임","랜덤"}:
                selected_motion=["줌인","왼쪽→오른쪽","오른쪽→왼쪽","위→아래","아래→위","대각선 이동","줌아웃","부드러운 흔들림"][index%8]
            if selected_motion=="고정":
                filter_chain="scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
            else:
                if selected_motion=="교차 줌": selected_motion="줌인" if index%2==0 else "줌아웃"
                motion_map={
                    "줌인":("min(zoom+0.0012,1.14)","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
                    "줌아웃":("if(eq(on,1),1.14,max(zoom-0.0012,1.0))","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
                    "왼쪽→오른쪽":("1.10",f"(iw-iw/zoom)*on/{total_frames}","ih/2-(ih/zoom/2)"),
                    "오른쪽→왼쪽":("1.10",f"(iw-iw/zoom)*(1-on/{total_frames})","ih/2-(ih/zoom/2)"),
                    "위→아래":("1.10","iw/2-(iw/zoom/2)",f"(ih-ih/zoom)*on/{total_frames}"),
                    "아래→위":("1.10","iw/2-(iw/zoom/2)",f"(ih-ih/zoom)*(1-on/{total_frames})"),
                    "대각선 이동":("1.12",f"(iw-iw/zoom)*on/{total_frames}",f"(ih-ih/zoom)*(1-on/{total_frames})"),
                    "부드러운 흔들림":("1.08","iw/2-(iw/zoom/2)+8*sin(on/8)","ih/2-(ih/zoom/2)+6*cos(on/10)")}
                zoom_expr,x_expr,y_expr=motion_map.get(selected_motion,motion_map["줌인"])
                filter_chain=("scale=1350:2400:force_original_aspect_ratio=increase,"+"zoompan="+f"z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s=1080x1920:fps={fps},setsar=1")

            cmd = [
                ffmpeg,
                "-y",
                "-loop", "1",
                "-i", str(source_path),
                "-vf", filter_chain,
                "-t", f"{seconds_per_cut:.3f}",
                "-r", str(fps),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(clip_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"CUT {cut_number} 영상 변환 실패: "
                    + result.stderr[-1200:]
                )

            clip_paths.append(clip_path)

        list_path = temp_dir_path / "clips.txt"
        list_path.write_text(
            "\n".join(
                f"file '{path.as_posix()}'"
                for path in clip_paths
            ),
            encoding="utf-8",
        )

        concat_cmd = [
            ffmpeg,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

        concat_result = subprocess.run(
            concat_cmd,
            capture_output=True,
            text=True,
            timeout=240,
        )

        if concat_result.returncode != 0:
            raise RuntimeError(
                "릴스 영상 합치기 실패: "
                + concat_result.stderr[-1500:]
            )

    return output_filename, {
        "seconds_per_cut": seconds_per_cut,
        "fps": fps,
        "transition_seconds": transition_seconds,
        "motion_style": motion_style,
        "cut_count": len(sequence),
    }


def google_client_config():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID 또는 GOOGLE_CLIENT_SECRET가 없습니다.")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["https://ai-blog-factory.onrender.com/oauth2callback"],
        }
    }


def blogger_credentials():
    token_json = get_setting("google_credentials")
    if not token_json:
        return None
    info = json.loads(token_json)
    return Credentials.from_authorized_user_info(info, GOOGLE_SCOPES)


def blogger_service():
    creds = blogger_credentials()
    if not creds:
        raise RuntimeError("Google Blogger 연결이 필요합니다.")
    return build("blogger", "v3", credentials=creds, cache_discovery=False)


def get_blogs():
    service = blogger_service()
    data = service.blogs().listByUser(userId="self").execute()
    return data.get("items", [])


def article_labels(article):
    return [
        item.strip().lstrip("#")
        for item in (article.tags or "").split(",")
        if item.strip()
    ]


def valid_public_url(value):
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("상품 링크는 http:// 또는 https://로 시작하는 정상 주소여야 합니다.")
    return value


def coupang_api_configured():
    return bool(COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY)


def coupang_generate_hmac(method, path_with_query):
    """쿠팡 오픈API가 요구하는 HMAC 서명을 만듭니다. 공식 가이드 방식 그대로이며,
    Access Key/Secret Key는 쿠팡파트너스 사이트의 '오픈API' 메뉴에서 발급받습니다."""
    path, _, query = path_with_query.partition("?")
    signed_date = time.strftime("%y%m%d", time.gmtime()) + "T" + time.strftime("%H%M%S", time.gmtime()) + "Z"
    message = signed_date + method + path + query
    signature = hmac.new(
        COUPANG_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, "
        f"signed-date={signed_date}, signature={signature}"
    )


def coupang_search_products(keyword, limit=8):
    """쿠팡파트너스 오픈API로 상품을 검색해, 제휴 링크가 이미 포함된
    상품 목록을 돌려줍니다. API 키가 없거나 호출에 실패하면 빈 리스트를
    반환합니다(화면에서는 '직접 입력해 주세요' 안내로 대체됩니다).
    참고: 이 API는 파트너스 계정의 누적 판매금액이 15만원을 넘어야
    쿠팡에서 활성화해 줍니다. 그 전까지는 키를 넣어도 계속 실패해요."""
    if not coupang_api_configured():
        return []

    keyword = (keyword or "").strip()
    if not keyword:
        return []

    limit = max(1, min(int(limit or 8), 10))  # 쿠팡 검색 API는 최대 10개까지만 허용
    path_with_query = (
        "/v2/providers/affiliate_open_api/apis/openapi/products/search"
        f"?keyword={quote(keyword)}&limit={limit}"
    )
    authorization = coupang_generate_hmac("GET", path_with_query)

    req = urllib.request.Request(
        COUPANG_API_DOMAIN + path_with_query,
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json;charset=UTF-8",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        # 네트워크 오류, 키 미승인(15만원 조건 미충족), 시간당 호출 제한
        # 초과 등 어떤 이유로든 실패하면 빈 목록만 돌려주고 화면에서는
        # 손으로 입력하는 방식으로 자연스럽게 넘어가게 합니다.
        return []

    products = (
        payload.get("data", {}).get("productData", [])
        if isinstance(payload, dict)
        else []
    )

    results = []
    for item in products:
        if not isinstance(item, dict):
            continue
        results.append({
            "name": item.get("productName", ""),
            "price": item.get("productPrice", ""),
            "image": item.get("productImage", ""),
            "url": item.get("productUrl", ""),
            "is_rocket": bool(item.get("isRocket")),
        })
    return results


def build_affiliate_html(article):
    items = []
    if article.coupang_product_name and article.coupang_link:
        items.append(("쿠팡 추천", article.coupang_product_name, article.coupang_link))
    if article.atomy_product_name and article.atomy_link:
        items.append(("애터미 추천", article.atomy_product_name, article.atomy_link))
    if article.toss_product_name and article.toss_link:
        items.append(("토스쇼핑 추천", article.toss_product_name, article.toss_link))
    if not items:
        return ""

    cards = []
    for label, name, link in items:
        cards.append(
            '<div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:12px 0">'
            f'<strong>{escape(label)}</strong>'
            f'<p style="margin:8px 0 12px">{escape(name)}</p>'
            f'<a href="{escape(link, quote=True)}" target="_blank" rel="nofollow sponsored noopener" '
            'style="display:inline-block;padding:10px 14px;border-radius:9px;background:#6d5dfc;color:#fff;text-decoration:none;font-weight:700">상품 보러 가기</a>'
            '</div>'
        )

    disclosure = (
        '<p style="font-size:13px;color:#6b7280;background:#f7f8fc;padding:10px;border-radius:8px">'
        '이 글에는 제휴 링크가 포함될 수 있으며, 링크를 통한 구매 시 작성자에게 일정 수수료가 제공될 수 있습니다. 구매 가격에는 영향을 주지 않습니다.'
        '</p>'
    )
    return '<section><h2>함께 보면 좋은 추천</h2>' + disclosure + ''.join(cards) + '</section>'


def article_content_for_blogger(article):
    content = article.body_html or ""
    if article.thumbnail_path:
        public_image_url = url_for(
            "media", filename=article.thumbnail_path, _external=True
        )
        hero = (
            f'<p><img src="{public_image_url}" alt="{article.title}" '
            f'style="max-width:100%;height:auto"></p>'
        )
        content = hero + content
    if article.affiliate_enabled and article.affiliate_html:
        content = content + article.affiliate_html
    return content


def add_publish_log(article, action, status, message="", blogger_url=None):
    log = PublishLog(
        article_id=article.id,
        action=action,
        status=status,
        message=str(message or "")[:3000],
        blogger_url=blogger_url or article.blogger_url,
    )
    db.session.add(log)


def now_kst_naive():
    return datetime.now(KST).replace(tzinfo=None)


def save_blogger_result(article, result, blog_id, mode):
    article.blogger_post_id = result.get("id") or article.blogger_post_id
    article.blogger_blog_id = str(blog_id)
    article.blogger_url = result.get("url") or article.blogger_url
    article.blogger_status = "Blogger 초안" if mode == "draft" else "Blogger 공개"
    if mode != "scheduled":
        article.scheduled_at = None
    add_publish_log(
        article,
        action="초안 저장" if mode == "draft" else "공개 발행",
        status="성공",
        message=article.blogger_status,
        blogger_url=article.blogger_url,
    )
    db.session.commit()


def instagram_configured():
    return bool(INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID)


def publish_to_instagram(image_url, caption):
    """인스타그램에 이미지+캡션을 게시합니다. 2단계로 진행됩니다:
    1) 미디어 컨테이너 생성 2) 그 컨테이너를 실제로 게시.
    이미지는 반드시 인터넷에서 접근 가능한 공개 URL이어야 합니다
    (인스타그램 서버가 그 URL로 직접 이미지를 가져가요)."""
    if not instagram_configured():
        raise RuntimeError(
            "인스타그램이 아직 연결되지 않았어요. Render 환경변수에 "
            "INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID를 등록해 주세요."
        )

    container_resp = requests.post(
        f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_ACCOUNT_ID}/media",
        params={"access_token": INSTAGRAM_ACCESS_TOKEN},
        json={
            "image_url": image_url,
            "caption": caption,
        },
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    container_data = container_resp.json()
    if container_resp.status_code >= 400 or "id" not in container_data:
        raise RuntimeError(
            f"게시물 준비 실패: {container_data.get('error', container_data)}"
        )

    creation_id = container_data["id"]

    publish_resp = requests.post(
        f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        params={"access_token": INSTAGRAM_ACCESS_TOKEN},
        json={"creation_id": creation_id},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    publish_data = publish_resp.json()
    if publish_resp.status_code >= 400 or "id" not in publish_data:
        raise RuntimeError(
            f"게시 실패: {publish_data.get('error', publish_data)}"
        )

    return publish_data["id"]


def upsert_blogger_post(article, blog_id, mode="draft"):
    service = blogger_service()
    body = {
        "title": article.title,
        "content": article_content_for_blogger(article),
        "labels": article_labels(article),
    }

    is_draft = mode == "draft"
    same_blog = article.blogger_post_id and article.blogger_blog_id == str(blog_id)

    if same_blog:
        result = service.posts().update(
            blogId=blog_id,
            postId=article.blogger_post_id,
            body=body,
            publish=not is_draft,
            revert=is_draft,
            fetchImages=True,
        ).execute()
        action = "업데이트"
    else:
        result = service.posts().insert(
            blogId=blog_id,
            body=body,
            isDraft=is_draft,
            fetchImages=True,
        ).execute()
        action = "발행"

    save_blogger_result(article, result, blog_id, mode)
    return action


def generate_social_pack(article):
    is_fortune_brand = "운세" in (article.brand_style or "")
    fortune_url = os.getenv("FORTUNE_URL", "https://ai-blog-factory.onrender.com/fortune/")

    cta_instruction = ""
    if is_fortune_brand:
        cta_instruction = f"""
이 콘텐츠는 "오늘의 운세" 광고성 콘텐츠입니다. 아래 CTA 규칙을 반드시 지키세요.
- instagram_caption: 마지막 줄에 "🔮 내 생년월일로 보는 자세한 운세는 프로필 링크에서
  확인하세요 (3,000원)"처럼, 인스타그램은 캡션 안 링크가 눌리지 않으니
  "프로필 링크"를 안내하는 문구를 자연스럽게 넣으세요.
- threads_text: 마지막 줄에 실제 링크를 그대로 넣으세요: {fortune_url}
- youtube_description: 마지막 문단에 실제 링크를 그대로 넣으세요: {fortune_url}
- tiktok_caption: 마지막 줄에 "프로필 링크에서 내 운세 확인" 같은 문구를 넣으세요
  (틱톡도 캡션 링크가 안 눌리므로 프로필 링크 안내 방식).
- 가격(3,000원)은 최소 인스타그램·유튜브 설명 중 한 곳에는 자연스럽게 언급하세요.
- 과장 광고 문구("무조건", "100% 적중")는 쓰지 마세요.
"""

    prompt = f"""
다음 블로그 글을 바탕으로 한국어 SNS 콘텐츠 패키지를 만드세요.

제목: {article.title}
핵심 키워드: {article.keyword}
본문 요약: {plain_text_from_html(article.body_html)[:2500]}
{cta_instruction}
작성 규칙:
1. instagram_caption
   - 첫 문장은 시선을 끄는 훅
   - 본문 5~8문장
   - 마지막에 자연스러운 CTA
   - 해시태그 5~8개

2. threads_text
   - 짧고 자연스러운 대화체
   - 5~9문장
   - 과장 표현 금지

3. shorts_script
   - 35~50초 분량
   - 첫 2초 훅
   - 장면별 대사
   - 화면 자막
   - 마지막 CTA

4. instatoon
   - 반드시 정확히 8컷
   - 각 컷은 반드시 아래 형식으로 작성
   - 각 컷 사이에는 반드시 [CUT] 구분자를 넣기

[CUT]
컷 번호: 1
장면:
대사:
자막:

[CUT]
컷 번호: 2
장면:
대사:
자막:

이 형식을 8컷까지 반복

5. thumbnail_text
   - 18자 이내
   - 핵심 키워드를 자연스럽게 포함
   - 과장하지 않으면서 클릭하고 싶은 문구

6. youtube_title
   - 60자 이내
   - 핵심 키워드를 앞쪽에 배치
   - 과장 표현 금지

7. youtube_description
   - 3~5문단
   - 첫 문단에 영상 핵심 요약(검색 노출용)
   - 마지막에 채널 구독 유도 CTA

8. youtube_tags
   - 쉼표로 구분한 키워드 10~15개

9. tiktok_caption
   - 짧고 임팩트 있는 한 줄 훅으로 시작
   - 2~4문장
   - 해시태그 4~6개 (틱톡에서 자주 쓰는 형태)

반드시 아래 JSON 형식 하나만 출력하세요.

{{
  "instagram_caption": "...",
  "threads_text": "...",
  "shorts_script": "...",
"instatoon": "[CUT]\n컷 번호: 1\n장면: ...\n대사: ...\n자막: ...\n\n[CUT]\n컷 번호: 2\n장면: ...\n대사: ...\n자막: ...",
"...",
  "thumbnail_text": "...",
  "youtube_title": "...",
  "youtube_description": "...",
  "youtube_tags": "...",
  "tiktok_caption": "..."
}}
"""

    response = openai_client().responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )
    log_ai_usage("text")

    raw = strip_code_fence(response.output_text)

    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)

        if not match:
            raise RuntimeError(
                "SNS 콘텐츠 응답을 JSON으로 읽지 못했습니다."
            )

        return json.loads(match.group(0))




def current_instatoon_text(article):
    return canonical_instatoon_text(article)


def replace_instatoon_text(article, new_instatoon_text):
    notes = article.notes or ""
    marker = "🎨 인스타툰 8컷"

    if marker in notes:
        prefix = notes.split(marker, 1)[0].rstrip()
    else:
        prefix = notes.rstrip()

    article.notes = (
        prefix
        + "\n\n========================"
        + "\n🎨 인스타툰 8컷"
        + "\n========================\n"
        + (new_instatoon_text or "").strip()
    )


def generate_director_revision(article, tone="공감형", intensity="보통"):
    instatoon_text = current_instatoon_text(article)

    if not instatoon_text:
        raise ValueError(
            "분석할 인스타툰 8컷이 없습니다. 먼저 전체 파이프라인을 실행해 주세요."
        )

    prompt = f"""
당신은 한국 인스타툰 전문 연출 감독입니다.

콘텐츠 제목:
{article.title}

핵심 키워드:
{article.keyword}

브랜드 스타일:
{article.brand_style}

독자:
{article.audience or '일반 독자'}

원본 인스타툰:
{instatoon_text}

연출 방향:
- 톤: {tone}
- 수정 강도: {intensity}

분석 목표:
1. 첫 컷이 1초 안에 시선을 끄는지 평가
2. 컷마다 장면과 감정이 실제로 변화하는지 평가
3. 같은 구도나 비슷한 대사가 반복되는지 확인
4. 엄마와 딸의 감정선이 자연스럽게 이어지는지 확인
5. 7~8컷에 반전, 깨달음, 행동 유도 중 하나가 있는지 확인
6. 이미지 생성에 적합하도록 장면은 구체적으로 작성
7. 대사와 자막은 짧고 자연스러운 한국어로 작성
8. 반드시 정확히 8컷 유지
9. 사실을 새로 꾸며내지 말 것
10. 제품 광고는 원본에 있는 경우에만 자연스럽게 유지

수정 강도 기준:
- 약하게: 원본 의미를 유지하고 문장과 구도만 정리
- 보통: 훅, 감정선, 장면 변화까지 개선
- 강하게: 핵심 주제만 유지하고 연출을 적극 재구성

반드시 아래 JSON 형식 하나만 출력하세요.

{{
  "score": 0,
  "summary": "전체 평가",
  "strengths": ["장점1", "장점2"],
  "problems": ["문제1", "문제2"],
  "directing_notes": [
    {{
      "cut_number": 1,
      "problem": "현재 문제",
      "direction": "연출 수정 방향",
      "camera": "추천 구도",
      "emotion": "핵심 감정"
    }}
  ],
  "revised_instatoon": "[CUT]\\n컷 번호: 1\\n장면: ...\\n대사: ...\\n자막: ...\\n\\n[CUT]\\n컷 번호: 2\\n장면: ...\\n대사: ...\\n자막: ..."
}}
"""

    response = openai_client().responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )
    log_ai_usage("text")

    raw = strip_code_fence(response.output_text)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)

        if not match:
            raise RuntimeError("연출 감독 응답을 JSON으로 읽지 못했습니다.")

        data = json.loads(match.group(0))

    revised = str(data.get("revised_instatoon", "")).strip()
    cut_count = len([
        chunk
        for chunk in revised.split("[CUT]")
        if "컷 번호" in chunk
    ])

    if cut_count != 8:
        raise RuntimeError(
            f"AI 수정안이 정확히 8컷이 아닙니다. 현재 {cut_count}컷입니다."
        )

    return data



def production_queue_snapshot(article):
    images = load_json_map(article.instatoon_images)
    captioned = load_json_map(article.instatoon_captioned_images)
    audio = load_json_map(article.instatoon_audio)

    return {
        "images": sum(1 for i in range(1, 9) if images.get(str(i))),
        "captioned": sum(1 for i in range(1, 9) if captioned.get(str(i))),
        "audio": sum(1 for i in range(1, 9) if audio.get(str(i))),
        "reels": bool(article.reels_path),
        "reels_voice": bool(article.reels_voice_path),
        "reels_final": bool(article.reels_final_path),
        "zip": bool(article.export_package_path),
        "bgm": bool(article.reels_bgm_path),
    }


def save_queue_state(article, step, status, message=""):
    state = load_json_map(article.production_queue_state)
    state.update({
        "step": step,
        "status": status,
        "message": message,
        "updated_at": datetime.utcnow().isoformat(),
        "snapshot": production_queue_snapshot(article),
    })
    article.production_queue_state = json.dumps(
        state,
        ensure_ascii=False,
    )


def clear_instatoon_generated_assets(article):
    filenames = []

    for json_value in [
        article.instatoon_images,
        article.instatoon_captioned_images,
    ]:
        mapping = load_json_map(json_value)
        filenames.extend(mapping.values())

    audio_map = load_json_map(article.instatoon_audio)

    for entries in audio_map.values():
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("filename"):
                filenames.append(entry["filename"])

    filenames.extend([
        article.reels_path,
        article.reels_voice_path,
        article.reels_final_path,
        article.export_package_path,
    ])

    for filename in filenames:
        delete_media_if_exists(filename)

    article.instatoon_images = "{}"
    article.instatoon_captioned_images = "{}"
    article.instatoon_audio = "{}"
    article.instatoon_audio_settings = "{}"
    article.reels_path = None
    article.reels_settings = "{}"
    article.reels_voice_path = None
    article.reels_voice_settings = "{}"
    article.reels_final_path = None
    article.reels_final_settings = "{}"
    article.export_package_path = None
    article.export_package_settings = "{}"


def generate_content_ideas(topic, count=12):
    count = max(5, min(int(count or 12), 30))
    prompt = f"""
한국어 콘텐츠 기획자 역할을 하세요.

주제: {topic}
아이디어 개수: {count}

블로그, 인스타툰, 릴스/쇼츠, Threads에 활용할 수 있는 서로 겹치지 않는 아이디어를 만드세요.
각 아이디어는 실제 제작이 가능해야 하며 과장된 사실을 만들지 마세요.

JSON 배열 하나만 출력하세요.
[
  {{
    "title": "콘텐츠 제목",
    "hook": "첫 1~2초 또는 첫 문장에 사용할 훅",
    "format_type": "블로그|인스타툰|릴스/쇼츠|Threads"
  }}
]
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    log_ai_usage("text")
    raw = strip_code_fence(response.output_text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise RuntimeError("아이디어 응답을 JSON으로 읽지 못했습니다.")
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise RuntimeError("아이디어 응답 형식이 올바르지 않습니다.")
    return data[:count]


def pipeline_progress(article):
    steps = [
        bool(article.body_html),
        bool(article.seo_score),
        bool(article.thumbnail_path),
        bool(article.instagram_caption),
        bool(article.threads_text),
        bool(article.shorts_script),
    ]
    return round(sum(steps) / len(steps) * 100)


def parse_local_datetime(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


BASE_HTML = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ page_title or 'MI Creator OS' }}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" as="style" crossorigin
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700;900&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#221f2b;
  --muted:#7a7488;
  --line:#e8e3ee;
  --brand:#4b3f72;
  --brand-dark:#352c54;
  --brand-soft:#f4f1fb;
  --gold:#b8925a;
  --gold-soft:#faf3e6;
  --paper:#faf8f4;
  --ok:#127a53;
  --bad:#c23b3b;
  --warn:#a86a1f;
  --shadow:0 12px 32px rgba(43,32,74,.08);
  --shadow-lift:0 18px 44px rgba(43,32,74,.14);
}
*{box-sizing:border-box}
body{
  margin:0;
  background:var(--paper);
  color:var(--ink);
  font-family:'Pretendard Variable','Pretendard',-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
  letter-spacing:-0.01em;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1040px;margin:34px auto;padding:0 18px}
.card{
  background:#fff;
  border:1px solid var(--line);
  border-radius:20px;
  padding:26px;
  margin-bottom:18px;
  box-shadow:var(--shadow);
}
h1{
  margin:0 0 10px;
  font-family:'Noto Serif KR',serif;
  font-size:32px;
  font-weight:800;
  letter-spacing:-0.01em;
  color:var(--brand-dark);
  line-height:1.3;
}
h1::before{
  content:"";
  display:block;
  width:40px;
  height:4px;
  background:var(--gold);
  border-radius:3px;
  margin-bottom:14px;
}
h2{margin:0 0 18px;font-size:21px;font-weight:800;letter-spacing:-0.01em}
h3{margin:18px 0 8px;font-weight:700}
.lead,.small{color:var(--muted)}.small{font-size:14px}
label{font-weight:700;display:block;margin:14px 0 7px;color:#3a3450}
input,textarea,select{
  width:100%;
  border:1.5px solid #e2dced;
  border-radius:12px;
  padding:12px 13px;
  font:inherit;
  background:#fff;
  transition:border-color .15s ease, box-shadow .15s ease;
}
input:focus,textarea:focus,select:focus{
  outline:none;
  border-color:var(--brand);
  box-shadow:0 0 0 3px var(--brand-soft);
}
textarea{min-height:150px;resize:vertical}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.btn{
  border:0;
  border-radius:11px;
  padding:12px 18px;
  background:var(--brand-dark);
  color:#fff;
  font-weight:700;
  cursor:pointer;
  text-decoration:none;
  display:inline-block;
  box-shadow:0 4px 14px rgba(75,63,114,.28);
  transition:transform .12s ease, box-shadow .12s ease, filter .12s ease;
}
.btn:hover{transform:translateY(-1px);filter:brightness(1.05)}
.btn:disabled{opacity:.55;cursor:not-allowed;transform:none;filter:none}
.spin{display:inline-block;animation:spin 1s linear infinite}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.btn.gray{background:#f1eef8;color:#3a3450;box-shadow:none}
.btn.gray:hover{background:#e7e1f5}
.btn.green{background:var(--ok);box-shadow:0 4px 14px rgba(18,122,83,.24)}
.btn.red{background:var(--bad);box-shadow:0 4px 14px rgba(194,59,59,.24)}
.btn.orange{background:var(--warn);box-shadow:0 4px 14px rgba(168,106,31,.24)}
.flash{padding:13px 16px;border-radius:12px;background:var(--gold-soft);border:1px solid #ecd9b6;margin-bottom:15px;color:#6b4e1e}
.status{display:inline-block;padding:5px 10px;border-radius:99px;background:#e7f5ee;color:var(--ok);font-size:13px;font-weight:700}
.status.draft{background:var(--gold-soft);color:var(--warn)}
.status.off{background:#f1eff5;color:#6b6478}
.status.scheduled{background:var(--brand-soft);color:var(--brand)}
table{width:100%;border-collapse:collapse}
th,td{padding:12px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.preview{border:1px solid var(--line);border-radius:14px;padding:20px;line-height:1.75}
.article-preview-header{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:14px;
  margin-bottom:14px;
}

.article-live-preview{
  min-height:300px;
  padding:28px;
  background:#fff;
  line-height:1.85;
}

.article-live-preview h1{
  font-family:'Noto Serif KR',serif;
  font-size:30px;
  line-height:1.35;
  margin:0 0 22px;
  color:var(--brand-dark);
}

.article-live-preview h2{
  font-size:24px;
  line-height:1.4;
  margin:30px 0 14px;
}

.article-live-preview h3{
  font-size:20px;
  margin:24px 0 10px;
}

.article-live-preview p{
  margin:0 0 16px;
}

.article-live-preview li{
  margin-bottom:10px;
}

.html-editor-details{
  margin-top:18px;
  border:1px solid var(--line);
  border-radius:14px;
  overflow:hidden;
  background:var(--paper);
}

.html-editor-details summary{
  cursor:pointer;
  padding:16px 18px;
  font-weight:800;
  background:var(--brand-soft);
  color:var(--brand-dark);
  user-select:none;
}

.html-editor-details[open] summary{
  border-bottom:1px solid var(--line);
}

.html-editor-inner{
  padding:18px;
  background:#fff;
}

@media(max-width:700px){
  .article-preview-header{
    align-items:flex-start;
    flex-direction:column;
  }

  .article-live-preview{
    padding:20px;
  }
}
.thumb-wrap{position:relative;border-radius:16px;overflow:hidden;background:#ddd}.thumb{width:100%;display:block}.thumb-badge{position:absolute;left:5%;bottom:8%;max-width:88%;background:rgba(31,25,46,.82);color:#fff;padding:13px 18px;border-radius:11px;font-weight:800;font-size:clamp(18px,3vw,34px)}
.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}
.stat{background:var(--brand-soft);border:1px solid #e6defa;border-radius:16px;padding:16px}
.stat strong{display:block;font-size:28px;margin-bottom:4px;color:var(--brand-dark);font-weight:800}
.copy-box{position:relative}.copy-btn{margin-top:7px;background:#f1eef8;color:#3a3450}.calendar-item{padding:14px 0;border-bottom:1px solid var(--line)}
.progress{height:11px;background:#efeaf9;border-radius:999px;overflow:hidden}
.progress>span{display:block;height:100%;background:var(--brand);border-radius:999px}
.pipeline-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:14px}
.pipeline-step{border:1px solid var(--line);border-radius:13px;padding:12px;background:#fff}
.idea-card{border:1px solid var(--line);border-radius:15px;padding:16px;margin:12px 0}
.instatoon-grid{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:14px;
  margin-top:18px;
}

.instatoon-card{
  position:relative;
  border:1px solid var(--line);
  border-radius:20px;
  padding:18px;
  background:#ffffff;
  box-shadow:var(--shadow);
}

.instatoon-card h3{
  margin:10px 0 12px;
  font-size:18px;
}

.instatoon-card-content{
  white-space:pre-wrap;
  line-height:1.8;
  min-height:180px;
  color:#4a4458;
}

.instatoon-number{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:48px;
  height:32px;
  padding:0 12px;
  border-radius:999px;
  background:var(--brand-soft);
  color:var(--brand-dark);
  font-size:13px;
  font-weight:900;
}

@media(max-width:700px){
  .instatoon-grid{
    grid-template-columns:1fr;
  }
}
.checklist{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.check-item{border:1px solid var(--line);border-radius:13px;padding:12px;background:var(--brand-soft)}
.money-box{border:1px solid #ecd9b6;background:var(--gold-soft);border-radius:16px;padding:18px}
.notice{font-size:13px;color:var(--muted);background:var(--paper);border-radius:10px;padding:10px}
.toggle{display:flex;align-items:center;gap:9px;margin-top:14px}.toggle input{width:auto}
.score{font-size:46px;font-weight:900;color:var(--brand-dark)}
.check{padding:10px 0;border-bottom:1px solid var(--line)}
.pass{color:var(--ok);font-weight:800}.fail{color:var(--bad);font-weight:800}
.tags{display:flex;gap:7px;flex-wrap:wrap}
.tag{background:var(--brand-soft);color:var(--brand-dark);padding:7px 11px;border-radius:99px;font-weight:600}
@media(max-width:900px){
  .stat-grid{
    grid-template-columns:repeat(2,minmax(0,1fr))!important;
  }
}
@media(max-width:700px){
  .grid,.stat-grid,.pipeline-grid,.checklist,.instatoon-grid,.cut-menu-grid{
    grid-template-columns:1fr!important;
  }
  .wrap{margin-top:18px}
  .card{padding:18px}
  table thead{display:none}
  table tr,table td{display:block}
  table tr{padding:12px 0;border-bottom:1px solid var(--line)}
  table td{border:0;padding:4px 0}
}
@media(max-width:480px){
  [class*="grid" i]{
    grid-template-columns:1fr!important;
  }
  html,body{overflow-x:hidden}
  img{max-width:100%;height:auto}
  .wrap{padding:0 12px}
  h1{font-size:24px}
  h2{font-size:19px}
}

.nav-shell{position:sticky;top:0;z-index:50;background:rgba(250,248,244,.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.nav-inner{max-width:1180px;margin:0 auto;padding:12px 18px;display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.nav-brand{font-family:'Noto Serif KR',serif;font-weight:700;text-decoration:none;color:var(--brand-dark);margin-right:auto;font-size:19px;letter-spacing:-0.01em}
.nav-home{background:var(--brand-soft);color:var(--brand-dark)!important;padding:9px 14px;border-radius:11px;text-decoration:none;font-weight:700}
.all-menu{position:relative}
.all-menu summary{list-style:none;cursor:pointer;padding:9px 14px;border-radius:11px;background:var(--brand-dark);color:#fff;font-weight:700;user-select:none;box-shadow:0 4px 14px rgba(75,63,114,.28)}
.all-menu summary::-webkit-details-marker{display:none}
.all-menu[open] summary{filter:brightness(.94)}
.all-menu-panel{position:absolute;top:47px;right:0;width:min(430px,calc(100vw - 28px));max-height:calc(100vh - 80px);overflow:auto;background:#fff;border:1px solid var(--line);border-radius:20px;padding:15px;box-shadow:var(--shadow-lift)}
.menu-section{padding:5px 0 12px}
.menu-section+.menu-section{border-top:1px solid var(--line);padding-top:14px}
.menu-title{font-size:12px;font-weight:800;color:var(--gold);text-transform:uppercase;letter-spacing:.06em;margin:0 0 7px;padding:0 5px}
.menu-links{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}
.menu-links a{display:block;padding:11px 10px;border-radius:12px;text-decoration:none;color:var(--ink);background:var(--paper);font-weight:600;font-size:14px;transition:background .12s ease}
.menu-links a:hover{background:var(--brand-soft);color:var(--brand-dark)}
@media(max-width:600px){
  .nav-brand{font-size:16px}
  .nav-home{display:none}
  .all-menu-panel{position:fixed;top:61px;left:14px;right:14px;width:auto}
  .menu-links{grid-template-columns:1fr}
}

.content-tabs{
  position:sticky;
  top:62px;
  z-index:40;
  display:flex;
  gap:8px;
  overflow-x:auto;
  padding:12px;
  margin-bottom:18px;
  background:rgba(250,248,244,.96);
  backdrop-filter:blur(10px);
  border:1px solid var(--line);
  border-radius:18px;
}

.content-tab{
  flex:0 0 auto;
  border:0;
  border-radius:999px;
  padding:10px 16px;
  background:#f1eef8;
  color:#4a4458;
  font-weight:700;
  cursor:pointer;
}

.content-tab.active{
  background:var(--brand-dark);
  color:#fff;
}

.tab-panel{
  display:none;
}

.tab-panel.active{
  display:block;
}

</style>
</head>
<body>

<div class="nav-shell">
  <div class="nav-inner">
    <a class="nav-brand" href="{{url_for('home_v16.dashboard')}}">MI Creator OS</a>
    <a class="nav-home" href="{{url_for('home_v16.dashboard')}}">홈</a>

    <details class="all-menu">
      <summary>☰ 전체 메뉴</summary>
      <div class="all-menu-panel">
        <div class="menu-section">
          <div class="menu-title">콘텐츠 제작</div>
          <div class="menu-links">
            <a href="/fortune-quick/">🔮 오늘의 운세</a>
            <a href="{{url_for('factory_v15.dashboard')}}">콘텐츠 팩토리</a>
            <a href="{{url_for('generator_v12.dashboard')}}">AI 프로젝트 자동 생성</a>
            <a href="{{url_for('assistant_v92.dashboard')}}">AI 콘텐츠 비서</a>
            <a href="{{url_for('marketing_v14.ideas')}}">AI 아이디어 연구소</a>
            <a href="{{url_for('library_v11.dashboard')}}">콘텐츠 라이브러리</a>
            <a href="{{url_for('manager_v10.dashboard')}}">AI 콘텐츠 매니저</a>
          </div>
        </div>

        <div class="menu-section">
          <div class="menu-title">운영 관리</div>
          <div class="menu-links">
            <a href="{{url_for('pipeline_v13.board')}}">콘텐츠 파이프라인</a>
            <a href="{{url_for('marketing_v14.shooting')}}">촬영 체크리스트</a>
            <a href="{{url_for('planner_v93.dashboard')}}">주간 콘텐츠 플래너</a>
            <a href="{{url_for('calendar_v94.dashboard')}}">콘텐츠 캘린더</a>
          </div>
        </div>

        <div class="menu-section">
          <div class="menu-title">마케팅·소통</div>
          <div class="menu-links">
            <a href="{{url_for('marketing_v14.dashboard')}}">AI 마케팅 센터</a>
            <a href="{{url_for('analytics_v95.dashboard')}}">성과 분석</a>
            <a href="{{url_for('marketing_v14.monthly_report')}}">월간 리포트</a>
            <a href="{{url_for('social_v96.dashboard')}}">AI 소통 비서</a>
          </div>
        </div>

        <div class="menu-section">
          <div class="menu-title">사업·시스템</div>
          <div class="menu-links">
            <a href="{{url_for('business_v91.dashboard')}}">수익 대시보드</a>
            <a href="{{url_for('diagnostics_v95.dashboard')}}">시스템 점검</a>
          </div>
        </div>

        <div class="menu-section">
          <div class="menu-title">고객용 서비스</div>
          <div class="menu-links">
            <a href="/fortune/" target="_blank">🔮 오늘의 운세 (손님용 결제 페이지)</a>
          </div>
        </div>

        <div class="menu-section">
          <div class="menu-title">기존 도구</div>
          <div class="menu-links">
            <a href="{{url_for('content_calendar')}}">기존 콘텐츠 캘린더</a>
            <a href="{{url_for('idea_lab')}}">기존 AI 아이디어 연구소</a>
          </div>
        </div>
      </div>
    </details>
  </div>
</div>
<main class="wrap">
{% with messages=get_flashed_messages() %}{% if messages %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endif %}{% endwith %}
{{ body|safe }}
</main>
<script>
async function copyText(id, button){
  const el=document.getElementById(id);
  if(!el) return;
  try{
    await navigator.clipboard.writeText(el.value || el.innerText || "");
    const old=button.innerText;
    button.innerText="복사 완료";
    setTimeout(()=>button.innerText=old,1400);
  }catch(e){
    el.focus(); el.select();
    document.execCommand("copy");
    button.innerText="복사 완료";
  }
}
</script>
</body></html>
"""


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)

def page_file(template_name, **context):
    body = render_template(template_name, **context)

    return render_template_string(
        BASE_HTML,
        body=Markup(body),
        **context,
    )

@app.get("/")
def home():
    return redirect(url_for("home_v16.dashboard"))


@app.post("/articles")
def create_article():
    try:
        data = generate_article(
            request.form["keyword"].strip(),
            request.form.get("brand_style", "육아·생활"),
            request.form.get("article_type", "정보형"),
            request.form.get("length", "약 2,500자"),
            request.form.get("audience", "").strip(),
            request.form.get("notes", "").strip(),
        )
        tags = data.get("tags", [])
        if isinstance(tags, list):
            tags = ",".join(str(x).strip().lstrip("#") for x in tags if str(x).strip())
        article = Article(
            keyword=request.form["keyword"].strip(),
            title=data.get("title", request.form["keyword"].strip()),
            meta_description=data.get("meta_description", ""),
            body_html=data.get("body_html", ""),
            brand_style=request.form.get("brand_style", "육아·생활"),
            article_type=request.form.get("article_type", "정보형"),
            audience=request.form.get("audience", "").strip(),
            notes=request.form.get("notes", "").strip(),
            tags=tags,
        )
        db.session.add(article)
        db.session.flush()
        article.seo_score, report = analyze_seo(article)
        article.seo_report = json.dumps(report, ensure_ascii=False)
        db.session.commit()
        flash("AI 초안이 만들어졌어요. 내용을 확인하고 수정해 주세요.")
        return redirect(url_for("edit_article", article_id=article.id))
    except Exception as e:
        db.session.rollback()
        flash(f"글 생성 실패: {e}")
        return redirect(url_for("home"))


@app.route("/articles/<int:article_id>", methods=["GET", "POST"])
def edit_article(article_id):
    article = Article.query.get_or_404(article_id)
    if request.method == "POST":
        article.title = request.form.get("title", "").strip()
        article.meta_description = request.form.get("meta_description", "").strip()
        article.body_html = request.form.get("body_html", "").strip()
        article.tags = request.form.get("tags", "").strip()
        article.seo_score, report = analyze_seo(article)
        article.seo_report = json.dumps(report, ensure_ascii=False)
        db.session.commit()
        flash("수정 내용과 SEO 분석을 저장했습니다.")
        return redirect(url_for("edit_article", article_id=article.id))

    try:
        seo_report = json.loads(article.seo_report or "{}")
    except json.JSONDecodeError:
        seo_report = {}
    blogs = []
    if get_setting("google_credentials"):
        try:
            blogs = get_blogs()
        except Exception as e:
            flash(f"Blogger 목록을 불러오지 못했습니다: {e}")
    tags = [x.strip() for x in (article.tags or "").split(",") if x.strip()]
    publish_logs = PublishLog.query.filter_by(article_id=article.id).order_by(PublishLog.created_at.desc()).limit(20).all()

    progress = pipeline_progress(article)

    instatoon_images = load_json_map(article.instatoon_images)
    instatoon_captioned_images = load_json_map(
        article.instatoon_captioned_images
    )

    instatoon_character_profile = get_instatoon_character_profile(article)
    instatoon_audio = load_json_map(article.instatoon_audio)
    instatoon_audio_settings = load_json_map(
        article.instatoon_audio_settings
    )
    instatoon_presets = InstatoonPreset.query.order_by(
        InstatoonPreset.updated_at.desc()
    ).all()
    director_report = load_json_map(article.director_report)
    production_queue_state = load_json_map(
        article.production_queue_state
    )
    production_queue_snapshot_data = production_queue_snapshot(article)
    instatoon_cuts = get_instatoon_cuts(article)
    instatoon_text = canonical_instatoon_text(article)

    try:
        fortune_cards = json.loads(article.fortune_card_paths or "[]")
        if not isinstance(fortune_cards, list):
            fortune_cards = []
    except json.JSONDecodeError:
        fortune_cards = []

    return page_file(
        "edit_article.html",
        a=article,
        seo_report=seo_report,
        tags=tags,
        blogs=blogs,
        publish_logs=publish_logs,
        progress=progress,
        fortune_cards=fortune_cards,
        instatoon_images=instatoon_images,
        instatoon_captioned_images=instatoon_captioned_images,
        instatoon_character_profile=instatoon_character_profile,
        instatoon_audio=instatoon_audio,
        instatoon_audio_settings=instatoon_audio_settings,
        instatoon_presets=instatoon_presets,
        director_report=director_report,
        production_queue_state=production_queue_state,
        production_queue_snapshot=production_queue_snapshot_data,
        instatoon_cuts=instatoon_cuts,
        instatoon_text=instatoon_text,
        page_title=f"{article.title} | MI Creator OS",
    )




@app.post("/articles/<int:article_id>/instatoon/character-profile")
def save_instatoon_character_profile(article_id):
    article = Article.query.get_or_404(article_id)

    profile = {
        "project_name": request.form.get("project_name", "").strip(),
        "mother_name": request.form.get("mother_name", "").strip(),
        "mother_appearance": request.form.get("mother_appearance", "").strip(),
        "daughter_name": request.form.get("daughter_name", "").strip(),
        "daughter_appearance": request.form.get("daughter_appearance", "").strip(),
        "art_style": request.form.get("art_style", "").strip(),
        "location_style": request.form.get("location_style", "").strip(),
        "negative_rules": request.form.get("negative_rules", "").strip(),
        "caption_style": request.form.get("caption_style", "").strip(),
        "caption_font_size": request.form.get("caption_font_size", "").strip(),
        "subtitle_font_size": request.form.get("subtitle_font_size", "").strip(),
        "reference_priority": request.form.get("reference_priority", "").strip(),
    }

    default_profile = default_instatoon_character_profile()

    for key, value in default_profile.items():
        if not profile.get(key):
            profile[key] = value

    article.instatoon_character_profile = json.dumps(
        profile,
        ensure_ascii=False,
    )

    db.session.commit()
    flash("인스타툰 캐릭터 설정을 저장했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/instatoon/character-sheet")
def generate_instatoon_character_sheet_route(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        profile = get_instatoon_character_profile(article)
        style = request.form.get(
            "character_sheet_style",
            profile.get("art_style", "따뜻한 한국 웹툰 일러스트"),
        ).strip()

        old_filename = article.instatoon_character_sheet
        filename = generate_instatoon_character_sheet(
            article=article,
            profile=profile,
            style=style,
            expression_hint=request.form.get("expression_hint", ""),
        )

        article.instatoon_character_sheet = filename
        db.session.commit()

        if old_filename and old_filename != filename:
            old_file = MEDIA_DIR / old_filename

            if old_file.exists():
                old_file.unlink()

        flash("캐릭터 시트를 만들었습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"캐릭터 시트 생성 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/instatoon/rebuild-captions")
def rebuild_instatoon_captions(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        cuts = get_instatoon_cuts(article)

        raw_map = load_json_map(article.instatoon_images)
        captioned_map = load_json_map(article.instatoon_captioned_images)
        old_captioned_files = []

        for cut_number, cut_text in enumerate(cuts, start=1):
            raw_filename = raw_map.get(str(cut_number))

            if not raw_filename:
                continue

            old_captioned = captioned_map.get(str(cut_number))
            new_captioned = compose_instatoon_text_overlay(
                article=article,
                cut_number=cut_number,
                source_filename=raw_filename,
                cut_text=cut_text,
            )

            captioned_map[str(cut_number)] = new_captioned

            if old_captioned and old_captioned != new_captioned:
                old_captioned_files.append(old_captioned)

        article.instatoon_captioned_images = json.dumps(
            captioned_map,
            ensure_ascii=False,
        )

        db.session.commit()
        delete_replaced_media(*old_captioned_files)
        flash("기존 그림에 한글 대사와 자막을 다시 입혔습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"한글 자막 다시 만들기 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/instatoon/reference-image")
def upload_instatoon_reference_image(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        uploaded_file = request.files.get("reference_image")
        old_filename = article.instatoon_reference_image
        filename = save_reference_image_upload(
            file_storage=uploaded_file,
            article_id=article.id,
        )

        article.instatoon_reference_image = filename
        db.session.commit()

        if old_filename and old_filename != filename:
            old_path = MEDIA_DIR / old_filename

            if old_path.exists():
                old_path.unlink()

        flash(
            "참조 이미지를 저장했습니다. "
            "이제 컷 생성 시 해당 인물의 얼굴과 분위기를 우선 참고합니다."
        )

    except Exception as e:
        db.session.rollback()
        flash(f"참조 이미지 업로드 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/instatoon/reference-image/delete")
def delete_instatoon_reference_image(article_id):
    article = Article.query.get_or_404(article_id)
    old_filename = article.instatoon_reference_image

    article.instatoon_reference_image = None
    db.session.commit()

    if old_filename:
        old_path = MEDIA_DIR / old_filename

        if old_path.exists():
            old_path.unlink()

    flash("참조 이미지를 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/reels/create")
def create_reels_video(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        old_filename = article.reels_path
        filename, settings = make_reels_video(
            article=article,
            seconds_per_cut=request.form.get("seconds_per_cut", "3"),
            fps=request.form.get("fps", "30"),
            transition_seconds=request.form.get("transition_seconds", "0.35"),
            motion_style=request.form.get("motion_style", "교차 줌"),
        )

        article.reels_path = filename
        article.reels_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        db.session.commit()

        if old_filename and old_filename != filename:
            old_path = MEDIA_DIR / old_filename

            if old_path.exists():
                old_path.unlink()

        flash(
            f"릴스 영상 생성 완료! "
            f"{settings.get('cut_count', 0)}컷을 세로형 MP4로 만들었습니다."
        )

    except Exception as e:
        db.session.rollback()
        flash(f"릴스 생성 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/reels/delete")
def delete_reels_video(article_id):
    article = Article.query.get_or_404(article_id)
    old_filename = article.reels_path

    article.reels_path = None
    article.reels_settings = "{}"
    db.session.commit()

    if old_filename:
        old_path = MEDIA_DIR / old_filename

        if old_path.exists():
            old_path.unlink()

    flash("생성된 릴스 영상을 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/instatoon/<int:cut_number>/audio-json")
def generate_instatoon_cut_audio_json(article_id, cut_number):
    article = Article.query.get_or_404(article_id)

    mother_mood = request.form.get("mother_mood", "따뜻하고 자연스럽게")
    daughter_mood = request.form.get("daughter_mood", "밝고 장난스럽게")
    narration_mood = request.form.get("narration_mood", "편안하게 이야기하듯")

    try:
        old_entries, new_entries = generate_cut_audio(
            article=article,
            cut_number=cut_number,
            mother_mood=mother_mood,
            daughter_mood=daughter_mood,
            narration_mood=narration_mood,
        )

        article.instatoon_audio_settings = json.dumps(
            {
                "mother_mood": mother_mood,
                "daughter_mood": daughter_mood,
                "narration_mood": narration_mood,
                "model": TTS_MODEL,
                "mother_voice": TTS_VOICES["mother"],
                "daughter_voice": TTS_VOICES["daughter"],
                "narration_voice": TTS_VOICES["narration"],
            },
            ensure_ascii=False,
        )

        db.session.commit()
        delete_audio_entries(old_entries)

        return {
            "ok": True,
            "cut_number": cut_number,
            "entries": [
                {
                    **entry,
                    "audio_url": url_for(
                        "media",
                        filename=entry["filename"],
                    ),
                }
                for entry in new_entries
            ],
        }

    except Exception as e:
        db.session.rollback()

        return {
            "ok": False,
            "cut_number": cut_number,
            "message": str(e),
        }, 500


@app.post("/articles/<int:article_id>/instatoon/audio/delete")
def delete_instatoon_audio(article_id):
    article = Article.query.get_or_404(article_id)
    audio_map = load_json_map(article.instatoon_audio)

    for entries in audio_map.values():
        delete_audio_entries(entries)

    article.instatoon_audio = "{}"
    article.instatoon_audio_settings = "{}"
    db.session.commit()
    flash("인스타툰 음성을 모두 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/reels/create-with-voice")
def create_reels_video_with_voice(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        old_filename = article.reels_voice_path
        filename, settings = make_voice_reels_video(
            article=article,
            voice_volume=request.form.get("voice_volume", "1.0"),
            cut_duration_override=request.form.get(
                "voice_cut_duration",
                "",
            ),
        )

        article.reels_voice_path = filename
        article.reels_voice_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        db.session.commit()

        if old_filename and old_filename != filename:
            old_path = MEDIA_DIR / old_filename

            if old_path.exists():
                old_path.unlink()

        flash(
            f"음성 포함 릴스 생성 완료! "
            f"{settings.get('cut_count', 0)}컷 음성을 영상에 배치했습니다."
        )

    except Exception as e:
        db.session.rollback()
        flash(f"음성 포함 릴스 생성 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/reels/delete-with-voice")
def delete_reels_video_with_voice(article_id):
    article = Article.query.get_or_404(article_id)
    old_filename = article.reels_voice_path

    article.reels_voice_path = None
    article.reels_voice_settings = "{}"
    db.session.commit()

    if old_filename:
        old_path = MEDIA_DIR / old_filename

        if old_path.exists():
            old_path.unlink()

    flash("음성 포함 릴스 영상을 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/reels/bgm/upload")
def upload_reels_bgm(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        uploaded_file = request.files.get("bgm_file")
        old_filename = article.reels_bgm_path
        filename = save_bgm_upload(
            file_storage=uploaded_file,
            article_id=article.id,
        )

        article.reels_bgm_path = filename
        db.session.commit()

        if old_filename and old_filename != filename:
            old_path = MEDIA_DIR / old_filename

            if old_path.exists():
                old_path.unlink()

        flash("BGM 파일을 저장했습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"BGM 업로드 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/reels/bgm/delete")
def delete_reels_bgm(article_id):
    article = Article.query.get_or_404(article_id)
    old_bgm = article.reels_bgm_path
    old_final = article.reels_final_path

    article.reels_bgm_path = None
    article.reels_final_path = None
    article.reels_final_settings = "{}"
    db.session.commit()

    for filename in [old_bgm, old_final]:
        if not filename:
            continue

        path = MEDIA_DIR / filename

        if path.exists():
            path.unlink()

    flash("BGM과 최종 릴스 파일을 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/reels/create-final")
def create_final_reels_video(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        old_filename = article.reels_final_path
        filename, settings = make_final_reels_with_bgm(
            article=article,
            bgm_volume=request.form.get("bgm_volume", "0.16"),
            voice_volume=request.form.get("final_voice_volume", "1.0"),
            bgm_start_seconds=request.form.get(
                "bgm_start_seconds",
                "0",
            ),
        )

        article.reels_final_path = filename
        article.reels_final_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        db.session.commit()

        if old_filename and old_filename != filename:
            old_path = MEDIA_DIR / old_filename

            if old_path.exists():
                old_path.unlink()

        flash("음성·BGM이 포함된 최종 릴스를 만들었습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"최종 릴스 생성 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/reels/delete-final")
def delete_final_reels_video(article_id):
    article = Article.query.get_or_404(article_id)
    old_filename = article.reels_final_path

    article.reels_final_path = None
    article.reels_final_settings = "{}"
    db.session.commit()

    if old_filename:
        old_path = MEDIA_DIR / old_filename

        if old_path.exists():
            old_path.unlink()

    flash("최종 릴스 영상을 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/export-package/create")
def create_content_export_package(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        old_filename = article.export_package_path
        filename, settings = create_export_package(
            article=article,
            include_raw=request.form.get("include_raw") == "1",
            include_audio=request.form.get("include_audio") == "1",
        )

        article.export_package_path = filename
        article.export_package_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        db.session.commit()

        if old_filename and old_filename != filename:
            old_path = MEDIA_DIR / old_filename

            if old_path.exists():
                old_path.unlink()

        flash("콘텐츠 전체 ZIP 패키지를 만들었습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"ZIP 패키지 생성 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/export-package/delete")
def delete_content_export_package(article_id):
    article = Article.query.get_or_404(article_id)
    old_filename = article.export_package_path

    article.export_package_path = None
    article.export_package_settings = "{}"
    db.session.commit()

    if old_filename:
        old_path = MEDIA_DIR / old_filename

        if old_path.exists():
            old_path.unlink()

    flash("콘텐츠 ZIP 패키지를 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/instatoon/presets/save")
def save_instatoon_preset(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        name = request.form.get("preset_name", "").strip()
        description = request.form.get("preset_description", "").strip()

        if not name:
            raise ValueError("프리셋 이름을 입력해 주세요.")

        profile = get_instatoon_character_profile(article)
        existing = InstatoonPreset.query.filter_by(name=name).first()

        if existing:
            preset = existing
            old_reference = preset.reference_image
            old_sheet = preset.character_sheet
        else:
            preset = InstatoonPreset(name=name)
            db.session.add(preset)
            old_reference = None
            old_sheet = None

        preset.description = description
        preset.profile_json = json.dumps(
            profile,
            ensure_ascii=False,
        )

        copied_reference = copy_media_file(
            article.instatoon_reference_image,
            f"preset_reference_{safe_zip_name(name)}",
        )
        copied_sheet = copy_media_file(
            article.instatoon_character_sheet,
            f"preset_sheet_{safe_zip_name(name)}",
        )

        if copied_reference:
            preset.reference_image = copied_reference

        if copied_sheet:
            preset.character_sheet = copied_sheet

        db.session.commit()

        if copied_reference and old_reference != copied_reference:
            delete_media_if_exists(old_reference)

        if copied_sheet and old_sheet != copied_sheet:
            delete_media_if_exists(old_sheet)

        flash(f"‘{name}’ 프리셋을 저장했습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"프리셋 저장 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/instatoon/presets/<int:preset_id>/apply")
def apply_instatoon_preset(article_id, preset_id):
    article = Article.query.get_or_404(article_id)
    preset = InstatoonPreset.query.get_or_404(preset_id)

    try:
        old_reference = article.instatoon_reference_image
        old_sheet = article.instatoon_character_sheet

        article.instatoon_character_profile = json.dumps(
            preset_profile(preset),
            ensure_ascii=False,
        )

        copied_reference = copy_media_file(
            preset.reference_image,
            f"article_{article.id}_reference_from_preset",
        )
        copied_sheet = copy_media_file(
            preset.character_sheet,
            f"article_{article.id}_sheet_from_preset",
        )

        if copied_reference:
            article.instatoon_reference_image = copied_reference

        if copied_sheet:
            article.instatoon_character_sheet = copied_sheet

        db.session.commit()

        if copied_reference and old_reference != copied_reference:
            delete_media_if_exists(old_reference)

        if copied_sheet and old_sheet != copied_sheet:
            delete_media_if_exists(old_sheet)

        flash(f"‘{preset.name}’ 프리셋을 적용했습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"프리셋 적용 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/instatoon/presets/<int:preset_id>/delete")
def delete_instatoon_preset(article_id, preset_id):
    article = Article.query.get_or_404(article_id)
    preset = InstatoonPreset.query.get_or_404(preset_id)

    reference_filename = preset.reference_image
    sheet_filename = preset.character_sheet
    preset_name = preset.name

    db.session.delete(preset)
    db.session.commit()

    delete_media_if_exists(reference_filename)
    delete_media_if_exists(sheet_filename)

    flash(f"‘{preset_name}’ 프리셋을 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.post("/articles/<int:article_id>/instatoon/director/analyze")
def analyze_instatoon_direction(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        tone = request.form.get("director_tone", "공감형").strip()
        intensity = request.form.get("director_intensity", "보통").strip()

        result = generate_director_revision(
            article=article,
            tone=tone,
            intensity=intensity,
        )

        article.director_report = json.dumps(
            {
                "score": result.get("score", 0),
                "summary": result.get("summary", ""),
                "strengths": result.get("strengths", []),
                "problems": result.get("problems", []),
                "directing_notes": result.get("directing_notes", []),
                "tone": tone,
                "intensity": intensity,
            },
            ensure_ascii=False,
        )
        article.director_revised_instatoon = result.get(
            "revised_instatoon",
            "",
        )

        db.session.commit()
        flash("AI 연출 감독이 8컷을 분석하고 수정안을 만들었습니다.")

    except Exception as e:
        db.session.rollback()
        flash(f"AI 연출 분석 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/instatoon/director/apply")
def apply_instatoon_direction(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        revised = (article.director_revised_instatoon or "").strip()

        if not revised:
            raise ValueError("적용할 연출 수정안이 없습니다.")

        cut_count = len([
            chunk
            for chunk in revised.split("[CUT]")
            if "컷 번호" in chunk
        ])

        if cut_count != 8:
            raise ValueError(
                f"수정안이 정확히 8컷이 아닙니다. 현재 {cut_count}컷입니다."
            )

        replace_instatoon_text(article, revised)

        if request.form.get("clear_generated_assets") == "1":
            clear_instatoon_generated_assets(article)

        db.session.commit()
        flash(
            "AI 연출 수정안을 인스타툰에 적용했습니다. "
            "이미지를 다시 생성하면 새 연출이 반영됩니다."
        )

    except Exception as e:
        db.session.rollback()
        flash(f"연출 수정안 적용 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/instatoon/director/delete")
def delete_instatoon_direction(article_id):
    article = Article.query.get_or_404(article_id)

    article.director_report = "{}"
    article.director_revised_instatoon = ""
    db.session.commit()
    flash("AI 연출 분석 결과를 삭제했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )



@app.get("/articles/<int:article_id>/production/status")
def production_queue_status(article_id):
    article = Article.query.get_or_404(article_id)

    return {
        "ok": True,
        "state": load_json_map(article.production_queue_state),
        "snapshot": production_queue_snapshot(article),
    }


@app.post("/articles/<int:article_id>/production/reels-json")
def production_create_reels_json(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        save_queue_state(article, "reels", "running", "기본 릴스 생성 중")
        db.session.commit()

        old_filename = article.reels_path
        filename, settings = make_reels_video(
            article=article,
            seconds_per_cut=request.form.get("seconds_per_cut", "3"),
            fps=request.form.get("fps", "30"),
            transition_seconds=request.form.get(
                "transition_seconds",
                "0.35",
            ),
            motion_style=request.form.get(
                "motion_style",
                "교차 줌",
            ),
        )

        article.reels_path = filename
        article.reels_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        save_queue_state(article, "reels", "done", "기본 릴스 생성 완료")
        db.session.commit()

        if old_filename and old_filename != filename:
            delete_media_if_exists(old_filename)

        return {
            "ok": True,
            "filename": filename,
            "video_url": url_for("media", filename=filename),
            "snapshot": production_queue_snapshot(article),
        }

    except Exception as e:
        db.session.rollback()
        article = Article.query.get_or_404(article_id)
        save_queue_state(article, "reels", "error", str(e))
        db.session.commit()

        return {
            "ok": False,
            "message": str(e),
        }, 500


@app.post("/articles/<int:article_id>/production/reels-voice-json")
def production_create_voice_reels_json(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        save_queue_state(
            article,
            "reels_voice",
            "running",
            "음성 포함 릴스 생성 중",
        )
        db.session.commit()

        old_filename = article.reels_voice_path
        filename, settings = make_voice_reels_video(
            article=article,
            voice_volume=request.form.get("voice_volume", "1.0"),
            cut_duration_override=request.form.get(
                "voice_cut_duration",
                "",
            ),
        )

        article.reels_voice_path = filename
        article.reels_voice_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        save_queue_state(
            article,
            "reels_voice",
            "done",
            "음성 포함 릴스 생성 완료",
        )
        db.session.commit()

        if old_filename and old_filename != filename:
            delete_media_if_exists(old_filename)

        return {
            "ok": True,
            "filename": filename,
            "video_url": url_for("media", filename=filename),
            "snapshot": production_queue_snapshot(article),
        }

    except Exception as e:
        db.session.rollback()
        article = Article.query.get_or_404(article_id)
        save_queue_state(article, "reels_voice", "error", str(e))
        db.session.commit()

        return {
            "ok": False,
            "message": str(e),
        }, 500


@app.post("/articles/<int:article_id>/production/reels-final-json")
def production_create_final_reels_json(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        if not article.reels_bgm_path:
            return {
                "ok": True,
                "skipped": True,
                "message": "BGM이 없어 최종 마스터링을 건너뜁니다.",
                "snapshot": production_queue_snapshot(article),
            }

        save_queue_state(
            article,
            "reels_final",
            "running",
            "최종 릴스 마스터링 중",
        )
        db.session.commit()

        old_filename = article.reels_final_path
        filename, settings = make_final_reels_with_bgm(
            article=article,
            bgm_volume=request.form.get("bgm_volume", "0.16"),
            voice_volume=request.form.get(
                "final_voice_volume",
                "1.0",
            ),
            bgm_start_seconds=request.form.get(
                "bgm_start_seconds",
                "0",
            ),
        )

        article.reels_final_path = filename
        article.reels_final_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        save_queue_state(
            article,
            "reels_final",
            "done",
            "최종 릴스 마스터링 완료",
        )
        db.session.commit()

        if old_filename and old_filename != filename:
            delete_media_if_exists(old_filename)

        return {
            "ok": True,
            "filename": filename,
            "video_url": url_for("media", filename=filename),
            "snapshot": production_queue_snapshot(article),
        }

    except Exception as e:
        db.session.rollback()
        article = Article.query.get_or_404(article_id)
        save_queue_state(article, "reels_final", "error", str(e))
        db.session.commit()

        return {
            "ok": False,
            "message": str(e),
        }, 500


@app.post("/articles/<int:article_id>/production/export-json")
def production_create_export_json(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        save_queue_state(article, "zip", "running", "ZIP 패키지 생성 중")
        db.session.commit()

        old_filename = article.export_package_path
        filename, settings = create_export_package(
            article=article,
            include_raw=request.form.get("include_raw", "1") == "1",
            include_audio=request.form.get("include_audio", "1") == "1",
        )

        article.export_package_path = filename
        article.export_package_settings = json.dumps(
            settings,
            ensure_ascii=False,
        )
        save_queue_state(article, "zip", "done", "ZIP 패키지 생성 완료")
        db.session.commit()

        if old_filename and old_filename != filename:
            delete_media_if_exists(old_filename)

        return {
            "ok": True,
            "filename": filename,
            "download_url": url_for("media", filename=filename),
            "snapshot": production_queue_snapshot(article),
        }

    except Exception as e:
        db.session.rollback()
        article = Article.query.get_or_404(article_id)
        save_queue_state(article, "zip", "error", str(e))
        db.session.commit()

        return {
            "ok": False,
            "message": str(e),
        }, 500


@app.post("/articles/<int:article_id>/production/reset")
def reset_production_queue(article_id):
    article = Article.query.get_or_404(article_id)
    article.production_queue_state = "{}"
    db.session.commit()
    flash("원클릭 제작 진행 기록을 초기화했습니다.")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )


@app.post("/articles/<int:article_id>/pipeline")
def run_pipeline(article_id):
    article = Article.query.get_or_404(article_id)

    try:
        article.seo_score, report = analyze_seo(article)
        article.seo_report = json.dumps(report, ensure_ascii=False)

        social = generate_social_pack(article)

        article.instagram_caption = social.get("instagram_caption", "")
        article.threads_text = social.get("threads_text", "")
        article.shorts_script = social.get("shorts_script", "")
        article.youtube_title = social.get("youtube_title", "")
        article.youtube_description = social.get("youtube_description", "")
        article.youtube_tags = social.get("youtube_tags", "")
        article.tiktok_caption = social.get("tiktok_caption", "")

        replace_instatoon_text(article, social.get("instatoon", ""))

        article.thumbnail_text = social.get(
            "thumbnail_text",
            article.thumbnail_text or article.title,
        )

        style = request.form.get(
            "thumbnail_style",
            "따뜻한 생활 사진",
        )
        thumbnail_text = article.thumbnail_text or article.title
        old_path = article.thumbnail_path

        article.thumbnail_path = generate_thumbnail(
            article,
            style,
            thumbnail_text,
        )
        article.thumbnail_text = thumbnail_text

        db.session.commit()

        if old_path and old_path != article.thumbnail_path:
            old_file = MEDIA_DIR / old_path
            if old_file.exists():
                old_file.unlink()

        flash(
            "AI 콘텐츠 파이프라인이 완료됐어요. "
            "블로그, SNS, 인스타툰, 썸네일까지 준비했습니다."
        )

    except Exception as e:
        db.session.rollback()
        flash(f"파이프라인 실행 실패: {e}")

    return redirect(
        url_for("edit_article", article_id=article.id)
        + "#instatoon"
    )

@app.post("/articles/<int:article_id>/instatoon/<int:cut_number>/image")
def generate_instatoon_cut_image(article_id, cut_number):
    article = Article.query.get_or_404(article_id)
    try:
        cuts = get_instatoon_cuts(article)
        if cut_number < 1 or cut_number > len(cuts):
            raise ValueError("선택한 인스타툰 컷을 찾을 수 없습니다.")
        style=request.form.get("instatoon_style","따뜻한 한국 웹툰 일러스트")
        cut_text=cuts[cut_number-1]
        filename=generate_instatoon_image(article=article,cut_number=cut_number,cut_text=cut_text,style=style)
        versions=save_instatoon_image_versions(article=article,cut_number=cut_number,raw_filename=filename,cut_text=cut_text)
        db.session.commit()
        delete_replaced_media(versions["old_raw"] if versions["old_raw"]!=versions["raw_filename"] else None,versions["old_captioned"] if versions["old_captioned"]!=versions["captioned_filename"] else None)
        flash(f"인스타툰 {cut_number}컷 이미지를 만들었습니다.")
    except Exception as e:
        db.session.rollback(); flash(f"인스타툰 이미지 생성 실패: {e}")
    return redirect(url_for("edit_article",article_id=article.id)+"#instatoon")


@app.post("/articles/<int:article_id>/instatoon/all")
def generate_all_instatoon_images(article_id):
    article=Article.query.get_or_404(article_id)
    try:
        cuts=get_instatoon_cuts(article)
        if len(cuts)!=8:
            raise ValueError(f"인스타툰은 정확히 8컷이어야 합니다. 현재 {len(cuts)}컷입니다.")
        style=request.form.get("instatoon_style","따뜻한 한국 웹툰 일러스트")
        replaced=[]
        for number,cut_text in enumerate(cuts,start=1):
            filename=generate_instatoon_image(article=article,cut_number=number,cut_text=cut_text,style=style)
            versions=save_instatoon_image_versions(article=article,cut_number=number,raw_filename=filename,cut_text=cut_text)
            replaced += [versions["old_raw"] if versions["old_raw"]!=versions["raw_filename"] else None,versions["old_captioned"] if versions["old_captioned"]!=versions["captioned_filename"] else None]
        db.session.commit(); delete_replaced_media(*replaced); flash("인스타툰 8컷 이미지 생성을 완료했습니다.")
    except Exception as e:
        db.session.rollback(); flash(f"인스타툰 전체 이미지 생성 실패: {e}")
    return redirect(url_for("edit_article",article_id=article.id)+"#instatoon")


@app.post("/articles/<int:article_id>/instatoon/<int:cut_number>/image-json")
def generate_instatoon_cut_image_json(article_id,cut_number):
    article=Article.query.get_or_404(article_id)
    try:
        cuts=get_instatoon_cuts(article)
        if cut_number<1 or cut_number>len(cuts):
            return {"ok":False,"message":"선택한 인스타툰 컷을 찾을 수 없습니다."},400
        style=request.form.get("instatoon_style","따뜻한 한국 웹툰 일러스트")
        cut_text=cuts[cut_number-1]
        filename=generate_instatoon_image(article=article,cut_number=cut_number,cut_text=cut_text,style=style)
        versions=save_instatoon_image_versions(article=article,cut_number=cut_number,raw_filename=filename,cut_text=cut_text)
        db.session.commit()
        delete_replaced_media(versions["old_raw"] if versions["old_raw"]!=versions["raw_filename"] else None,versions["old_captioned"] if versions["old_captioned"]!=versions["captioned_filename"] else None)
        return {"ok":True,"cut_number":cut_number,"filename":filename,"image_url":url_for("media",filename=filename),"captioned_filename":versions["captioned_filename"],"captioned_image_url":url_for("media",filename=versions["captioned_filename"])}
    except Exception as e:
        db.session.rollback(); return {"ok":False,"cut_number":cut_number,"message":str(e)},500


@app.post("/articles/<int:article_id>/checklist")
def save_checklist(article_id):
    article = Article.query.get_or_404(article_id)
    article.blog_done = request.form.get("blog_done") == "1"
    article.instagram_done = request.form.get("instagram_done") == "1"
    article.threads_done = request.form.get("threads_done") == "1"
    article.shorts_done = request.form.get("shorts_done") == "1"
    db.session.commit()
    flash("업로드 체크리스트를 저장했습니다.")
    return redirect(url_for("edit_article", article_id=article.id))


@app.route("/ideas", methods=["GET", "POST"])
def idea_lab():
    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        count = request.form.get("count", "12")
        if not topic:
            flash("아이디어를 만들 주제를 입력해 주세요.")
            return redirect(url_for("idea_lab"))
        try:
            ideas = generate_content_ideas(topic, count)
            saved = 0
            for item in ideas:
                title = str(item.get("title", "")).strip()
                if not title:
                    continue
                db.session.add(ContentIdea(
                    topic=topic,
                    title=title[:300],
                    hook=str(item.get("hook", "")).strip(),
                    format_type=str(item.get("format_type", "블로그")).strip()[:80],
                ))
                saved += 1
            db.session.commit()
            flash(f"{saved}개의 콘텐츠 아이디어를 만들었습니다.")
        except Exception as e:
            db.session.rollback()
            flash(f"아이디어 생성 실패: {e}")
        return redirect(url_for("idea_lab"))

    ideas = ContentIdea.query.order_by(ContentIdea.created_at.desc()).limit(100).all()
    return page("""
<div class="card">
<a href="{{url_for('home')}}">← 홈으로</a>
<h1 style="margin-top:14px">AI 아이디어 연구소</h1>
<p class="lead">주제 하나를 넣으면 블로그, 인스타툰, 릴스, Threads용 소재를 한 꾸러미로 만듭니다.</p>
<form method="post">
<div class="grid">
<div><label>주제</label><input name="topic" required placeholder="예: 말썽쟁이 딸 현실 육아"></div>
<div><label>아이디어 개수</label><select name="count"><option value="8">8개</option><option value="12" selected>12개</option><option value="20">20개</option><option value="30">30개</option></select></div>
</div>
<div class="actions"><button class="btn" type="submit">AI 아이디어 생성</button></div>
</form>
</div>

<section class="card">
<h2>저장된 아이디어</h2>
{% if ideas %}
{% for idea in ideas %}
<div class="idea-card">
<span class="tag">{{idea.format_type}}</span>
<h3>{{idea.title}}</h3>
<p>{{idea.hook}}</p>
<div class="small">{{idea.topic}} · {{idea.created_at.strftime('%Y-%m-%d %H:%M')}}</div>
<form method="post" action="{{url_for('idea_to_article',idea_id=idea.id)}}" style="margin-top:10px">
<div class="actions"><button class="btn gray" type="submit">이 아이디어로 AI 글 만들기</button></div>
</form>
</div>
{% endfor %}
{% else %}
<p class="small">아직 저장된 아이디어가 없습니다.</p>
{% endif %}
</section>
""", ideas=ideas, page_title="AI 아이디어 연구소 | MI Creator OS")


@app.post("/ideas/<int:idea_id>/article")
def idea_to_article(idea_id):
    idea = ContentIdea.query.get_or_404(idea_id)
    try:
        data = generate_article(
            idea.title,
            "육아·생활",
            "스토리형" if idea.format_type in {"인스타툰", "릴스/쇼츠"} else "정보형",
            "약 2,500자",
            "일반 독자",
            f"콘텐츠 훅: {idea.hook}",
        )
        tags = data.get("tags", [])
        if isinstance(tags, list):
            tags = ",".join(str(x).strip().lstrip("#") for x in tags if str(x).strip())
        article = Article(
            keyword=idea.title,
            title=data.get("title", idea.title),
            meta_description=data.get("meta_description", ""),
            body_html=data.get("body_html", ""),
            brand_style="육아·생활",
            article_type="스토리형" if idea.format_type in {"인스타툰", "릴스/쇼츠"} else "정보형",
            notes=f"아이디어 훅: {idea.hook}",
            tags=tags,
        )
        db.session.add(article)
        db.session.flush()
        article.seo_score, report = analyze_seo(article)
        article.seo_report = json.dumps(report, ensure_ascii=False)
        idea.status = "글 생성"
        db.session.commit()
        flash("선택한 아이디어로 AI 글을 만들었습니다.")
        return redirect(url_for("edit_article", article_id=article.id))
    except Exception as e:
        db.session.rollback()
        flash(f"글 생성 실패: {e}")
        return redirect(url_for("idea_lab"))


@app.get("/articles/<int:article_id>/monetization/coupang-search")
def coupang_product_search(article_id):
    Article.query.get_or_404(article_id)  # 존재하지 않는 글이면 404

    if not coupang_api_configured():
        return jsonify({
            "ok": False,
            "message": (
                "쿠팡파트너스 API 키가 아직 설정되지 않았어요. "
                "환경변수에 COUPANG_ACCESS_KEY, COUPANG_SECRET_KEY를 "
                "등록하면 이 검색 기능을 쓸 수 있어요."
            ),
            "results": [],
        })

    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"ok": False, "message": "검색어를 입력해 주세요.", "results": []})

    results = coupang_search_products(keyword)
    if not results:
        return jsonify({
            "ok": False,
            "message": (
                "검색 결과가 없거나 API 호출에 실패했어요. "
                "(API 키 승인 조건 미충족이거나, 시간당 호출 제한 초과일 수 있어요.)"
            ),
            "results": [],
        })

    return jsonify({"ok": True, "message": "", "results": results})


@app.post("/articles/<int:article_id>/monetization")
def save_monetization(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        article.coupang_product_name = request.form.get("coupang_product_name", "").strip()[:300]
        article.coupang_link = valid_public_url(request.form.get("coupang_link", ""))
        article.atomy_product_name = request.form.get("atomy_product_name", "").strip()[:300]
        article.atomy_link = valid_public_url(request.form.get("atomy_link", ""))
        article.toss_product_name = request.form.get("toss_product_name", "").strip()[:300]
        article.toss_link = valid_public_url(request.form.get("toss_link", ""))
        article.affiliate_enabled = request.form.get("affiliate_enabled") == "1"

        if bool(article.coupang_product_name) != bool(article.coupang_link):
            raise ValueError("쿠팡 상품명과 링크는 둘 다 입력하거나 둘 다 비워주세요.")
        if bool(article.atomy_product_name) != bool(article.atomy_link):
            raise ValueError("애터미 상품명과 링크는 둘 다 입력하거나 둘 다 비워주세요.")
        if bool(article.toss_product_name) != bool(article.toss_link):
            raise ValueError("토스쇼핑 상품명과 링크는 둘 다 입력하거나 둘 다 비워주세요.")

        article.affiliate_html = build_affiliate_html(article)
        if article.affiliate_enabled and not article.affiliate_html:
            raise ValueError("추천 영역을 포함하려면 상품명과 링크를 한 세트 이상 입력해 주세요.")

        db.session.commit()
        flash("수익화 링크와 제휴 고지 설정을 저장했어요.")
    except Exception as e:
        db.session.rollback()
        flash(f"수익화 설정 저장 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.post("/articles/<int:article_id>/thumbnail")
def generate_thumbnail_route(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        text = request.form.get("thumbnail_text", article.title).strip()[:45]
        style = request.form.get("thumbnail_style", "따뜻한 생활 사진")
        old_path = article.thumbnail_path
        filename = generate_thumbnail(article, style, text)
        article.thumbnail_path = filename
        article.thumbnail_text = text
        db.session.commit()
        if old_path and old_path != filename:
            old_file = MEDIA_DIR / old_path
            if old_file.exists():
                old_file.unlink()
        flash("AI 썸네일이 완성됐어요.")
    except Exception as e:
        db.session.rollback()
        flash(f"썸네일 생성 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.post("/articles/<int:article_id>/fortune-card")
def generate_fortune_card_route(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        old_paths = []
        if article.fortune_card_paths:
            try:
                old_paths = json.loads(article.fortune_card_paths)
            except json.JSONDecodeError:
                old_paths = []

        filenames = generate_fortune_carousel(article)
        article.fortune_card_paths = json.dumps(filenames, ensure_ascii=False)
        article.fortune_card_path = filenames[0]  # 대표 이미지(호환용)
        db.session.commit()

        for old_path in old_paths:
            if old_path not in filenames:
                old_file = MEDIA_DIR / old_path
                if old_file.exists():
                    old_file.unlink()

        flash(f"운세 카드뉴스 {len(filenames)}장을 만들었어요. SNS 탭에서 다운로드하실 수 있어요.")
    except Exception as e:
        db.session.rollback()
        flash(f"운세 카드 생성 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.post("/articles/<int:article_id>/fortune-reel")
def generate_fortune_reel_route(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        filenames = json.loads(article.fortune_card_paths or "[]")
    except json.JSONDecodeError:
        filenames = []

    if not filenames:
        flash("먼저 위에서 운세 카드뉴스(7장)를 만들어 주세요.")
        return redirect(url_for("edit_article", article_id=article.id))

    try:
        old_path = article.fortune_reel_path
        video_filename = generate_fortune_reel_video(article, filenames)
        article.fortune_reel_path = video_filename
        db.session.commit()
        if old_path and old_path != video_filename:
            old_file = MEDIA_DIR / old_path
            if old_file.exists():
                old_file.unlink()
        flash("릴스용 영상을 만들었어요. 다운로드하거나 바로 공유해보세요.")
    except Exception as e:
        db.session.rollback()
        flash(f"릴스 영상 생성 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.get("/media/<path:filename>")
def media(filename):
    return send_from_directory(MEDIA_DIR, filename)


@app.get("/media/<path:filename>/download")
def media_download(filename):
    return send_from_directory(MEDIA_DIR, filename, as_attachment=True)


@app.get("/google/connect")
def google_connect():
    try:
        flow = Flow.from_client_config(
            google_client_config(),
            scopes=GOOGLE_SCOPES,
            redirect_uri="https://ai-blog-factory.onrender.com/oauth2callback",
            autogenerate_code_verifier=True,
        )

        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account consent",
        )

        # 구글 로그인 후 다시 확인할 값 저장
        session["oauth_state"] = state
        session["oauth_code_verifier"] = flow.code_verifier

        return redirect(authorization_url)

    except Exception as e:
        flash(f"Google 연결 준비 실패: {e}")
        return redirect(url_for("home"))


@app.get("/oauth2callback")
def google_callback():
    try:
        oauth_state = session.get("oauth_state")
        code_verifier = session.get("oauth_code_verifier")

        if not oauth_state:
            raise RuntimeError(
                "Google 로그인 정보가 만료됐습니다. Google 연결 버튼을 다시 눌러주세요."
            )

        if not code_verifier:
            raise RuntimeError(
                "Google 인증 확인키가 없습니다. Google 연결 버튼을 다시 눌러주세요."
            )

        flow = Flow.from_client_config(
            google_client_config(),
            scopes=GOOGLE_SCOPES,
            state=oauth_state,
            redirect_uri="https://ai-blog-factory.onrender.com/oauth2callback",
            code_verifier=code_verifier,
        )

        flow.fetch_token(authorization_response=request.url)

        creds = flow.credentials
        set_setting("google_credentials", creds.to_json())

        # 연결이 끝났으므로 임시 인증값 삭제
        session.pop("oauth_state", None)
        session.pop("oauth_code_verifier", None)

        flash("Google Blogger 연결이 완료됐어요.")

    except Exception as e:
        session.pop("oauth_state", None)
        session.pop("oauth_code_verifier", None)
        flash(f"Google 연결 실패: {e}")

    return redirect(url_for("home"))


@app.get("/google/change-account")
def google_change_account():
    row = AppSetting.query.filter_by(
        setting_key="google_credentials"
    ).first()

    if row:
        db.session.delete(row)
        db.session.commit()

    session.pop("oauth_state", None)
    session.pop("oauth_code_verifier", None)

    flash("기존 Google 연결을 해제했습니다. 사용할 계정을 다시 선택해 주세요.")
    return redirect(url_for("google_connect"))


@app.get("/google/disconnect")
def google_disconnect():
    row = AppSetting.query.filter_by(
        setting_key="google_credentials"
    ).first()

    if row:
        db.session.delete(row)
        db.session.commit()

    session.pop("oauth_state", None)
    session.pop("oauth_code_verifier", None)

    flash("Google 연결을 해제했습니다.")
    return redirect(url_for("home"))


@app.post("/articles/<int:article_id>/blogger")
def publish_blogger(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        blog_id = request.form["blog_id"]
        mode = request.form.get("mode", "draft")
        action = upsert_blogger_post(article, blog_id, mode)
        flash(f"Blogger {action}이 완료됐어요. 상태: {article.blogger_status}")
    except Exception as e:
        db.session.rollback()
        try:
            add_publish_log(article, "Blogger 발행", "실패", str(e))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f"Blogger 발행 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.post("/articles/<int:article_id>/social")
def generate_social_route(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        data = generate_social_pack(article)
        article.instagram_caption = data.get("instagram_caption", "")
        article.threads_text = data.get("threads_text", "")
        article.shorts_script = data.get("shorts_script", "")
        article.youtube_title = data.get("youtube_title", "")
        article.youtube_description = data.get("youtube_description", "")
        article.youtube_tags = data.get("youtube_tags", "")
        article.tiktok_caption = data.get("tiktok_caption", "")
        db.session.commit()
        flash("인스타그램, Threads, 유튜브, 틱톡, 쇼츠용 콘텐츠를 만들었어요.")
    except Exception as e:
        db.session.rollback()
        flash(f"SNS 콘텐츠 생성 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.post("/articles/<int:article_id>/publish-instagram")
def publish_instagram_route(article_id):
    article = Article.query.get_or_404(article_id)

    if not article.instagram_caption:
        flash("먼저 인스타그램 캡션을 생성해 주세요.")
        return redirect(url_for("edit_article", article_id=article.id))

    # 게시할 이미지를 고릅니다: 썸네일이 있으면 썸네일, 없으면 인스타툰
    # 1컷(글씨 있는 버전)을 사용합니다.
    image_filename = article.fortune_card_path or article.thumbnail_path
    if not image_filename and article.instatoon_captioned_images:
        try:
            images_map = json.loads(article.instatoon_captioned_images)
            image_filename = images_map.get("1") or next(iter(images_map.values()), None)
        except (json.JSONDecodeError, TypeError):
            image_filename = None

    if not image_filename:
        flash("게시할 이미지가 없어요. 썸네일이나 인스타툰 이미지를 먼저 만들어 주세요.")
        return redirect(url_for("edit_article", article_id=article.id))

    # 실제로 서버 디스크에 그 파일이 있는지 먼저 확인합니다. Render는
    # 재배포될 때 이전에 만든 이미지 파일이 사라질 수 있어서, 여기서
    # 미리 걸러내면 "사진이 아니다"라는 헷갈리는 에러 대신 정확한
    # 원인을 바로 알려줄 수 있습니다.
    if not (MEDIA_DIR / image_filename).exists():
        flash(
            f"게시하려던 이미지 파일이 서버에 없어요 ({image_filename}). "
            "Render가 재배포되면서 예전 이미지가 사라졌을 수 있어요. "
            "썸네일이나 인스타툰 이미지를 다시 만든 뒤 시도해 주세요."
        )
        return redirect(url_for("edit_article", article_id=article.id))

    # 인스타그램이 큰 PNG 파일을 못 가져가는 경우가 종종 있어서, 보내기
    # 직전에 용량 작은 JPG로 한 번 변환합니다(원본 파일은 그대로 둡니다).
    try:
        with Image.open(MEDIA_DIR / image_filename) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            jpg_filename = f"instagram_ready_{article.id}.jpg"
            img.save(MEDIA_DIR / jpg_filename, "JPEG", quality=85, optimize=True)
        image_filename = jpg_filename
    except Exception as e:
        flash(f"이미지 변환 실패: {e}")
        return redirect(url_for("edit_article", article_id=article.id))

    image_url = url_for("media", filename=image_filename, _external=True)

    try:
        media_id = publish_to_instagram(image_url, article.instagram_caption)
        add_publish_log(article, "인스타그램 게시", "성공", f"media_id={media_id}")
        db.session.commit()
        flash("인스타그램에 게시했어요! 몇 분 안에 실제 게시물이 보일 거예요.")
    except Exception as e:
        try:
            add_publish_log(article, "인스타그램 게시", "실패", str(e))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f"인스타그램 게시 실패: {e} (사용한 이미지 주소: {image_url})")

    return redirect(url_for("edit_article", article_id=article.id))


@app.post("/articles/<int:article_id>/schedule")
def schedule_blogger(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        scheduled_at = parse_local_datetime(request.form.get("scheduled_at"))
        if not scheduled_at or scheduled_at <= now_kst_naive():
            raise RuntimeError("현재 시간보다 뒤의 예약 시간을 선택해 주세요.")
        article.scheduled_at = scheduled_at
        article.blogger_blog_id = request.form["blog_id"]
        article.blogger_status = "Blogger 예약"
        add_publish_log(article, "예약 등록", "성공", scheduled_at.strftime('%Y-%m-%d %H:%M'))
        db.session.commit()
        flash(f"{scheduled_at.strftime('%Y-%m-%d %H:%M')} 공개 발행으로 예약했어요.")
    except Exception as e:
        db.session.rollback()
        flash(f"예약 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.post("/articles/<int:article_id>/schedule/cancel")
def cancel_schedule(article_id):
    article = Article.query.get_or_404(article_id)
    article.scheduled_at = None
    article.blogger_status = "Blogger 공개" if article.blogger_url else None
    add_publish_log(article, "예약 취소", "성공", "예약을 취소했습니다.")
    db.session.commit()
    flash("예약을 취소했어요.")
    return redirect(url_for("edit_article", article_id=article.id))


@app.route("/tasks/publish-due", methods=["GET", "POST"])
def publish_due_articles():
    expected = os.getenv("CRON_SECRET", "")
    supplied = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        return {"ok": False, "error": "unauthorized"}, 401

    due = Article.query.filter(
        Article.scheduled_at.isnot(None),
        Article.scheduled_at <= now_kst_naive(),
    ).all()

    published = []
    failed = []
    for article in due:
        try:
            upsert_blogger_post(article, article.blogger_blog_id, "publish")
            published.append(article.id)
        except Exception as e:
            db.session.rollback()
            try:
                add_publish_log(article, "예약 발행", "실패", str(e))
                db.session.commit()
            except Exception:
                db.session.rollback()
            failed.append({"id": article.id, "error": str(e)})

    return {"ok": True, "published": published, "failed": failed}


# 매일 아침 자동으로 "오늘의 운세" 글 + SNS 콘텐츠를 만들어주는 작업입니다.
# /tasks/publish-due 와 완전히 같은 방식(CRON_SECRET)으로 보호되어 있어요.
# 매일 안 겹치게, 요일별로 다른 주제를 순서대로 돌려씁니다.
FORTUNE_DAILY_TOPICS = [
    "오늘의 12띠 운세 총정리",
    "오늘의 별자리 운세",
    "이번 주 재물운 좋은 띠 TOP3",
    "오늘 연애운 좋은 별자리",
    "오늘 조심해야 할 띠 운세",
    "오늘의 행운의 컬러와 아이템",
    "오늘 인간관계운이 좋은 별자리",
]


def create_daily_fortune_article(custom_brief=None):
    """오늘의 운세 글 + SNS 콘텐츠(캡션)까지 만들어서 저장합니다.
    수동 버튼과 매일 아침 자동 크론 작업이 이 함수를 같이 씁니다.

    custom_brief가 있으면(사장님이 미리 써둔 요일별 대본을 붙여넣은
    경우) 그 내용을 최대한 그대로 반영해서 글을 씁니다. 없으면 기존
    방식대로 요일 순환 주제를 자동으로 고릅니다."""
    today = datetime.utcnow().date()
    custom_brief = (custom_brief or "").strip()

    if custom_brief:
        topic = custom_brief.splitlines()[0][:60]
        keyword = f"{today.strftime('%Y-%m-%d')} {topic}"
        notes = (
            "아래는 오늘 이 운세 콘텐츠에 반드시 반영해야 하는 기획안입니다. "
            "여기 적힌 훅 문구, 특정 띠, 순위(TOP3), 핵심 메시지, CTA를 "
            "다른 주제로 바꾸지 말고 최대한 그대로 살려서 글과 카드 문구의 "
            "톤을 맞추세요.\n\n"
            f"{custom_brief}"
        )
    else:
        topic = FORTUNE_DAILY_TOPICS[today.toordinal() % len(FORTUNE_DAILY_TOPICS)]
        keyword = f"{today.strftime('%Y-%m-%d')} {topic}"
        notes = (
            "재미로 보는 오늘의 운세 콘텐츠. 특정 개인을 지목하지 않고 "
            "띠·별자리 등 일반적인 기준으로 작성한다. 의학적·재정적 확정 "
            "조언처럼 들리지 않게 하고, 글 마지막에 '재미로 보는 콘텐츠입니다' "
            "같은 안내를 자연스럽게 넣는다. 근거 없는 특정 수치(로또 번호, "
            "정확한 금액 등)는 만들어내지 않는다."
        )

    data = generate_article(
        keyword=keyword,
        brand_style="운세·라이프스타일",
        article_type="정보형",
        length="약 1,500자",
        audience="매일 아침 오늘의 운세를 가볍게 확인하고 싶은 사람",
        notes=notes,
    )

    tags = data.get("tags", [])
    if isinstance(tags, list):
        tags = ",".join(str(t).strip().lstrip("#") for t in tags if str(t).strip())

    article = Article(
        keyword=keyword,
        title=data.get("title", keyword),
        meta_description=data.get("meta_description", ""),
        body_html=data.get("body_html", ""),
        brand_style="운세·라이프스타일",
        article_type="정보형",
        audience="매일 아침 오늘의 운세를 가볍게 확인하고 싶은 사람",
        tags=tags,
    )
    db.session.add(article)
    db.session.flush()

    article.seo_score, report = analyze_seo(article)
    article.seo_report = json.dumps(report, ensure_ascii=False)

    social = generate_social_pack(article)
    article.instagram_caption = social.get("instagram_caption", "")
    article.threads_text = social.get("threads_text", "")
    article.shorts_script = social.get("shorts_script", "")
    article.youtube_title = social.get("youtube_title", "")
    article.youtube_description = social.get("youtube_description", "")
    article.youtube_tags = social.get("youtube_tags", "")
    article.tiktok_caption = social.get("tiktok_caption", "")

    db.session.commit()
    return article, topic


@app.route("/tasks/generate-daily-fortune", methods=["GET", "POST"])
def generate_daily_fortune():
    expected = os.getenv("CRON_SECRET", "")
    supplied = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        return {"ok": False, "error": "unauthorized"}, 401

    try:
        article, topic = create_daily_fortune_article()
        return {"ok": True, "article_id": article.id, "title": article.title, "topic": topic}
    except Exception as e:
        db.session.rollback()
        return {"ok": False, "error": str(e)}, 500


@app.get("/fortune-quick/")
def fortune_quick_page():
    recent = (
        Article.query.filter_by(brand_style="운세·라이프스타일")
        .order_by(Article.created_at.desc())
        .limit(8)
        .all()
    )
    icons_ready = all((MEDIA_DIR / f"zodiac_icon_{a}.png").exists() for a in ZODIAC_ANIMALS)
    return page("""
<section class="card">
  <h1>🔮 오늘의 운세 한 번에 만들기</h1>
  <p class="lead">
    버튼 하나로 오늘의 운세 글, 운세 카드뉴스 7장, 인스타·Threads·
    유튜브·틱톡용 캡션까지 전부 자동으로 만들어요. 시간이 걸리는
    작업이라 3단계로 나눠서 진행해요 — 이 화면에서 진행 상황이
    보여요. 완료되면 자동으로 결과 화면으로 이동해요.
  </p>
  <div class="notice" id="fortune_quick_status">
    {% if icons_ready %}
      준비 완료! 버튼을 누르면 보통 40초~1분 정도 걸려요.
    {% else %}
      처음 실행하는 거면 띠 아이콘 12개를 새로 만드느라 좀 더 걸려요
      (1~2분). 한 번 만들어두면 다음부터는 훨씬 빨라져요.
    {% endif %}
  </div>
  <label for="fortune_quick_brief" style="display:block;margin-top:16px;font-weight:600">
    오늘 반영할 대본 (선택)
  </label>
  <p class="small" style="margin-top:4px">
    미리 준비한 요일별 대본을 그대로 붙여넣으면 그 내용을 반영해서
    만들어요. <strong>"N위 OO띠 - 이유"</strong> 형식이 들어있으면
    12지신 전부가 아니라 그 순위만 크게 보여주는 빨강·블랙 톤의
    임팩트형 카드로 만들어져요. 비워두면 자동으로 주제를 골라서
    기존 방식(12지신 전체)으로 만들어요.
  </p>
  <textarea id="fortune_quick_brief" rows="6" style="width:100%;padding:10px;font-size:15px;box-sizing:border-box"
    placeholder="예) 오늘 통장에 돈 들어오는 띠, 지금 바로 확인하세요&#10;1위 뱀띠 - 예상치 못한 부수입&#10;2위 원숭이띠 - 미뤄뒀던 정산금 성사&#10;3위 돼지띠 - 귀인의 도움으로 재물운 상승&#10;저장하고 내일 운세도 받아가세요"></textarea>
  <button class="btn" id="fortune_quick_btn" type="button" style="width:100%;padding:18px;font-size:17px;margin-top:14px" onclick="runFortuneQuick()">🔮 오늘의 운세 만들기</button>
</section>

<section class="card">
  <h2>최근에 만든 운세 콘텐츠</h2>
  {% if recent %}
    {% for article in recent %}
    <div class="calendar-item">
      <strong>{{ article.title }}</strong>
      <div class="small">{{ article.created_at.strftime('%Y-%m-%d %H:%M') }}</div>
      <a class="btn gray" style="margin-top:8px" href="{{ url_for('edit_article', article_id=article.id) }}">열어서 공유하기</a>
    </div>
    {% endfor %}
  {% else %}
    <p class="small">아직 만든 운세 콘텐츠가 없어요.</p>
  {% endif %}
</section>

<script>
window.addEventListener('error', function(e){
  alert('페이지 스크립트 오류: ' + e.message + ' (파일: ' + e.filename + ', 줄: ' + e.lineno + ')');
});

let fortuneQuickTimer = null;
let fortuneQuickStartedAt = null;

function fortuneQuickSetStep(text){
  const status = document.getElementById('fortune_quick_status');
  const elapsed = fortuneQuickStartedAt ? Math.floor((Date.now() - fortuneQuickStartedAt) / 1000) : 0;
  status.innerHTML = `<span class="spin">⏳</span> ${text} <b>(경과 ${elapsed}초, 멈춘 게 아니라 실제로 돌아가는 중이에요)</b>`;
}

async function safeFetchJson(url, options, stepLabel) {
  const startedAt = Date.now();
  let res;
  try {
    res = await fetch(url, options);
  } catch (networkErr) {
    // fetch 자체가 실패(네트워크 끊김, 서버가 아예 연결을 끊어버림 등)
    throw new Error(`[${stepLabel}] 네트워크 오류로 서버에 연결이 끊겼어요 (${Math.floor((Date.now()-startedAt)/1000)}초 경과): ${networkErr.message}`);
  }
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (parseErr) {
    // JSON이 아니라는 건 Flask 코드가 실행되기도 전에 Render 서버
    // 자체가 먼저 끊어버렸다는 뜻입니다(대부분 처리 시간 초과). 어느
    // 단계에서, 몇 초 만에, 어떤 상태코드로 끊겼는지 정확히 보여줘서
    // 다음에 원인을 바로 찾을 수 있게 합니다.
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    const preview = text.slice(0, 120).split(/[\\n\\t ]+/).join(' ');
    throw new Error(`[${stepLabel}] 서버가 JSON 대신 다른 응답을 보냈어요 (상태코드 ${res.status}, ${elapsed}초 경과). 응답 미리보기: ${preview}`);
  }
  return data;
}

async function runFortuneQuick(){
  const btn = document.getElementById('fortune_quick_btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin">⏳</span> 처리 중이에요...';
  fortuneQuickStartedAt = Date.now();
  fortuneQuickTimer = setInterval(() => fortuneQuickSetStep(window.__fortuneQuickCurrentStep || '준비 중...'), 1000);

  try {
    window.__fortuneQuickCurrentStep = '1/3 띠 아이콘 목록 확인 중...';
    fortuneQuickSetStep(window.__fortuneQuickCurrentStep);
    const d1 = await safeFetchJson("{{ url_for('fortune_quick_step_icons') }}", {method:'POST'}, '1/3 아이콘 목록');
    if(!d1.ok) throw new Error(d1.error || '아이콘 준비 실패');

    for (let i = 0; i < d1.animals.length; i++) {
      const animal = d1.animals[i];
      window.__fortuneQuickCurrentStep = `1/3 띠 아이콘 준비 중... (${i+1}/${d1.animals.length}: ${animal}띠)`;
      fortuneQuickSetStep(window.__fortuneQuickCurrentStep);
      const di = await safeFetchJson(`/fortune-quick/step-icon/${encodeURIComponent(animal)}`, {method:'POST'}, `1/3 ${animal}띠 아이콘`);
      if(!di.ok) throw new Error(di.error || `${animal}띠 아이콘 생성 실패`);
    }

    window.__fortuneQuickCurrentStep = '2/3 글과 캡션 만드는 중...';
    fortuneQuickSetStep(window.__fortuneQuickCurrentStep);
    const briefText = (document.getElementById('fortune_quick_brief').value || '').trim();
    const d2 = await safeFetchJson("{{ url_for('fortune_quick_step_article') }}", {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({custom_brief: briefText}),
    }, '2/3 글·캡션');
    if(!d2.ok) throw new Error(d2.error || '글 생성 실패');

    window.__fortuneQuickCurrentStep = '3/3 운세 카드 이미지 만드는 중...';
    fortuneQuickSetStep(window.__fortuneQuickCurrentStep);
    const d3 = await safeFetchJson(`/fortune-quick/${d2.article_id}/step-images`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({custom_brief: briefText}),
    }, '3/3 카드 이미지');
    if(!d3.ok) throw new Error(d3.error || '이미지 생성 실패');

    clearInterval(fortuneQuickTimer);
    document.getElementById('fortune_quick_status').textContent = '✅ 완료! 결과 화면으로 이동해요...';
    window.location.href = `/articles/${d2.article_id}#sns`;
  } catch(err) {
    clearInterval(fortuneQuickTimer);
    document.getElementById('fortune_quick_status').textContent = '❌ 실패했어요: ' + err.message;
    btn.disabled = false;
    btn.innerHTML = '🔮 오늘의 운세 만들기';
  }
}
</script>
""", recent=recent, icons_ready=icons_ready, page_title="오늘의 운세 만들기 | MI Creator OS")


@app.post("/fortune-quick/step-icons")
def fortune_quick_step_icons():
    """예전 방식(12개 한 번에)은 시간이 너무 오래 걸려서 타임아웃이
    났어요. 지금은 프론트엔드에서 동물 하나씩 따로 요청을 보내요."""
    return jsonify({"ok": True, "animals": ZODIAC_ANIMALS})


@app.post("/fortune-quick/step-icon/<animal>")
def fortune_quick_step_one_icon(animal):
    if animal not in ZODIAC_ANIMALS:
        return jsonify({"ok": False, "error": "알 수 없는 띠입니다."}), 400
    try:
        filename = get_zodiac_icon(animal)
        return jsonify({"ok": True, "animal": animal, "filename": filename})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/fortune-quick/step-article")
def fortune_quick_step_article():
    try:
        payload = request.get_json(silent=True) or {}
        custom_brief = payload.get("custom_brief")
        article, topic = create_daily_fortune_article(custom_brief=custom_brief)
        return jsonify({"ok": True, "article_id": article.id, "topic": topic})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/fortune-quick/<int:article_id>/step-images")
def fortune_quick_step_images(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        payload = request.get_json(silent=True) or {}
        parsed_top3 = parse_top3_brief(payload.get("custom_brief"))
        if parsed_top3:
            # "N위 OO띠 - 이유" 형식이 대본에 있으면, 12지신 전부가 아니라
            # 해당 순위만 크게 보여주는 강렬한 TOP N 카드로 만듭니다.
            filenames = generate_top3_fortune_carousel(article, parsed_top3)
        else:
            filenames = generate_fortune_carousel(article)
        article.fortune_card_paths = json.dumps(filenames, ensure_ascii=False)
        article.fortune_card_path = filenames[0]
        db.session.commit()
        return jsonify({"ok": True, "count": len(filenames)})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500



@app.get("/calendar")
def content_calendar():
    scheduled = Article.query.filter(
        Article.scheduled_at.isnot(None)
    ).order_by(Article.scheduled_at.asc()).all()

    recent_logs = PublishLog.query.order_by(
        PublishLog.created_at.desc()
    ).limit(30).all()

    return page("""
<div class="card">
<a href="{{url_for('home')}}">← 홈으로</a>
<h1 style="margin-top:14px">콘텐츠 캘린더</h1>
<p class="lead">예약 글과 최근 발행 기록을 한눈에 확인해요.</p>
</div>

<section class="card">
<h2>예약된 Blogger 글</h2>
{% if scheduled %}
<table>
<thead><tr><th>예약 시간</th><th>제목</th><th>상태</th><th></th></tr></thead>
<tbody>
{% for a in scheduled %}
<tr>
<td>{{a.scheduled_at.strftime('%Y-%m-%d %H:%M')}}</td>
<td><strong>{{a.title}}</strong><div class="small">{{a.keyword}}</div></td>
<td><span class="status scheduled">예약됨</span></td>
<td><a class="btn gray" href="{{url_for('edit_article',article_id=a.id)}}">열기·수정</a></td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p class="small">현재 예약된 글이 없습니다.</p>
{% endif %}
</section>

<section class="card">
<h2>최근 발행 활동</h2>
{% if recent_logs %}
<table>
<thead><tr><th>시간</th><th>글</th><th>작업</th><th>결과</th></tr></thead>
<tbody>
{% for log in recent_logs %}
<tr>
<td>{{log.created_at.strftime('%Y-%m-%d %H:%M')}}</td>
<td><a href="{{url_for('edit_article',article_id=log.article_id)}}">{{log.article.title}}</a></td>
<td>{{log.action}}</td>
<td>{{log.status}}{% if log.blogger_url %} · <a href="{{log.blogger_url}}" target="_blank" rel="noopener">Blogger 열기</a>{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p class="small">아직 발행 기록이 없습니다.</p>
{% endif %}
</section>
""", scheduled=scheduled, recent_logs=recent_logs,
       page_title="콘텐츠 캘린더 | MI Creator OS")


@app.get("/health")
def health():
    return {"status": "ok", "version": "16.0.1"}


@app.get("/healthz")
def healthz():
    database_ok = True
    database_error = ""

    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as error:
        database_ok = False
        database_error = str(error)

    status_code = 200 if database_ok else 503

    return {
        "ok": database_ok,
        "app": "MI Creator OS",
        "version": globals().get("APP_VERSION", "V31"),
        "database": "ok" if database_ok else "error",
        "database_error": database_error,
        "media_dir": str(MEDIA_DIR),
        "media_dir_exists": MEDIA_DIR.exists(),
        "timestamp": datetime.utcnow().isoformat(),
    }, status_code


if __name__ == "__main__":
    app.run(debug=True)