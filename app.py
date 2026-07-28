import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, flash, redirect, render_template_string, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", "/tmp/ai_blog_factory.db"))
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret")

PAGE = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 블로그 공장</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--accent:#111827}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Noto Sans KR",sans-serif}
.wrap{max-width:920px;margin:auto;padding:18px}.hero{padding:22px 0}.hero h1{margin:0;font-size:29px}.hero p{color:var(--muted);margin:8px 0 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px;margin-bottom:16px;box-shadow:0 5px 20px rgba(0,0,0,.04)}
label{display:block;font-weight:700;margin:12px 0 7px}input,select,textarea{width:100%;padding:13px;border:1px solid #d1d5db;border-radius:12px;font-size:16px;background:#fff}textarea{min-height:100px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.btn{display:inline-block;border:0;border-radius:12px;padding:13px 17px;font-weight:800;font-size:15px;cursor:pointer;text-decoration:none;background:var(--accent);color:#fff}.btn.light{background:#eef2f7;color:#111827}.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px}.notice{padding:12px;border-radius:10px;background:#fff7ed;margin-bottom:14px}.ok{background:#ecfdf5}.article{border-top:1px solid var(--line);padding:15px 0}.article:first-child{border-top:0}.meta{font-size:13px;color:var(--muted)}
@media(max-width:640px){.grid{grid-template-columns:1fr}.hero h1{font-size:25px}}
</style></head><body><main class="wrap">
<section class="hero"><h1>AI 블로그 공장</h1><p>키워드 하나로 초안을 만들고, 확인한 뒤 Blogger에 발행합니다.</p></section>
{% with messages=get_flashed_messages(with_categories=true) %}{% for cat,msg in messages %}<div class="notice {{'ok' if cat=='ok' else ''}}">{{msg}}</div>{% endfor %}{% endwith %}
<section class="card"><h2>새 글 만들기</h2><form method="post" action="{{url_for('generate')}}">
<label>키워드</label><input name="keyword" required placeholder="예: 초등학생 여름방학 간식">
<div class="grid"><div><label>글 유형</label><select name="article_type"><option>정보형</option><option>후기형</option><option>비교형</option><option>구매 가이드</option></select></div><div><label>분량</label><select name="length"><option value="1800">약 1,800자</option><option value="2500">약 2,500자</option><option value="3500">약 3,500자</option></select></div></div>
<label>내 경험·메모</label><textarea name="experience" placeholder="직접 사용한 느낌, 주의점, 꼭 넣을 내용"></textarea>
<div class="actions"><button class="btn" type="submit">AI 글 생성</button></div></form></section>
<section class="card"><h2>환경 연결 상태</h2><p>OpenAI: <strong>{{'연결됨' if openai_ready else '미연결'}}</strong></p><p>Blogger: <strong>{{'연결됨' if blogger_ready else '미연결'}}</strong></p><p class="meta">Blogger 발행에는 BLOGGER_BLOG_ID와 BLOGGER_ACCESS_TOKEN이 필요합니다. 먼저 글 생성부터 테스트하세요.</p></section>
<section class="card"><h2>저장된 글</h2>{% if not articles %}<p class="meta">아직 글이 없습니다.</p>{% endif %}{% for a in articles %}<article class="article"><h3>{{a['title']}}</h3><div class="meta">{{a['keyword']}} · {{a['created_at']}} · {{a['status']}}</div><div class="actions"><a class="btn light" href="{{url_for('edit',article_id=a['id'])}}">열기·수정</a></div></article>{% endfor %}</section>
</main></body></html>'''

EDIT_PAGE = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>글 수정</title><style>
body{font-family:system-ui,-apple-system,"Noto Sans KR",sans-serif;background:#f6f7fb;margin:0;color:#1f2937}.wrap{max-width:900px;margin:auto;padding:18px}.card{background:white;border:1px solid #e5e7eb;border-radius:18px;padding:18px}label{display:block;font-weight:800;margin:12px 0 7px}input,textarea{width:100%;box-sizing:border-box;padding:12px;border:1px solid #d1d5db;border-radius:11px;font-size:16px}textarea{min-height:430px;font-family:ui-monospace,monospace}.btn{border:0;border-radius:11px;padding:12px 15px;font-weight:800;background:#111827;color:white;text-decoration:none;display:inline-block;cursor:pointer}.light{background:#e5e7eb;color:#111827}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}</style></head><body><main class="wrap"><p><a href="/">← 목록</a></p><section class="card"><h2>글 확인 및 수정</h2><form method="post" action="{{url_for('save',article_id=a['id'])}}"><label>제목</label><input name="title" value="{{a['title']}}"><label>메타 설명</label><input name="meta_description" value="{{a['meta_description'] or ''}}"><label>본문 HTML</label><textarea name="content_html">{{a['content_html']}}</textarea><div class="actions"><button class="btn" type="submit">저장</button></form><form method="post" action="{{url_for('publish',article_id=a['id'])}}"><button class="btn" type="submit">Blogger 초안 발행</button></form><a class="btn light" href="/">취소</a></div></section></main></body></html>'''


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS articles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,title TEXT NOT NULL,meta_description TEXT,
            content_html TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'saved',
            blogger_post_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')


def extract_output_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]
    out=[]
    for item in payload.get("output",[]):
        for c in item.get("content",[]):
            if c.get("type") in ("output_text","text"):
                out.append(c.get("text", ""))
    return "".join(out)


