"""V12.0 one-click multi-channel content project generator."""
import json
import re

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup

from ..legacy_app import (
    BASE_HTML,
    Article,
    analyze_seo,
    db,
    openai_client,
    strip_code_fence,
)
from .assistant import BRAND_PRESETS
from .library import (
    BRANDS,
    CATEGORIES,
    ContentLibraryItem,
    normalize_tags,
    next_episode,
)


generator_bp = Blueprint("generator_v12", __name__, url_prefix="/generator")


CONTENT_GOALS = [
    "조회와 도달",
    "저장과 공유",
    "댓글과 공감",
    "브랜드 신뢰",
    "상품 관심",
    "상담 문의",
]

FORMATS = [
    "인스타툰 + 릴스 + 블로그 + SNS",
    "인스타툰 중심",
    "릴스 중심",
    "블로그 중심",
    "SNS 짧은 글 중심",
]


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def parse_json_response(raw):
    cleaned = strip_code_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise RuntimeError("AI 응답을 JSON으로 읽지 못했습니다. 다시 생성해 주세요.")
        return json.loads(match.group(0))


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def as_lines(value):
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return as_text(value)


def brand_instruction(brand):
    preset = BRAND_PRESETS.get(brand, {})
    if preset:
        return (
            f"대상 독자: {preset.get('audience', '일반 독자')}\n"
            f"브랜드 규칙: {preset.get('notes', '')}"
        )
    return "대상 독자: 일반 독자\n브랜드 규칙: 사실을 꾸며내지 않고 친절하고 자연스럽게 작성합니다."


def build_prompt(topic, brand, category, goal, primary_format, audience, facts, tone, series_name):
    return f"""
당신은 한국어 멀티채널 콘텐츠 기획자입니다.
한 번의 기획으로 인스타툰, 릴스·쇼츠, 블로그, 인스타그램, Threads용 콘텐츠를 만드세요.

주제: {topic}
브랜드: {brand}
카테고리: {category}
목표: {goal}
우선 형식: {primary_format}
시리즈명: {series_name or '없음'}
사용자가 지정한 독자: {audience or '없음'}
사용자가 지정한 말투: {tone or '브랜드에 맞는 자연스러운 한국어'}
사용자가 제공한 사실·경험·제품·링크: {facts or '없음'}

{brand_instruction(brand)}

필수 안전 규칙:
1. 사용자가 제공하지 않은 제품명, 가격, 할인, 링크, 후기, 체험, 실적, 통계, 수익, 조회수는 만들지 않습니다.
2. 제휴 상품이나 판매 콘텐츠는 사용자가 제공한 정보만 활용합니다.
3. 보험·재무 콘텐츠는 보장과 상품 조건이 개인 및 약관에 따라 다를 수 있음을 자연스럽게 알립니다.
4. 의료적 효능, 확정 수익, 과장 광고, 공포를 이용한 압박 표현을 사용하지 않습니다.
5. 딸이나 가족이 등장하는 콘텐츠는 가족 친화적으로 작성합니다.
6. 블로그 본문은 HTML로 작성하며 h2, h3, p, ul, li, strong 위주로 구성합니다.
7. 인스타툰은 정확히 8컷으로 작성합니다.
8. 릴스 대본은 20~35초 내외이며 장면, 촬영, 대사, 자막, 편집을 포함합니다.
9. 해시태그는 # 없이 8~15개를 작성합니다.
10. 모든 결과는 한국어로 작성합니다.

반드시 아래 JSON 구조 하나만 출력하세요.
{{
  "project_title": "프로젝트 제목",
  "summary": "콘텐츠 전체 요약",
  "hook": "첫 1~2초 또는 첫 문장 훅",
  "toon_plan": [
    {{"cut": 1, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}},
    {{"cut": 2, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}},
    {{"cut": 3, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}},
    {{"cut": 4, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}},
    {{"cut": 5, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}},
    {{"cut": 6, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}},
    {{"cut": 7, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}},
    {{"cut": 8, "image": "상황과 구도", "dialogue": "대사", "caption": "자막"}}
  ],
  "reel_script": [
    {{"time": "0-3초", "camera": "카메라 구도", "action": "행동", "dialogue": "대사", "subtitle": "자막", "edit": "편집"}},
    {{"time": "3-8초", "camera": "카메라 구도", "action": "행동", "dialogue": "대사", "subtitle": "자막", "edit": "편집"}}
  ],
  "blog_title": "블로그 제목",
  "meta_description": "80~150자 메타 설명",
  "blog_html": "<h2>...</h2>",
  "instagram_caption": "훅, 본문, CTA가 포함된 캡션",
  "threads_text": "짧고 대화형인 Threads 글",
  "cta": "부담 없는 행동 유도 문구",
  "hashtags": ["태그1", "태그2"],
  "shooting_props": ["필요한 소품"],
  "thumbnail_texts": ["짧은 썸네일 문구 1", "짧은 썸네일 문구 2", "짧은 썸네일 문구 3"],
  "safety_note": "사실 확인 또는 광고 표현에서 사용자가 확인할 점"
}}
"""


