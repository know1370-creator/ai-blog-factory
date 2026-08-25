"""V9.2 one-click AI content assistant."""
import json
from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup

from ..legacy_app import (
    BASE_HTML,
    Article,
    analyze_seo,
    db,
    generate_social_pack,
    pipeline_progress,
)

from ..services.ai_service import AIService

assistant_bp = Blueprint("assistant_v92", __name__, url_prefix="/assistant")

ai_service = AIService()

BRAND_PRESETS = {
    "말썽쟁이 딸랑구": {
        "brand_style": "육아·생활",
        "audience": "초등학생 자녀를 키우는 부모와 현실 육아 콘텐츠를 좋아하는 사람",
        "notes": "엄마와 말썽쟁이 딸의 현실적인 대화와 공감 포인트를 살리되 사실을 꾸며내지 않는다.",
    },
    "미우와 웅이": {
        "brand_style": "육아·생활",
        "audience": "커플과 일상 공감 콘텐츠를 좋아하는 사람",
        "notes": "미우와 웅이의 티키타카가 살아나는 따뜻하고 현실적인 말투로 작성한다.",
    },
    "보험·재무": {
        "brand_style": "보험·재무",
        "audience": "보험과 재무 정보를 쉽게 이해하고 싶은 일반 고객",
        "notes": "불안감을 과도하게 자극하지 말고, 상품별 조건은 확인이 필요하다고 명시한다.",
    },
    "애터미·생활용품": {
        "brand_style": "애터미·생활용품",
        "audience": "생활용품과 홈케어 제품에 관심 있는 사람",
        "notes": "직접 확인하지 않은 효능, 가격, 수익을 단정하지 않는다.",
    },
    "쿠팡·쇼핑": {
        "brand_style": "쿠팡·쇼핑",
        "audience": "실용적인 육아·주방·생활용품을 찾는 사람",
        "notes": "구매를 강요하지 않고 장단점과 선택 기준을 중심으로 작성한다.",
    },
    "오늘의 운세": {
        "brand_style": "운세·라이프스타일",
        "audience": "매일 아침 오늘의 띠별·별자리 운세를 가볍게 확인하고 싶은 사람",
        "notes": (
            "재미로 보는 오늘의 운세 콘텐츠. 특정 개인을 지목하지 않고 "
            "띠·별자리 등 일반적인 기준으로 작성한다. 의학적·재정적 확정 조언처럼 "
            "들리지 않게 하고, 글 마지막에 '재미로 보는 콘텐츠입니다' 같은 안내를 "
            "자연스럽게 넣는다. 근거 없는 특정 수치(로또 번호, 정확한 금액 등)는 "
            "만들어내지 않는다."
        ),
    },
}


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


@assistant_bp.get("/")
def dashboard():
    prompt = request.args.get("prompt", "")
    recent = Article.query.order_by(Article.created_at.desc()).limit(8).all()
    progress_map = {article.id: pipeline_progress(article) for article in recent}

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>새 콘텐츠 만들기</h1>
      <p class="lead">주제 하나로 글·이미지·영상·발행 준비까지 한 흐름에서 진행하세요.</p>
    </div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>오늘 콘텐츠 만들기</h2>
  <form method="post" action="{{url_for('assistant_v92.generate')}}">
    <label>주제 또는 핵심 키워드</label>
    <input
name="topic"
required
maxlength="200"
value="{{prompt}}"
placeholder="예: 엄마, 과자 봉지가 왜 반이나 비어 있어?"
>

    <label>브랜드</label>
    <select name="brand_name" required>
      {% for name in presets %}<option value="{{name}}">{{name}}</option>{% endfor %}
    </select>

    <div class="grid">
      <div>
        <label>글 유형</label>
        <select name="article_type">
          <option>정보형</option>
          <option>후기형</option>
          <option>문제 해결형</option>
          <option>공감 스토리형</option>
          <option>비교형</option>
        </select>
      </div>
      <div>
        <label>글 분량</label>
        <select name="length">
          <option>약 1,500자</option>
          <option selected>약 2,500자</option>
          <option>약 3,500자</option>
        </select>
      </div>
    </div>

    <label>추가로 꼭 넣을 내용</label>
    <textarea name="extra_notes" placeholder="실제 경험, 촬영 장면, 제품명, 주의할 표현 등을 적어주세요."></textarea>

    <div class="actions">
      <button class="btn" type="submit">블로그 + SNS 한 번에 생성</button>
    </div>
  </form>

  <p class="notice">
    한 번 실행할 때 AI 요청이 두 번 발생합니다. 블로그 글을 만든 뒤 그 내용을 기준으로 SNS 콘텐츠를 생성합니다.
    썸네일은 비용을 아끼기 위해 자동 생성하지 않으며, 완성 화면에서 따로 만들 수 있어요.
  </p>
