import base64
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, flash, redirect, render_template_string, request,
    send_from_directory, session, url_for
)
from flask_sqlalchemy import SQLAlchemy
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
    blogger_status = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text, default="")


with app.app_context():
    db.create_all()


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
            "redirect_uris": [url_for("google_callback", _external=True)],
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


BASE_HTML = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ page_title or 'MI Creator Hub' }}</title>
<style>
:root{--ink:#202124;--muted:#6b7280;--line:#e5e7eb;--brand:#6d5dfc;--soft:#f6f5ff;--ok:#0f9d58;--bad:#d93025}
*{box-sizing:border-box}body{margin:0;background:#f7f8fc;color:var(--ink);font-family:Arial,'Apple SD Gothic Neo','Noto Sans KR',sans-serif}
.wrap{max-width:1040px;margin:34px auto;padding:0 18px}.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;margin-bottom:18px;box-shadow:0 8px 30px rgba(0,0,0,.04)}
h1{margin:0 0 7px;font-size:30px}h2{margin:0 0 18px;font-size:22px}h3{margin:18px 0 8px}.lead,.small{color:var(--muted)}.small{font-size:14px}
label{font-weight:700;display:block;margin:14px 0 7px}input,textarea,select{width:100%;border:1px solid #ccd0d5;border-radius:10px;padding:12px;font:inherit;background:#fff}textarea{min-height:150px;resize:vertical}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.btn{border:0;border-radius:10px;padding:12px 17px;background:var(--brand);color:#fff;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}.btn.gray{background:#edf0f4;color:#202124}.btn.green{background:var(--ok)}.btn.red{background:var(--bad)}
.flash{padding:13px 16px;border-radius:10px;background:#fff4d6;border:1px solid #f4cc63;margin-bottom:15px}.status{display:inline-block;padding:5px 9px;border-radius:99px;background:#edf7f0;color:var(--ok);font-size:13px;font-weight:700}
table{width:100%;border-collapse:collapse}th,td{padding:12px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.preview{border:1px solid var(--line);border-radius:12px;padding:20px;line-height:1.75}.thumb-wrap{position:relative;border-radius:15px;overflow:hidden;background:#ddd}.thumb{width:100%;display:block}.thumb-badge{position:absolute;left:5%;bottom:8%;max-width:88%;background:rgba(20,20,20,.78);color:#fff;padding:13px 18px;border-radius:10px;font-weight:800;font-size:clamp(18px,3vw,34px)}
.score{font-size:46px;font-weight:900}.check{padding:10px 0;border-bottom:1px solid var(--line)}.pass{color:var(--ok);font-weight:800}.fail{color:var(--bad);font-weight:800}.tags{display:flex;gap:7px;flex-wrap:wrap}.tag{background:var(--soft);color:#5046b8;padding:7px 10px;border-radius:99px}
@media(max-width:700px){.grid{grid-template-columns:1fr}.wrap{margin-top:18px}.card{padding:18px}table thead{display:none}table tr,table td{display:block}table tr{padding:12px 0;border-bottom:1px solid var(--line)}table td{border:0;padding:4px 0}}
</style>
</head>
<body><main class="wrap">
{% with messages=get_flashed_messages() %}{% if messages %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endif %}{% endwith %}
{{ body|safe }}
</main></body></html>
"""


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


@app.get("/")
def home():
    articles = Article.query.order_by(Article.created_at.desc()).all()
    google_connected = bool(get_setting("google_credentials"))
    return page("""
<div class="card">
<h1>MI Creator Hub <span class="status">V5.1</span></h1>
<p class="lead">키워드 하나로 글, SEO, 썸네일, Blogger 발행까지 한 흐름으로 만들어요.</p>
</div>

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
<td><strong>{{a.title}}</strong><div class="small">{{a.keyword}} · {{a.created_at.strftime('%Y-%m-%d %H:%M')}}</div></td>
<td>{{a.seo_score}}점</td><td>{{a.blogger_status or '저장됨'}}</td>
<td><a class="btn gray" href="{{url_for('edit_article',article_id=a.id)}}">열기·수정</a></td>
</tr>{% endfor %}
</tbody></table>
{% else %}<p class="small">아직 글이 없습니다. 위에서 첫 글을 만들어보세요.</p>{% endif %}
</section>
""", articles=articles, google_connected=google_connected,
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

<section class="card"><h2>미리보기</h2><div class="preview"><h1>{{a.title}}</h1>{{a.body_html|safe}}</div></section>

<section class="card">
<h2>Blogger 보내기</h2><p class="small">처음에는 초안으로 보내 확인하는 것을 권장해요.</p>
{% if blogs %}
<form method="post" action="{{url_for('publish_blogger',article_id=a.id)}}">
<label>블로그 선택</label><select name="blog_id">{% for b in blogs %}<option value="{{b.id}}">{{b.name}}</option>{% endfor %}</select>
<label>발행 방식</label><select name="mode"><option value="draft">초안으로 보내기</option><option value="publish">바로 공개 발행</option></select>
<div class="actions"><button class="btn green" type="submit">Blogger로 보내기</button></div>
</form>
{% else %}<p>홈 화면에서 Google Blogger를 먼저 연결해 주세요.</p><a class="btn" href="{{url_for('google_connect')}}">Google 연결</a>{% endif %}
</section>
""", a=article, seo_report=seo_report, tags=tags, blogs=blogs,
       page_title=f"{article.title} | MI Creator Hub")


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
            redirect_uri=url_for("google_callback", _external=True),
        )
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account consent",
        )
        session["oauth_state"] = state
        return redirect(authorization_url)
    except Exception as e:
        flash(f"Google 연결 준비 실패: {e}")
        return redirect(url_for("home"))


@app.get("/oauth2callback")
def google_callback():
    try:
        flow = Flow.from_client_config(
            google_client_config(),
            scopes=GOOGLE_SCOPES,
            state=session.get("oauth_state"),
            redirect_uri=url_for("google_callback", _external=True),
        )
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        set_setting("google_credentials", creds.to_json())
        flash("Google Blogger 연결이 완료됐어요.")
    except Exception as e:
        flash(f"Google 연결 실패: {e}")
    return redirect(url_for("home"))


@app.get("/google/change-account")
def google_change_account():
    row = AppSetting.query.filter_by(setting_key="google_credentials").first()
    if row:
        db.session.delete(row)
        db.session.commit()
    session.pop("oauth_state", None)
    flash("기존 Google 연결을 해제했습니다. 사용할 계정을 다시 선택해 주세요.")
    return redirect(url_for("google_connect"))


@app.get("/google/disconnect")
def google_disconnect():
    row = AppSetting.query.filter_by(setting_key="google_credentials").first()
    if row:
        db.session.delete(row)
        db.session.commit()
    flash("Google 연결을 해제했습니다.")
    return redirect(url_for("home"))


@app.post("/articles/<int:article_id>/blogger")
def publish_blogger(article_id):
    article = Article.query.get_or_404(article_id)
    try:
        blog_id = request.form["blog_id"]
        mode = request.form.get("mode", "draft")
        content = article.body_html
        if article.thumbnail_path:
            public_image_url = url_for("media", filename=article.thumbnail_path, _external=True)
            hero = (
                f'<p><img src="{public_image_url}" alt="{article.title}" '
                f'style="max-width:100%;height:auto"></p>'
            )
            content = hero + content

        labels = [x.strip().lstrip("#") for x in (article.tags or "").split(",") if x.strip()]
        body = {"title": article.title, "content": content, "labels": labels}
        service = blogger_service()
        result = service.posts().insert(
            blogId=blog_id,
            body=body,
            isDraft=(mode == "draft"),
            fetchImages=True,
        ).execute()

        article.blogger_post_id = result.get("id")
        article.blogger_status = "Blogger 초안" if mode == "draft" else "Blogger 공개"
        db.session.commit()
        flash(f"{article.blogger_status}으로 보냈습니다.")
    except Exception as e:
        db.session.rollback()
        flash(f"Blogger 발행 실패: {e}")
    return redirect(url_for("edit_article", article_id=article.id))


@app.get("/health")
def health():
    return {"status": "ok", "version": "5.1"}


if __name__ == "__main__":
    app.run(debug=True)
