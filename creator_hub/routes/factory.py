"""V15.0 content factory, reusable templates, series memory, and project progress."""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup
from sqlalchemy import func

from ..legacy_app import BASE_HTML, db
from .library import BRANDS, CONTENT_TYPES, ContentLibraryItem


factory_bp = Blueprint("factory_v15", __name__, url_prefix="/factory")


FACTORY_FORMATS = [
    "블로그",
    "릴스·쇼츠",
    "인스타툰",
    "Threads",
    "인스타그램 캡션",
    "뉴스레터",
]

FACTORY_STAGES = [
    ("planning_done", "기획"),
    ("script_done", "대본"),
    ("shooting_done", "촬영"),
    ("editing_done", "편집"),
    ("review_done", "검토"),
    ("publishing_done", "게시"),
]


class ContentFactoryProject(db.Model):
    __tablename__ = "content_factory_project"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    brand = db.Column(db.String(100), nullable=False, default="말썽쟁이 딸랑구")
    category = db.Column(db.String(100), nullable=False, default="일반")
    source_item_id = db.Column(
        db.Integer,
        db.ForeignKey("content_library_item.id"),
        nullable=True,
        index=True,
    )
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("content_factory_template.id"),
        nullable=True,
        index=True,
    )
    series_name = db.Column(db.String(200), default="")
    episode_number = db.Column(db.Integer, nullable=True)
    target_formats = db.Column(db.Text, default="")
    source_text = db.Column(db.Text, default="")
    brand_memory = db.Column(db.Text, default="")
    character_memory = db.Column(db.Text, default="")
    continuity_note = db.Column(db.Text, default="")
    next_episode_hint = db.Column(db.Text, default="")
    planning_done = db.Column(db.Boolean, nullable=False, default=True)
    script_done = db.Column(db.Boolean, nullable=False, default=False)
    shooting_done = db.Column(db.Boolean, nullable=False, default=False)
    editing_done = db.Column(db.Boolean, nullable=False, default=False)
    review_done = db.Column(db.Boolean, nullable=False, default=False)
    publishing_done = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(30), nullable=False, default="제작 중")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    source_item = db.relationship(
        "ContentLibraryItem",
        foreign_keys=[source_item_id],
        backref=db.backref("factory_projects", lazy=True),
    )
    template = db.relationship(
        "ContentFactoryTemplate",
        foreign_keys=[template_id],
        backref=db.backref("projects", lazy=True),
    )