def format_toon(rows):
    if not isinstance(rows, list):
        return as_lines(rows)
    output = []
    for index, row in enumerate(rows[:8], start=1):
        if isinstance(row, dict):
            cut = row.get("cut") or index
            image = as_text(row.get("image"))
            dialogue = as_text(row.get("dialogue"))
            caption = as_text(row.get("caption"))
            output.append(
                f"컷 {cut}\n"
                f"이미지: {image}\n"
                f"대사: {dialogue}\n"
                f"자막: {caption}"
            )
        else:
            output.append(f"컷 {index}\n{as_text(row)}")
    return "\n\n".join(output)


def format_reel(rows):
    if not isinstance(rows, list):
        return as_lines(rows)
    output = []
    for row in rows:
        if isinstance(row, dict):
            output.append(
                f"[{as_text(row.get('time'))}]\n"
                f"카메라: {as_text(row.get('camera'))}\n"
                f"행동: {as_text(row.get('action'))}\n"
                f"대사: {as_text(row.get('dialogue'))}\n"
                f"자막: {as_text(row.get('subtitle'))}\n"
                f"편집: {as_text(row.get('edit'))}"
            )
        else:
            output.append(as_text(row))
    return "\n\n".join(output)


@generator_bp.get("/")
def dashboard():
    recent = ContentLibraryItem.query.order_by(
        ContentLibraryItem.created_at.desc()
    ).limit(8).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>AI 프로젝트 자동 생성기 <span class="status">V12.0</span></h1>
      <p class="lead">주제 하나를 넣으면 인스타툰, 릴스, 블로그, 캡션, Threads와 CTA를 하나의 프로젝트로 만듭니다.</p>
    </div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>한 번에 콘텐츠 만들기</h2>
  <form method="post" action="{{url_for('generator_v12.generate')}}">
    <label>주제</label>
    <input name="topic" required maxlength="300" placeholder="예: 엄마! 왜 과자 봉지가 반이나 비어 있어?">

    <div class="grid">
      <div>
        <label>브랜드</label>
        <select name="brand" required>
          {% for value in brands %}<option value="{{value}}">{{value}}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>카테고리</label>
        <select name="category">
          {% for value in categories %}<option value="{{value}}">{{value}}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>콘텐츠 목표</label>
        <select name="goal">
          {% for value in goals %}<option value="{{value}}">{{value}}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>우선 형식</label>
        <select name="primary_format">
          {% for value in formats %}<option value="{{value}}">{{value}}</option>{% endfor %}
        </select>
      </div>
    </div>

    <div class="grid">
      <div>
        <label>시리즈명</label>
        <input name="series_name" maxlength="200" placeholder="예: 엄마, 경제가 뭐야?">
        <p class="small">입력하면 다음 EP 번호가 자동 지정됩니다.</p>
      </div>
      <div>
        <label>독자</label>
        <input name="audience" maxlength="300" placeholder="예: 초등학생 자녀를 키우는 부모">
      </div>
    </div>

    <label>원하는 말투</label>
    <input name="tone" maxlength="300" placeholder="예: 엄마와 딸의 빠른 티키타카, 쉽고 유쾌하게">

    <label>반드시 지켜야 할 실제 정보</label>
    <textarea name="facts" rows="6" placeholder="실제 경험, 제품명, 직접 확인한 정보, 사용할 제휴 링크, 피해야 할 표현을 적어주세요. 비워두면 AI가 제품·가격·성과를 만들지 않습니다."></textarea>

    <label>
      <input type="checkbox" name="create_article" value="1" checked>
      블로그 글을 기존 Article에도 함께 저장
    </label>

    <div class="actions">
      <button class="btn" type="submit">전체 프로젝트 생성</button>
    </div>
  </form>

  <p class="notice">
    AI 요청은 한 번 발생합니다. 제품, 가격, 링크, 수익, 실적은 사용자가 제공하지 않으면 생성하지 않습니다.
    생성 결과는 먼저 콘텐츠 라이브러리에 저장되며 외부 채널에 자동 게시되지 않습니다.
  </p>
</section>

<section class="card">
  <h2>이번 실행 결과</h2>
  <div class="calendar-item"><strong>인스타툰 8컷</strong><div class="small">상황, 대사, 자막</div></div>
  <div class="calendar-item"><strong>릴스 촬영안</strong><div class="small">시간, 카메라, 행동, 대사, 자막, 편집</div></div>
  <div class="calendar-item"><strong>블로그 초안</strong><div class="small">제목, 메타 설명, HTML 본문</div></div>
  <div class="calendar-item"><strong>SNS 패키지</strong><div class="small">인스타 캡션, Threads, CTA, 해시태그</div></div>
  <div class="calendar-item"><strong>촬영 준비</strong><div class="small">소품, 썸네일 문구, 확인 사항</div></div>
</section>
</div>

