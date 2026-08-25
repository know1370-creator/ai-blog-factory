"""V9.5 manual content performance analytics."""
from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup
from sqlalchemy import func

from ..legacy_app import BASE_HTML, Article, db


analytics_bp = Blueprint("analytics_v95", __name__, url_prefix="/analytics")


class ContentMetric(db.Model):
    __tablename__ = "content_metric"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False, index=True)
    channel = db.Column(db.String(30), nullable=False, default="blog")
    measured_at = db.Column(db.Date, nullable=False, default=date.today, index=True)
    views = db.Column(db.Integer, nullable=False, default=0)
    likes = db.Column(db.Integer, nullable=False, default=0)
    comments = db.Column(db.Integer, nullable=False, default=0)
    saves = db.Column(db.Integer, nullable=False, default=0)
    shares = db.Column(db.Integer, nullable=False, default=0)
    clicks = db.Column(db.Integer, nullable=False, default=0)
    revenue = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    memo = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    article = db.relationship(
        "Article",
        backref=db.backref("performance_metrics", lazy=True, cascade="all, delete-orphan"),
    )


CHANNELS = {
    "blog": "블로그",
    "instagram": "인스타그램",
    "threads": "Threads",
    "shorts": "릴스·쇼츠",
}


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def nonnegative_int(name):
    raw = request.form.get(name, "0").replace(",", "").strip()
    value = int(raw or 0)
    if value < 0:
        raise ValueError
    return value


def recommendations(rows):
    if not rows:
        return [
            "아직 성과 기록이 없습니다. 먼저 발행한 콘텐츠 3개 정도의 조회수와 저장 수를 입력해 보세요.",
            "플랫폼마다 같은 시점의 수치를 입력하면 비교가 더 정확해집니다.",
            "성과는 자동 추측하지 않고 미경님이 확인한 실제 값만 사용합니다.",
        ]

    channel_stats = {}
    article_stats = {}

    for metric, article in rows:
        engagement = metric.likes + metric.comments + metric.saves + metric.shares

        channel = channel_stats.setdefault(
            metric.channel, {"views": 0, "engagement": 0, "clicks": 0}
        )
        channel["views"] += metric.views
        channel["engagement"] += engagement
        channel["clicks"] += metric.clicks

        item = article_stats.setdefault(
            article.id, {"title": article.title, "views": 0, "engagement": 0}
        )
        item["views"] += metric.views
        item["engagement"] += engagement

    best_channel_key, best_channel = max(
        channel_stats.items(),
        key=lambda row: (
            row[1]["engagement"] / max(row[1]["views"], 1),
            row[1]["views"],
        ),
    )
    best_article = max(
        article_stats.values(),
        key=lambda row: (row["engagement"], row["views"]),
    )

    rate = best_channel["engagement"] / max(best_channel["views"], 1) * 100
    return [
        f"{CHANNELS.get(best_channel_key, best_channel_key)} 채널의 입력 기록상 반응률이 가장 높습니다. 현재 약 {rate:.1f}%입니다.",
        f"현재 가장 반응이 좋은 콘텐츠는 ‘{best_article['title']}’입니다. 제목의 핵심 단어와 첫 훅을 다음 콘텐츠에 변주해 보세요.",
        "조회수만 보지 말고 저장, 공유, 클릭을 함께 비교하면 실제 구매나 재방문 가능성을 보기 좋습니다.",
    ]