class ContentFactoryOutput(db.Model):
    __tablename__ = "content_factory_output"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("content_factory_project.id"),
        nullable=False,
        index=True,
    )
    format_name = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(300), default="")
    body = db.Column(db.Text, default="")
    hook = db.Column(db.Text, default="")
    cta = db.Column(db.Text, default="")
    hashtags = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    library_item_id = db.Column(
        db.Integer,
        db.ForeignKey("content_library_item.id"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    project = db.relationship(
        "ContentFactoryProject",
        backref=db.backref("outputs", cascade="all, delete-orphan", lazy=True),
    )
    library_item = db.relationship("ContentLibraryItem", foreign_keys=[library_item_id])


class ContentFactoryTemplate(db.Model):
    __tablename__ = "content_factory_template"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    brand = db.Column(db.String(100), nullable=False, default="말썽쟁이 딸랑구")
    tone = db.Column(db.String(200), default="")
    audience = db.Column(db.String(300), default="")
    hook_formula = db.Column(db.Text, default="")
    structure = db.Column(db.Text, default="")
    cta_formula = db.Column(db.Text, default="")
    safety_note = db.Column(db.Text, default="")
    is_favorite = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def parse_formats(raw_values):
    return [value for value in raw_values if value in FACTORY_FORMATS]


def joined_formats(values):
    return "|||".join(values)


def split_formats(raw):
    return [value for value in (raw or "").split("|||") if value]


def project_progress(project):
    values = [bool(getattr(project, field)) for field, _ in FACTORY_STAGES]
    return round(sum(values) / len(values) * 100)


def next_episode(series_name):
    if not series_name:
        return None
    max_project = (
        db.session.query(func.max(ContentFactoryProject.episode_number))
        .filter(ContentFactoryProject.series_name == series_name)
        .scalar()
    ) or 0
    max_library = (
        db.session.query(func.max(ContentLibraryItem.episode_number))
        .filter(ContentLibraryItem.series_name == series_name)
        .scalar()
    ) or 0
    return max(max_project, max_library) + 1


def default_output_text(project, format_name):
    source = project.source_text.strip()
    memory = project.continuity_note.strip()
    base = source if source else "사용자가 제공한 원문을 입력해 주세요."

    if format_name == "릴스·쇼츠":
        body = (
            "[훅 0~2초]\n"
            f"{project.title}\n\n"
            "[장면 1]\n상황을 짧게 보여주세요.\n\n"
            "[장면 2]\n핵심 메시지를 한 문장으로 전달하세요.\n\n"
            "[장면 3]\n반전이나 결론을 보여주세요.\n\n"
            "[마무리]\n댓글 또는 저장을 유도하는 CTA를 넣으세요."
        )
    elif format_name == "인스타툰":
        body = "\n\n".join(
            [
                "1컷: 표지와 강한 훅",
                "2컷: 상황 소개",
                "3컷: 문제 발생",
                "4컷: 갈등 확대",
                "5컷: 핵심 정보",
                "6컷: 현실적인 반응",
                "7컷: 결론 또는 반전",
                "8컷: CTA와 다음 편 예고",
            ]
        )
    elif format_name == "Threads":
        body = (
            f"{project.title}\n\n"
            "첫 문장에 결론이나 공감 포인트를 배치해.\n"
            "친한 친구에게 말하듯 자연스러운 반말로 써.\n"
            "짧은 문단 3~5개로 핵심만 정리하고, 존댓말은 쓰지 마.\n"
            "마지막에는 독자의 경험을 묻는 한 문장을 넣어."
        )
    elif format_name == "블로그":
        body = (
            f"<h1>{project.title}</h1>\n"
            "<p>도입부에 독자가 겪는 상황을 적어주세요.</p>\n"
            "<h2>핵심 내용</h2>\n"
            f"<p>{base}</p>\n"
            "<h2>정리</h2>\n"
            "<p>사실 확인이 필요한 표현은 게시 전에 검토하세요.</p>"
        )
    elif format_name == "뉴스레터":
        body = (
            f"제목: {project.title}\n\n"
            "안녕하세요.\n\n"
            f"{base}\n\n"
            "이번 주 핵심 포인트를 3개 이내로 정리하세요.\n\n"
            "다음 소식에서 다시 만나요."
        )
    else:
        body = (
            f"{project.title}\n\n"
            f"{base}\n\n"
            "짧은 문단과 자연스러운 CTA로 마무리하세요."
        )

    if memory:
        body += f"\n\n[연속성 메모]\n{memory}"

    return body


@factory_bp.get("/")
def dashboard():
    projects = ContentFactoryProject.query.order_by(
        ContentFactoryProject.updated_at.desc()
    ).all()
    rows = [
        {
            "project": project,
            "progress": project_progress(project),
            "formats": split_formats(project.target_formats),
            "output_count": len(project.outputs),
        }
        for project in projects
    ]

    templates = ContentFactoryTemplate.query.order_by(
        ContentFactoryTemplate.is_favorite.desc(),
        ContentFactoryTemplate.updated_at.desc(),
    ).limit(8).all()

    return page("""
<style>
.factory-progress{height:9px;background:#eceef3;border-radius:99px;overflow:hidden}
.factory-progress > div{height:100%;background:#4b3f72}
.factory-stage{display:inline-block;padding:5px 9px;border-radius:99px;background:#eef0f5;margin:2px;font-size:.82rem}
.factory-stage.done{background:#dcfce7;color:#166534;font-weight:700}
.factory-card{border:1px solid #e5e7eb;border-radius:16px;padding:15px;margin-bottom:12px;background:#fff}
</style>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>AI 콘텐츠 팩토리 <span class="status">V15.0</span></h1>
      <p class="lead">하나의 원본을 여러 콘텐츠 형식으로 묶어 제작하고 진행률까지 관리합니다.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('home_v16.dashboard')}}">홈</a>
      <a class="btn" href="{{url_for('factory_v15.create_project')}}">새 콘텐츠 패키지</a>
      <a class="btn gray" href="{{url_for('factory_v15.templates')}}">템플릿 관리</a>
      <a class="btn gray" href="{{url_for('factory_v15.series')}}">시리즈 메모리</a>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{rows|length}}</strong><span class="small">전체 패키지</span></div>
    <div class="stat"><strong>{{rows|selectattr('progress','equalto',100)|list|length}}</strong><span class="small">완료</span></div>
    <div class="stat"><strong>{{rows|rejectattr('progress','equalto',100)|list|length}}</strong><span class="small">진행 중</span></div>
    <div class="stat"><strong>{{templates|length}}</strong><span class="small">빠른 템플릿</span></div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>콘텐츠 패키지</h2>
  {% for row in rows %}
  <div class="factory-card">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div>
        <strong>
          {% if row.project.series_name and row.project.episode_number %}
            {{row.project.series_name}} EP.{{"%03d"|format(row.project.episode_number)}} ·
          {% endif %}
          {{row.project.title}}
        </strong>
        <div class="small">{{row.project.brand}} · 출력 {{row.output_count}}개 · {{row.progress}}%</div>
      </div>
      <a class="btn" href="{{url_for('factory_v15.project_detail', project_id=row.project.id)}}">열기</a>
    </div>

    <div class="factory-progress" style="margin:10px 0">
      <div style="width:{{row.progress}}%"></div>
    </div>

    <div>
      {% for field,label in stages %}
      <span class="factory-stage {% if row.project|attr(field) %}done{% endif %}">{{"✓ " if row.project|attr(field) else ""}}{{label}}</span>
      {% endfor %}
    </div>

    <div style="margin-top:8px">
      {% for format in row.formats %}<span class="tag">{{format}}</span>{% endfor %}
    </div>
  </div>
  {% else %}
  <p class="small">아직 콘텐츠 패키지가 없습니다.</p>
  {% endfor %}
</section>

<section class="card">
  <h2>빠른 템플릿</h2>
  {% for template in templates %}
  <div class="calendar-item">
    <strong>{{"★ " if template.is_favorite else ""}}{{template.name}}</strong>
    <div class="small">{{template.brand}}{% if template.tone %} · {{template.tone}}{% endif %}</div>
    <a href="{{url_for('factory_v15.create_project', template_id=template.id)}}">이 템플릿으로 시작</a>
  </div>
  {% else %}
  <p class="small">저장된 템플릿이 없습니다.</p>
  {% endfor %}
  <p class="notice">자동 변환 결과는 초안입니다. 사실, 보험 표현, 제품명, 가격, 링크는 게시 전 직접 확인해야 합니다.</p>
</section>
</div>
""",
        rows=rows,
        templates=templates,
        stages=FACTORY_STAGES,
        page_title="AI 콘텐츠 팩토리 | MI Creator OS",
    )


@factory_bp.route("/create", methods=["GET", "POST"])
def create_project():
    template_id = request.args.get("template_id", type=int)
    requested_series_name = request.args.get("series_name", "").strip()
    template = db.session.get(ContentFactoryTemplate, template_id) if template_id else None
    source_item_id = request.args.get("source_item_id", type=int)
    source_item = db.session.get(ContentLibraryItem, source_item_id) if source_item_id else None

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("프로젝트 제목을 입력해 주세요.")
            return redirect(url_for("factory_v15.create_project"))

        series_name = request.form.get("series_name", "").strip()
        raw_episode = request.form.get("episode_number", "").strip()
        if raw_episode:
            try:
                episode_number = max(1, int(raw_episode))
            except ValueError:
                flash("에피소드 번호는 숫자로 입력해 주세요.")
                return redirect(url_for("factory_v15.create_project"))
        else:
            episode_number = next_episode(series_name)

        formats = parse_formats(request.form.getlist("target_formats"))
        if not formats:
            flash("변환할 콘텐츠 형식을 하나 이상 선택해 주세요.")
            return redirect(url_for("factory_v15.create_project"))

        selected_template_id = request.form.get("template_id", type=int)
        selected_source_id = request.form.get("source_item_id", type=int)

        project = ContentFactoryProject(
            title=title[:300],
            brand=request.form.get("brand", "말썽쟁이 딸랑구").strip()[:100],
            category=request.form.get("category", "일반").strip()[:100],
            source_item_id=selected_source_id,
            template_id=selected_template_id,
            series_name=series_name[:200],
            episode_number=episode_number,
            target_formats=joined_formats(formats),
            source_text=request.form.get("source_text", "").strip(),
            brand_memory=request.form.get("brand_memory", "").strip(),
            character_memory=request.form.get("character_memory", "").strip(),
            continuity_note=request.form.get("continuity_note", "").strip(),
            next_episode_hint=request.form.get("next_episode_hint", "").strip(),
            planning_done=True,
        )
        db.session.add(project)
        db.session.flush()

        for format_name in formats:
            output = ContentFactoryOutput(
                project_id=project.id,
                format_name=format_name,
                title=title,
                body=default_output_text(project, format_name),
            )
            db.session.add(output)

        db.session.commit()
        flash("콘텐츠 패키지를 만들었어요.")
        return redirect(url_for("factory_v15.project_detail", project_id=project.id))

    library_items = ContentLibraryItem.query.order_by(
        ContentLibraryItem.updated_at.desc()
    ).limit(100).all()

    prefill = {
        "title": source_item.title if source_item else "",
        "brand": source_item.brand if source_item else (template.brand if template else "말썽쟁이 딸랑구"),
        "category": source_item.category if source_item else "일반",
        "series_name": source_item.series_name if source_item else requested_series_name,
        "episode_number": source_item.episode_number if source_item else "",
        "source_text": (
            (source_item.blog_draft or source_item.summary or source_item.reel_script or "")
            if source_item else ""
        ),
        "brand_memory": template.structure if template else "",
        "character_memory": "",
        "continuity_note": "",
        "next_episode_hint": "",
    }

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>새 콘텐츠 패키지</h1><p class="lead">원본 하나를 여러 형식의 초안으로 묶습니다.</p></div>
    <a class="btn gray" href="{{url_for('factory_v15.dashboard')}}">콘텐츠 팩토리</a>
  </div>

  <form method="post">
    <input type="hidden" name="template_id" value="{{template.id if template else ''}}">
    <input type="hidden" name="source_item_id" value="{{source_item.id if source_item else ''}}">

    {% if template %}<p class="notice">템플릿 적용: {{template.name}}</p>{% endif %}
    {% if source_item %}<p class="notice">라이브러리 원본 연결: {{source_item.title}}</p>{% endif %}

    <label>프로젝트 제목</label>
    <input name="title" required maxlength="300" value="{{prefill.title}}">

    <div class="grid">
      <div><label>브랜드</label><select name="brand">{% for value in brands %}<option value="{{value}}" {% if prefill.brand == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select></div>
      <div><label>카테고리</label><input name="category" value="{{prefill.category}}"></div>
    </div>

    <div class="grid">
      <div><label>시리즈명</label><input name="series_name" value="{{prefill.series_name}}" placeholder="예: 말썽쟁이 딸랑구"></div>
      <div><label>에피소드 번호</label><input type="number" min="1" name="episode_number" value="{{prefill.episode_number}}" placeholder="비우면 자동 번호"></div>
    </div>

    <label>만들 형식</label>
    <div class="grid">
      {% for value in formats %}
      <label class="calendar-item"><input type="checkbox" name="target_formats" value="{{value}}" {% if value in ['릴스·쇼츠','인스타툰','블로그','Threads'] %}checked{% endif %}> {{value}}</label>
      {% endfor %}
    </div>

    <label>원본 내용</label>
    <textarea name="source_text" rows="10" placeholder="직접 작성한 원문, 핵심 사실, 경험을 입력하세요.">{{prefill.source_text}}</textarea>

    <label>브랜드 톤·구조 메모</label>
    <textarea name="brand_memory" rows="4">{{prefill.brand_memory}}</textarea>

    <label>등장인물·세계관 메모</label>
    <textarea name="character_memory" rows="4" placeholder="말투, 관계, 반복 설정 등을 기록하세요.">{{prefill.character_memory}}</textarea>

    <label>이전 화와 이어질 내용</label>
    <textarea name="continuity_note" rows="4">{{prefill.continuity_note}}</textarea>

    <label>다음 화 힌트</label>
    <textarea name="next_episode_hint" rows="3">{{prefill.next_episode_hint}}</textarea>

    <button class="btn" type="submit">패키지 만들기</button>
  </form>

  <p class="notice">제품명, 가격, 할인, 제휴 링크, 실제 경험과 통계는 입력된 정보가 없으면 생성하지 않습니다.</p>
</section>
""",
        brands=BRANDS,
        formats=FACTORY_FORMATS,
        template=template,
        source_item=source_item,
        prefill=prefill,
        page_title="새 콘텐츠 패키지 | MI Creator OS",
    )


@factory_bp.route("/projects/<int:project_id>", methods=["GET", "POST"])
def project_detail(project_id):
    project = db.session.get(ContentFactoryProject, project_id)
    if not project:
        flash("콘텐츠 패키지를 찾을 수 없습니다.")
        return redirect(url_for("factory_v15.dashboard"))

    if request.method == "POST":
        for field, _ in FACTORY_STAGES:
            setattr(project, field, request.form.get(field) == "on")
        project.status = "완료" if project.publishing_done else "제작 중"
        project.brand_memory = request.form.get("brand_memory", "").strip()
        project.character_memory = request.form.get("character_memory", "").strip()
        project.continuity_note = request.form.get("continuity_note", "").strip()
        project.next_episode_hint = request.form.get("next_episode_hint", "").strip()
        db.session.commit()
        flash("프로젝트 진행 상태를 저장했어요.")
        return redirect(url_for("factory_v15.project_detail", project_id=project.id))

    outputs = sorted(project.outputs, key=lambda row: FACTORY_FORMATS.index(row.format_name) if row.format_name in FACTORY_FORMATS else 99)

    return page("""
<style>
.output-card{border:1px solid #e5e7eb;border-radius:15px;padding:14px;margin-bottom:12px}
.progress-track{height:10px;background:#eceef3;border-radius:99px;overflow:hidden}
.progress-fill{height:100%;background:#4b3f72}
</style>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>
        {% if project.series_name and project.episode_number %}
          {{project.series_name}} EP.{{"%03d"|format(project.episode_number)}} ·
        {% endif %}
        {{project.title}}
      </h1>
      <p class="lead">{{project.brand}} · {{project.status}} · 진행률 {{progress}}%</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('factory_v15.dashboard')}}">목록</a>
      <form method="post" action="{{url_for('factory_v15.delete_project', project_id=project.id)}}" onsubmit="return confirm('프로젝트를 삭제할까요?')"><button class="btn gray" type="submit">삭제</button></form>
    </div>
  </div>

  <div class="progress-track"><div class="progress-fill" style="width:{{progress}}%"></div></div>

  <form method="post">
    <div class="grid" style="margin-top:14px">
      {% for field,label in stages %}
      <label class="calendar-item"><input type="checkbox" name="{{field}}" {% if project|attr(field) %}checked{% endif %}> <strong>{{label}}</strong></label>
      {% endfor %}
    </div>

    <label>브랜드 톤·구조 메모</label>
    <textarea name="brand_memory" rows="3">{{project.brand_memory or ''}}</textarea>

    <label>등장인물·세계관 메모</label>
    <textarea name="character_memory" rows="3">{{project.character_memory or ''}}</textarea>

    <label>연속성 메모</label>
    <textarea name="continuity_note" rows="3">{{project.continuity_note or ''}}</textarea>

    <label>다음 화 힌트</label>
    <textarea name="next_episode_hint" rows="3">{{project.next_episode_hint or ''}}</textarea>

    <button class="btn" type="submit">진행 상태 저장</button>
  </form>
</section>

<section class="card">
  <h2>콘텐츠 결과물</h2>
  {% for output in outputs %}
  <div class="output-card">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div><strong>{{output.format_name}}</strong>{% if output.library_item_id %}<span class="tag">라이브러리 저장됨</span>{% endif %}</div>
      <div class="actions" style="margin-top:0">
        <a class="btn" href="{{url_for('factory_v15.edit_output', output_id=output.id)}}">편집</a>
        {% if not output.library_item_id %}
        <form method="post" action="{{url_for('factory_v15.output_to_library', output_id=output.id)}}"><button class="btn gray" type="submit">라이브러리 저장</button></form>
        {% else %}
        <a class="btn gray" href="{{url_for('library_v11.detail', item_id=output.library_item_id)}}">라이브러리 열기</a>
        {% endif %}
      </div>
    </div>
    {% if output.hook %}<p><strong>훅:</strong> {{output.hook}}</p>{% endif %}
    <pre style="white-space:pre-wrap;font-family:inherit;background:#f8fafc;padding:12px;border-radius:12px;max-height:250px;overflow:auto">{{output.body[:1400]}}{{'…' if output.body|length > 1400 else ''}}</pre>
  </div>
  {% endfor %}
</section>
""",
        project=project,
        outputs=outputs,
        progress=project_progress(project),
        stages=FACTORY_STAGES,
        page_title="콘텐츠 패키지 | MI Creator OS",
    )


@factory_bp.route("/outputs/<int:output_id>/edit", methods=["GET", "POST"])
def edit_output(output_id):
    output = db.session.get(ContentFactoryOutput, output_id)
    if not output:
        flash("결과물을 찾을 수 없습니다.")
        return redirect(url_for("factory_v15.dashboard"))

    if request.method == "POST":
        output.title = request.form.get("title", "").strip()[:300]
        output.hook = request.form.get("hook", "").strip()
        output.body = request.form.get("body", "").strip()
        output.cta = request.form.get("cta", "").strip()
        output.hashtags = request.form.get("hashtags", "").strip()
        output.notes = request.form.get("notes", "").strip()
        db.session.commit()
        flash("결과물을 저장했어요.")
        return redirect(url_for("factory_v15.project_detail", project_id=output.project_id))

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>{{output.format_name}} 편집</h1><p class="lead">{{output.project.title}}</p></div>
    <a class="btn gray" href="{{url_for('factory_v15.project_detail', project_id=output.project_id)}}">프로젝트</a>
  </div>

  <form method="post">
    <label>제목</label><input name="title" value="{{output.title or ''}}">
    <label>훅</label><textarea name="hook" rows="3">{{output.hook or ''}}</textarea>
    <label>본문</label><textarea name="body" rows="22">{{output.body or ''}}</textarea>
    <label>CTA</label><textarea name="cta" rows="3">{{output.cta or ''}}</textarea>
    <label>해시태그</label><textarea name="hashtags" rows="3">{{output.hashtags or ''}}</textarea>
    <label>검토 메모</label><textarea name="notes" rows="4">{{output.notes or ''}}</textarea>
    <button class="btn" type="submit">결과물 저장</button>
  </form>
</section>
""",
        output=output,
        page_title="결과물 편집 | MI Creator OS",
    )


@factory_bp.post("/outputs/<int:output_id>/to-library")
def output_to_library(output_id):
    output = db.session.get(ContentFactoryOutput, output_id)
    if not output:
        flash("결과물을 찾을 수 없습니다.")
        return redirect(url_for("factory_v15.dashboard"))

    if output.library_item_id:
        return redirect(url_for("library_v11.detail", item_id=output.library_item_id))

    project = output.project
    content_type_map = {
        "블로그": "블로그",
        "릴스·쇼츠": "릴스·쇼츠",
        "인스타툰": "인스타툰",
        "Threads": "Threads",
        "인스타그램 캡션": "인스타그램",
        "뉴스레터": "뉴스레터",
    }

    item = ContentLibraryItem(
        title=output.title or project.title,
        brand=project.brand,
        category=project.category,
        content_type=content_type_map.get(output.format_name, output.format_name),
        series_name=project.series_name,
        episode_number=project.episode_number,
        status="검토",
        summary=output.notes or project.source_text[:1000],
        hook=output.hook,
        blog_draft=output.body if output.format_name in {"블로그", "뉴스레터"} else "",
        reel_script=output.body if output.format_name == "릴스·쇼츠" else "",
        instagram_caption=output.body if output.format_name == "인스타그램 캡션" else "",
        threads_text=output.body if output.format_name == "Threads" else "",
        instagram_comic_plan=output.body if output.format_name == "인스타툰" else "",
        cta=output.cta,
        tags=output.hashtags,
    )
    db.session.add(item)
    db.session.flush()
    output.library_item_id = item.id
    db.session.commit()

    flash("결과물을 콘텐츠 라이브러리에 검토 상태로 저장했어요.")
    return redirect(url_for("library_v11.detail", item_id=item.id))


@factory_bp.post("/projects/<int:project_id>/delete")
def delete_project(project_id):
    project = db.session.get(ContentFactoryProject, project_id)
    if project:
        db.session.delete(project)
        db.session.commit()
        flash("콘텐츠 패키지를 삭제했어요.")
    return redirect(url_for("factory_v15.dashboard"))


@factory_bp.route("/templates", methods=["GET", "POST"])
def templates():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("템플릿 이름을 입력해 주세요.")
            return redirect(url_for("factory_v15.templates"))

        template = ContentFactoryTemplate(
            name=name[:200],
            brand=request.form.get("brand", "말썽쟁이 딸랑구").strip()[:100],
            tone=request.form.get("tone", "").strip()[:200],
            audience=request.form.get("audience", "").strip()[:300],
            hook_formula=request.form.get("hook_formula", "").strip(),
            structure=request.form.get("structure", "").strip(),
            cta_formula=request.form.get("cta_formula", "").strip(),
            safety_note=request.form.get("safety_note", "").strip(),
            is_favorite=request.form.get("is_favorite") == "on",
        )
        db.session.add(template)
        db.session.commit()
        flash("템플릿을 저장했어요.")
        return redirect(url_for("factory_v15.templates"))

    rows = ContentFactoryTemplate.query.order_by(
        ContentFactoryTemplate.is_favorite.desc(),
        ContentFactoryTemplate.updated_at.desc(),
    ).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>콘텐츠 템플릿</h1><p class="lead">자주 쓰는 브랜드 톤과 구성법을 저장합니다.</p></div>
    <a class="btn gray" href="{{url_for('factory_v15.dashboard')}}">콘텐츠 팩토리</a>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>새 템플릿</h2>
  <form method="post">
    <label>템플릿 이름</label><input name="name" required placeholder="예: 말썽쟁이 딸랑구 현실육아형">
    <label>브랜드</label><select name="brand">{% for value in brands %}<option>{{value}}</option>{% endfor %}</select>
    <label>톤</label><input name="tone" placeholder="예: 현실적이고 유쾌한 모녀 대화">
    <label>대상 독자</label><input name="audience" placeholder="예: 초등 자녀를 키우는 부모">
    <label>훅 공식</label><textarea name="hook_formula" rows="3"></textarea>
    <label>기본 구조</label><textarea name="structure" rows="5"></textarea>
    <label>CTA 공식</label><textarea name="cta_formula" rows="3"></textarea>
    <label>주의사항</label><textarea name="safety_note" rows="3" placeholder="제품명·가격·효과를 추정하지 않기"></textarea>
    <label><input type="checkbox" name="is_favorite"> 즐겨찾기</label>
    <button class="btn" type="submit">템플릿 저장</button>
  </form>
</section>

<section class="card">
  <h2>저장된 템플릿</h2>
  {% for row in rows %}
  <div class="calendar-item">
    <strong>{{"★ " if row.is_favorite else ""}}{{row.name}}</strong>
    <div class="small">{{row.brand}}{% if row.tone %} · {{row.tone}}{% endif %}</div>
    {% if row.structure %}<p class="small">{{row.structure[:160]}}{{'…' if row.structure|length > 160 else ''}}</p>{% endif %}
    <div class="actions">
      <a class="btn" href="{{url_for('factory_v15.create_project', template_id=row.id)}}">사용</a>
      <form method="post" action="{{url_for('factory_v15.toggle_template_favorite', template_id=row.id)}}"><button class="btn gray" type="submit">즐겨찾기 변경</button></form>
      <form method="post" action="{{url_for('factory_v15.delete_template', template_id=row.id)}}" onsubmit="return confirm('삭제할까요?')"><button class="btn gray" type="submit">삭제</button></form>
    </div>
  </div>
  {% else %}
  <p class="small">저장된 템플릿이 없습니다.</p>
  {% endfor %}
</section>
</div>
""",
        rows=rows,
        brands=BRANDS,
        page_title="콘텐츠 템플릿 | MI Creator OS",
    )


@factory_bp.post("/templates/<int:template_id>/favorite")
def toggle_template_favorite(template_id):
    template = db.session.get(ContentFactoryTemplate, template_id)
    if template:
        template.is_favorite = not template.is_favorite
        db.session.commit()
    return redirect(url_for("factory_v15.templates"))


@factory_bp.post("/templates/<int:template_id>/delete")
def delete_template(template_id):
    template = db.session.get(ContentFactoryTemplate, template_id)
    if template:
        if template.projects:
            flash("사용 중인 템플릿은 삭제할 수 없습니다.")
        else:
            db.session.delete(template)
            db.session.commit()
            flash("템플릿을 삭제했어요.")
    return redirect(url_for("factory_v15.templates"))


@factory_bp.get("/series")
def series():
    project_rows = (
        db.session.query(
            ContentFactoryProject.series_name,
            func.count(ContentFactoryProject.id),
            func.max(ContentFactoryProject.episode_number),
        )
        .filter(ContentFactoryProject.series_name != "")
        .group_by(ContentFactoryProject.series_name)
        .order_by(func.max(ContentFactoryProject.updated_at).desc())
        .all()
    )

    rows = []
    for series_name, count, max_episode in project_rows:
        latest = (
            ContentFactoryProject.query
            .filter(ContentFactoryProject.series_name == series_name)
            .order_by(ContentFactoryProject.episode_number.desc().nullslast(), ContentFactoryProject.updated_at.desc())
            .first()
        )
        rows.append({
            "series_name": series_name,
            "count": count,
            "max_episode": max_episode or 0,
            "latest": latest,
            "next_episode": max_episode + 1 if max_episode else 1,
        })

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>시리즈 메모리</h1><p class="lead">연재 설정과 다음 에피소드 번호를 이어서 관리합니다.</p></div>
    <a class="btn gray" href="{{url_for('factory_v15.dashboard')}}">콘텐츠 팩토리</a>
  </div>
</section>

<section class="card">
  {% for row in rows %}
  <div class="calendar-item">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div>
        <strong>{{row.series_name}}</strong>
        <div class="small">팩토리 프로젝트 {{row.count}}개 · 최신 EP.{{"%03d"|format(row.max_episode)}} · 다음 EP.{{"%03d"|format(row.next_episode)}}</div>
      </div>
      <a class="btn" href="{{url_for('factory_v15.create_project')}}?series_name={{row.series_name|urlencode}}">다음 편 만들기</a>
    </div>
    {% if row.latest.character_memory %}<p><strong>등장인물·세계관:</strong> {{row.latest.character_memory[:220]}}{{'…' if row.latest.character_memory|length > 220 else ''}}</p>{% endif %}
    {% if row.latest.next_episode_hint %}<p class="small"><strong>다음 화 힌트:</strong> {{row.latest.next_episode_hint}}</p>{% endif %}
  </div>
  {% else %}
  <p class="small">시리즈로 저장된 콘텐츠 패키지가 없습니다.</p>
  {% endfor %}
</section>
""",
        rows=rows,
        page_title="시리즈 메모리 | MI Creator OS",
    )