<section class="card">
  <h2>최근 생성·저장된 프로젝트</h2>
  {% for item in recent %}
  <div class="calendar-item">
    <strong>
      {% if item.series_name and item.episode_number %}
        {{item.series_name}} EP.{{"%03d"|format(item.episode_number)}} ·
      {% endif %}
      {{item.title}}
    </strong>
    <div class="small">{{item.brand}} · {{item.category}} · {{item.created_at.strftime('%Y-%m-%d %H:%M')}}</div>
    <div class="actions"><a class="btn gray" href="{{url_for('library_v11.detail', item_id=item.id)}}">열기</a></div>
  </div>
  {% else %}
  <p class="small">아직 프로젝트가 없습니다.</p>
  {% endfor %}
</section>
""",
        brands=BRANDS,
        categories=CATEGORIES,
        goals=CONTENT_GOALS,
        formats=FORMATS,
        recent=recent,
        page_title="AI 프로젝트 자동 생성기 | MI Creator OS",
    )


@generator_bp.post("/generate")
def generate():
    topic = request.form.get("topic", "").strip()
    brand = request.form.get("brand", "").strip()
    category = request.form.get("category", "").strip()
    goal = request.form.get("goal", "").strip()
    primary_format = request.form.get("primary_format", "").strip()
    audience = request.form.get("audience", "").strip()
    facts = request.form.get("facts", "").strip()
    tone = request.form.get("tone", "").strip()
    series_name = request.form.get("series_name", "").strip()
    create_article = request.form.get("create_article") == "1"

    if not topic:
        flash("주제를 입력해 주세요.")
        return redirect(url_for("generator_v12.dashboard"))
    if brand not in BRANDS:
        flash("올바른 브랜드를 선택해 주세요.")
        return redirect(url_for("generator_v12.dashboard"))
    if category not in CATEGORIES:
        category = "일반"
    if goal not in CONTENT_GOALS:
        goal = CONTENT_GOALS[0]
    if primary_format not in FORMATS:
        primary_format = FORMATS[0]

    try:
        prompt = build_prompt(
            topic=topic,
            brand=brand,
            category=category,
            goal=goal,
            primary_format=primary_format,
            audience=audience,
            facts=facts,
            tone=tone,
            series_name=series_name,
        )
        response = openai_client().responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )
        data = parse_json_response(response.output_text)

        tags = data.get("hashtags", [])
        if isinstance(tags, list):
            tags = ", ".join(
                str(value).strip().lstrip("#")
                for value in tags
                if str(value).strip()
            )
        tags = normalize_tags(as_text(tags))

        props = as_lines(data.get("shooting_props"))
        thumbnail_texts = as_lines(data.get("thumbnail_texts"))
        safety_note = as_text(data.get("safety_note"))
        summary_parts = [as_text(data.get("summary"))]
        if props:
            summary_parts.append(f"촬영 소품\n{props}")
        if thumbnail_texts:
            summary_parts.append(f"썸네일 문구\n{thumbnail_texts}")
        if safety_note:
            summary_parts.append(f"확인 사항\n{safety_note}")

        article = None
        blog_title = as_text(data.get("blog_title")) or as_text(data.get("project_title")) or topic
        blog_html = as_text(data.get("blog_html"))
        meta_description = as_text(data.get("meta_description"))

        if create_article:
            article = Article(
                keyword=topic,
                title=blog_title,
                meta_description=meta_description,
                body_html=blog_html,
                brand_style=BRAND_PRESETS.get(brand, {}).get("brand_style", brand),
                article_type="V12 통합 프로젝트",
                audience=audience or BRAND_PRESETS.get(brand, {}).get("audience", ""),
                notes=facts,
                tags=tags,
                instagram_caption=as_text(data.get("instagram_caption")),
                threads_text=as_text(data.get("threads_text")),
                shorts_script=format_reel(data.get("reel_script")),
            )
            db.session.add(article)
            db.session.flush()
            article.seo_score, report = analyze_seo(article)
            article.seo_report = json.dumps(report, ensure_ascii=False)

        item = ContentLibraryItem(
            article_id=article.id if article else None,
            title=as_text(data.get("project_title")) or topic,
            brand=brand,
            category=category,
            content_type="통합 프로젝트",
            series_name=series_name,
            episode_number=next_episode(series_name, brand) if series_name else None,
            status="검토",
            summary="\n\n".join(part for part in summary_parts if part),
            hook=as_text(data.get("hook")),
            toon_plan=format_toon(data.get("toon_plan")),
            reel_script=format_reel(data.get("reel_script")),
            blog_content=blog_html,
            instagram_caption=as_text(data.get("instagram_caption")),
            threads_text=as_text(data.get("threads_text")),
            cta=as_text(data.get("cta")),
            tags=tags,
        )
        db.session.add(item)
        db.session.commit()

        flash("인스타툰, 릴스, 블로그와 SNS 콘텐츠를 하나의 프로젝트로 만들었어요.")
        return redirect(url_for("library_v11.detail", item_id=item.id))

    except Exception as exc:
        db.session.rollback()
        flash(f"AI 프로젝트 생성 실패: {exc}")
        return redirect(url_for("generator_v12.dashboard"))
