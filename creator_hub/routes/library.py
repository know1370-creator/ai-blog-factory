"""V11.0 searchable content library and series manager."""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup
from sqlalchemy import or_, func

from ..legacy_app import BASE_HTML, Article, db


library_bp = Blueprint("library_v11", __name__, url_prefix="/library")


class ContentLibraryItem(db.Model):
    __tablename__ = "content_library_item"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(
        db.Integer,
        db.ForeignKey("article.id"),
        nullable=True,
        index=True,
    )
    title = db.Column(db.String(300), nullable=False)
    brand = db.Column(db.String(100), nullable=False, default="말썽쟁이 딸랑구")
    category = db.Column(db.String(100), nullable=False, default="일반")
    content_type = db.Column(db.String(50), nullable=False, default="통합 프로젝트")
    series_name = db.Column(db.String(200), default="")
    episode_number = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="기획")
    summary = db.Column(db.Text, default="")
    hook = db.Column(db.Text, default="")
    blog_content = db.Column(db.Text, default="")
    reel_script = db.Column(db.Text, default="")
    instagram_caption = db.Column(db.Text, default="")
    threads_text = db.Column(db.Text, default="")
    toon_plan = db.Column(db.Text, default="")
    cta = db.Column(db.Text, default="")
    tags = db.Column(db.Text, default="")
    source_url = db.Column(db.String(1000), default="")
    is_favorite = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    article = db.relationship("Article", backref=db.backref("library_items", lazy=True))


BRANDS = [
    "말썽쟁이 딸랑구",
    "미우와 웅이",
    "보험·재무",
    "애터미·생활용품",
    "쿠팡·쇼핑",
    "기타",
]

CATEGORIES = [
    "현실육아",
    "부부·데이트",
    "생활용품",
    "주방",
    "뷰티",
    "보험",
    "재무",
    "쇼핑",
    "정보",
    "일반",
]

CONTENT_TYPES = [
    "통합 프로젝트",
    "인스타툰",
    "릴스·쇼츠",
    "블로그",
    "인스타 피드",
    "Threads",
    "상담 스크립트",
]

STATUSES = ["기획", "제작 중", "검토", "예약", "게시 완료", "보류"]


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def clean_text(name, limit=None):
    value = request.form.get(name, "").strip()
    return value[:limit] if limit else value


def normalize_tags(value):
    tags = []
    seen = set()
    for raw in value.replace("#", "").replace("\n", ",").split(","):
        tag = raw.strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return ", ".join(tags[:30])


def next_episode(series_name, brand):
    if not series_name:
        return None
    highest = (
        db.session.query(func.max(ContentLibraryItem.episode_number))
        .filter(
            ContentLibraryItem.series_name == series_name,
            ContentLibraryItem.brand == brand,
        )
        .scalar()
    )
    return (highest or 0) + 1


