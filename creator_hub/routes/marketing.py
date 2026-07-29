"""V14.0 marketing center, idea bank, shooting checklist, and monthly report."""
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup
from sqlalchemy import func

from ..legacy_app import BASE_HTML, Article, db
from .analytics import CHANNELS, ContentMetric
from .library import BRANDS, CONTENT_TYPES, ContentLibraryItem


marketing_bp = Blueprint("marketing_v14", __name__, url_prefix="/marketing")


class MarketingIdea(db.Model):
    __tablename__ = "marketing_idea"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    brand = db.Column(db.String(100), nullable=False, default="말썽쟁이 딸랑구")
    category = db.Column(db.String(100), nullable=False, default="일반")
    content_type = db.Column(db.String(50), nullable=False, default="릴스·쇼츠")
    hook = db.Column(db.Text, default="")
    angle = db.Column(db.Text, default="")
    tags = db.Column(db.Text, default="")
    priority = db.Column(db.String(20), nullable=False, default="보통")
    status = db.Column(db.String(30), nullable=False, default="아이디어")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ShootingChecklist(db.Model):
    __tablename__ = "shooting_checklist"

    id = db.Column(db.Integer, primary_key=True)
    library_item_id = db.Column(
        db.Integer,
        db.ForeignKey("content_library_item.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    location_ready = db.Column(db.Boolean, nullable=False, default=False)
    props_ready = db.Column(db.Boolean, nullable=False, default=False)
    cast_ready = db.Column(db.Boolean, nullable=False, default=False)
    script_ready = db.Column(db.Boolean, nullable=False, default=False)
    filming_done = db.Column(db.Boolean, nullable=False, default=False)
    editing_done = db.Column(db.Boolean, nullable=False, default=False)
    thumbnail_done = db.Column(db.Boolean, nullable=False, default=False)
    caption_done = db.Column(db.Boolean, nullable=False, default=False)
    location_note = db.Column(db.String(500), default="")
    props_note = db.Column(db.String(1000), default="")
    cast_note = db.Column(db.String(500), default="")
    editing_note = db.Column(db.String(1000), default="")
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    item = db.relationship(
        "ContentLibraryItem",
        backref=db.backref(
            "shooting_checklist",
            uselist=False,
            cascade="all, delete-orphan",
        ),
    )


IDEA_PRIORITIES = ["높음", "보통", "낮음"]
IDEA_STATUSES = ["아이디어", "선정", "제작 전", "사용 완료", "보류"]


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def parse_period():
    raw = request.args.get("days", "30").strip()
    try:
        days = int(raw)
    except ValueError:
        days = 30
    if days not in {7, 30, 90, 365}:
        days = 30
    return days


def metric_rows(start_date, brand=""):
    query = (
        db.session.query(ContentMetric, Article, ContentLibraryItem)
        .join(Article, Article.id == ContentMetric.article_id)
        .outerjoin(ContentLibraryItem, ContentLibraryItem.article_id == Article.id)
        .filter(ContentMetric.measured_at >= start_date)
    )
    if brand:
        query = query.filter(ContentLibraryItem.brand == brand)
    return query.order_by(ContentMetric.measured_at.asc(), ContentMetric.id.asc()).all()


def summarize_metrics(rows):
    totals = {
        "views": 0, "likes": 0, "comments": 0, "saves": 0,
        "shares": 0, "clicks": 0, "revenue": 0.0, "records": len(rows),
    }
    channels = {}
    brands = {}
    contents = {}

    for metric, article, library_item in rows:
        reaction = metric.likes + metric.comments + metric.saves + metric.shares
        totals["views"] += metric.views
        totals["likes"] += metric.likes
        totals["comments"] += metric.comments
        totals["saves"] += metric.saves
        totals["shares"] += metric.shares
        totals["clicks"] += metric.clicks
        totals["revenue"] += float(metric.revenue or 0)

        channel = channels.setdefault(metric.channel, {
            "name": CHANNELS.get(metric.channel, metric.channel),
            "views": 0, "reactions": 0, "saves": 0, "clicks": 0, "revenue": 0.0,
        })
        channel["views"] += metric.views
        channel["reactions"] += reaction
        channel["saves"] += metric.saves
        channel["clicks"] += metric.clicks
        channel["revenue"] += float(metric.revenue or 0)

        brand_name = library_item.brand if library_item else "브랜드 미연결"
        brand_row = brands.setdefault(brand_name, {
            "name": brand_name, "views": 0, "reactions": 0,
            "saves": 0, "clicks": 0, "revenue": 0.0,
        })
        brand_row["views"] += metric.views
        brand_row["reactions"] += reaction
        brand_row["saves"] += metric.saves
        brand_row["clicks"] += metric.clicks
        brand_row["revenue"] += float(metric.revenue or 0)

        item = contents.setdefault(article.id, {
            "id": article.id,
            "title": article.title,
            "brand": brand_name,
            "hook": library_item.hook if library_item else "",
            "content_type": library_item.content_type if library_item else article.article_type,
            "views": 0, "reactions": 0, "saves": 0, "clicks": 0, "revenue": 0.0,
        })
        item["views"] += metric.views
        item["reactions"] += reaction
        item["saves"] += metric.saves
        item["clicks"] += metric.clicks
        item["revenue"] += float(metric.revenue or 0)

    totals["reactions"] = (
        totals["likes"] + totals["comments"] + totals["saves"] + totals["shares"]
    )
    totals["engagement_rate"] = (
        totals["reactions"] / totals["views"] * 100 if totals["views"] else 0
    )
    totals["save_rate"] = totals["saves"] / totals["views"] * 100 if totals["views"] else 0
    totals["click_rate"] = totals["clicks"] / totals["views"] * 100 if totals["views"] else 0

    for group in (channels, brands, contents):
        for row in group.values():
            views = row["views"]
            row["engagement_rate"] = row["reactions"] / views * 100 if views else 0
            row["save_rate"] = row["saves"] / views * 100 if views else 0
            row["click_rate"] = row["clicks"] / views * 100 if views else 0

    return (
        totals,
        sorted(channels.values(), key=lambda row: (row["engagement_rate"], row["views"]), reverse=True),
        sorted(brands.values(), key=lambda row: (row["engagement_rate"], row["views"]), reverse=True),
        sorted(contents.values(), key=lambda row: (row["reactions"], row["views"]), reverse=True),
    )


def build_recommendations(totals, channels, brands, contents):
    if not totals["records"]:
        return [
            "선택한 기간에 성과 기록이 없습니다. 실제 플랫폼 수치를 먼저 입력해 주세요.",
            "성과 기록은 같은 기준 시점으로 입력하면 비교가 더 정확해집니다.",
            "이 센터는 입력된 수치만 계산하며 조회수나 수익을 추정하지 않습니다.",
        ]

    result = []
    if channels:
        best = channels[0]
        result.append(
            f"{best['name']}의 반응률이 {best['engagement_rate']:.1f}%로 현재 입력 데이터 중 가장 높습니다. "
            "다음 주 콘텐츠 배치에서 이 채널을 우선 검토하세요."
        )
    if contents:
        best = contents[0]
        hook_hint = f" 훅 ‘{best['hook'][:50]}’의 구조를 변주해 보세요." if best["hook"] else ""
        result.append(
            f"‘{best['title']}’이 반응 {best['reactions']:,}건으로 가장 앞섭니다.{hook_hint}"
        )
    if brands and brands[0]["name"] != "브랜드 미연결":
        best = brands[0]
        result.append(
            f"{best['name']} 브랜드가 현재 가장 높은 반응률을 보입니다. "
            "같은 주제군에서 후속편 1개를 기획하는 것이 좋습니다."
        )
    if totals["save_rate"] > totals["click_rate"] * 2 and totals["saves"] > 0:
        result.append(
            "저장률이 클릭률보다 크게 높습니다. 정보형 콘텐츠 강점은 유지하고 CTA를 더 구체적으로 다듬어 보세요."
        )
    elif totals["click_rate"] > totals["save_rate"] and totals["clicks"] > 0:
        result.append(
            "클릭률이 저장률보다 높습니다. 구매·상담 연결형 콘텐츠의 제목과 CTA 패턴을 재사용해 볼 만합니다."
        )
    else:
        result.append(
            "조회수만 단독으로 판단하지 말고 저장, 공유, 클릭을 함께 확인하세요."
        )
    return result[:4]


@marketing_bp.get("/")
def dashboard():
    days = parse_period()
    brand = request.args.get("brand", "").strip()
    start_date = date.today() - timedelta(days=days - 1)
    rows = metric_rows(start_date, brand)
    totals, channels, brand_rows, contents = summarize_metrics(rows)
    recommendations = build_recommendations(totals, channels, brand_rows, contents)

    # Daily trend, rendered with simple CSS bars to avoid external chart libraries.
    trend_map = {}
    for metric, _, _ in rows:
        day = metric.measured_at.isoformat()
        trend = trend_map.setdefault(day, {"day": metric.measured_at, "views": 0, "reactions": 0})
        trend["views"] += metric.views
        trend["reactions"] += metric.likes + metric.comments + metric.saves + metric.shares

    trend = list(trend_map.values())
    max_views = max((row["views"] for row in trend), default=1)
    for row in trend:
        row["width"] = max(2, row["views"] / max_views * 100) if row["views"] else 0

    return page("""
<style>
.bar-track{height:18px;border-radius:99px;background:#eef0f5;overflow:hidden;min-width:120px}
.bar-fill{height:100%;background:linear-gradient(90deg,#4f46e5,#8b5cf6);border-radius:99px}
.metric-good{font-weight:700}
.mini-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.mini-card{border:1px solid #e5e7eb;border-radius:13px;padding:12px;background:#fafafa}
</style>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>AI 마케팅 센터 <span class="status">V14.0</span></h1>
      <p class="lead">직접 저장한 실제 성과를 브랜드, 채널, 콘텐츠별로 비교합니다.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn" href="{{url_for('marketing_v14.ideas')}}">아이디어 뱅크</a>
      <a class="btn gray" href="{{url_for('marketing_v14.shooting')}}">촬영 체크리스트</a>
      <a class="btn gray" href="{{url_for('marketing_v14.monthly_report')}}">월간 리포트</a>
    </div>
  </div>

  <form method="get" class="grid">
    <div>
      <label>분석 기간</label>
      <select name="days">
        {% for value,label in [(7,'최근 7일'),(30,'최근 30일'),(90,'최근 90일'),(365,'최근 1년')] %}
        <option value="{{value}}" {% if days == value %}selected{% endif %}>{{label}}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label>브랜드</label>
      <select name="brand">
        <option value="">전체 브랜드</option>
        {% for value in brands %}
        <option value="{{value}}" {% if brand == value %}selected{% endif %}>{{value}}</option>
        {% endfor %}
      </select>
    </div>
    <div style="align-self:end"><button class="btn" type="submit">분석 적용</button></div>
  </form>

  <div class="stat-grid">
    <div class="stat"><strong>{{"{:,}".format(totals.views)}}</strong><span class="small">조회수</span></div>
    <div class="stat"><strong>{{"{:.1f}%".format(totals.engagement_rate)}}</strong><span class="small">반응률</span></div>
    <div class="stat"><strong>{{"{:.1f}%".format(totals.save_rate)}}</strong><span class="small">저장률</span></div>
    <div class="stat"><strong>{{"{:.1f}%".format(totals.click_rate)}}</strong><span class="small">클릭률</span></div>
    <div class="stat"><strong>{{"{:,.0f}원".format(totals.revenue)}}</strong><span class="small">연결 수익</span></div>
  </div>
  <p class="notice">모든 계산은 성과 분석 화면에 입력된 실제 기록만 사용합니다.</p>
</section>

<div class="grid">
<section class="card">
  <h2>데이터 기반 추천</h2>
  {% for text in recommendations %}
  <div class="calendar-item">{{text}}</div>
  {% endfor %}
</section>

<section class="card">
  <h2>기간별 조회 흐름</h2>
  {% for row in trend %}
  <div style="display:grid;grid-template-columns:70px 1fr 75px;gap:10px;align-items:center;margin:9px 0">
    <span class="small">{{row.day.strftime('%m/%d')}}</span>
    <div class="bar-track"><div class="bar-fill" style="width:{{row.width}}%"></div></div>
    <strong>{{"{:,}".format(row.views)}}</strong>
  </div>
  {% else %}
  <p class="small">표시할 성과 흐름이 없습니다.</p>
  {% endfor %}
</section>
</div>

<section class="card">
  <h2>채널별 성과</h2>
  {% if channels %}
  <table>
    <thead><tr><th>채널</th><th>조회</th><th>반응률</th><th>저장률</th><th>클릭률</th><th>수익</th></tr></thead>
    <tbody>
    {% for row in channels %}
    <tr>
      <td><strong>{{row.name}}</strong></td>
      <td>{{"{:,}".format(row.views)}}</td>
      <td>{{"{:.1f}%".format(row.engagement_rate)}}</td>
      <td>{{"{:.1f}%".format(row.save_rate)}}</td>
      <td>{{"{:.1f}%".format(row.click_rate)}}</td>
      <td>{{"{:,.0f}원".format(row.revenue)}}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="small">선택 기간의 채널 데이터가 없습니다.</p>{% endif %}
</section>

<section class="card">
  <h2>브랜드별 성과</h2>
  {% if brand_rows %}
  <table>
    <thead><tr><th>브랜드</th><th>조회</th><th>반응</th><th>반응률</th><th>저장률</th><th>클릭률</th></tr></thead>
    <tbody>
    {% for row in brand_rows %}
    <tr>
      <td><strong>{{row.name}}</strong></td>
      <td>{{"{:,}".format(row.views)}}</td>
      <td>{{"{:,}".format(row.reactions)}}</td>
      <td>{{"{:.1f}%".format(row.engagement_rate)}}</td>
      <td>{{"{:.1f}%".format(row.save_rate)}}</td>
      <td>{{"{:.1f}%".format(row.click_rate)}}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="small">브랜드에 연결된 성과 데이터가 없습니다.</p>{% endif %}
</section>

<section class="card">
  <h2>반응이 좋은 콘텐츠</h2>
  {% if contents %}
  <table>
    <thead><tr><th>콘텐츠</th><th>브랜드</th><th>유형</th><th>조회</th><th>반응</th><th>저장</th><th>클릭</th></tr></thead>
    <tbody>
    {% for row in contents[:12] %}
    <tr>
      <td><strong>{{row.title}}</strong>{% if row.hook %}<div class="small">{{row.hook[:70]}}</div>{% endif %}</td>
      <td>{{row.brand}}</td>
      <td>{{row.content_type}}</td>
      <td>{{"{:,}".format(row.views)}}</td>
      <td>{{"{:,}".format(row.reactions)}}</td>
      <td>{{"{:,}".format(row.saves)}}</td>
      <td>{{"{:,}".format(row.clicks)}}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="small">분석할 콘텐츠가 없습니다.</p>{% endif %}
</section>
""",
        days=days, brand=brand, brands=BRANDS, totals=totals,
        channels=channels, brand_rows=brand_rows, contents=contents,
        recommendations=recommendations, trend=trend,
        page_title="AI 마케팅 센터 | MI Creator Hub",
    )


@marketing_bp.route("/ideas", methods=["GET", "POST"])
def ideas():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("아이디어 제목을 입력해 주세요.")
            return redirect(url_for("marketing_v14.ideas"))

        idea = MarketingIdea(
            title=title[:300],
            brand=request.form.get("brand", "말썽쟁이 딸랑구").strip()[:100],
            category=request.form.get("category", "일반").strip()[:100],
            content_type=request.form.get("content_type", "릴스·쇼츠").strip()[:50],
            hook=request.form.get("hook", "").strip(),
            angle=request.form.get("angle", "").strip(),
            tags=request.form.get("tags", "").strip(),
            priority=request.form.get("priority", "보통").strip(),
            status="아이디어",
        )
        if idea.priority not in IDEA_PRIORITIES:
            idea.priority = "보통"
        db.session.add(idea)
        db.session.commit()
        flash("아이디어를 저장했어요.")
        return redirect(url_for("marketing_v14.ideas"))

    brand = request.args.get("brand", "").strip()
    status = request.args.get("status", "").strip()
    query = MarketingIdea.query
    if brand:
        query = query.filter(MarketingIdea.brand == brand)
    if status:
        query = query.filter(MarketingIdea.status == status)
    rows = query.order_by(
        MarketingIdea.priority.asc(), MarketingIdea.updated_at.desc()
    ).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>콘텐츠 아이디어 뱅크</h1><p class="lead">번뜩인 아이디어를 놓치기 전에 저장합니다.</p></div>
    <a class="btn gray" href="{{url_for('marketing_v14.dashboard')}}">마케팅 센터</a>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>새 아이디어</h2>
  <form method="post">
    <label>아이디어 제목</label>
    <input name="title" required maxlength="300" placeholder="예: 과자 봉지가 반이나 비어 있는 이유">

    <div class="grid">
      <div><label>브랜드</label><select name="brand">{% for value in brands %}<option>{{value}}</option>{% endfor %}</select></div>
      <div><label>형식</label><select name="content_type">{% for value in content_types %}<option>{{value}}</option>{% endfor %}</select></div>
    </div>

    <div class="grid">
      <div><label>카테고리</label><input name="category" value="일반"></div>
      <div><label>우선순위</label><select name="priority">{% for value in priorities %}<option>{{value}}</option>{% endfor %}</select></div>
    </div>

    <label>첫 훅</label>
    <textarea name="hook" rows="3" placeholder="처음 1~2초에 보여줄 말"></textarea>
    <label>전개 방향</label>
    <textarea name="angle" rows="4" placeholder="어떤 상황과 결말로 풀지 적어주세요."></textarea>
    <label>태그</label>
    <input name="tags" placeholder="육아, 경제, 모녀코미디">
    <button class="btn" type="submit">아이디어 저장</button>
  </form>
</section>

<section class="card">
  <h2>필터</h2>
  <form method="get">
    <label>브랜드</label>
    <select name="brand"><option value="">전체</option>{% for value in brands %}<option value="{{value}}" {% if brand == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select>
    <label>상태</label>
    <select name="status"><option value="">전체</option>{% for value in statuses %}<option value="{{value}}" {% if status == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select>
    <button class="btn" type="submit">적용</button>
  </form>
</section>
</div>

<section class="card">
  <h2>저장된 아이디어 {{rows|length}}개</h2>
  {% for idea in rows %}
  <div class="calendar-item">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div>
        <strong>{{idea.title}}</strong>
        <div class="small">{{idea.brand}} · {{idea.content_type}} · {{idea.category}} · 우선순위 {{idea.priority}} · {{idea.status}}</div>
      </div>
      <div class="actions" style="margin-top:0">
        <form method="post" action="{{url_for('marketing_v14.idea_status', idea_id=idea.id)}}">
          <select name="status" onchange="this.form.submit()">{% for value in statuses %}<option value="{{value}}" {% if idea.status == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select>
        </form>
        <form method="post" action="{{url_for('marketing_v14.idea_to_library', idea_id=idea.id)}}"><button class="btn" type="submit">라이브러리로</button></form>
        <form method="post" action="{{url_for('marketing_v14.delete_idea', idea_id=idea.id)}}" onsubmit="return confirm('삭제할까요?')"><button class="btn gray" type="submit">삭제</button></form>
      </div>
    </div>
    {% if idea.hook %}<p><strong>훅:</strong> {{idea.hook}}</p>{% endif %}
    {% if idea.angle %}<p class="small">{{idea.angle}}</p>{% endif %}
  </div>
  {% else %}<p class="small">저장된 아이디어가 없습니다.</p>{% endfor %}
</section>
""",
        rows=rows, brands=BRANDS, content_types=CONTENT_TYPES,
        priorities=IDEA_PRIORITIES, statuses=IDEA_STATUSES,
        brand=brand, status=status,
        page_title="콘텐츠 아이디어 뱅크 | MI Creator Hub",
    )


@marketing_bp.post("/ideas/<int:idea_id>/status")
def idea_status(idea_id):
    idea = db.session.get(MarketingIdea, idea_id)
    if not idea:
        flash("아이디어를 찾을 수 없습니다.")
        return redirect(url_for("marketing_v14.ideas"))
    status = request.form.get("status", "").strip()
    if status in IDEA_STATUSES:
        idea.status = status
        db.session.commit()
    return redirect(url_for("marketing_v14.ideas"))


@marketing_bp.post("/ideas/<int:idea_id>/to-library")
def idea_to_library(idea_id):
    idea = db.session.get(MarketingIdea, idea_id)
    if not idea:
        flash("아이디어를 찾을 수 없습니다.")
        return redirect(url_for("marketing_v14.ideas"))

    item = ContentLibraryItem(
        title=idea.title,
        brand=idea.brand,
        category=idea.category,
        content_type=idea.content_type,
        status="기획",
        summary=idea.angle,
        hook=idea.hook,
        tags=idea.tags,
    )
    idea.status = "선정"
    db.session.add(item)
    db.session.commit()
    flash("아이디어를 콘텐츠 라이브러리에 기획 상태로 보냈어요.")
    return redirect(url_for("library_v11.detail", item_id=item.id))


@marketing_bp.post("/ideas/<int:idea_id>/delete")
def delete_idea(idea_id):
    idea = db.session.get(MarketingIdea, idea_id)
    if idea:
        db.session.delete(idea)
        db.session.commit()
        flash("아이디어를 삭제했어요.")
    return redirect(url_for("marketing_v14.ideas"))


def checklist_progress(row):
    fields = [
        row.location_ready, row.props_ready, row.cast_ready, row.script_ready,
        row.filming_done, row.editing_done, row.thumbnail_done, row.caption_done,
    ]
    return round(sum(bool(value) for value in fields) / len(fields) * 100)


@marketing_bp.get("/shooting")
def shooting():
    items = (
        ContentLibraryItem.query
        .filter(ContentLibraryItem.status.in_(["기획", "제작 중", "검토", "예약"]))
        .order_by(ContentLibraryItem.updated_at.desc())
        .all()
    )
    rows = []
    for item in items:
        checklist = item.shooting_checklist
        rows.append({"item": item, "checklist": checklist, "progress": checklist_progress(checklist) if checklist else 0})

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>촬영 체크리스트</h1><p class="lead">소품부터 자막까지 준비 상태를 한눈에 확인합니다.</p></div>
    <a class="btn gray" href="{{url_for('marketing_v14.dashboard')}}">마케팅 센터</a>
  </div>
</section>

<section class="card">
  {% for row in rows %}
  <div class="calendar-item">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div>
        <strong>{{row.item.title}}</strong>
        <div class="small">{{row.item.brand}} · {{row.item.content_type}} · {{row.item.status}}</div>
      </div>
      <div><strong>{{row.progress}}%</strong> <a class="btn" href="{{url_for('marketing_v14.edit_shooting', item_id=row.item.id)}}">체크하기</a></div>
    </div>
    <div style="height:8px;background:#eceef3;border-radius:99px;overflow:hidden;margin-top:10px">
      <div style="height:100%;width:{{row.progress}}%;background:linear-gradient(90deg,#4f46e5,#8b5cf6)"></div>
    </div>
  </div>
  {% else %}
  <p class="small">촬영 준비 중인 콘텐츠가 없습니다.</p>
  {% endfor %}
</section>
""",
        rows=rows,
        page_title="촬영 체크리스트 | MI Creator Hub",
    )


@marketing_bp.route("/shooting/<int:item_id>", methods=["GET", "POST"])
def edit_shooting(item_id):
    item = db.session.get(ContentLibraryItem, item_id)
    if not item:
        flash("콘텐츠를 찾을 수 없습니다.")
        return redirect(url_for("marketing_v14.shooting"))

    checklist = item.shooting_checklist
    if checklist is None:
        checklist = ShootingChecklist(library_item_id=item.id)
        db.session.add(checklist)
        db.session.flush()

    fields = [
        "location_ready", "props_ready", "cast_ready", "script_ready",
        "filming_done", "editing_done", "thumbnail_done", "caption_done",
    ]

    if request.method == "POST":
        for field in fields:
            setattr(checklist, field, request.form.get(field) == "on")
        checklist.location_note = request.form.get("location_note", "").strip()[:500]
        checklist.props_note = request.form.get("props_note", "").strip()[:1000]
        checklist.cast_note = request.form.get("cast_note", "").strip()[:500]
        checklist.editing_note = request.form.get("editing_note", "").strip()[:1000]
        db.session.commit()
        flash("촬영 체크리스트를 저장했어요.")
        return redirect(url_for("marketing_v14.shooting"))

    labels = [
        ("location_ready", "촬영 장소 준비"),
        ("props_ready", "소품 준비"),
        ("cast_ready", "출연자·의상 준비"),
        ("script_ready", "대본·컷 순서 확정"),
        ("filming_done", "촬영 완료"),
        ("editing_done", "편집 완료"),
        ("thumbnail_done", "커버·썸네일 완료"),
        ("caption_done", "캡션·CTA 완료"),
    ]

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>촬영 준비</h1><p class="lead">{{item.title}}</p></div>
    <a class="btn gray" href="{{url_for('marketing_v14.shooting')}}">목록</a>
  </div>
  <form method="post">
    <div class="mini-grid">
      {% for field,label in labels %}
      <label class="mini-card"><input type="checkbox" name="{{field}}" {% if checklist|attr(field) %}checked{% endif %}> <strong>{{label}}</strong></label>
      {% endfor %}
    </div>
    <label>장소 메모</label><input name="location_note" value="{{checklist.location_note or ''}}" placeholder="예: 거실 식탁, 창가 자연광">
    <label>소품 메모</label><textarea name="props_note" rows="3">{{checklist.props_note or ''}}</textarea>
    <label>출연자·의상 메모</label><input name="cast_note" value="{{checklist.cast_note or ''}}">
    <label>편집 메모</label><textarea name="editing_note" rows="4">{{checklist.editing_note or ''}}</textarea>
    <button class="btn" type="submit">체크리스트 저장</button>
  </form>
</section>
""",
        item=item, checklist=checklist, labels=labels,
        page_title="촬영 준비 | MI Creator Hub",
    )


@marketing_bp.get("/monthly-report")
def monthly_report():
    raw = request.args.get("month", date.today().strftime("%Y-%m"))
    try:
        year, month = map(int, raw.split("-"))
        start = date(year, month, 1)
    except (ValueError, TypeError):
        start = date.today().replace(day=1)
        raw = start.strftime("%Y-%m")
    end = date(start.year, start.month, monthrange(start.year, start.month)[1])

    metric_rows_data = (
        db.session.query(ContentMetric, Article, ContentLibraryItem)
        .join(Article, Article.id == ContentMetric.article_id)
        .outerjoin(ContentLibraryItem, ContentLibraryItem.article_id == Article.id)
        .filter(ContentMetric.measured_at.between(start, end))
        .all()
    )
    totals, channels, brand_rows, contents = summarize_metrics(metric_rows_data)

    created_count = ContentLibraryItem.query.filter(
        ContentLibraryItem.created_at >= datetime.combine(start, datetime.min.time()),
        ContentLibraryItem.created_at <= datetime.combine(end, datetime.max.time()),
    ).count()
    completed_count = ContentLibraryItem.query.filter(
        ContentLibraryItem.status == "게시 완료",
        ContentLibraryItem.updated_at >= datetime.combine(start, datetime.min.time()),
        ContentLibraryItem.updated_at <= datetime.combine(end, datetime.max.time()),
    ).count()
    active_count = ContentLibraryItem.query.filter(
        ContentLibraryItem.status.in_(["기획", "제작 중", "검토", "예약"])
    ).count()
    idea_count = MarketingIdea.query.filter(
        MarketingIdea.created_at >= datetime.combine(start, datetime.min.time()),
        MarketingIdea.created_at <= datetime.combine(end, datetime.max.time()),
    ).count()

    completion_rate = completed_count / created_count * 100 if created_count else 0

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>월간 운영 리포트</h1><p class="lead">{{start.strftime('%Y년 %m월')}} 실제 저장 데이터 요약입니다.</p></div>
    <a class="btn gray" href="{{url_for('marketing_v14.dashboard')}}">마케팅 센터</a>
  </div>
  <form method="get">
    <label>월 선택</label>
    <div class="actions"><input type="month" name="month" value="{{month_value}}"><button class="btn" type="submit">보기</button></div>
  </form>

  <div class="stat-grid">
    <div class="stat"><strong>{{created_count}}</strong><span class="small">새 콘텐츠</span></div>
    <div class="stat"><strong>{{completed_count}}</strong><span class="small">게시 완료</span></div>
    <div class="stat"><strong>{{"{:.1f}%".format(completion_rate)}}</strong><span class="small">완료율</span></div>
    <div class="stat"><strong>{{active_count}}</strong><span class="small">현재 진행 중</span></div>
    <div class="stat"><strong>{{idea_count}}</strong><span class="small">새 아이디어</span></div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>성과 요약</h2>
  <div class="calendar-item"><strong>조회수</strong> {{'{:,}'.format(totals.views)}}</div>
  <div class="calendar-item"><strong>반응률</strong> {{'{:.1f}%'.format(totals.engagement_rate)}}</div>
  <div class="calendar-item"><strong>저장률</strong> {{'{:.1f}%'.format(totals.save_rate)}}</div>
  <div class="calendar-item"><strong>클릭률</strong> {{'{:.1f}%'.format(totals.click_rate)}}</div>
  <div class="calendar-item"><strong>연결 수익</strong> {{'{:,.0f}원'.format(totals.revenue)}}</div>
</section>

<section class="card">
  <h2>운영 해석</h2>
  {% if not totals.records %}
  <p class="small">이달의 성과 입력이 없어 조회·반응 분석은 비어 있습니다.</p>
  {% else %}
  <p>입력된 성과 기록은 총 {{totals.records}}건입니다.</p>
  {% if contents %}<p>가장 반응이 높은 콘텐츠는 <strong>{{contents[0].title}}</strong>입니다.</p>{% endif %}
  {% if channels %}<p>현재 반응률이 가장 높은 채널은 <strong>{{channels[0].name}}</strong>입니다.</p>{% endif %}
  {% endif %}
  <p class="notice">리포트는 자동 게시 여부를 확인하지 않습니다. 앱에 저장된 상태와 성과 기록을 기준으로 계산합니다.</p>
</section>
</div>

<section class="card">
  <h2>브랜드별 월간 성과</h2>
  {% if brand_rows %}
  <table>
    <thead><tr><th>브랜드</th><th>조회</th><th>반응률</th><th>저장률</th><th>클릭률</th><th>수익</th></tr></thead>
    <tbody>{% for row in brand_rows %}<tr>
      <td><strong>{{row.name}}</strong></td><td>{{'{:,}'.format(row.views)}}</td>
      <td>{{'{:.1f}%'.format(row.engagement_rate)}}</td><td>{{'{:.1f}%'.format(row.save_rate)}}</td>
      <td>{{'{:.1f}%'.format(row.click_rate)}}</td><td>{{'{:,.0f}원'.format(row.revenue)}}</td>
    </tr>{% endfor %}</tbody>
  </table>
  {% else %}<p class="small">브랜드별 성과가 없습니다.</p>{% endif %}
</section>
""",
        start=start, month_value=raw, totals=totals, channels=channels,
        brand_rows=brand_rows, contents=contents, created_count=created_count,
        completed_count=completed_count, active_count=active_count,
        idea_count=idea_count, completion_rate=completion_rate,
        page_title="월간 운영 리포트 | MI Creator Hub",
    )
