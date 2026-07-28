"""V9.4.1 content calendar, scheduling workflow, and operations dashboard."""
import calendar as calendar_module
from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template_string, request, url_for
from markupsafe import Markup
from sqlalchemy import func

from ..legacy_app import BASE_HTML, Article, PublishLog, db
from .business import FinanceEntry, INCOME_CATEGORIES
from .planner import WeeklyPlanItem


calendar_bp = Blueprint("calendar_v94", __name__, url_prefix="/calendar")

WORKFLOW_STATUSES = ["기획", "초안", "검토", "예약", "발행완료"]
STATUS_LABELS = {
    "기획": "기획",
    "초안": "초안",
    "검토": "검토",
    "예약": "예약",
    "발행완료": "발행완료",
}


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def parse_month(value):
    today = date.today()
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError):
        return today.replace(day=1)


def month_shift(month_start, amount):
    year = month_start.year
    month = month_start.month + amount
    while month < 1:
        year -= 1
        month += 12
    while month > 12:
        year += 1
        month -= 12
    return date(year, month, 1)


def month_days(month_start):
    cal = calendar_module.Calendar(firstweekday=0)
    return list(cal.monthdatescalendar(month_start.year, month_start.month))


def normalize_status(item):
    if item.status in WORKFLOW_STATUSES:
        return item.status
    if item.article_id:
        return "초안"
    return "기획"


