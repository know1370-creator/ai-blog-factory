import base64
import json
import os
import re
import secrets
from html import escape
from urllib.parse import urlparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from flask import (
    Flask, flash, redirect, render_template_string, request,
    send_from_directory, session, url_for
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from markupsafe import Markup
from openai import OpenAI

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build


BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'creator.db'}")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

db = SQLAlchemy(app)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/blogger"]
KST = ZoneInfo("Asia/Seoul")


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
    thumbnail_text = db.Column(db.String(300), nullable=True)
    blogger_post_id = db.Column(db.String(200), nullable=True)
    blogger_blog_id = db.Column(db.String(200), nullable=True)
    blogger_url = db.Column(db.String(1000), nullable=True)
    blogger_status = db.Column(db.String(50), nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    instagram_caption = db.Column(db.Text, default="")
    threads_text = db.Column(db.Text, default="")
    shorts_script = db.Column(db.Text, default="")
    coupang_product_name = db.Column(db.String(300), default="")
    coupang_link = db.Column(db.String(1000), default="")
    atomy_product_name = db.Column(db.String(300), default="")
    atomy_link = db.Column(db.String(1000), default="")
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
        "coupang_product_name": "VARCHAR(300)",
        "coupang_link": "VARCHAR(1000)",
        "atomy_product_name": "VARCHAR(300)",
        "atomy_link": "VARCHAR(1000)",
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
    image_b64 = result.data[0].b64_json
    if not image_b64:
        raise RuntimeError("이미지 데이터가 반환되지 않았습니다.")
    filename = f"article_{article.id}_{int(datetime.utcnow().timestamp())}.png"
    (MEDIA_DIR / filename).write_bytes(base64.b64decode(image_b64))
    return filename


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


def build_affiliate_html(article):
    items = []
    if article.coupang_product_name and article.coupang_link:
        items.append(("쿠팡 추천", article.coupang_product_name, article.coupang_link))
    if article.atomy_product_name and article.atomy_link:
        items.append(("애터미 추천", article.atomy_product_name, article.atomy_link))
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
    prompt = f"""
다음 블로그 글을 바탕으로 한국어 SNS 콘텐츠를 만드세요.
제목: {article.title}
핵심 키워드: {article.keyword}
본문 요약: {plain_text_from_html(article.body_html)[:2500]}

규칙:
1. instagram_caption: 첫 문장 훅, 본문 5~8문장, 마지막 CTA, 해시태그 5~8개.
2. threads_text: 짧고 대화체로 5~9문장. 과장 금지.
3. shorts_script: 35~50초 분량. 훅, 장면별 대사, 자막, 마무리 CTA 포함.
4. 사실을 새로 꾸며내지 마세요.

JSON 하나만 출력하세요.
{{
  "instagram_caption": "...",
  "threads_text": "...",
  "shorts_script": "..."
}}
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    raw = strip_code_fence(response.output_text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise RuntimeError("SNS 콘텐츠 응답을 JSON으로 읽지 못했습니다.")
        return json.loads(match.group(0))



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
<title>{{ page_title or 'MI Creator Hub' }}</title>
<style>
:root{--ink:#202124;--muted:#6b7280;--line:#e5e7eb;--brand:#6d5dfc;--soft:#f6f5ff;--ok:#0f9d58;--bad:#d93025;--warn:#b26a00}
*{box-sizing:border-box}body{margin:0;background:#f7f8fc;color:var(--ink);font-family:Arial,'Apple SD Gothic Neo','Noto Sans KR',sans-serif}
.wrap{max-width:1040px;margin:34px auto;padding:0 18px}.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;margin-bottom:18px;box-shadow:0 8px 30px rgba(0,0,0,.04)}
h1{margin:0 0 7px;font-size:30px}h2{margin:0 0 18px;font-size:22px}h3{margin:18px 0 8px}.lead,.small{color:var(--muted)}.small{font-size:14px}
label{font-weight:700;display:block;margin:14px 0 7px}input,textarea,select{width:100%;border:1px solid #ccd0d5;border-radius:10px;padding:12px;font:inherit;background:#fff}textarea{min-height:150px;resize:vertical}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.btn{border:0;border-radius:10px;padding:12px 17px;background:var(--brand);color:#fff;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}.btn.gray{background:#edf0f4;color:#202124}.btn.green{background:var(--ok)}.btn.red{background:var(--bad)}.btn.orange{background:var(--warn)}
.flash{padding:13px 16px;border-radius:10px;background:#fff4d6;border:1px solid #f4cc63;margin-bottom:15px}.status{display:inline-block;padding:5px 9px;border-radius:99px;background:#edf7f0;color:var(--ok);font-size:13px;font-weight:700}.status.draft{background:#fff4d6;color:var(--warn)}.status.off{background:#f1f3f4;color:#5f6368}.status.scheduled{background:#eef2ff;color:#4f46e5}
table{width:100%;border-collapse:collapse}th,td{padding:12px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.preview{border:1px solid var(--line);border-radius:12px;padding:20px;line-height:1.75}.thumb-wrap{position:relative;border-radius:15px;overflow:hidden;background:#ddd}.thumb{width:100%;display:block}.thumb-badge{position:absolute;left:5%;bottom:8%;max-width:88%;background:rgba(20,20,20,.78);color:#fff;padding:13px 18px;border-radius:10px;font-weight:800;font-size:clamp(18px,3vw,34px)}
.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}.stat{background:var(--soft);border:1px solid #e8e5ff;border-radius:14px;padding:16px}.stat strong{display:block;font-size:28px;margin-bottom:4px}.copy-box{position:relative}.copy-btn{margin-top:7px;background:#edf0f4;color:#202124}.calendar-item{padding:14px 0;border-bottom:1px solid var(--line)}
.progress{height:12px;background:#ececf5;border-radius:999px;overflow:hidden}
.progress>span{display:block;height:100%;background:var(--brand);border-radius:999px}
.pipeline-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:14px}
.pipeline-step{border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff}
.idea-card{border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0}
.checklist{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.check-item{border:1px solid var(--line);border-radius:12px;padding:12px;background:var(--soft)}.money-box{border:1px solid #f0d9a7;background:#fffaf0;border-radius:14px;padding:18px}.notice{font-size:13px;color:var(--muted);background:#f7f8fc;border-radius:9px;padding:10px}.toggle{display:flex;align-items:center;gap:9px;margin-top:14px}.toggle input{width:auto}.score{font-size:46px;font-weight:900}.check{padding:10px 0;border-bottom:1px solid var(--line)}.pass{color:var(--ok);font-weight:800}.fail{color:var(--bad);font-weight:800}.tags{display:flex;gap:7px;flex-wrap:wrap}.tag{background:var(--soft);color:#5046b8;padding:7px 10px;border-radius:99px}
@media(max-width:700px){.grid,.stat-grid,.pipeline-grid,.checklist{grid-template-columns:1fr}.wrap{margin-top:18px}.card{padding:18px}table thead{display:none}table tr,table td{display:block}table tr{padding:12px 0;border-bottom:1px solid var(--line)}table td{border:0;padding:4px 0}}
</style>
</head>
<body><main class="wrap">
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


@app.get("/")
def home():
    articles = Article.query.order_by(Article.created_at.desc()).all()
    google_connected = bool(get_setting("google_credentials"))
    total_count = Article.query.count()
    public_count = Article.query.filter_by(blogger_status="Blogger 공개").count()
    draft_count = Article.query.filter_by(blogger_status="Blogger 초안").count()
    scheduled_count = Article.query.filter(Article.scheduled_at.isnot(None)).count()
    upcoming = Article.query.filter(
        Article.scheduled_at.isnot(None)
    ).order_by(Article.scheduled_at.asc()).limit(5).all()
    progress_map = {a.id: pipeline_progress(a) for a in articles}
    return page("""
<div class="card">
<h1>MI Creator Hub <span class="status">V15.0</span></h1>
<p class="lead">키워드 하나로 글, SEO, 썸네일, Blogger 발행과 수익화 링크까지 한 흐름으로 만들어요.</p>
<div class="actions"><a class="btn" href="{{url_for('factory_v15.dashboard')}}">AI 콘텐츠 팩토리</a><a class="btn gray" href="{{url_for('marketing_v14.dashboard')}}">AI 마케팅 센터</a><a class="btn gray" href="{{url_for('pipeline_v13.board')}}">콘텐츠 파이프라인</a><a class="btn gray" href="{{url_for('generator_v12.dashboard')}}">AI 프로젝트 자동 생성</a><a class="btn gray" href="{{url_for('library_v11.dashboard')}}">콘텐츠 라이브러리</a><a class="btn gray" href="{{url_for('manager_v10.dashboard')}}">AI 콘텐츠 매니저</a><a class="btn gray" href="{{url_for('social_v96.dashboard')}}">AI 소통 비서</a><a class="btn gray" href="{{url_for('analytics_v95.dashboard')}}">성과 분석</a><a class="btn gray" href="{{url_for('diagnostics_v95.dashboard')}}">시스템 점검</a><a class="btn gray" href="{{url_for('calendar_v94.dashboard')}}">콘텐츠 캘린더</a><a class="btn gray" href="{{url_for('planner_v93.dashboard')}}">주간 콘텐츠 플래너</a><a class="btn gray" href="{{url_for('assistant_v92.dashboard')}}">AI 콘텐츠 비서</a><a class="btn gray" href="{{url_for('business_v91.dashboard')}}">수익 대시보드</a><a class="btn gray" href="{{url_for('content_calendar')}}">콘텐츠 캘린더</a><a class="btn gray" href="{{url_for('idea_lab')}}">AI 아이디어 연구소</a></div>
<div class="stat-grid">
<div class="stat"><strong>{{total_count}}</strong><span class="small">전체 글</span></div>
<div class="stat"><strong>{{public_count}}</strong><span class="small">공개 발행</span></div>
<div class="stat"><strong>{{draft_count}}</strong><span class="small">Blogger 초안</span></div>
<div class="stat"><strong>{{scheduled_count}}</strong><span class="small">예약 글</span></div>
</div>
</div>

{% if upcoming %}
<section class="card">
<h2>다가오는 예약</h2>
{% for item in upcoming %}
<div class="calendar-item"><strong>{{item.scheduled_at.strftime('%Y-%m-%d %H:%M')}}</strong> · {{item.title}}
<a class="btn gray" style="float:right;padding:7px 10px" href="{{url_for('edit_article',article_id=item.id)}}">열기</a></div>
{% endfor %}
</section>
{% endif %}

<div class="grid">
<section class="card">
<h2>1. 새 글 만들기</h2>
<form method="post" action="{{url_for('create_article')}}">
<label>키워드</label><input name="keyword" required placeholder="예: 초등학생 여름방학 간식">
<div class="grid">
<div><label>브랜드 스타일</label><select name="brand_style"><option>육아·생활</option><option>보험·재무</option><option>애터미·생활용품</option><option>쿠팡·쇼핑</option><option>일반 정보</option></select></div>
<div><label>글 유형</label><select name="article_type"><option>정보형</option><option>후기형</option><option>비교형</option><option>문제 해결형</option></select></div>
<div><label>분량</label><select name="length"><option>약 1,500자</option><option selected>약 2,500자</option><option>약 3,500자</option></select></div>
<div><label>독자</label><input name="audience" placeholder="예: 초등학생 자녀를 둔 부모"></div>
</div>
<label>내 경험·꼭 넣을 내용</label><textarea name="notes" placeholder="직접 사용한 느낌, 주의점, 가격 등. 모르는 사실은 비워두세요."></textarea>
<div class="actions"><button class="btn" type="submit">AI 글 생성</button></div>
</form>
</section>

<section class="card">
<h2>2. 연결 상태</h2>
<h3>OpenAI</h3><p class="small">글과 썸네일 생성용</p>
<p><span class="status">{{'연결됨' if openai_ok else '환경변수 필요'}}</span></p>
<h3>Google Blogger</h3><p class="small">내 블로그 목록 불러오기와 발행</p>
{% if google_connected %}
<p><span class="status">연결됨</span></p>
<div class="actions">
<a class="btn" href="{{url_for('google_change_account')}}">Google 계정 변경</a>
<a class="btn gray" href="{{url_for('google_disconnect')}}">연결 해제</a>
</div>
{% else %}
<div class="actions"><a class="btn" href="{{url_for('google_connect')}}">Google 연결</a></div>
{% endif %}
</section>
</div>

<section class="card">
<h2>저장된 글</h2>
{% if articles %}
<table><thead><tr><th>제목</th><th>SEO</th><th>상태</th><th></th></tr></thead><tbody>
{% for a in articles %}<tr>
<td><strong>{{a.title}}</strong><div class="small">{{a.keyword}} · {{a.created_at.strftime('%Y-%m-%d %H:%M')}}</div>
<div class="progress" style="margin-top:8px"><span style="width:{{progress_map.get(a.id,0)}}%"></span></div>
<div class="small">콘텐츠 파이프라인 {{progress_map.get(a.id,0)}}%</div></td>
<td>{{a.seo_score}}점</td><td>
{% if a.scheduled_at %}<span class="status scheduled">예약됨</span>
{% elif a.blogger_status == 'Blogger 공개' %}<span class="status">공개됨</span>
{% elif a.blogger_status == 'Blogger 초안' %}<span class="status draft">초안</span>
{% else %}<span class="status off">미발행</span>{% endif %}
</td>
<td><a class="btn gray" href="{{url_for('edit_article',article_id=a.id)}}">열기·수정</a></td>
</tr>{% endfor %}
</tbody></table>
{% else %}<p class="small">아직 글이 없습니다. 위에서 첫 글을 만들어보세요.</p>{% endif %}
</section>
""", articles=articles, google_connected=google_connected,
       total_count=total_count, public_count=public_count, draft_count=draft_count,
       scheduled_count=scheduled_count, upcoming=upcoming, progress_map=progress_map,
       openai_ok=bool(os.getenv("OPENAI_API_KEY")), page_title="MI Creator Hub")


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
    return page("""
<div class="card">
<a href="{{url_for('home')}}">← 홈으로</a>
<h1 style="margin-top:14px">글 확인 및 수정</h1>
<form method="post">
<label>제목</label><input name="title" value="{{a.title}}" required>
<label>메타 설명</label><textarea name="meta_description" style="min-height:90px">{{a.meta_description}}</textarea>
<label>태그 <span class="small">쉼표로 구분</span></label><input name="tags" value="{{a.tags}}">
<label>본문 HTML</label><textarea name="body_html" style="min-height:430px">{{a.body_html}}</textarea>
<div class="actions"><button class="btn" type="submit">수정 내용 저장·SEO 재분석</button></div>
</form>
</div>

<section class="card">
<h2>AI 콘텐츠 파이프라인</h2>
<p class="small">한 번의 실행으로 SEO 재분석, 썸네일, 인스타, Threads, 쇼츠 대본까지 준비합니다.</p>
<div class="progress"><span style="width:{{progress}}%"></span></div>
<p><strong>{{progress}}%</strong> 준비 완료</p>
<div class="pipeline-grid">
<div class="pipeline-step"><strong>블로그 본문</strong><div class="small">{{'완료' if a.body_html else '대기'}}</div></div>
<div class="pipeline-step"><strong>SEO 분석</strong><div class="small">{{'완료' if a.seo_score else '대기'}}</div></div>
<div class="pipeline-step"><strong>썸네일</strong><div class="small">{{'완료' if a.thumbnail_path else '대기'}}</div></div>
<div class="pipeline-step"><strong>인스타</strong><div class="small">{{'완료' if a.instagram_caption else '대기'}}</div></div>
<div class="pipeline-step"><strong>Threads</strong><div class="small">{{'완료' if a.threads_text else '대기'}}</div></div>
<div class="pipeline-step"><strong>쇼츠 대본</strong><div class="small">{{'완료' if a.shorts_script else '대기'}}</div></div>
</div>
<form method="post" action="{{url_for('run_pipeline',article_id=a.id)}}">
<label>썸네일 분위기</label>
<select name="thumbnail_style"><option>따뜻한 생활 사진</option><option>깔끔한 매거진</option><option>밝은 일러스트</option><option>전문적인 인포그래픽</option></select>
<div class="actions"><button class="btn" type="submit">전체 파이프라인 실행</button></div>
</form>
<p class="notice">이미 만들어진 결과도 새 내용으로 다시 생성됩니다. AI 이미지 생성 비용이 발생할 수 있습니다.</p>
</section>

<section class="card">
<h2>업로드 체크리스트</h2>
<form method="post" action="{{url_for('save_checklist',article_id=a.id)}}">
<div class="checklist">
<label class="check-item"><input type="checkbox" name="blog_done" value="1" {{'checked' if a.blog_done else ''}}> 블로그 작성·확인</label>
<label class="check-item"><input type="checkbox" name="instagram_done" value="1" {{'checked' if a.instagram_done else ''}}> 인스타 업로드</label>
<label class="check-item"><input type="checkbox" name="threads_done" value="1" {{'checked' if a.threads_done else ''}}> Threads 업로드</label>
<label class="check-item"><input type="checkbox" name="shorts_done" value="1" {{'checked' if a.shorts_done else ''}}> 릴스·쇼츠 촬영</label>
</div>
<div class="actions"><button class="btn gray" type="submit">체크리스트 저장</button></div>
</form>
</section>

<div class="grid">
<section class="card">
<h2>SEO 분석</h2><div class="score">{{a.seo_score}}<span class="small"> / 100</span></div>
{% for c in seo_report.get('checks',[]) %}
<div class="check"><span class="{{'pass' if c.passed else 'fail'}}">{{'통과' if c.passed else '보완'}}</span> · <strong>{{c.name}}</strong>
{% if not c.passed %}<div class="small">{{c.advice}}</div>{% endif %}</div>
{% endfor %}
<h3>추천 태그</h3><div class="tags">{% for t in tags %}<span class="tag">#{{t}}</span>{% endfor %}</div>
</section>

<section class="card">
<h2>AI 썸네일</h2>
{% if a.thumbnail_path %}<div class="thumb-wrap"><img class="thumb" src="{{url_for('media',filename=a.thumbnail_path)}}" alt="{{a.title}}"><div class="thumb-badge">{{a.thumbnail_text or a.title}}</div></div>
{% else %}<p class="small">아직 썸네일이 없습니다. 글 내용에 맞는 가로형 대표 이미지를 만들어요.</p>{% endif %}
<form method="post" action="{{url_for('generate_thumbnail_route',article_id=a.id)}}">
<label>썸네일 문구</label><input name="thumbnail_text" value="{{a.thumbnail_text or a.title}}" maxlength="45">
<label>이미지 분위기</label><select name="thumbnail_style"><option>따뜻한 생활 사진</option><option>깔끔한 매거진</option><option>밝은 일러스트</option><option>전문적인 인포그래픽</option></select>
<div class="actions"><button class="btn" type="submit">{{'썸네일 다시 만들기' if a.thumbnail_path else 'AI 썸네일 만들기'}}</button></div>
</form>
</section>
</div>

<section class="card">
<h2>수익화 링크</h2>
<p class="small">상품명과 본인의 제휴 링크를 넣으면 Blogger 글 아래에 추천 영역과 제휴 고지가 자동으로 붙습니다.</p>
<form method="post" action="{{url_for('save_monetization',article_id=a.id)}}">
<div class="grid">
<div><label>쿠팡 상품명</label><input name="coupang_product_name" value="{{a.coupang_product_name or ''}}" placeholder="예: 어린이 간식 보관용기"></div>
<div><label>쿠팡파트너스 링크</label><input name="coupang_link" value="{{a.coupang_link or ''}}" placeholder="https://..."></div>
<div><label>애터미 상품명</label><input name="atomy_product_name" value="{{a.atomy_product_name or ''}}" placeholder="예: 애터미 주방세제"></div>
<div><label>애터미 공유 링크</label><input name="atomy_link" value="{{a.atomy_link or ''}}" placeholder="https://..."></div>
</div>
<label class="toggle"><input type="checkbox" name="affiliate_enabled" value="1" {{'checked' if a.affiliate_enabled else ''}}> Blogger 발행 글에 추천 영역 포함</label>
<div class="actions"><button class="btn" type="submit">수익화 설정 저장</button></div>
</form>
{% if a.affiliate_html %}<div class="money-box" style="margin-top:18px"><h3>발행될 추천 영역 미리보기</h3>{{a.affiliate_html|safe}}</div>{% endif %}
<p class="notice">실제 상품 정보와 링크는 직접 확인해서 입력해 주세요. 이 기능은 상품을 자동 검색하거나 가격·효능을 확인하지 않습니다.</p>
</section>

<section class="card"><h2>미리보기</h2><div class="preview"><h1>{{a.title}}</h1>{{a.body_html|safe}}{% if a.affiliate_enabled %}{{a.affiliate_html|safe}}{% endif %}</div></section>

<section class="card">
<h2>SNS 변환</h2>
<p class="small">블로그 글을 인스타그램, Threads, 쇼츠용으로 한 번에 바꿉니다.</p>
<form method="post" action="{{url_for('generate_social_route',article_id=a.id)}}">
<div class="actions"><button class="btn" type="submit">SNS 콘텐츠 자동 생성</button></div>
</form>
{% if a.instagram_caption %}<label>인스타그램 캡션</label><div class="copy-box"><textarea id="instagram_text" readonly>{{a.instagram_caption}}</textarea><button class="btn copy-btn" type="button" onclick="copyText('instagram_text',this)">인스타 캡션 복사</button></div>{% endif %}
{% if a.threads_text %}<label>Threads 글</label><div class="copy-box"><textarea id="threads_text" readonly>{{a.threads_text}}</textarea><button class="btn copy-btn" type="button" onclick="copyText('threads_text',this)">Threads 글 복사</button></div>{% endif %}
{% if a.shorts_script %}<label>쇼츠 대본</label><div class="copy-box"><textarea id="shorts_text" readonly style="min-height:240px">{{a.shorts_script}}</textarea><button class="btn copy-btn" type="button" onclick="copyText('shorts_text',this)">쇼츠 대본 복사</button></div>{% endif %}
</section>

<section class="card">
<h2>Blogger 발행</h2>
{% if a.blogger_url %}<p><a class="btn gray" href="{{a.blogger_url}}" target="_blank" rel="noopener">발행된 글 바로가기</a></p>{% endif %}
<p class="small">처음에는 초안으로 확인하고, 이후 같은 블로그에 다시 보내면 기존 글이 업데이트됩니다.</p>
{% if blogs %}
<form method="post" action="{{url_for('publish_blogger',article_id=a.id)}}">
<label>블로그 선택</label><select name="blog_id">{% for b in blogs %}<option value="{{b.id}}" {{'selected' if a.blogger_blog_id == b.id else ''}}>{{b.name}}</option>{% endfor %}</select>
<label>발행 방식</label><select name="mode"><option value="draft">초안으로 저장</option><option value="publish">바로 공개 발행</option></select>
<div class="actions"><button class="btn green" type="submit">{{'Blogger 글 업데이트' if a.blogger_post_id else 'Blogger로 보내기'}}</button></div>
</form>

<form method="post" action="{{url_for('schedule_blogger',article_id=a.id)}}">
<label>예약 발행 시간</label><input type="datetime-local" name="scheduled_at" required>
<label>예약할 블로그</label><select name="blog_id">{% for b in blogs %}<option value="{{b.id}}">{{b.name}}</option>{% endfor %}</select>
<div class="actions"><button class="btn orange" type="submit">공개 발행 예약</button>
{% if a.scheduled_at %}<button class="btn gray" type="submit" formaction="{{url_for('cancel_schedule',article_id=a.id)}}" formnovalidate>예약 취소</button>{% endif %}</div>
</form>
{% if a.scheduled_at %}<p class="small">현재 예약: {{a.scheduled_at.strftime('%Y-%m-%d %H:%M')}}</p>{% endif %}
{% else %}<p>홈 화면에서 Google Blogger를 먼저 연결해 주세요.</p><a class="btn" href="{{url_for('google_connect')}}">Google 연결</a>{% endif %}
</section>

<section class="card">
<h2>발행 이력</h2>
{% if publish_logs %}
<table><thead><tr><th>시간</th><th>작업</th><th>결과</th><th>링크</th></tr></thead><tbody>
{% for log in publish_logs %}<tr>
<td>{{log.created_at.strftime('%Y-%m-%d %H:%M')}}</td>
<td>{{log.action}}</td>
<td>{{log.status}}{% if log.message %}<div class="small">{{log.message}}</div>{% endif %}</td>
<td>{% if log.blogger_url %}<a href="{{log.blogger_url}}" target="_blank" rel="noopener">열기</a>{% else %}-{% endif %}</td>
</tr>{% endfor %}
</tbody></table>
{% else %}<p class="small">아직 발행 이력이 없습니다.</p>{% endif %}
</section>
""", a=article, seo_report=seo_report, tags=tags, blogs=blogs, publish_logs=publish_logs,
       progress=progress, page_title=f"{article.title} | MI Creator Hub")




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

        style = request.form.get("thumbnail_style", "따뜻한 생활 사진")
        thumbnail_text = article.thumbnail_text or article.title
        old_path = article.thumbnail_path
        article.thumbnail_path = generate_thumbnail(article, style, thumbnail_text)
        article.thumbnail_text = thumbnail_text

        db.session.commit()

        if old_path and old_path != article.thumbnail_path:
            old_file = MEDIA_DIR / old_path
            if old_file.exists():
                old_file.unlink()

        flash("AI 콘텐츠 파이프라인이 완료됐어요. 블로그, SNS, 썸네일까지 준비했습니다.")
    except Exception as e:
        db.session.rollback()
        flash(f"파이프라인 실행 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


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
""", ideas=ideas, page_title="AI 아이디어 연구소 | MI Creator Hub")


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