@analytics_bp.get("/")
def dashboard():
    rows = (
        db.session.query(ContentMetric, Article)
        .join(Article, Article.id == ContentMetric.article_id)
        .order_by(ContentMetric.measured_at.desc(), ContentMetric.id.desc())
        .all()
    )

    totals = {
        "views": sum(metric.views for metric, _ in rows),
        "likes": sum(metric.likes for metric, _ in rows),
        "comments": sum(metric.comments for metric, _ in rows),
        "saves": sum(metric.saves for metric, _ in rows),
        "shares": sum(metric.shares for metric, _ in rows),
        "clicks": sum(metric.clicks for metric, _ in rows),
        "revenue": sum(float(metric.revenue or 0) for metric, _ in rows),
    }
    engagement = totals["likes"] + totals["comments"] + totals["saves"] + totals["shares"]
    totals["engagement_rate"] = engagement / totals["views"] * 100 if totals["views"] else 0
    totals["click_rate"] = totals["clicks"] / totals["views"] * 100 if totals["views"] else 0

    channel_rows = (
        db.session.query(
            ContentMetric.channel,
            func.coalesce(func.sum(ContentMetric.views), 0),
            func.coalesce(
                func.sum(
                    ContentMetric.likes
                    + ContentMetric.comments
                    + ContentMetric.saves
                    + ContentMetric.shares
                ),
                0,
            ),
            func.coalesce(func.sum(ContentMetric.clicks), 0),
            func.coalesce(func.sum(ContentMetric.revenue), 0),
        )
        .group_by(ContentMetric.channel)
        .all()
    )

    channel_summary = []
    for channel, views, reactions, clicks, revenue in channel_rows:
        views = int(views or 0)
        reactions = int(reactions or 0)
        channel_summary.append(
            {
                "channel": CHANNELS.get(channel, channel),
                "views": views,
                "reactions": reactions,
                "rate": reactions / views * 100 if views else 0,
                "clicks": int(clicks or 0),
                "revenue": float(revenue or 0),
            }
        )

    articles = Article.query.order_by(Article.created_at.desc()).limit(200).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>콘텐츠 성과 분석 <span class="status">V9.5</span></h1>
      <p class="lead">실제 조회수와 반응을 기록하고, 다음 콘텐츠 방향을 데이터로 찾아요.</p>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{"{:,}".format(totals.views)}}</strong><span class="small">총 조회수</span></div>
    <div class="stat"><strong>{{"{:.1f}%".format(totals.engagement_rate)}}</strong><span class="small">전체 반응률</span></div>
    <div class="stat"><strong>{{"{:.1f}%".format(totals.click_rate)}}</strong><span class="small">클릭률</span></div>
    <div class="stat"><strong>{{"{:,.0f}원".format(totals.revenue)}}</strong><span class="small">연결 수익</span></div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>성과 입력</h2>
  <form method="post" action="{{url_for('analytics_v95.add_metric')}}">
    <label>콘텐츠</label>
    <select name="article_id" required>
      <option value="">선택해 주세요</option>
      {% for article in articles %}
      <option value="{{article.id}}">{{article.title}}</option>
      {% endfor %}
    </select>

    <div class="grid">
      <div>
        <label>채널</label>
        <select name="channel">
          {% for key,label in channels.items() %}
          <option value="{{key}}">{{label}}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label>측정일</label>
        <input type="date" name="measured_at" value="{{today.isoformat()}}" required>
      </div>
    </div>

    <div class="grid">
      <div><label>조회수</label><input type="number" min="0" name="views" value="0"></div>
      <div><label>좋아요</label><input type="number" min="0" name="likes" value="0"></div>
      <div><label>댓글</label><input type="number" min="0" name="comments" value="0"></div>
      <div><label>저장</label><input type="number" min="0" name="saves" value="0"></div>
      <div><label>공유</label><input type="number" min="0" name="shares" value="0"></div>
      <div><label>클릭</label><input type="number" min="0" name="clicks" value="0"></div>
    </div>

    <label>연결 수익</label>
    <input type="number" min="0" step="1" name="revenue" value="0">

    <label>메모</label>
    <input name="memo" maxlength="500" placeholder="예: 업로드 48시간 후 수치">

    <div class="actions"><button class="btn" type="submit">성과 저장</button></div>
  </form>
  <p class="notice">각 플랫폼에서 직접 확인한 실제 값만 입력해 주세요.</p>
</section>

<section class="card">
  <h2>데이터 기반 추천</h2>
  {% for text in recommendations %}
  <div class="calendar-item">{{text}}</div>
  {% endfor %}
</section>
</div>