@library_bp.get("/")
def dashboard():
    q = request.args.get("q", "").strip()
    brand = request.args.get("brand", "").strip()
    category = request.args.get("category", "").strip()
    content_type = request.args.get("content_type", "").strip()
    status = request.args.get("status", "").strip()
    favorite = request.args.get("favorite", "").strip()

    query = ContentLibraryItem.query

    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                ContentLibraryItem.title.ilike(pattern),
                ContentLibraryItem.summary.ilike(pattern),
                ContentLibraryItem.hook.ilike(pattern),
                ContentLibraryItem.tags.ilike(pattern),
                ContentLibraryItem.series_name.ilike(pattern),
                ContentLibraryItem.blog_content.ilike(pattern),
                ContentLibraryItem.reel_script.ilike(pattern),
                ContentLibraryItem.instagram_caption.ilike(pattern),
                ContentLibraryItem.threads_text.ilike(pattern),
                ContentLibraryItem.toon_plan.ilike(pattern),
            )
        )
    if brand:
        query = query.filter_by(brand=brand)
    if category:
        query = query.filter_by(category=category)
    if content_type:
        query = query.filter_by(content_type=content_type)
    if status:
        query = query.filter_by(status=status)
    if favorite == "1":
        query = query.filter_by(is_favorite=True)

    items = query.order_by(
        ContentLibraryItem.is_favorite.desc(),
        ContentLibraryItem.updated_at.desc(),
    ).all()

    total = ContentLibraryItem.query.count()
    favorites = ContentLibraryItem.query.filter_by(is_favorite=True).count()
    completed = ContentLibraryItem.query.filter_by(status="게시 완료").count()
    series_count = (
        db.session.query(func.count(func.distinct(ContentLibraryItem.series_name)))
        .filter(ContentLibraryItem.series_name != "")
        .scalar()
        or 0
    )

    series_rows = (
        db.session.query(
            ContentLibraryItem.brand,
            ContentLibraryItem.series_name,
            func.count(ContentLibraryItem.id),
            func.max(ContentLibraryItem.episode_number),
        )
        .filter(ContentLibraryItem.series_name != "")
        .group_by(ContentLibraryItem.brand, ContentLibraryItem.series_name)
        .order_by(ContentLibraryItem.brand, ContentLibraryItem.series_name)
        .all()
    )

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>콘텐츠 라이브러리 <span class="status">V11.0</span></h1>
      <p class="lead">브랜드, 시리즈, EP, 형식, 태그로 모든 콘텐츠를 한곳에 정리합니다.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn" href="{{url_for('library_v11.create')}}">새 프로젝트</a>
      <a class="btn gray" href="{{url_for('library_v11.import_articles')}}">기존 글 가져오기</a>
      <a class="btn gray" href="{{url_for('manager_v10.dashboard')}}">콘텐츠 매니저</a>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{total}}</strong><span class="small">전체 프로젝트</span></div>
    <div class="stat"><strong>{{series_count}}</strong><span class="small">시리즈</span></div>
    <div class="stat"><strong>{{favorites}}</strong><span class="small">즐겨찾기</span></div>
    <div class="stat"><strong>{{completed}}</strong><span class="small">게시 완료</span></div>
  </div>
</section>

<section class="card">
  <h2>검색과 필터</h2>
  <form method="get">
    <label>통합 검색</label>
    <input name="q" value="{{filters.q}}" placeholder="제목, 훅, 태그, 본문, 시리즈 검색">

    <div class="grid">
      <div>
        <label>브랜드</label>
        <select name="brand">
          <option value="">전체</option>
          {% for value in brands %}<option value="{{value}}" {% if filters.brand == value %}selected{% endif %}>{{value}}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>카테고리</label>
        <select name="category">
          <option value="">전체</option>
          {% for value in categories %}<option value="{{value}}" {% if filters.category == value %}selected{% endif %}>{{value}}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>콘텐츠 형식</label>
        <select name="content_type">
          <option value="">전체</option>
          {% for value in content_types %}<option value="{{value}}" {% if filters.content_type == value %}selected{% endif %}>{{value}}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>상태</label>
        <select name="status">
          <option value="">전체</option>
          {% for value in statuses %}<option value="{{value}}" {% if filters.status == value %}selected{% endif %}>{{value}}</option>{% endfor %}
        </select>
      </div>
    </div>

    <label>
      <input type="checkbox" name="favorite" value="1" {% if filters.favorite == '1' %}checked{% endif %}>
      즐겨찾기만 보기
    </label>

    <div class="actions">
      <button class="btn" type="submit">검색</button>
      <a class="btn gray" href="{{url_for('library_v11.dashboard')}}">초기화</a>
    </div>
  </form>
</section>

