"""V13.0 content pipeline, Kanban board, and daily operations brief."""
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template_string, request, url_for
from markupsafe import Markup
from sqlalchemy import case, func

from ..legacy_app import BASE_HTML, db
from .library import BRANDS, ContentLibraryItem


pipeline_bp = Blueprint("pipeline_v13", __name__, url_prefix="/pipeline")


PIPELINE_STATUSES = ["기획", "제작 중", "검토", "예약", "게시 완료", "보류"]
ACTIVE_STATUSES = ["기획", "제작 중", "검토", "예약"]
PRIORITIES = ["높음", "보통", "낮음"]

STATUS_PROGRESS = {
    "기획": 10,
    "제작 중": 40,
    "검토": 70,
    "예약": 90,
    "게시 완료": 100,
    "보류": 0,
}


class PipelineMeta(db.Model):
    __tablename__ = "pipeline_meta"

    id = db.Column(db.Integer, primary_key=True)
    library_item_id = db.Column(
        db.Integer,
        db.ForeignKey("content_library_item.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    priority = db.Column(db.String(20), nullable=False, default="보통")
    due_date = db.Column(db.Date, nullable=True, index=True)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    owner_note = db.Column(db.Text, default="")
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    item = db.relationship(
        "ContentLibraryItem",
        backref=db.backref("pipeline_meta", uselist=False, cascade="all, delete-orphan"),
    )


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def get_or_create_meta(item):
    meta = item.pipeline_meta
    if meta is None:
        meta = PipelineMeta(library_item_id=item.id)
        db.session.add(meta)
        db.session.flush()
    return meta


def parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    return datetime.strptime(raw, "%Y-%m-%d").date()


def project_score(item):
    meta = item.pipeline_meta
    priority_weight = {"높음": 30, "보통": 15, "낮음": 5}.get(
        meta.priority if meta else "보통", 15
    )
    status_weight = {
        "검토": 35,
        "제작 중": 30,
        "예약": 25,
        "기획": 20,
        "보류": 0,
        "게시 완료": -100,
    }.get(item.status, 10)

    due_weight = 0
    if meta and meta.due_date:
        days = (meta.due_date - date.today()).days
        if days < 0:
            due_weight = 50
        elif days == 0:
            due_weight = 40
        elif days <= 2:
            due_weight = 25
        elif days <= 7:
            due_weight = 10

    return priority_weight + status_weight + due_weight


def build_daily_tasks(items):
    active = [item for item in items if item.status in ACTIVE_STATUSES]
    ordered = sorted(active, key=project_score, reverse=True)
    tasks = []

    for item in ordered[:7]:
        meta = item.pipeline_meta
        due_text = ""
        if meta and meta.due_date:
            days = (meta.due_date - date.today()).days
            if days < 0:
                due_text = f"{abs(days)}일 지연"
            elif days == 0:
                due_text = "오늘 마감"
            else:
                due_text = f"{days}일 남음"

        action = {
            "기획": "훅과 핵심 메시지를 확정하세요.",
            "제작 중": "대본·이미지·본문 중 미완성 부분을 마무리하세요.",
            "검토": "표현, 사실, CTA와 오탈자를 최종 확인하세요.",
            "예약": "게시 시간과 링크를 다시 확인하세요.",
        }.get(item.status, "다음 작업을 확인하세요.")

        tasks.append({
            "item": item,
            "action": action,
            "due_text": due_text,
            "priority": meta.priority if meta else "보통",
        })
    return tasks


@pipeline_bp.get("/")
def board():
    brand = request.args.get("brand", "").strip()
    q = request.args.get("q", "").strip()

    query = ContentLibraryItem.query
    if brand:
        query = query.filter(ContentLibraryItem.brand == brand)
    if q:
        query = query.filter(ContentLibraryItem.title.ilike(f"%{q}%"))

    priority_order = case(
        (PipelineMeta.priority == "높음", 1),
        (PipelineMeta.priority == "보통", 2),
        else_=3,
    )

    items = (
        query.outerjoin(PipelineMeta, PipelineMeta.library_item_id == ContentLibraryItem.id)
        .order_by(
            priority_order,
            PipelineMeta.due_date.asc().nullslast(),
            ContentLibraryItem.updated_at.desc(),
        )
        .all()
    )

    columns = {status: [] for status in PIPELINE_STATUSES}
    for item in items:
        columns.setdefault(item.status, []).append(item)

    active_count = sum(len(columns.get(status, [])) for status in ACTIVE_STATUSES)
    completed_count = len(columns.get("게시 완료", []))
    overdue_count = sum(
        1
        for item in items
        if item.pipeline_meta
        and item.pipeline_meta.due_date
        and item.pipeline_meta.due_date < date.today()
        and item.status != "게시 완료"
    )
    due_today_count = sum(
        1
        for item in items
        if item.pipeline_meta
        and item.pipeline_meta.due_date == date.today()
        and item.status != "게시 완료"
    )

    tasks = build_daily_tasks(items)

    return page("""
<style>
.pipeline-wrap{overflow-x:auto;padding-bottom:12px}
.pipeline-board{display:grid;grid-template-columns:repeat(6,minmax(260px,1fr));gap:14px;min-width:1640px}
.pipeline-column{background:#f7f7fb;border:1px solid #e5e7eb;border-radius:16px;padding:12px;min-height:420px}
.pipeline-column.drag-over{outline:3px solid rgba(90,100,220,.25);background:#f0f1ff}
.pipeline-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.pipeline-card{background:white;border:1px solid #e5e7eb;border-radius:14px;padding:12px;margin-bottom:10px;cursor:grab;box-shadow:0 3px 10px rgba(0,0,0,.04)}
.pipeline-card:active{cursor:grabbing}
.pipeline-card.dragging{opacity:.45}
.progress-track{height:7px;background:#eceef3;border-radius:99px;overflow:hidden;margin:9px 0}
.progress-fill{height:100%;background:linear-gradient(90deg,#4f46e5,#7c3aed)}
.priority-high{border-left:5px solid #dc2626}
.priority-normal{border-left:5px solid #f59e0b}
.priority-low{border-left:5px solid #64748b}
.due-over{font-weight:700;color:#b91c1c}
.due-today{font-weight:700;color:#c2410c}
.task-row{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid #eceef3}
.task-num{display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:#111827;color:white;font-weight:700;flex:0 0 auto}
@media(max-width:800px){.pipeline-board{grid-template-columns:repeat(6,250px)}}
</style>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>콘텐츠 파이프라인 <span class="status">V13.0</span></h1>
      <p class="lead">카드를 끌어서 기획부터 게시 완료까지 흐름을 관리합니다.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn" href="{{url_for('generator_v12.dashboard')}}">AI 프로젝트 생성</a>
      <a class="btn gray" href="{{url_for('library_v11.dashboard')}}">라이브러리</a>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{active_count}}</strong><span class="small">진행 중</span></div>
    <div class="stat"><strong>{{due_today_count}}</strong><span class="small">오늘 마감</span></div>
    <div class="stat"><strong>{{overdue_count}}</strong><span class="small">기한 지남</span></div>
    <div class="stat"><strong>{{completed_count}}</strong><span class="small">게시 완료</span></div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>오늘의 운영 브리핑</h2>
  {% for task in tasks %}
  <div class="task-row">
    <div class="task-num">{{loop.index}}</div>
    <div>
      <strong>{{task.item.title}}</strong>
      <div class="small">{{task.item.brand}} · {{task.item.status}} · 우선순위 {{task.priority}}{% if task.due_text %} · {{task.due_text}}{% endif %}</div>
      <p style="margin:5px 0 0">{{task.action}}</p>
      <a href="{{url_for('pipeline_v13.edit_meta', item_id=task.item.id)}}">일정·우선순위 설정</a>
    </div>
  </div>
  {% else %}
  <p class="small">진행 중인 콘텐츠가 없습니다. 오늘은 콘텐츠 씨앗을 하나 심어도 좋은 날이에요.</p>
  {% endfor %}
</section>

<section class="card">
  <h2>필터</h2>
  <form method="get">
    <label>제목 검색</label>
    <input name="q" value="{{q}}" placeholder="콘텐츠 제목">
    <label>브랜드</label>
    <select name="brand">
      <option value="">전체 브랜드</option>
      {% for value in brands %}<option value="{{value}}" {% if brand == value %}selected{% endif %}>{{value}}</option>{% endfor %}
    </select>
    <div class="actions">
      <button class="btn" type="submit">적용</button>
      <a class="btn gray" href="{{url_for('pipeline_v13.board')}}">초기화</a>
    </div>
  </form>
  <p class="notice">드래그한 상태는 즉시 저장됩니다. 외부 채널에는 아무것도 자동 게시되지 않습니다.</p>
</section>
</div>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <h2>칸반 보드</h2>
    <span id="save-state" class="small">저장 준비</span>
  </div>
  <div class="pipeline-wrap">
    <div class="pipeline-board">
      {% for status in statuses %}
      <div class="pipeline-column" data-status="{{status}}">
        <div class="pipeline-head">
          <strong>{{status}}</strong>
          <span class="tag">{{columns[status]|length}}</span>
        </div>

        {% for item in columns[status] %}
        {% set meta = item.pipeline_meta %}
        {% set priority = meta.priority if meta else '보통' %}
        <article class="pipeline-card {% if priority == '높음' %}priority-high{% elif priority == '낮음' %}priority-low{% else %}priority-normal{% endif %}"
                 draggable="true" data-item-id="{{item.id}}">
          <strong>
            {% if item.series_name and item.episode_number %}
              {{item.series_name}} EP.{{"%03d"|format(item.episode_number)}} ·
            {% endif %}
            {{item.title}}
          </strong>
          <div class="small">{{item.brand}} · {{item.content_type}}</div>

          <div class="progress-track">
            <div class="progress-fill" style="width:{{progress[item.status]}}%"></div>
          </div>

          <div class="small">
            우선순위 {{priority}}
            {% if meta and meta.due_date %}
              · <span class="{% if meta.due_date < today and item.status != '게시 완료' %}due-over{% elif meta.due_date == today and item.status != '게시 완료' %}due-today{% endif %}">
                {{meta.due_date.strftime('%m/%d')}} 마감
              </span>
            {% endif %}
          </div>

          {% if item.hook %}<p class="small" style="margin:7px 0">{{item.hook[:85]}}{{'…' if item.hook|length > 85 else ''}}</p>{% endif %}

          <div class="actions">
            <a href="{{url_for('library_v11.detail', item_id=item.id)}}">열기</a>
            <a href="{{url_for('pipeline_v13.edit_meta', item_id=item.id)}}">업무 설정</a>
          </div>
        </article>
        {% endfor %}
      </div>
      {% endfor %}
    </div>
  </div>
</section>

<script>
(() => {
  let dragged = null;
  const state = document.getElementById("save-state");

  document.querySelectorAll(".pipeline-card").forEach(card => {
    card.addEventListener("dragstart", () => {
      dragged = card;
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      dragged = null;
      document.querySelectorAll(".pipeline-column").forEach(c => c.classList.remove("drag-over"));
    });
  });

  document.querySelectorAll(".pipeline-column").forEach(column => {
    column.addEventListener("dragover", event => {
      event.preventDefault();
      column.classList.add("drag-over");
    });
    column.addEventListener("dragleave", () => column.classList.remove("drag-over"));
    column.addEventListener("drop", async event => {
      event.preventDefault();
      column.classList.remove("drag-over");
      if (!dragged) return;

      const oldColumn = dragged.closest(".pipeline-column");
      const newStatus = column.dataset.status;
      column.appendChild(dragged);
      updateCount(oldColumn);
      updateCount(column);
      state.textContent = "저장 중…";

      try {
        const response = await fetch(`/pipeline/api/items/${dragged.dataset.itemId}/status`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({status: newStatus})
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "저장 실패");
        state.textContent = `저장 완료 · ${newStatus}`;
        setTimeout(() => { state.textContent = "저장 준비"; }, 1800);
      } catch (error) {
        state.textContent = "저장 실패 · 새로고침해 주세요";
        oldColumn.appendChild(dragged);
        updateCount(oldColumn);
        updateCount(column);
      }
    });
  });

  function updateCount(column) {
    if (!column) return;
    const badge = column.querySelector(".pipeline-head .tag");
    if (badge) badge.textContent = column.querySelectorAll(".pipeline-card").length;
  }
})();
</script>
""",
        columns=columns,
        statuses=PIPELINE_STATUSES,
        progress=STATUS_PROGRESS,
        brands=BRANDS,
        brand=brand,
        q=q,
        tasks=tasks,
        active_count=active_count,
        completed_count=completed_count,
        overdue_count=overdue_count,
        due_today_count=due_today_count,
        today=date.today(),
        page_title="콘텐츠 파이프라인 | MI Creator Hub",
    )


@pipeline_bp.post("/api/items/<int:item_id>/status")
def update_status(item_id):
    item = db.session.get(ContentLibraryItem, item_id)
    if not item:
        return jsonify({"ok": False, "error": "콘텐츠를 찾을 수 없습니다."}), 404

    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip()
    if status not in PIPELINE_STATUSES:
        return jsonify({"ok": False, "error": "허용되지 않은 상태입니다."}), 400

    item.status = status
    if status == "예약":
        meta = get_or_create_meta(item)
        if meta.due_date and not meta.scheduled_at:
            meta.scheduled_at = datetime.combine(meta.due_date, datetime.min.time())
    db.session.commit()

    return jsonify({
        "ok": True,
        "item_id": item.id,
        "status": item.status,
        "progress": STATUS_PROGRESS[item.status],
    })


@pipeline_bp.route("/items/<int:item_id>/settings", methods=["GET", "POST"])
def edit_meta(item_id):
    item = db.session.get(ContentLibraryItem, item_id)
    if not item:
        flash("콘텐츠를 찾을 수 없습니다.")
        return redirect(url_for("pipeline_v13.board"))

    meta = get_or_create_meta(item)

    if request.method == "POST":
        priority = request.form.get("priority", "").strip()
        if priority not in PRIORITIES:
            priority = "보통"

        try:
            due_date = parse_date(request.form.get("due_date"))
        except ValueError:
            flash("마감일 형식이 올바르지 않습니다.")
            return redirect(url_for("pipeline_v13.edit_meta", item_id=item.id))

        status = request.form.get("status", "").strip()
        if status not in PIPELINE_STATUSES:
            status = item.status

        meta.priority = priority
        meta.due_date = due_date
        meta.owner_note = request.form.get("owner_note", "").strip()
        item.status = status

        if status == "예약" and due_date:
            meta.scheduled_at = datetime.combine(due_date, datetime.min.time())
        elif status != "예약":
            meta.scheduled_at = None

        db.session.commit()
        flash("파이프라인 업무 설정을 저장했어요.")
        return redirect(url_for("pipeline_v13.board"))

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>파이프라인 업무 설정</h1>
      <p class="lead">{{item.title}}</p>
    </div>
    <a class="btn gray" href="{{url_for('pipeline_v13.board')}}">칸반 보드</a>
  </div>

  <form method="post">
    <div class="grid">
      <div>
        <label>진행 상태</label>
        <select name="status">
          {% for value in statuses %}
          <option value="{{value}}" {% if item.status == value %}selected{% endif %}>{{value}}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label>우선순위</label>
        <select name="priority">
          {% for value in priorities %}
          <option value="{{value}}" {% if meta.priority == value %}selected{% endif %}>{{value}}</option>
          {% endfor %}
        </select>
      </div>
    </div>

    <label>마감일 또는 게시 예정일</label>
    <input type="date" name="due_date" value="{{meta.due_date.isoformat() if meta.due_date else ''}}">

    <label>내 작업 메모</label>
    <textarea name="owner_note" rows="6" placeholder="촬영 준비, 수정할 문구, 확인할 링크 등을 적어주세요.">{{meta.owner_note or ''}}</textarea>

    <div class="actions">
      <button class="btn" type="submit">저장</button>
      <a class="btn gray" href="{{url_for('library_v11.detail', item_id=item.id)}}">콘텐츠 열기</a>
    </div>
  </form>

  <p class="notice">예약 상태는 외부 게시를 실행하는 기능이 아닙니다. 내부 일정 표시와 작업 관리에만 사용됩니다.</p>
</section>
""",
        item=item,
        meta=meta,
        statuses=PIPELINE_STATUSES,
        priorities=PRIORITIES,
        page_title="파이프라인 업무 설정 | MI Creator Hub",
    )


@pipeline_bp.get("/brief")
def brief():
    items = (
        ContentLibraryItem.query
        .filter(ContentLibraryItem.status.in_(ACTIVE_STATUSES))
        .order_by(ContentLibraryItem.updated_at.desc())
        .all()
    )
    tasks = build_daily_tasks(items)
    upcoming = []
    end = date.today() + timedelta(days=7)

    for item in items:
        meta = item.pipeline_meta
        if meta and meta.due_date and date.today() <= meta.due_date <= end:
            upcoming.append(item)

    upcoming.sort(key=lambda item: item.pipeline_meta.due_date)

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>오늘의 콘텐츠 브리핑</h1>
      <p class="lead">{{today.strftime('%Y년 %m월 %d일')}} 저장된 일정과 진행 상태만으로 정리했습니다.</p>
    </div>
    <a class="btn gray" href="{{url_for('pipeline_v13.board')}}">칸반 보드</a>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>오늘 먼저 할 일</h2>
  {% for task in tasks %}
  <div class="calendar-item">
    <strong>{{loop.index}}. {{task.item.title}}</strong>
    <div class="small">{{task.item.status}} · 우선순위 {{task.priority}}{% if task.due_text %} · {{task.due_text}}{% endif %}</div>
    <p>{{task.action}}</p>
  </div>
  {% else %}
  <p class="small">진행 중인 작업이 없습니다.</p>
  {% endfor %}
</section>

<section class="card">
  <h2>7일 안의 마감</h2>
  {% for item in upcoming %}
  <div class="calendar-item">
    <strong>{{item.pipeline_meta.due_date.strftime('%m월 %d일')}} · {{item.title}}</strong>
    <div class="small">{{item.brand}} · {{item.status}} · 우선순위 {{item.pipeline_meta.priority}}</div>
  </div>
  {% else %}
  <p class="small">7일 안에 저장된 마감 일정이 없습니다.</p>
  {% endfor %}
</section>
</div>
""",
        tasks=tasks,
        upcoming=upcoming,
        today=date.today(),
        page_title="오늘의 콘텐츠 브리핑 | MI Creator Hub",
    )
