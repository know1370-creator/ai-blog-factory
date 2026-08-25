"""V9.3 weekly AI content planner."""
import json
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup

from ..legacy_app import (
    BASE_HTML,
    Article,
    analyze_seo,
    db,
    generate_article,
    generate_social_pack,
    openai_client,
    OPENAI_MODEL,
    strip_code_fence,
)


planner_bp = Blueprint("planner_v93", __name__, url_prefix="/planner")


class WeeklyPlanItem(db.Model):
    __tablename__ = "weekly_plan_item"

    id = db.Column(db.Integer, primary_key=True)
    plan_date = db.Column(db.Date, nullable=False, index=True)
    brand_name = db.Column(db.String(100), nullable=False)
    theme = db.Column(db.String(200), nullable=False)
    format_type = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    hook = db.Column(db.Text, default="")
    content_angle = db.Column(db.Text, default="")
    cta = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="기획")
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    article = db.relationship("Article", lazy=True)


BRAND_PRESETS = {
    "말썽쟁이 딸랑구": "현실 육아, 엄마와 딸의 티키타카, 공감과 생활 정보",
    "미우와 웅이": "커플 일상, 데이트, 선물, 따뜻한 대화와 공감",
    "보험·재무": "보험과 재무 정보를 과장 없이 쉽게 설명",
    "애터미·생활용품": "생활 밀착형 사용 팁과 제품 선택 기준",
    "쿠팡·쇼핑": "육아·주방·생활용품의 실용적인 비교와 후기",
}