<div class="grid">
<section class="card">
  <h2>콘텐츠 목록</h2>
  {% for item in items %}
  <div class="calendar-item" style="margin-bottom:14px">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div>
        {% if item.is_favorite %}<span class="tag">★ 즐겨찾기</span>{% endif %}
        <span class="status">{{item.status}}</span>
        <strong>
          {% if item.series_name and item.episode_number %}
            {{item.series_name}} EP.{{"%03d"|format(item.episode_number)}} ·
          {% endif %}
          {{item.title}}
        </strong>
      </div>
      <span class="small">{{item.updated_at.strftime('%Y-%m-%d')}}</span>
    </div>

    <p class="small">{{item.brand}} · {{item.category}} · {{item.content_type}}</p>
    {% if item.hook %}<p><strong>훅:</strong> {{item.hook}}</p>{% endif %}
    {% if item.summary %}<p>{{item.summary[:180]}}{{'…' if item.summary|length > 180 else ''}}</p>{% endif %}
    {% if item.tags %}<p class="small">#{{item.tags.replace(', ', ' #')}}</p>{% endif %}

    <div class="actions">
      <a class="btn" href="{{url_for('library_v11.detail', item_id=item.id)}}">열기</a>
      <a class="btn gray" href="{{url_for('library_v11.edit', item_id=item.id)}}">수정</a>
      <form method="post" action="{{url_for('library_v11.toggle_favorite', item_id=item.id)}}">
        <button class="btn gray" type="submit">{{'즐겨찾기 해제' if item.is_favorite else '즐겨찾기'}}</button>
      </form>
    </div>
  </div>
  {% else %}
  <p class="small">검색 조건에 맞는 콘텐츠가 없습니다.</p>
  {% endfor %}
</section>

<section class="card">
  <h2>시리즈 현황</h2>
  {% for row in series_rows %}
  <a class="calendar-item" style="display:block;text-decoration:none" href="{{url_for('library_v11.dashboard', brand=row[0], q=row[1])}}">
    <strong>{{row[1]}}</strong><br>
    <span class="small">{{row[0]}} · {{row[2]}}개 · 최근 EP.{{"%03d"|format(row[3] or 0)}}</span>
  </a>
  {% else %}
  <p class="small">시리즈가 아직 없습니다. 새 프로젝트에서 시리즈명을 입력하면 자동으로 묶입니다.</p>
  {% endfor %}
</section>
</div>
""",
        items=items,
        total=total,
        favorites=favorites,
        completed=completed,
        series_count=series_count,
        series_rows=series_rows,
        filters={
            "q": q,
            "brand": brand,
            "category": category,
            "content_type": content_type,
            "status": status,
            "favorite": favorite,
        },
        brands=BRANDS,
        categories=CATEGORIES,
        content_types=CONTENT_TYPES,
        statuses=STATUSES,
        page_title="콘텐츠 라이브러리 | MI Creator OS",
    )


def item_form(item=None, duplicate=False):
    articles = Article.query.order_by(Article.created_at.desc()).limit(200).all()
    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>{{'콘텐츠 수정' if item and not duplicate else '새 콘텐츠 프로젝트'}}</h1>
      <p class="lead">하나의 프로젝트 안에 블로그, 릴스, 인스타툰, 캡션과 CTA를 함께 보관합니다.</p>
    </div>
    <a class="btn gray" href="{{url_for('library_v11.dashboard')}}">라이브러리</a>
  </div>

  <form method="post">
    <label>제목</label>
    <input name="title" required maxlength="300" value="{{item.title if item else ''}}" placeholder="예: 엄마, 왜 과자 봉지가 반이나 비어 있어?">

    <div class="grid">
      <div>
        <label>브랜드</label>
        <select name="brand">{% for value in brands %}<option value="{{value}}" {% if item and item.brand == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select>
      </div>
      <div>
        <label>카테고리</label>
        <select name="category">{% for value in categories %}<option value="{{value}}" {% if item and item.category == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select>
      </div>
      <div>
        <label>콘텐츠 형식</label>
        <select name="content_type">{% for value in content_types %}<option value="{{value}}" {% if item and item.content_type == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select>
      </div>
      <div>
        <label>상태</label>
        <select name="status">{% for value in statuses %}<option value="{{value}}" {% if item and item.status == value %}selected{% endif %}>{{value}}</option>{% endfor %}</select>
      </div>
    </div>

    <div class="grid">
      <div>
        <label>시리즈명</label>
        <input name="series_name" maxlength="200" value="{{item.series_name if item else ''}}" placeholder="예: 엄마, 경제가 뭐야?">
        <p class="small">같은 브랜드와 같은 시리즈명은 자동으로 묶입니다.</p>
      </div>
      <div>
        <label>EP 번호</label>
        <input type="number" min="1" name="episode_number" value="{{item.episode_number if item and item.episode_number else ''}}" placeholder="비우면 다음 번호 자동 지정">
        <p class="small">새 프로젝트에서 비워두면 해당 시리즈의 다음 번호가 자동 입력됩니다.</p>
      </div>
    </div>

    <label>연결할 기존 블로그 글</label>
    <select name="article_id">
      <option value="">연결하지 않음</option>
      {% for article in articles %}
      <option value="{{article.id}}" {% if item and item.article_id == article.id %}selected{% endif %}>{{article.title}}</option>
      {% endfor %}
    </select>

    <label>요약</label>
    <textarea name="summary" rows="3">{{item.summary if item else ''}}</textarea>

    <label>첫 훅</label>
    <textarea name="hook" rows="2">{{item.hook if item else ''}}</textarea>

    <label>인스타툰 구성</label>
    <textarea name="toon_plan" rows="7" placeholder="컷 1~8 구성">{{item.toon_plan if item else ''}}</textarea>

    <label>릴스·쇼츠 대본</label>
    <textarea name="reel_script" rows="7">{{item.reel_script if item else ''}}</textarea>

    <label>블로그 본문 또는 초안</label>
    <textarea name="blog_content" rows="10">{{item.blog_content if item else ''}}</textarea>

    <label>인스타그램 캡션</label>
    <textarea name="instagram_caption" rows="5">{{item.instagram_caption if item else ''}}</textarea>

    <label>Threads 문구</label>
    <textarea name="threads_text" rows="5">{{item.threads_text if item else ''}}</textarea>

    <label>CTA</label>
    <textarea name="cta" rows="3">{{item.cta if item else ''}}</textarea>

    <label>태그</label>
    <input name="tags" value="{{item.tags if item else ''}}" placeholder="육아, 경제교육, 슈링크플레이션">

    <label>게시물 또는 참고 링크</label>
    <input type="url" name="source_url" value="{{item.source_url if item else ''}}" placeholder="https://">

    <label>
      <input type="checkbox" name="is_favorite" value="1" {% if item and item.is_favorite %}checked{% endif %}>
      즐겨찾기
    </label>

    <div class="actions">
      <button class="btn" type="submit">{{'수정 저장' if item and not duplicate else '프로젝트 저장'}}</button>
      <a class="btn gray" href="{{url_for('library_v11.dashboard')}}">취소</a>
    </div>
  </form>
</section>
""",
        item=item,
        duplicate=duplicate,
        articles=articles,
        brands=BRANDS,
        categories=CATEGORIES,
        content_types=CONTENT_TYPES,
        statuses=STATUSES,
        page_title="콘텐츠 프로젝트 | MI Creator OS",
    )