@app.post("/articles/<int:article_id>/monetization")
def save_monetization(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        article.coupang_product_name = request.form.get("coupang_product_name", "").strip()[:300]
        article.coupang_link = valid_public_url(request.form.get("coupang_link", ""))
        article.atomy_product_name = request.form.get("atomy_product_name", "").strip()[:300]
        article.atomy_link = valid_public_url(request.form.get("atomy_link", ""))
        article.affiliate_enabled = request.form.get("affiliate_enabled") == "1"

        if bool(article.coupang_product_name) != bool(article.coupang_link):
            raise ValueError("쿠팡 상품명과 링크는 둘 다 입력하거나 둘 다 비워주세요.")
        if bool(article.atomy_product_name) != bool(article.atomy_link):
            raise ValueError("애터미 상품명과 링크는 둘 다 입력하거나 둘 다 비워주세요.")

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


@app.get("/media/<path:filename>")
def media(filename):
    return send_from_directory(MEDIA_DIR, filename)


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
        db.session.commit()
        flash("인스타그램, Threads, 쇼츠용 콘텐츠를 만들었어요.")
    except Exception as e:
        db.session.rollback()
        flash(f"SNS 콘텐츠 생성 실패: {e}")
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
       page_title="콘텐츠 캘린더 | MI Creator Hub")


@app.get("/health")
def health():
    return {"status": "ok", "version": "15.0"}


if __name__ == "__main__":
    app.run(debug=True)