FORMAT_OPTIONS = ["블로그", "인스타툰", "릴스/쇼츠", "Threads", "쇼핑 콘텐츠"]


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def next_monday(today=None):
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def parse_json_array(raw):
    raw = strip_code_fence(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise RuntimeError("AI 주간 계획을 JSON으로 읽지 못했습니다.")
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise RuntimeError("AI 주간 계획 형식이 올바르지 않습니다.")
    return data


def generate_weekly_plan(theme, brand_name, start_date, notes):
    brand_guide = BRAND_PRESETS[brand_name]
    dates = [(start_date + timedelta(days=i)).isoformat() for i in range(7)]
    prompt = f"""
한국어 SNS·블로그 콘텐츠 편집장 역할을 하세요.

브랜드: {brand_name}
브랜드 방향: {brand_guide}
이번 주 중심 주제: {theme}
추가 요청: {notes or '없음'}
날짜: {', '.join(dates)}

7일 동안 서로 겹치지 않는 콘텐츠 계획을 정확히 7개 만드세요.
블로그, 인스타툰, 릴스/쇼츠, Threads, 쇼핑 콘텐츠를 균형 있게 섞으세요.
확인하지 않은 가격, 효과, 수익, 경험을 사실처럼 만들지 마세요.
외부 발행은 사용자가 검토한 뒤 진행하므로 여기서는 기획만 만드세요.

JSON 배열만 출력하세요.
[
  {{
    "date": "YYYY-MM-DD",
    "format_type": "블로그|인스타툰|릴스/쇼츠|Threads|쇼핑 콘텐츠",
    "title": "콘텐츠 제목",
    "hook": "첫 문장 또는 첫 2초 훅",
    "content_angle": "구성 방향과 핵심 장면 또는 소제목",
    "cta": "댓글·저장·공유·DM 중 자연스러운 행동 유도"
  }}
]
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    return parse_json_array(response.output_text)


@planner_bp.get("/")
def dashboard():
    start = request.args.get("start")
    try:
        selected_start = datetime.strptime(start, "%Y-%m-%d").date() if start else next_monday()
    except ValueError:
        selected_start = next_monday()
    selected_end = selected_start + timedelta(days=6)

    items = WeeklyPlanItem.query.filter(
        WeeklyPlanItem.plan_date >= selected_start,
        WeeklyPlanItem.plan_date <= selected_end,
    ).order_by(WeeklyPlanItem.plan_date.asc(), WeeklyPlanItem.id.asc()).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>주간 콘텐츠 플래너 <span class="status">V9.3</span></h1>
      <p class="lead">주제 하나로 7일치 콘텐츠 기획을 만들고, 마음에 드는 항목만 실제 초안으로 변환해요.</p>
    </div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>이번 주 계획 만들기</h2>
  <form method="post" action="{{url_for('planner_v93.generate')}}">
    <label>주 시작일</label>
    <input type="date" name="start_date" value="{{selected_start.isoformat()}}" required>

    <label>브랜드</label>
    <select name="brand_name" required>
      {% for name in presets %}<option value="{{name}}">{{name}}</option>{% endfor %}
    </select>

    <label>이번 주 중심 주제</label>
    <input name="theme" maxlength="200" required placeholder="예: 과자 양이 줄어든 이유를 딸과 알아보기">

    <label>추가 요청</label>
    <textarea name="notes" placeholder="예: 실사 릴스 2개, 인스타툰 2개, 제품 판매는 자연스럽게"></textarea>

    <div class="actions"><button class="btn" type="submit">7일치 AI 기획 생성</button></div>
  </form>
  <p class="notice">기존 주간 계획은 자동으로 지우지 않습니다. 같은 주를 다시 만들면 새 기획이 추가되므로, 필요 없는 항목만 삭제해 주세요.</p>
</section>

<section class="card">
  <h2>작동 방식</h2>
  <div class="calendar-item"><strong>1. 일주일 기획</strong><div class="small">요일별 제목, 훅, 구성, CTA 생성</div></div>
  <div class="calendar-item"><strong>2. 검토와 수정</strong><div class="small">마음에 드는 항목만 선택</div></div>
  <div class="calendar-item"><strong>3. 초안 만들기</strong><div class="small">선택한 기획을 블로그와 SNS 초안으로 변환</div></div>
  <div class="calendar-item"><strong>4. 직접 승인</strong><div class="small">자동 외부 발행은 하지 않음</div></div>
</section>
</div>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <h2>{{selected_start.strftime('%Y-%m-%d')}} ~ {{selected_end.strftime('%Y-%m-%d')}}</h2>
    <form method="get">
      <input type="date" name="start" value="{{selected_start.isoformat()}}" style="width:auto;display:inline-block">
      <button class="btn gray" type="submit">주간 보기</button>
    </form>
  </div>

  {% if items %}
  {% for item in items %}
  <div class="calendar-item">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div>
        <span class="tag">{{item.plan_date.strftime('%m/%d')}}</span>
        <span class="tag">{{item.format_type}}</span>
        <span class="status">{{item.status}}</span>
      </div>
      <div class="actions" style="margin-top:0">
        {% if item.article_id %}
          <a class="btn gray" href="{{url_for('edit_article', article_id=item.article_id)}}">완성본 열기</a>
        {% else %}
          <form method="post" action="{{url_for('planner_v93.create_content', item_id=item.id)}}">
            <button class="btn" type="submit">AI 초안 만들기</button>
          </form>
        {% endif %}
        <form method="post" action="{{url_for('planner_v93.delete_item', item_id=item.id)}}" onsubmit="return confirm('이 기획을 삭제할까요?')">
          <button class="btn red" type="submit">삭제</button>
        </form>
      </div>
    </div>
    <h3>{{item.title}}</h3>
    <p><strong>훅:</strong> {{item.hook}}</p>
    <p><strong>구성:</strong> {{item.content_angle}}</p>
    <p><strong>CTA:</strong> {{item.cta}}</p>
    <div class="small">{{item.brand_name}} · 주제: {{item.theme}}</div>
  </div>
  {% endfor %}
  {% else %}
  <p class="small">이 주에 저장된 계획이 없습니다. 왼쪽 폼에서 7일치 기획을 만들어 보세요.</p>
  {% endif %}
</section>
""",
        presets=BRAND_PRESETS,
        selected_start=selected_start,
        selected_end=selected_end,
        items=items,
        page_title="주간 콘텐츠 플래너 | MI Creator OS",
    )