def populate_item(item, is_new=False):
    title = clean_text("title", 300)
    if not title:
        raise ValueError("제목을 입력해 주세요.")

    brand = clean_text("brand", 100)
    if brand not in BRANDS:
        brand = BRANDS[0]

    category = clean_text("category", 100)
    if category not in CATEGORIES:
        category = "일반"

    content_type = clean_text("content_type", 50)
    if content_type not in CONTENT_TYPES:
        content_type = CONTENT_TYPES[0]

    status = clean_text("status", 30)
    if status not in STATUSES:
        status = "기획"

    series_name = clean_text("series_name", 200)
    raw_episode = clean_text("episode_number", 20)
    episode_number = int(raw_episode) if raw_episode else None
    if episode_number is not None and episode_number < 1:
        raise ValueError("EP 번호는 1 이상이어야 합니다.")
    if is_new and series_name and episode_number is None:
        episode_number = next_episode(series_name, brand)

    article_id_raw = clean_text("article_id", 30)
    article_id = int(article_id_raw) if article_id_raw else None
    if article_id and not db.session.get(Article, article_id):
        article_id = None

    item.title = title
    item.brand = brand
    item.category = category
    item.content_type = content_type
    item.status = status
    item.series_name = series_name
    item.episode_number = episode_number
    item.article_id = article_id
    item.summary = clean_text("summary")
    item.hook = clean_text("hook")
    item.toon_plan = clean_text("toon_plan")
    item.reel_script = clean_text("reel_script")
    item.blog_content = clean_text("blog_content")
    item.instagram_caption = clean_text("instagram_caption")
    item.threads_text = clean_text("threads_text")
    item.cta = clean_text("cta")
    item.tags = normalize_tags(clean_text("tags"))
    item.source_url = clean_text("source_url", 1000)
    item.is_favorite = request.form.get("is_favorite") == "1"


