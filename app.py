import html
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from flask import Flask, flash, redirect, render_template_string, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", "/tmp/mi_creator_hub.db"))
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

STYLE = r'''
:root{--bg:#f5f7fb;--card:#fff;--ink:#182033;--muted:#667085;--line:#e5e9f2;--accent:#6d5dfc;--accent2:#5145cd;--good:#067647;--warn:#b54708}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#f3f0ff 0,#f7f8fc 260px);color:var(--ink);font-family:system-ui,-apple-system,"Noto Sans KR",sans-serif}.wrap{max-width:940px;margin:auto;padding:18px}.hero{padding:25px 2px 17px}.hero h1{margin:0;font-size:30px;letter-spacing:-1px}.hero p{color:var(--muted);margin:8px 0 0}.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:18px;margin-bottom:16px;box-shadow:0 8px 30px rgba(35,28,90,.06)}h2{font-size:20px;margin:0 0 12px}label{display:block;font-weight:750;margin:12px 0 7px}input,select,textarea{width:100%;padding:13px;border:1px solid #d0d5dd;border-radius:12px;font-size:16px;background:#fff;color:var(--ink)}textarea{min-height:115px;resize:vertical}.editor{min-height:470px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.btn{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:12px;padding:12px 16px;font-weight:800;font-size:15px;cursor:pointer;text-decoration:none;background:var(--accent);color:#fff}.btn:hover{background:var(--accent2)}.btn.light{background:#eef0f6;color:#252b3b}.btn.good{background:#067647}.btn.danger{background:#b42318}.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px}.notice{padding:12px 14px;border-radius:12px;background:#fff4e5;border:1px solid #fedf89;margin-bottom:14px}.notice.ok{background:#ecfdf3;border-color:#abefc6}.article{border-top:1px solid var(--line);padding:15px 0}.article:first-child{border-top:0}.article h3{margin:0 0 6px;font-size:18px}.meta{font-size:13px;color:var(--muted)}.status{display:inline-block;padding:5px 9px;border-radius:999px;background:#f2f4f7;font-size:12px;font-weight:700}.status.on{background:#ecfdf3;color:var(--good)}.status.off{background:#fff4e5;color:var(--warn)}.connection{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px 0;border-top:1px solid var(--line)}.connection:first-of-type{border-top:0}.preview{line-height:1.75}.preview h2{margin-top:28px}.preview h3{margin-top:22px}.preview img{max-width:100%}.small{font-size:13px;color:var(--muted)}
@media(max-width:640px){.grid{grid-template-columns:1fr}.hero h1{font-size:26px}.wrap{padding:13px}.card{padding:15px;border-radius:17px}.btn{width:100%}.actions form{width:100%}.actions form .btn{width:100%}.connection{align-items:flex-start;flex-direction:column}}
'''