@calendar_bp.get("/")
def dashboard():
    month_start = parse_month(request.args.get("month"))
    month_end = month_shift(month_start, 1) - timedelta(days=1)

    items = WeeklyPlanItem.query.filter(
        WeeklyPlanItem.plan_date >= month_start,
        WeeklyPlanItem.plan_date <= month_end,
    ).order_by(WeeklyPlanItem.plan_date.asc(), WeeklyPlanItem.id.asc()).all()

    by_date = {}
    for item in items:
        item.status = normalize_status(item)
        by_date.setdefault(item.plan_date, []).append(item)

    today = date.today()
    today_count = WeeklyPlanItem.query.filter_by(plan_date=today).count()
    scheduled_count = WeeklyPlanItem.query.filter_by(status="예약").count()
    review_count = WeeklyPlanItem.query.filter_by(status="검토").count()
    published_count = WeeklyPlanItem.query.filter_by(status="발행완료").count()

    month_revenue = db.session.query(func.coalesce(func.sum(FinanceEntry.amount), 0)).filter(
        FinanceEntry.category.in_(list(INCOME_CATEGORIES.keys())),
        FinanceEntry.entry_date >= month_start,
        FinanceEntry.entry_date <= month_end,
    ).scalar() or 0

    return page("""
<style>
.calendar-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px}
.calendar-head{font-weight:700;text-align:center;padding:10px 4px}
.calendar-day{min-height:150px;border:1px solid #e8e8e8;border-radius:14px;padding:9px;background:#fff}
.calendar-day.outside{opacity:.42;background:#fafafa}
.calendar-day.today{outline:2px solid #111}
.day-number{font-weight:800;margin-bottom:7px}
.plan-chip{border:1px solid #ddd;border-radius:10px;padding:7px;margin:6px 0;background:#fafafa;cursor:grab}
.plan-chip:active{cursor:grabbing}
.plan-title{font-size:13px;font-weight:700;line-height:1.35}
.plan-meta{font-size:11px;color:#666;margin-top:4px}
.status-dot{display:inline-block;padding:2px 7px;border-radius:999px;background:#ececec;font-size:10px;margin-top:5px}
.drop-ready{outline:2px dashed #555;background:#f7f7f7}
.stat-row{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}
.stat-box{border:1px solid #e8e8e8;border-radius:14px;padding:16px;background:#fff}
.stat-num{font-size:26px;font-weight:900;margin-top:5px}
@media(max-width:900px){
  .calendar-grid{grid-template-columns:1fr}
  .calendar-head{display:none}
  .calendar-day{min-height:auto}
  .stat-row{grid-template-columns:1fr 1fr}
}
</style>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>콘텐츠 캘린더 <span class="status">V9.4.1</span></h1>
      <p class="lead">기획부터 초안, 검토, 예약, 발행완료까지 한 달 흐름을 한눈에 관리해요.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('planner_v93.dashboard')}}">주간 플래너</a>
      <a class="btn gray" href="{{url_for('home')}}">홈으로</a>
    </div>
  </div>
</section>

<section class="card">
  <h2>운영 현황</h2>
  <div class="stat-row">
    <div class="stat-box"><div class="small">오늘 일정</div><div class="stat-num">{{today_count}}</div></div>
    <div class="stat-box"><div class="small">검토 대기</div><div class="stat-num">{{review_count}}</div></div>
    <div class="stat-box"><div class="small">예약</div><div class="stat-num">{{scheduled_count}}</div></div>
    <div class="stat-box"><div class="small">발행완료</div><div class="stat-num">{{published_count}}</div></div>
    <div class="stat-box"><div class="small">이번 달 수익</div><div class="stat-num">{{"{:,.0f}".format(month_revenue)}}원</div></div>
  </div>
</section>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('calendar_v94.dashboard', month=prev_month)}}">이전 달</a>
      <a class="btn gray" href="{{url_for('calendar_v94.dashboard', month=current_month)}}">이번 달</a>
      <a class="btn gray" href="{{url_for('calendar_v94.dashboard', month=next_month)}}">다음 달</a>
    </div>
    <h2>{{month_start.strftime('%Y년 %m월')}}</h2>
  </div>

  <div class="calendar-grid">
    {% for weekday in ['월','화','수','목','금','토','일'] %}
      <div class="calendar-head">{{weekday}}</div>
    {% endfor %}

    {% for week in weeks %}
      {% for day in week %}
      <div class="calendar-day {% if day.month != month_start.month %}outside{% endif %} {% if day == today %}today{% endif %}"
           data-date="{{day.isoformat()}}">
        <div class="day-number">{{day.day}}</div>

        {% for item in by_date.get(day, []) %}
        <div class="plan-chip" draggable="true" data-item-id="{{item.id}}">
          <div class="plan-title">{{item.title}}</div>
          <div class="plan-meta">{{item.format_type}} · {{item.brand_name}}</div>
          <span class="status-dot">{{item.status}}</span>

          <form method="post" action="{{url_for('calendar_v94.update_item', item_id=item.id)}}" style="margin-top:7px">
            <select name="status" style="font-size:12px;padding:5px">
              {% for status in statuses %}
              <option value="{{status}}" {% if item.status == status %}selected{% endif %}>{{status}}</option>
              {% endfor %}
            </select>
            <input type="datetime-local" name="scheduled_at"
                   value="{% if item.article and item.article.scheduled_at %}{{item.article.scheduled_at.strftime('%Y-%m-%dT%H:%M')}}{% endif %}"
                   style="font-size:12px;padding:5px">
            <button class="btn gray" type="submit" style="padding:5px 8px;font-size:11px">저장</button>
          </form>

          <div class="actions" style="margin-top:6px">
            {% if item.article_id %}
            <a class="btn gray" href="{{url_for('edit_article', article_id=item.article_id)}}" style="padding:5px 8px;font-size:11px">콘텐츠 열기</a>
            {% else %}
            <a class="btn gray" href="{{url_for('planner_v93.dashboard', start=item.plan_date.isoformat())}}" style="padding:5px 8px;font-size:11px">초안 만들기</a>
            {% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
      {% endfor %}
    {% endfor %}
  </div>

  <p class="notice">일정을 다른 날짜 칸으로 끌어다 놓으면 날짜가 변경됩니다. 예약 상태는 실제 자동 발행이 아니라, 미경님이 확인한 콘텐츠의 예약 준비 상태입니다.</p>
</section>

<script>
let draggedId = null;

document.querySelectorAll('.plan-chip').forEach((chip) => {
  chip.addEventListener('dragstart', () => {
    draggedId = chip.dataset.itemId;
  });
});

document.querySelectorAll('.calendar-day').forEach((day) => {
  day.addEventListener('dragover', (event) => {
    event.preventDefault();
    day.classList.add('drop-ready');
  });
  day.addEventListener('dragleave', () => day.classList.remove('drop-ready'));
  day.addEventListener('drop', async (event) => {
    event.preventDefault();
    day.classList.remove('drop-ready');
    if (!draggedId) return;

    const response = await fetch(`/calendar/items/${draggedId}/move`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({plan_date: day.dataset.date})
    });

    if (response.ok) {
      window.location.reload();
    } else {
      const data = await response.json().catch(() => ({}));
      alert(data.error || '날짜 변경에 실패했습니다.');
    }
  });
});
</script>
""",
        month_start=month_start,
        weeks=month_days(month_start),
        by_date=by_date,
        today=today,
        statuses=WORKFLOW_STATUSES,
        today_count=today_count,
        review_count=review_count,
        scheduled_count=scheduled_count,
        published_count=published_count,
        month_revenue=month_revenue,
        prev_month=month_shift(month_start, -1).strftime("%Y-%m"),
        current_month=date.today().strftime("%Y-%m"),
        next_month=month_shift(month_start, 1).strftime("%Y-%m"),
        page_title="콘텐츠 캘린더 | MI Creator Hub",
    )