@library_bp.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        item = ContentLibraryItem()
        try:
            populate_item(item, is_new=True)
            db.session.add(item)
            db.session.commit()
            flash("콘텐츠 프로젝트를 저장했어요.")
            return redirect(url_for("library_v11.detail", item_id=item.id))
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc))
    return item_form()


@library_bp.get("/<int:item_id>")
def detail(item_id):
    item = db.session.get(ContentLibraryItem, item_id)
    if not item:
        flash("콘텐츠를 찾을 수 없습니다.")
        return redirect(url_for("library_v11.dashboard"))

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>
        {% if item.series_name and item.episode_number %}
          {{item.series_name}} EP.{{"%03d"|format(item.episode_number)}} ·
        {% endif %}
        {{item.title}}
      </h1>
      <p class="lead">{{item.brand}} · {{item.category}} · {{item.content_type}} · {{item.status}}</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn" href="{{url_for('library_v11.edit', item_id=item.id)}}">수정</a>
      <a class="btn gray" href="{{url_for('library_v11.duplicate', item_id=item.id)}}">복제</a>
      <a class="btn gray" href="{{url_for('library_v11.dashboard')}}">목록</a>
    </div>
  </div>

  {% if item.is_favorite %}<span class="tag">★ 즐겨찾기</span>{% endif %}
  {% if item.tags %}<p class="small">#{{item.tags.replace(', ', ' #')}}</p>{% endif %}
  {% if item.source_url %}<p><a href="{{item.source_url}}" target="_blank" rel="noopener">연결된 게시물·참고 링크 열기</a></p>{% endif %}
  {% if item.article %}<p><strong>연결된 블로그:</strong> {{item.article.title}}</p>{% endif %}
</section>

{% for heading,content in sections %}
  {% if content %}
  <section class="card">
    <h2>{{heading}}</h2>
    <div style="white-space:pre-wrap">{{content}}</div>
  </section>
  {% endif %}
{% endfor %}

<section class="card">
  <div class="actions">
    <form method="post" action="{{url_for('library_v11.toggle_favorite', item_id=item.id)}}">
      <button class="btn gray" type="submit">{{'즐겨찾기 해제' if item.is_favorite else '즐겨찾기 추가'}}</button>
    </form>
    <form method="post" action="{{url_for('library_v11.delete', item_id=item.id)}}" onsubmit="return confirm('이 콘텐츠 프로젝트를 삭제할까요?')">
      <button class="btn red" type="submit">삭제</button>
    </form>
  </div>
  <p class="small">생성 {{item.created_at.strftime('%Y-%m-%d %H:%M')}} · 수정 {{item.updated_at.strftime('%Y-%m-%d %H:%M')}}</p>