PAGE = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MI Creator Hub</title><style>''' + STYLE + r'''</style></head><body><main class="wrap">
<section class="hero"><h1>MI Creator Hub</h1><p>키워드 하나로 글을 만들고, 확인한 뒤 Blogger에 발행해요.</p></section>
{% with messages=get_flashed_messages(with_categories=true) %}{% for cat,msg in messages %}<div class="notice {{'ok' if cat=='ok' else ''}}">{{msg}}</div>{% endfor %}{% endwith %}
<section class="card"><h2>1. 새 글 만들기</h2><form method="post" action="{{url_for('generate')}}">
<label>키워드</label><input name="keyword" required placeholder="예: 초등학생 여름방학 간식">
<div class="grid"><div><label>브랜드 스타일</label><select name="brand"><option>육아·생활</option><option>보험 정보</option><option>애터미 후기</option><option>쿠팡 구매가이드</option><option>일반 정보</option></select></div><div><label>글 유형</label><select name="article_type"><option>정보형</option><option>후기형</option><option>비교형</option><option>구매 가이드</option></select></div></div>
<div class="grid"><div><label>분량</label><select name="length"><option value="1800">약 1,800자</option><option value="2500" selected>약 2,500자</option><option value="3500">약 3,500자</option></select></div><div><label>독자</label><input name="audience" placeholder="예: 초등학생 자녀를 둔 부모"></div></div>
<label>내 경험·꼭 넣을 내용</label><textarea name="experience" placeholder="직접 사용한 느낌, 주의점, 가격 등. 모르는 사실은 비워두세요."></textarea>
<div class="actions"><button class="btn" type="submit">AI 글 생성</button></div></form></section>
<section class="card"><h2>2. 연결 상태</h2>
<div class="connection"><div><strong>OpenAI</strong><div class="small">AI 글 생성용</div></div><span class="status {{'on' if openai_ready else 'off'}}">{{'연결됨' if openai_ready else '미연결'}}</span></div>
<div class="connection"><div><strong>Google Blogger</strong><div class="small">내 블로그 목록 불러오기와 발행</div></div>{% if google_ready %}<div class="actions"><span class="status on">연결됨</span><a class="btn light" href="{{url_for('google_disconnect')}}">연결 해제</a></div>{% else %}<a class="btn" href="{{url_for('google_login')}}">Google 연결</a>{% endif %}</div>
{% if google_ready and blogs %}<form method="post" action="{{url_for('choose_blog')}}"><label>발행할 Blogger 선택</label><div class="grid"><select name="blog_id">{% for b in blogs %}<option value="{{b['id']}}" {{'selected' if b['id']==selected_blog_id else ''}}>{{b['name']}}</option>{% endfor %}</select><button class="btn good" type="submit">이 블로그 사용</button></div></form>{% endif %}
</section>
<section class="card"><h2>저장된 글</h2>{% if not articles %}<p class="meta">아직 글이 없습니다. 위에서 첫 글을 만들어보세요.</p>{% endif %}{% for a in articles %}<article class="article"><h3>{{a['title']}}</h3><div class="meta">{{a['keyword']}} · {{a['created_at']}} · {{a['status']}}</div><div class="actions"><a class="btn light" href="{{url_for('edit',article_id=a['id'])}}">열기·수정</a></div></article>{% endfor %}</section>
</main></body></html>'''

EDIT_PAGE = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>글 수정</title><style>''' + STYLE + r'''</style></head><body><main class="wrap"><section class="hero"><h1>글 확인 및 수정</h1><p><a href="/">← 홈으로</a></p></section>
{% with messages=get_flashed_messages(with_categories=true) %}{% for cat,msg in messages %}<div class="notice {{'ok' if cat=='ok' else ''}}">{{msg}}</div>{% endfor %}{% endwith %}
<section class="card"><form method="post" action="{{url_for('save',article_id=a['id'])}}"><label>제목</label><input name="title" value="{{a['title']}}"><label>메타 설명</label><input name="meta_description" value="{{a['meta_description'] or ''}}"><label>본문 HTML</label><textarea class="editor" name="content_html">{{a['content_html']}}</textarea><div class="actions"><button class="btn" type="submit">수정 내용 저장</button></div></form></section>
<section class="card"><h2>미리보기</h2><div class="preview">{{a['content_html']|safe}}</div></section>
<section class="card"><h2>Blogger 보내기</h2><p class="small">처음에는 ‘초안’으로 보내 확인하는 것을 권장해요.</p><div class="actions"><form method="post" action="{{url_for('publish',article_id=a['id'])}}"><input type="hidden" name="draft" value="true"><button class="btn light" type="submit">Blogger 초안으로 보내기</button></form><form method="post" action="{{url_for('publish',article_id=a['id'])}}"><input type="hidden" name="draft" value="false"><button class="btn good" type="submit">바로 공개 발행</button></form></div></section>
</main></body></html>'''


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS articles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            title TEXT NOT NULL,
            meta_description TEXT,
            content_html TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'saved',
            blogger_post_id TEXT,
            blogger_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS oauth_tokens(
            provider TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at TEXT,
            token_type TEXT
        )''')
        # 이전 버전 DB를 그대로 써도 동작하도록 누락 열을 보완합니다.
        columns = {r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()}
        if "blogger_url" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN blogger_url TEXT")


def set_setting(key, value):
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_setting(key, default=""):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def extract_output_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                chunks.append(content.get("text", ""))
    return "".join(chunks)


def clean_json(text):
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1:] if first_newline >= 0 else text
        if text.endswith("```"):
            text = text[:-3]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError("AI 응답을 글 형식으로 읽지 못했습니다. 다시 시도해 주세요.")
    return json.loads(text[start:end + 1])


def generate_article(keyword, brand, article_type, length, audience, experience):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
    brand_rules = {
        "육아·생활": "따뜻하고 현실적인 부모 시점. 과도한 감성 표현 없이 바로 써먹을 팁 중심.",
        "보험 정보": "정확하고 신중한 정보형 문체. 가입을 단정하거나 불안을 과장하지 말고 상품별 약관 확인을 안내.",
        "애터미 후기": "생활 속 사용 경험 중심. 효능을 의학적으로 단정하지 말고 광고성 과장을 피함.",
        "쿠팡 구매가이드": "선택 기준과 장단점 중심. 실제 가격이나 재고를 모르면 특정 수치를 꾸며내지 않음.",
        "일반 정보": "명료하고 친절한 한국어 정보형 문체."
    }
    prompt = f'''당신은 한국어 SEO 블로그 편집자입니다. 다음 조건으로 게시 전 검토용 초안을 작성하세요.