@calendar_bp.post("/items/<int:item_id>/move")
def move_item(item_id):
    item = db.session.get(WeeklyPlanItem, item_id)
    if not item:
        return jsonify({"error": "기획 항목을 찾을 수 없습니다."}), 404

    payload = request.get_json(silent=True) or {}
    try:
        new_date = datetime.strptime(payload.get("plan_date", ""), "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "날짜 형식이 올바르지 않습니다."}), 400

    item.plan_date = new_date
    if item.article and item.article.scheduled_at:
        old_time = item.article.scheduled_at.time()
        item.article.scheduled_at = datetime.combine(new_date, old_time)

    db.session.commit()
    return jsonify({"status": "ok", "plan_date": new_date.isoformat()})


@calendar_bp.post("/items/<int:item_id>/update")
def update_item(item_id):
    item = db.session.get(WeeklyPlanItem, item_id)
    if not item:
        flash("기획 항목을 찾을 수 없습니다.")
        return redirect(url_for("calendar_v94.dashboard"))

    status = request.form.get("status", "기획").strip()
    if status not in WORKFLOW_STATUSES:
        status = "기획"

    scheduled_value = request.form.get("scheduled_at", "").strip()
    scheduled_at = None
    if scheduled_value:
        try:
            scheduled_at = datetime.strptime(scheduled_value, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("예약 날짜와 시간을 확인해 주세요.")
            return redirect(url_for("calendar_v94.dashboard", month=item.plan_date.strftime("%Y-%m")))

    if status == "예약" and not item.article_id:
        flash("먼저 AI 초안을 만든 뒤 예약 상태로 변경해 주세요.")
        return redirect(url_for("calendar_v94.dashboard", month=item.plan_date.strftime("%Y-%m")))

    if status == "예약" and not scheduled_at:
        flash("예약 상태에는 예약 날짜와 시간이 필요합니다.")
        return redirect(url_for("calendar_v94.dashboard", month=item.plan_date.strftime("%Y-%m")))

    item.status = status

    if item.article:
        item.article.scheduled_at = scheduled_at
        if status == "발행완료":
            item.article.blog_done = True
        elif status != "예약" and not scheduled_at:
            item.article.scheduled_at = None

    db.session.commit()
    flash("콘텐츠 상태와 일정을 저장했어요.")
    return redirect(url_for("calendar_v94.dashboard", month=item.plan_date.strftime("%Y-%m")))


@calendar_bp.get("/operations")
def operations():
    today = date.today()
    month_start = today.replace(day=1)
    month_end = month_shift(month_start, 1) - timedelta(days=1)

    total_articles = Article.query.count()
    this_month_articles = Article.query.filter(
        Article.created_at >= datetime.combine(month_start, time.min),
        Article.created_at <= datetime.combine(month_end, time.max),
    ).count()

    scheduled = Article.query.filter(Article.scheduled_at.isnot(None)).count()
    published = Article.query.filter(
        (Article.blog_done.is_(True)) |
        (Article.instagram_done.is_(True)) |
        (Article.threads_done.is_(True)) |
        (Article.shorts_done.is_(True))
    ).count()

    recent = Article.query.order_by(Article.updated_at.desc()).limit(10).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>운영 대시보드 <span class="status">V9.4.1</span></h1>
      <p class="lead">작성, 예약, 발행 현황을 빠르게 확인하는 관리자 화면입니다.</p>
    </div>
    <a class="btn gray" href="{{url_for('calendar_v94.dashboard')}}">캘린더로</a>
  </div>
</section>

<section class="card">
  <div class="grid">
    <div class="calendar-item"><div class="small">전체 콘텐츠</div><h2>{{total_articles}}</h2></div>
    <div class="calendar-item"><div class="small">이번 달 생성</div><h2>{{this_month_articles}}</h2></div>
    <div class="calendar-item"><div class="small">예약 시간 있음</div><h2>{{scheduled}}</h2></div>
    <div class="calendar-item"><div class="small">한 채널 이상 완료</div><h2>{{published}}</h2></div>
  </div>
</section>

<section class="card">
  <h2>최근 수정한 콘텐츠</h2>
  {% if recent %}
  <table>
    <thead><tr><th>제목</th><th>SEO</th><th>예약</th><th></th></tr></thead>
    <tbody>
    {% for article in recent %}
    <tr>
      <td><strong>{{article.title}}</strong><div class="small">{{article.updated_at.strftime('%Y-%m-%d %H:%M')}}</div></td>
      <td>{{article.seo_score}}</td>
      <td>{% if article.scheduled_at %}{{article.scheduled_at.strftime('%Y-%m-%d %H:%M')}}{% else %}-{% endif %}</td>
      <td><a class="btn gray" href="{{url_for('edit_article',article_id=article.id)}}">열기</a></td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="small">아직 콘텐츠가 없습니다.</p>
  {% endif %}
</section>
""",
        total_articles=total_articles,
        this_month_articles=this_month_articles,
        scheduled=scheduled,
        published=published,
        recent=recent,
        page_title="운영 대시보드 | MI Creator Hub",
    )