</section>
""",
        item=item,
        sections=[
            ("요약", item.summary),
            ("첫 훅", item.hook),
            ("인스타툰 구성", item.toon_plan),
            ("릴스·쇼츠 대본", item.reel_script),
            ("블로그 본문·초안", item.blog_content),
            ("인스타그램 캡션", item.instagram_caption),
            ("Threads 문구", item.threads_text),
            ("CTA", item.cta),
        ],
        page_title=f"{item.title} | 콘텐츠 라이브러리",
    )


@library_bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    item = db.session.get(ContentLibraryItem, item_id)
    if not item:
        flash("콘텐츠를 찾을 수 없습니다.")
        return redirect(url_for("library_v11.dashboard"))

    if request.method == "POST":
        try:
            populate_item(item, is_new=False)
            db.session.commit()
            flash("콘텐츠 프로젝트를 수정했어요.")
            return redirect(url_for("library_v11.detail", item_id=item.id))
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc))
    return item_form(item=item)


@library_bp.route("/<int:item_id>/duplicate", methods=["GET", "POST"])
def duplicate(item_id):
    source = db.session.get(ContentLibraryItem, item_id)
    if not source:
        flash("복제할 콘텐츠를 찾을 수 없습니다.")
        return redirect(url_for("library_v11.dashboard"))

    if request.method == "POST":
        item = ContentLibraryItem()
        try:
            populate_item(item, is_new=True)
            db.session.add(item)
            db.session.commit()
            flash("콘텐츠 프로젝트를 복제했어요.")
            return redirect(url_for("library_v11.detail", item_id=item.id))
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc))

    copy = ContentLibraryItem(
        title=f"{source.title} 복사본",
        brand=source.brand,
        category=source.category,
        content_type=source.content_type,
        series_name=source.series_name,
        episode_number=None,
        status="기획",
        summary=source.summary,
        hook=source.hook,
        blog_content=source.blog_content,
        reel_script=source.reel_script,
        instagram_caption=source.instagram_caption,
        threads_text=source.threads_text,
        toon_plan=source.toon_plan,
        cta=source.cta,
        tags=source.tags,
        source_url="",
        is_favorite=False,
        article_id=None,
    )
    return item_form(item=copy, duplicate=True)


@library_bp.post("/<int:item_id>/favorite")
def toggle_favorite(item_id):
    item = db.session.get(ContentLibraryItem, item_id)
    if item:
        item.is_favorite = not item.is_favorite
        db.session.commit()
        flash("즐겨찾기를 변경했어요.")
    return redirect(request.referrer or url_for("library_v11.dashboard"))


@library_bp.post("/<int:item_id>/delete")
def delete(item_id):
    item = db.session.get(ContentLibraryItem, item_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        flash("콘텐츠 프로젝트를 삭제했어요.")
    return redirect(url_for("library_v11.dashboard"))


@library_bp.route("/import-articles", methods=["GET", "POST"])
def import_articles():
    existing_ids = {
        row[0]
        for row in db.session.query(ContentLibraryItem.article_id)
        .filter(ContentLibraryItem.article_id.isnot(None))
        .all()
    }
    articles = (
        Article.query.filter(~Article.id.in_(existing_ids))
        .order_by(Article.created_at.desc())
        .all()
        if existing_ids
        else Article.query.order_by(Article.created_at.desc()).all()
    )

    if request.method == "POST":
        selected = request.form.getlist("article_ids")
        imported = 0
        for raw_id in selected:
            try:
                article_id = int(raw_id)
            except ValueError:
                continue
            if article_id in existing_ids:
                continue
            article = db.session.get(Article, article_id)
            if not article:
                continue

            item = ContentLibraryItem(
                article_id=article.id,
                title=article.title,
                brand=article.brand_style or "기타",
                category="정보",
                content_type="블로그",
                status="게시 완료" if article.blogger_url else "제작 중",
                summary=article.meta_description or "",
                blog_content=article.body_html or "",
                instagram_caption=article.instagram_caption or "",
                threads_text=article.threads_text or "",
                reel_script=article.shorts_script or "",
                tags=normalize_tags(article.tags or ""),
                source_url=article.blogger_url or "",
            )
            db.session.add(item)
            imported += 1

        db.session.commit()
        flash(f"기존 블로그 글 {imported}개를 라이브러리로 가져왔어요.")
        return redirect(url_for("library_v11.dashboard"))

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>기존 글 가져오기</h1>
      <p class="lead">아직 라이브러리에 연결되지 않은 블로그 글을 선택해 프로젝트로 가져옵니다.</p>
    </div>
    <a class="btn gray" href="{{url_for('library_v11.dashboard')}}">라이브러리</a>
  </div>

  <form method="post">
    {% for article in articles %}
    <label class="calendar-item" style="display:block;cursor:pointer">
      <input type="checkbox" name="article_ids" value="{{article.id}}">
      <strong>{{article.title}}</strong><br>
      <span class="small">{{article.brand_style}} · {{article.created_at.strftime('%Y-%m-%d')}}</span>
    </label>
    {% else %}
    <p class="small">가져올 새 글이 없습니다.</p>
    {% endfor %}

    {% if articles %}
    <div class="actions"><button class="btn" type="submit">선택한 글 가져오기</button></div>
    {% endif %}
  </form>
</section>
""",
        articles=articles,
        page_title="기존 글 가져오기 | 콘텐츠 라이브러리",
    )