<section class="card">
  <h2>채널별 성과</h2>
  {% if channel_summary %}
  <table>
    <thead><tr><th>채널</th><th>조회수</th><th>반응</th><th>반응률</th><th>클릭</th><th>수익</th></tr></thead>
    <tbody>
    {% for row in channel_summary %}
    <tr>
      <td><strong>{{row.channel}}</strong></td>
      <td>{{"{:,}".format(row.views)}}</td>
      <td>{{"{:,}".format(row.reactions)}}</td>
      <td>{{"{:.1f}%".format(row.rate)}}</td>
      <td>{{"{:,}".format(row.clicks)}}</td>
      <td>{{"{:,.0f}원".format(row.revenue)}}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="small">아직 채널별 성과가 없습니다.</p>
  {% endif %}
</section>

<section class="card">
  <h2>최근 성과 기록</h2>
  {% if rows %}
  <table>
    <thead><tr><th>날짜</th><th>콘텐츠</th><th>채널</th><th>조회수</th><th>저장</th><th>클릭</th><th></th></tr></thead>
    <tbody>
    {% for metric,article in rows[:30] %}
    <tr>
      <td>{{metric.measured_at.strftime('%Y-%m-%d')}}</td>
      <td><strong>{{article.title}}</strong></td>
      <td>{{channels.get(metric.channel, metric.channel)}}</td>
      <td>{{"{:,}".format(metric.views)}}</td>
      <td>{{"{:,}".format(metric.saves)}}</td>
      <td>{{"{:,}".format(metric.clicks)}}</td>
      <td>
        <form method="post" action="{{url_for('analytics_v95.delete_metric', metric_id=metric.id)}}" onsubmit="return confirm('이 기록을 삭제할까요?')">
          <button class="btn red" type="submit">삭제</button>
        </form>
      </td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="small">아직 저장된 성과 기록이 없습니다.</p>
  {% endif %}
</section>
""",
        totals=totals,
        channels=CHANNELS,
        channel_summary=channel_summary,
        articles=articles,
        rows=rows,
        recommendations=recommendations(rows),
        today=date.today(),
        page_title="콘텐츠 성과 분석 | MI Creator OS",
    )


@analytics_bp.post("/add")
def add_metric():
    try:
        article_id = int(request.form.get("article_id", ""))
        article = db.session.get(Article, article_id)
        if not article:
            raise ValueError

        channel = request.form.get("channel", "blog").strip()
        if channel not in CHANNELS:
            channel = "blog"

        measured_at = datetime.strptime(
            request.form.get("measured_at", ""), "%Y-%m-%d"
        ).date()

        revenue_raw = request.form.get("revenue", "0").replace(",", "").strip()
        revenue = float(revenue_raw or 0)
        if revenue < 0:
            raise ValueError

        metric = ContentMetric(
            article_id=article.id,
            channel=channel,
            measured_at=measured_at,
            views=nonnegative_int("views"),
            likes=nonnegative_int("likes"),
            comments=nonnegative_int("comments"),
            saves=nonnegative_int("saves"),
            shares=nonnegative_int("shares"),
            clicks=nonnegative_int("clicks"),
            revenue=revenue,
            memo=request.form.get("memo", "").strip()[:500],
        )
        db.session.add(metric)
        db.session.commit()
        flash("콘텐츠 성과를 저장했어요.")
    except (TypeError, ValueError):
        db.session.rollback()
        flash("입력값을 확인해 주세요. 숫자는 0 이상이어야 합니다.")
    except Exception as exc:
        db.session.rollback()
        flash(f"성과 저장 실패: {exc}")

    return redirect(url_for("analytics_v95.dashboard"))


@analytics_bp.post("/<int:metric_id>/delete")
def delete_metric(metric_id):
    metric = db.session.get(ContentMetric, metric_id)
    if not metric:
        flash("성과 기록을 찾을 수 없습니다.")
        return redirect(url_for("analytics_v95.dashboard"))

    db.session.delete(metric)
    db.session.commit()
    flash("성과 기록을 삭제했어요.")
    return redirect(url_for("analytics_v95.dashboard"))