키워드: {keyword}
브랜드 스타일: {brand}
문체 지침: {brand_rules.get(brand, brand_rules['일반 정보'])}
글 유형: {article_type}
목표 분량: 약 {length}자
주 독자: {audience or '일반 독자'}
작성자의 실제 경험 및 메모: {experience or '제공되지 않음'}

필수 규칙:
1. 확인되지 않은 경험, 가격, 통계, 제품 효과를 꾸며내지 마세요.
2. 최신 확인이 필요한 내용에는 자연스럽게 '공식 정보에서 최신 내용을 확인하세요'라고 안내하세요.
3. 제목은 핵심 키워드를 억지스럽지 않게 포함하고 클릭 유도 과장은 피하세요.
4. 도입부, H2 소제목 4~6개, 필요할 때 H3, 체크리스트 또는 목록, FAQ 3개, 결론을 포함하세요.
5. 본문 HTML은 h2, h3, p, ul, ol, li, strong, blockquote 태그만 사용하세요. script, style, a, img 태그는 사용하지 마세요.
6. 글만 읽어도 도움이 되도록 구체적으로 쓰되 같은 문장을 반복하지 마세요.
7. 반드시 아래 JSON 객체 하나만 반환하세요.

{{"title":"제목","meta_description":"검색 결과에 보일 110~150자 설명","content_html":"HTML 본문"}}'''
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1-mini"), "input": prompt},
        timeout=150,
    )
    if not response.ok:
        try:
            message = response.json().get("error", {}).get("message", response.text)
        except Exception:
            message = response.text
        raise RuntimeError(f"OpenAI 오류: {message[:300]}")
    data = clean_json(extract_output_text(response.json()))
    for field in ("title", "content_html"):
        if not data.get(field):
            raise RuntimeError("AI가 필요한 글 내용을 모두 만들지 못했습니다. 다시 시도해 주세요.")
    return data


def google_config_ready():
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def callback_uri():
    return os.getenv("GOOGLE_REDIRECT_URI", "").strip() or url_for("oauth2callback", _external=True)


def save_google_token(payload):
    expires_in = int(payload.get("expires_in", 3600))
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))).isoformat()
    with db() as conn:
        old = conn.execute("SELECT refresh_token FROM oauth_tokens WHERE provider='google'").fetchone()
        refresh_token = payload.get("refresh_token") or (old["refresh_token"] if old else None)
        conn.execute('''INSERT INTO oauth_tokens(provider,access_token,refresh_token,expires_at,token_type)
                        VALUES('google',?,?,?,?)
                        ON CONFLICT(provider) DO UPDATE SET access_token=excluded.access_token,
                        refresh_token=excluded.refresh_token,expires_at=excluded.expires_at,token_type=excluded.token_type''',
                     (payload["access_token"], refresh_token, expires_at, payload.get("token_type", "Bearer")))


def get_google_token():
    with db() as conn:
        row = conn.execute("SELECT * FROM oauth_tokens WHERE provider='google'").fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at > datetime.now(timezone.utc):
        return row["access_token"]
    if not row["refresh_token"]:
        return None
    response = requests.post(GOOGLE_TOKEN_URL, data={
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "refresh_token": row["refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=30)
    if not response.ok:
        return None
    payload = response.json()
    payload["refresh_token"] = row["refresh_token"]
    save_google_token(payload)
    return payload["access_token"]


def blogger_request(method, path, **kwargs):
    token = get_google_token()
    if not token:
        raise RuntimeError("Google 연결이 만료되었습니다. 홈에서 다시 연결해 주세요.")
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, f"https://www.googleapis.com/blogger/v3{path}", headers=headers, timeout=60, **kwargs)
    if not response.ok:
        try:
            msg = response.json().get("error", {}).get("message", response.text)
        except Exception:
            msg = response.text
        raise RuntimeError(f"Blogger 오류: {msg[:300]}")
    return response.json() if response.content else {}


def list_blogs():
    payload = blogger_request("GET", "/users/self/blogs")
    return [{"id": b["id"], "name": b.get("name", "이름 없는 블로그"), "url": b.get("url", "")} for b in payload.get("items", [])]


@app.get("/")
def index():
    with db() as conn:
        articles = conn.execute("SELECT * FROM articles ORDER BY id DESC").fetchall()
    token = get_google_token()
    blogs = []
    if token:
        try:
            blogs = list_blogs()
        except Exception as exc:
            flash(str(exc), "error")
    return render_template_string(
        PAGE,
        articles=articles,
        openai_ready=bool(os.getenv("OPENAI_API_KEY")),
        google_ready=bool(token),
        blogs=blogs,
        selected_blog_id=get_setting("blogger_blog_id"),
    )


@app.post("/generate")
def generate():
    try:
        keyword = request.form.get("keyword", "").strip()
        if not keyword:
            raise RuntimeError("키워드를 입력해 주세요.")
        data = generate_article(
            keyword,
            request.form.get("brand", "일반 정보"),
            request.form.get("article_type", "정보형"),
            request.form.get("length", "2500"),
            request.form.get("audience", "").strip(),
            request.form.get("experience", "").strip(),
        )
        now = datetime.now().isoformat(timespec="seconds")
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO articles(keyword,title,meta_description,content_html,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (keyword, data["title"], data.get("meta_description", ""), data["content_html"], "saved", now, now),
            )
            article_id = cur.lastrowid
        flash("AI 초안이 만들어졌어요. 내용을 확인하고 수정해 주세요.", "ok")
        return redirect(url_for("edit", article_id=article_id))
    except Exception as exc:
        flash(f"생성 실패: {exc}", "error")
        return redirect(url_for("index"))


@app.get("/article/<int:article_id>")
def edit(article_id):
    with db() as conn:
        article = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    if not article:
        return "Not found", 404
    return render_template_string(EDIT_PAGE, a=article)


@app.post("/article/<int:article_id>/save")
def save(article_id):
    with db() as conn:
        conn.execute(
            "UPDATE articles SET title=?,meta_description=?,content_html=?,updated_at=? WHERE id=?",
            (request.form.get("title", "").strip(), request.form.get("meta_description", "").strip(), request.form.get("content_html", ""), datetime.now().isoformat(timespec="seconds"), article_id),
        )
    flash("수정 내용을 저장했어요.", "ok")
    return redirect(url_for("edit", article_id=article_id))


@app.get("/google/login")
def google_login():
    if not google_config_ready():
        flash("GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET을 먼저 설정해 주세요.", "error")
        return redirect(url_for("index"))
    state = secrets.token_urlsafe(24)
    session["google_oauth_state"] = state
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "redirect_uri": callback_uri(),
        "response_type": "code",
        "scope": BLOGGER_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@app.get("/oauth2callback")
def oauth2callback():
    if request.args.get("state") != session.pop("google_oauth_state", None):
        flash("Google 연결 확인값이 맞지 않습니다. 다시 시도해 주세요.", "error")
        return redirect(url_for("index"))
    if request.args.get("error"):
        flash(f"Google 연결이 취소되었어요: {request.args.get('error')}", "error")
        return redirect(url_for("index"))
    code = request.args.get("code")
    response = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": callback_uri(),
        "grant_type": "authorization_code",
    }, timeout=30)
    if not response.ok:
        flash(f"Google 토큰 발급 실패: {response.text[:300]}", "error")
        return redirect(url_for("index"))
    save_google_token(response.json())
    flash("Google Blogger가 연결되었어요.", "ok")
    return redirect(url_for("index"))


@app.get("/google/disconnect")
def google_disconnect():
    with db() as conn:
        conn.execute("DELETE FROM oauth_tokens WHERE provider='google'")
    flash("Google 연결을 해제했어요.", "ok")
    return redirect(url_for("index"))


@app.post("/blogger/choose")
def choose_blog():
    blog_id = request.form.get("blog_id", "").strip()
    if not blog_id:
        flash("블로그를 선택해 주세요.", "error")
    else:
        set_setting("blogger_blog_id", blog_id)
        flash("발행할 Blogger를 저장했어요.", "ok")
    return redirect(url_for("index"))


@app.post("/article/<int:article_id>/publish")
def publish(article_id):
    try:
        blog_id = get_setting("blogger_blog_id")
        if not blog_id:
            raise RuntimeError("홈에서 발행할 Blogger를 먼저 선택해 주세요.")
        with db() as conn:
            article = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        if not article:
            raise RuntimeError("글을 찾지 못했습니다.")
        is_draft = request.form.get("draft", "true").lower() == "true"
        content = article["content_html"]
        if article["meta_description"]:
            content = f"<p><em>{html.escape(article['meta_description'])}</em></p>" + content
        result = blogger_request(
            "POST",
            f"/blogs/{blog_id}/posts/",
            params={"isDraft": "true" if is_draft else "false"},
            headers={"Content-Type": "application/json"},
            json={"kind": "blogger#post", "title": article["title"], "content": content},
        )
        status = "blogger_draft" if is_draft else "published"
        with db() as conn:
            conn.execute(
                "UPDATE articles SET status=?,blogger_post_id=?,blogger_url=?,updated_at=? WHERE id=?",
                (status, result.get("id", ""), result.get("url", ""), datetime.now().isoformat(timespec="seconds"), article_id),
            )
        flash("Blogger 초안으로 보냈어요." if is_draft else "Blogger에 공개 발행했어요.", "ok")
    except Exception as exc:
        flash(f"발행 실패: {exc}", "error")
    return redirect(url_for("edit", article_id=article_id))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=False)