@planner_bp.post("/generate")
def generate():
    theme = request.form.get("theme", "").strip()
    brand_name = request.form.get("brand_name", "").strip()
    notes = request.form.get("notes", "").strip()

    if not theme or brand_name not in BRAND_PRESETS:
        flash("브랜드와 중심 주제를 확인해 주세요.")
        return redirect(url_for("planner_v93.dashboard"))

    try:
        start_date = datetime.strptime(request.form.get("start_date", ""), "%Y-%m-%d").date()
        rows = generate_weekly_plan(theme, brand_name, start_date, notes)

        valid_dates = {start_date + timedelta(days=i) for i in range(7)}
        saved = 0
        for index, row in enumerate(rows[:7]):
            try:
                plan_date = datetime.strptime(str(row.get("date", "")), "%Y-%m-%d").date()
            except ValueError:
                plan_date = start_date + timedelta(days=index)
            if plan_date not in valid_dates:
                plan_date = start_date + timedelta(days=index)

            format_type = str(row.get("format_type", "블로그")).strip()
            if format_type not in FORMAT_OPTIONS:
                format_type = "블로그"

            item = WeeklyPlanItem(
                plan_date=plan_date,
                brand_name=brand_name,
                theme=theme,
                format_type=format_type,
                title=str(row.get("title", theme)).strip()[:300],
                hook=str(row.get("hook", "")).strip(),
                content_angle=str(row.get("content_angle", "")).strip(),
                cta=str(row.get("cta", "")).strip(),
            )
            db.session.add(item)
            saved += 1

        db.session.commit()
        flash(f"{saved}개의 주간 콘텐츠 기획을 저장했어요.")
        return redirect(url_for("planner_v93.dashboard", start=start_date.isoformat()))
    except Exception as exc:
        db.session.rollback()
        flash(f"주간 계획 생성 실패: {exc}")
        return redirect(url_for("planner_v93.dashboard"))


@planner_bp.post("/items/<int:item_id>/create")
def create_content(item_id):
    item = db.session.get(WeeklyPlanItem, item_id)
    if not item:
        flash("기획 항목을 찾을 수 없습니다.")
        return redirect(url_for("planner_v93.dashboard"))

    article_type = "스토리형" if item.format_type in {"인스타툰", "릴스/쇼츠", "Threads"} else "정보형"
    notes = (
        f"브랜드: {item.brand_name}\n"
        f"콘텐츠 형식: {item.format_type}\n"
        f"훅: {item.hook}\n"
        f"구성 방향: {item.content_angle}\n"
        f"CTA: {item.cta}\n"
        "확인하지 않은 사실, 가격, 효능, 수익을 만들어내지 않는다."
    )

    try:
        data = generate_article(
            item.title,
            "육아·생활" if item.brand_name in {"말썽쟁이 딸랑구", "미우와 웅이"} else item.brand_name,
            article_type,
            "약 2,500자",
            "해당 브랜드 콘텐츠에 관심 있는 일반 독자",
            notes,
        )
        tags = data.get("tags", [])
        if isinstance(tags, list):
            tags = ",".join(str(x).strip().lstrip("#") for x in tags if str(x).strip())

        article = Article(
            keyword=item.title,
            title=data.get("title", item.title),
            meta_description=data.get("meta_description", ""),
            body_html=data.get("body_html", ""),
            brand_style=item.brand_name,
            article_type=article_type,
            audience="해당 브랜드 콘텐츠에 관심 있는 일반 독자",
            notes=notes,
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

        item.article_id = article.id
        item.status = "초안 완성"
        db.session.commit()
        flash("선택한 주간 기획으로 블로그와 SNS 초안을 만들었어요.")
        return redirect(url_for("edit_article", article_id=article.id))
    except Exception as exc:
        db.session.rollback()
        flash(f"초안 생성 실패: {exc}")
        return redirect(url_for("planner_v93.dashboard", start=item.plan_date.isoformat()))


@planner_bp.post("/items/<int:item_id>/delete")
def delete_item(item_id):
    item = db.session.get(WeeklyPlanItem, item_id)
    if not item:
        flash("기획 항목을 찾을 수 없습니다.")
        return redirect(url_for("planner_v93.dashboard"))
    start = item.plan_date.isoformat()
    db.session.delete(item)
    db.session.commit()
    flash("주간 기획을 삭제했어요.")
    return redirect(url_for("planner_v93.dashboard", start=start))