</section>

<section class="card">
  <h2>이번 실행에서 만들어지는 것</h2>
  <div class="calendar-item"><strong>블로그 초안</strong><div class="small">제목, 메타 설명, HTML 본문, 태그</div></div>
  <div class="calendar-item"><strong>SEO 기본 분석</strong><div class="small">키워드, 제목, 본문 구조 점수</div></div>
  <div class="calendar-item"><strong>인스타그램 캡션</strong><div class="small">훅, 본문, CTA, 해시태그</div></div>
  <div class="calendar-item"><strong>Threads 글</strong><div class="small">짧고 대화형인 게시물</div></div>
  <div class="calendar-item"><strong>릴스·쇼츠 대본</strong><div class="small">훅, 장면별 대사, 자막, CTA</div></div>
</section>
</div>

<section class="card">
  <h2>최근 만든 콘텐츠</h2>
  {% if recent %}
  <table>
    <thead><tr><th>콘텐츠</th><th>진행률</th><th></th></tr></thead>
    <tbody>
    {% for article in recent %}
    <tr>
      <td>
        <strong>{{article.title}}</strong>
        <div class="small">{{article.keyword}} · {{article.created_at.strftime('%Y-%m-%d %H:%M')}}</div>
      </td>
      <td>
        <div class="progress"><span style="width:{{progress_map.get(article.id,0)}}%"></span></div>
        <div class="small">{{progress_map.get(article.id,0)}}%</div>
      </td>
      <td><a class="btn gray" href="{{url_for('edit_article',article_id=article.id)}}">열기</a></td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="small">아직 생성한 콘텐츠가 없습니다.</p>
  {% endif %}
</section>
""",
        presets=BRAND_PRESETS,
        recent=recent,
        progress_map=progress_map,
        prompt=prompt,
        page_title="새 콘텐츠 만들기 | MI Creator OS",
    )


@assistant_bp.post("/generate")
def generate():
    topic = request.form.get("topic", "").strip()
    brand_name = request.form.get("brand_name", "").strip()
    preset = BRAND_PRESETS.get(brand_name)

    if not topic:
        flash("주제를 입력해 주세요.")
        return redirect(url_for("assistant_v92.dashboard"))

    if not preset:
        flash("올바른 브랜드를 선택해 주세요.")
        return redirect(url_for("assistant_v92.dashboard"))

    extra_notes = request.form.get("extra_notes", "").strip()
    combined_notes = preset["notes"]

    if extra_notes:
        combined_notes += f"\n사용자가 추가한 내용: {extra_notes}"

    try:
        article_data = ai_service.generate(
            topic=topic,
            brand_style=preset["brand_style"],
            article_type=request.form.get("article_type", "정보형"),
            length=request.form.get("length", "약 2,500자"),
            audience=preset["audience"],
            notes=combined_notes,
        )

        tags = article_data.get("tags", [])
        if isinstance(tags, list):
            tags = ",".join(
                str(value).strip().lstrip("#")
                for value in tags
                if str(value).strip()
            )

        article = Article(
            keyword=topic,
            title=article_data.get("title", topic),
            meta_description=article_data.get("meta_description", ""),
            body_html=article_data.get("body_html", ""),
            brand_style=preset["brand_style"],
            article_type=request.form.get("article_type", "정보형"),
            audience=preset["audience"],
            notes=combined_notes,
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
        flash("AI 콘텐츠 비서가 블로그와 SNS 콘텐츠를 모두 만들었어요.")
        return redirect(url_for("edit_article", article_id=article.id))

    except Exception as exc:
        db.session.rollback()
        flash(f"AI 콘텐츠 생성 실패: {exc}")
        return redirect(url_for("assistant_v92.dashboard"))