def clean_json(text):
    text=text.strip()
    if text.startswith("```"):
        text=text.replace("```json", "", 1).replace("```", "", 1).strip()
    return json.loads(text)


def generate_article(keyword, article_type, length, experience):
    key=os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 아직 설정되지 않았습니다.")
    prompt=f'''당신은 한국어 SEO 블로그 편집자입니다. 아래 입력으로 사실을 꾸며내지 않는 고품질 초안을 작성하세요.
키워드: {keyword}\n글 유형: {article_type}\n목표 분량: 약 {length}자\n실제 경험 메모: {experience or '없음'}
규칙: 과장 금지, 최신 여부가 필요한 정보는 [확인 필요] 표시, HTML은 h2 h3 p ul li strong만 사용, FAQ 3개 포함.
반드시 JSON 하나만 반환:
{{"title":"제목","meta_description":"120자 안팎","content_html":"HTML 본문"}}'''
    r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json={"model":os.getenv("OPENAI_TEXT_MODEL","gpt-4.1-mini"),"input":prompt},timeout=120)
    r.raise_for_status()
    return clean_json(extract_output_text(r.json()))


def publish_blogger(title, content):
    blog_id=os.getenv("BLOGGER_BLOG_ID", "").strip()
    token=os.getenv("BLOGGER_ACCESS_TOKEN", "").strip()
    if not blog_id or not token:
        raise RuntimeError("Blogger 연결값이 아직 없습니다. 글 생성 테스트 후 연결합니다.")
    r=requests.post(f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/",params={"isDraft":"true"},headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},json={"kind":"blogger#post","title":title,"content":content},timeout=60)
    r.raise_for_status()
    return r.json()

@app.get("/")
def index():
    with db() as conn: articles=conn.execute("SELECT * FROM articles ORDER BY id DESC").fetchall()
    return render_template_string(PAGE,articles=articles,openai_ready=bool(os.getenv("OPENAI_API_KEY")),blogger_ready=bool(os.getenv("BLOGGER_BLOG_ID") and os.getenv("BLOGGER_ACCESS_TOKEN")))

@app.post("/generate")
def generate():
    try:
        keyword=request.form.get("keyword","").strip()
        data=generate_article(keyword,request.form.get("article_type","정보형"),request.form.get("length","1800"),request.form.get("experience","").strip())
        now=datetime.now().isoformat(timespec="seconds")
        with db() as conn:
            cur=conn.execute("INSERT INTO articles(keyword,title,meta_description,content_html,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(keyword,data["title"],data.get("meta_description",""),data["content_html"],"saved",now,now))
            article_id=cur.lastrowid
        flash("글 초안이 생성되었습니다. 내용을 꼭 확인하세요.","ok")
        return redirect(url_for("edit",article_id=article_id))
    except Exception as e:
        flash(f"생성 실패: {e}","error")
        return redirect(url_for("index"))

@app.get("/article/<int:article_id>")
def edit(article_id):
    with db() as conn: a=conn.execute("SELECT * FROM articles WHERE id=?",(article_id,)).fetchone()
    if not a: return "Not found",404
    return render_template_string(EDIT_PAGE,a=a)

@app.post("/article/<int:article_id>/save")
def save(article_id):
    with db() as conn:
        conn.execute("UPDATE articles SET title=?,meta_description=?,content_html=?,updated_at=? WHERE id=?",(request.form.get("title",""),request.form.get("meta_description",""),request.form.get("content_html",""),datetime.now().isoformat(timespec="seconds"),article_id))
    flash("저장했습니다.","ok")
    return redirect(url_for("edit",article_id=article_id))

@app.post("/article/<int:article_id>/publish")
def publish(article_id):
    try:
        with db() as conn: a=conn.execute("SELECT * FROM articles WHERE id=?",(article_id,)).fetchone()
        result=publish_blogger(a["title"],a["content_html"])
        with db() as conn: conn.execute("UPDATE articles SET status='draft_published',blogger_post_id=?,updated_at=? WHERE id=?",(result.get("id",""),datetime.now().isoformat(timespec="seconds"),article_id))
        flash("Blogger에 초안으로 발행했습니다.","ok")
    except Exception as e: flash(f"발행 실패: {e}","error")
    return redirect(url_for("edit",article_id=article_id))

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
