"""V10 AI content manager, hook generator, reel director, and A/B lab."""
import json
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup
from sqlalchemy import func

from ..legacy_app import (
    BASE_HTML,
    Article,
    OPENAI_MODEL,
    db,
    openai_client,
    strip_code_fence,
)
from .analytics import ContentMetric
from .planner import WeeklyPlanItem
from .social import SocialInteraction


manager_bp = Blueprint("manager_v10", __name__, url_prefix="/manager")


class HookPack(db.Model):
    __tablename__ = "hook_pack"

    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(300), nullable=False)
    brand = db.Column(db.String(100), nullable=False, default="말썽쟁이 딸랑구")
    audience = db.Column(db.String(300), default="")
    result_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ReelPlan(db.Model):
    __tablename__ = "reel_plan"

    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(300), nullable=False)
    brand = db.Column(db.String(100), nullable=False, default="말썽쟁이 딸랑구")
    duration = db.Column(db.Integer, nullable=False, default=15)
    cast = db.Column(db.String(200), default="엄마와 딸")
    result_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ABExperiment(db.Model):
    __tablename__ = "ab_experiment"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    channel = db.Column(db.String(30), nullable=False, default="instagram")
    variant_a = db.Column(db.Text, nullable=False)
    variant_b = db.Column(db.Text, nullable=False)
    views_a = db.Column(db.Integer, nullable=False, default=0)
    reactions_a = db.Column(db.Integer, nullable=False, default=0)
    clicks_a = db.Column(db.Integer, nullable=False, default=0)
    views_b = db.Column(db.Integer, nullable=False, default=0)
    reactions_b = db.Column(db.Integer, nullable=False, default=0)
    clicks_b = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="running")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


BRANDS = [
    "말썽쟁이 딸랑구",
    "미우와 웅이",
    "보험·재무",
    "애터미·생활용품",
    "쿠팡·쇼핑",
]

CHANNELS = {
    "instagram": "인스타그램",
    "shorts": "릴스·쇼츠",
    "threads": "Threads",
    "blog": "블로그",
}


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def parse_json_response(raw):
    raw = strip_code_fence(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise RuntimeError("AI 응답을 JSON으로 읽지 못했습니다.")
        return json.loads(match.group(0))


def nonnegative_int(name):
    value = int((request.form.get(name, "0") or "0").replace(",", "").strip())
    if value < 0:
        raise ValueError
    return value


def generate_hooks(topic, brand, audience):
    prompt = f"""
당신은 한국어 숏폼·SNS 훅 전문 기획자입니다.

주제: {topic}
브랜드: {brand}
대상: {audience or '일반 팔로워'}

아래 4종류의 훅을 각각 정확히 5개씩 만드세요.
- views: 첫 1초에 시선을 잡는 조회수형
- saves: 다시 보고 싶게 만드는 저장형
- comments: 경험과 의견을 묻게 하는 댓글유도형
- sales: 과장 없이 궁금증과 행동을 만드는 판매형

규칙:
1. 각 훅은 35자 안팎의 짧은 한국어 문장입니다.
2. 확인하지 않은 가격, 효과, 통계는 만들지 않습니다.
3. 보험·건강 콘텐츠는 공포를 과장하거나 가입을 강요하지 않습니다.
4. 제품이 주어지지 않았다면 특정 상품명이나 가격을 지어내지 않습니다.
5. 가족 콘텐츠는 자연스럽고 현실적인 대화처럼 씁니다.

JSON 하나만 출력하세요.
{{
  "views": ["...", "...", "...", "...", "..."],
  "saves": ["...", "...", "...", "...", "..."],
  "comments": ["...", "...", "...", "...", "..."],
  "sales": ["...", "...", "...", "...", "..."]
}}
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    data = parse_json_response(response.output_text)
    result = {}
    for key in ("views", "saves", "comments", "sales"):
        values = data.get(key) or []
        if len(values) != 5:
            raise RuntimeError(f"{key} 훅이 5개 생성되지 않았습니다.")
        result[key] = [str(value).strip()[:300] for value in values]
    return result


def generate_reel_plan(topic, brand, duration, cast):
    prompt = f"""
당신은 초보자도 그대로 촬영할 수 있게 설명하는 한국어 릴스 촬영 감독입니다.

주제: {topic}
브랜드: {brand}
총 길이: {duration}초
출연: {cast or '1명'}

필수 결과:
- title: 영상 제목
- hook: 시작 1~3초 훅
- shots: 시간순 촬영표
- subtitles: 핵심 자막 목록
- caption: 업로드 캡션
- cta: 마지막 행동 유도
- props: 필요한 소품
- edit_notes: 편집 주의사항

shots 각 항목에는 start, end, camera, action, dialogue, subtitle를 넣으세요.
총 시간은 {duration}초를 넘지 않게 구성하세요.
초보자가 휴대전화로 촬영할 수 있게 구체적으로 씁니다.
확인하지 않은 제품 효능과 가격은 만들지 않습니다.
JSON 하나만 출력하세요.

{{
  "title": "...",
  "hook": "...",
  "shots": [
    {{
      "start": 0,
      "end": 3,
      "camera": "...",
      "action": "...",
      "dialogue": "...",
      "subtitle": "..."
    }}
  ],
  "subtitles": ["...", "..."],
  "caption": "...",
  "cta": "...",
  "props": ["..."],
  "edit_notes": ["..."]
}}
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    data = parse_json_response(response.output_text)
    if not data.get("shots"):
        raise RuntimeError("촬영 순서가 생성되지 않았습니다.")
    return data


def experiment_result(exp):
    def score(views, reactions, clicks):
        if views <= 0:
            return 0
        return (reactions * 1.0 + clicks * 2.0) / views * 100

    score_a = score(exp.views_a, exp.reactions_a, exp.clicks_a)
    score_b = score(exp.views_b, exp.reactions_b, exp.clicks_b)

    if exp.views_a == 0 or exp.views_b == 0:
        winner = "데이터 대기"
    elif abs(score_a - score_b) < 0.1:
        winner = "현재 비슷함"
    elif score_a > score_b:
        winner = "A안 우세"
    else:
        winner = "B안 우세"

    return {
        "score_a": score_a,
        "score_b": score_b,
        "winner": winner,
    }


def today_brief():
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = today_start + timedelta(days=1)

    planned = WeeklyPlanItem.query.filter_by(plan_date=today).all()
    social_high = SocialInteraction.query.filter(
        SocialInteraction.priority == "high",
        SocialInteraction.status.in_(["new", "drafted"]),
    ).count()
    social_open = SocialInteraction.query.filter(
        SocialInteraction.status.in_(["new", "drafted", "approved"])
    ).count()

    recent_metrics = (
        db.session.query(ContentMetric, Article)
        .join(Article, Article.id == ContentMetric.article_id)
        .filter(ContentMetric.measured_at >= today - timedelta(days=30))
        .all()
    )

    best_title = None
    best_score = -1
    for metric, article in recent_metrics:
        views = max(metric.views, 1)
        score = (
            metric.likes
            + metric.comments
            + metric.saves
            + metric.shares
            + metric.clicks * 2
        ) / views
        if score > best_score:
            best_score = score
            best_title = article.title

    created_today = Article.query.filter(
        Article.created_at >= today_start,
        Article.created_at < today_end,
    ).count()

    return {
        "planned": planned,
        "social_high": social_high,
        "social_open": social_open,
        "best_title": best_title,
        "created_today": created_today,
    }


@manager_bp.get("/")
def dashboard():
    brief = today_brief()
    hook_packs = HookPack.query.order_by(HookPack.created_at.desc()).limit(5).all()
    reel_plans = ReelPlan.query.order_by(ReelPlan.created_at.desc()).limit(5).all()
    experiments = ABExperiment.query.order_by(ABExperiment.created_at.desc()).limit(10).all()
    experiment_rows = [(exp, experiment_result(exp)) for exp in experiments]

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>AI 콘텐츠 매니저 <span class="status">V10</span></h1>
      <p class="lead">오늘 할 일, 훅 제작, 릴스 촬영표, A/B 실험을 한곳에서 운영합니다.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('social_v96.dashboard')}}">AI 소통 비서</a>
      <a class="btn gray" href="{{url_for('home')}}">홈으로</a>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{brief.planned|length}}</strong><span class="small">오늘 계획</span></div>
    <div class="stat"><strong>{{brief.created_today}}</strong><span class="small">오늘 생성 콘텐츠</span></div>
    <div class="stat"><strong>{{brief.social_high}}</strong><span class="small">우선 답변</span></div>
    <div class="stat"><strong>{{brief.social_open}}</strong><span class="small">열린 소통 항목</span></div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>오늘의 운영 브리핑</h2>
  {% if brief.planned %}
    {% for item in brief.planned %}
    <div class="calendar-item">
      <strong>{{item.title}}</strong><br>
      <span class="small">{{item.brand}} · {{item.format_type}} · {{item.status}}</span>
      {% if item.hook %}<p>{{item.hook}}</p>{% endif %}
    </div>
    {% endfor %}
  {% else %}
    <div class="calendar-item">오늘 등록된 콘텐츠 계획이 없습니다. 주간 플래너에서 오늘 계획을 추가해 보세요.</div>
  {% endif %}

  {% if brief.best_title %}
  <div class="calendar-item">
    <strong>최근 30일 반응 힌트</strong><br>
    <span>입력된 성과 기록상 ‘{{brief.best_title}}’가 상대적으로 좋은 반응을 보였습니다.</span>
  </div>
  {% else %}
  <div class="calendar-item">
    <strong>성과 힌트 준비 중</strong><br>
    <span>성과 분석 화면에 실제 수치를 입력하면 추천 근거가 생깁니다.</span>
  </div>
  {% endif %}
</section>

<section class="card">
  <h2>빠른 실행</h2>
  <a class="calendar-item" style="display:block;text-decoration:none" href="{{url_for('manager_v10.hooks')}}">
    <strong>AI 훅 생성기</strong><br><span class="small">조회수형·저장형·댓글형·판매형 총 20개</span>
  </a>
  <a class="calendar-item" style="display:block;text-decoration:none" href="{{url_for('manager_v10.reels')}}">
    <strong>릴스 촬영 감독</strong><br><span class="small">초 단위 촬영 순서, 대사, 자막, CTA</span>
  </a>
  <a class="calendar-item" style="display:block;text-decoration:none" href="{{url_for('manager_v10.experiments')}}">
    <strong>콘텐츠 실험실</strong><br><span class="small">A안과 B안 성과를 같은 기준으로 비교</span>
  </a>
</section>
</div>

<section class="card">
  <h2>최근 작업</h2>
  <div class="grid">
    <div>
      <h3>훅 묶음</h3>
      {% for item in hook_packs %}
      <div class="calendar-item"><strong>{{item.topic}}</strong><br><span class="small">{{item.brand}} · {{item.created_at.strftime('%m-%d %H:%M')}}</span></div>
      {% else %}<p class="small">아직 생성한 훅이 없습니다.</p>{% endfor %}
    </div>
    <div>
      <h3>릴스 기획</h3>
      {% for item in reel_plans %}
      <div class="calendar-item"><strong>{{item.topic}}</strong><br><span class="small">{{item.duration}}초 · {{item.created_at.strftime('%m-%d %H:%M')}}</span></div>
      {% else %}<p class="small">아직 생성한 릴스 기획이 없습니다.</p>{% endfor %}
    </div>
  </div>

  <h3>A/B 실험 현황</h3>
  {% for exp,result in experiment_rows %}
  <div class="calendar-item">
    <strong>{{exp.name}}</strong>
    <span class="status">{{result.winner}}</span><br>
    <span class="small">A {{'%.1f'|format(result.score_a)}}점 · B {{'%.1f'|format(result.score_b)}}점 · {{channels.get(exp.channel, exp.channel)}}</span>
  </div>
  {% else %}<p class="small">진행 중인 실험이 없습니다.</p>{% endfor %}
</section>
""",
        brief=brief,
        hook_packs=hook_packs,
        reel_plans=reel_plans,
        experiment_rows=experiment_rows,
        channels=CHANNELS,
        page_title="AI 콘텐츠 매니저 | MI Creator Hub",
    )


@manager_bp.route("/hooks", methods=["GET", "POST"])
def hooks():
    generated = None
    current = None

    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        brand = request.form.get("brand", BRANDS[0]).strip()
        audience = request.form.get("audience", "").strip()
        if not topic:
            flash("훅을 만들 주제를 입력해 주세요.")
            return redirect(url_for("manager_v10.hooks"))

        try:
            generated = generate_hooks(topic, brand, audience)
            current = HookPack(
                topic=topic[:300],
                brand=brand[:100],
                audience=audience[:300],
                result_json=json.dumps(generated, ensure_ascii=False),
            )
            db.session.add(current)
            db.session.commit()
            flash("훅 20개를 만들었어요.")
        except Exception as exc:
            db.session.rollback()
            flash(f"훅 생성 실패: {exc}")

    pack_id = request.args.get("id", type=int)
    if pack_id and not generated:
        current = db.session.get(HookPack, pack_id)
        if current:
            generated = json.loads(current.result_json or "{}")

    recent = HookPack.query.order_by(HookPack.created_at.desc()).limit(20).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>AI 훅 생성기</h1><p class="lead">한 주제로 목적이 다른 훅 20개를 만듭니다.</p></div>
    <a class="btn gray" href="{{url_for('manager_v10.dashboard')}}">매니저 홈</a>
  </div>

  <form method="post">
    <label>주제</label>
    <input name="topic" required placeholder="예: 엄마, 왜 과자 봉지가 반이나 비어 있어?">

    <div class="grid">
      <div>
        <label>브랜드</label>
        <select name="brand">{% for brand in brands %}<option>{{brand}}</option>{% endfor %}</select>
      </div>
      <div>
        <label>대상</label>
        <input name="audience" placeholder="예: 초등학생 자녀를 둔 엄마">
      </div>
    </div>

    <div class="actions"><button class="btn" type="submit">훅 20개 생성</button></div>
  </form>
</section>

{% if generated %}
<section class="card">
  <h2>{{current.topic}}</h2>
  {% for key,label in labels.items() %}
  <h3>{{label}}</h3>
  {% for text in generated.get(key, []) %}
  <div class="calendar-item">{{loop.index}}. {{text}}</div>
  {% endfor %}
  {% endfor %}
</section>
{% endif %}

<section class="card">
  <h2>최근 생성 기록</h2>
  {% for item in recent %}
  <a class="calendar-item" style="display:block;text-decoration:none" href="{{url_for('manager_v10.hooks', id=item.id)}}">
    <strong>{{item.topic}}</strong><br><span class="small">{{item.brand}} · {{item.created_at.strftime('%Y-%m-%d %H:%M')}}</span>
  </a>
  {% else %}<p class="small">생성 기록이 없습니다.</p>{% endfor %}
</section>
""",
        generated=generated,
        current=current,
        recent=recent,
        brands=BRANDS,
        labels={
            "views": "조회수형",
            "saves": "저장형",
            "comments": "댓글유도형",
            "sales": "판매형",
        },
        page_title="AI 훅 생성기 | MI Creator Hub",
    )


@manager_bp.route("/reels", methods=["GET", "POST"])
def reels():
    generated = None
    current = None

    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        brand = request.form.get("brand", BRANDS[0]).strip()
        cast = request.form.get("cast", "엄마와 딸").strip()
        duration = request.form.get("duration", type=int) or 15
        duration = max(8, min(duration, 90))

        if not topic:
            flash("릴스 주제를 입력해 주세요.")
            return redirect(url_for("manager_v10.reels"))

        try:
            generated = generate_reel_plan(topic, brand, duration, cast)
            current = ReelPlan(
                topic=topic[:300],
                brand=brand[:100],
                duration=duration,
                cast=cast[:200],
                result_json=json.dumps(generated, ensure_ascii=False),
            )
            db.session.add(current)
            db.session.commit()
            flash("릴스 촬영표를 만들었어요.")
        except Exception as exc:
            db.session.rollback()
            flash(f"릴스 기획 생성 실패: {exc}")

    plan_id = request.args.get("id", type=int)
    if plan_id and not generated:
        current = db.session.get(ReelPlan, plan_id)
        if current:
            generated = json.loads(current.result_json or "{}")

    recent = ReelPlan.query.order_by(ReelPlan.created_at.desc()).limit(20).all()

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>릴스 촬영 감독</h1><p class="lead">휴대전화로 그대로 따라 찍을 수 있는 초 단위 촬영표를 만듭니다.</p></div>
    <a class="btn gray" href="{{url_for('manager_v10.dashboard')}}">매니저 홈</a>
  </div>

  <form method="post">
    <label>주제</label>
    <input name="topic" required placeholder="예: 딸이 엄마 치약을 몰래 쓴 날">

    <div class="grid">
      <div>
        <label>브랜드</label>
        <select name="brand">{% for brand in brands %}<option>{{brand}}</option>{% endfor %}</select>
      </div>
      <div>
        <label>출연</label>
        <input name="cast" value="엄마와 딸">
      </div>
      <div>
        <label>길이</label>
        <select name="duration">
          <option value="15">15초</option>
          <option value="30">30초</option>
          <option value="45">45초</option>
          <option value="60">60초</option>
        </select>
      </div>
    </div>

    <div class="actions"><button class="btn" type="submit">촬영표 생성</button></div>
  </form>
</section>

{% if generated %}
<section class="card">
  <h2>{{generated.get('title', current.topic)}}</h2>
  <div class="calendar-item"><strong>첫 훅</strong><br>{{generated.get('hook','')}}</div>

  <h3>촬영 순서</h3>
  <table>
    <thead><tr><th>시간</th><th>카메라</th><th>행동·대사</th><th>자막</th></tr></thead>
    <tbody>
    {% for shot in generated.get('shots', []) %}
    <tr>
      <td>{{shot.get('start',0)}}~{{shot.get('end',0)}}초</td>
      <td>{{shot.get('camera','')}}</td>
      <td><strong>{{shot.get('action','')}}</strong><br><span class="small">{{shot.get('dialogue','')}}</span></td>
      <td>{{shot.get('subtitle','')}}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>

  <div class="grid">
    <div>
      <h3>필요한 소품</h3>
      {% for item in generated.get('props', []) %}<div class="calendar-item">{{item}}</div>{% endfor %}
    </div>
    <div>
      <h3>편집 주의사항</h3>
      {% for item in generated.get('edit_notes', []) %}<div class="calendar-item">{{item}}</div>{% endfor %}
    </div>
  </div>

  <h3>캡션</h3>
  <div class="calendar-item" style="white-space:pre-wrap">{{generated.get('caption','')}}</div>
  <h3>마무리 CTA</h3>
  <div class="calendar-item">{{generated.get('cta','')}}</div>
</section>
{% endif %}

<section class="card">
  <h2>최근 촬영 기획</h2>
  {% for item in recent %}
  <a class="calendar-item" style="display:block;text-decoration:none" href="{{url_for('manager_v10.reels', id=item.id)}}">
    <strong>{{item.topic}}</strong><br><span class="small">{{item.brand}} · {{item.duration}}초 · {{item.created_at.strftime('%Y-%m-%d %H:%M')}}</span>
  </a>
  {% else %}<p class="small">생성 기록이 없습니다.</p>{% endfor %}
</section>
""",
        generated=generated,
        current=current,
        recent=recent,
        brands=BRANDS,
        page_title="릴스 촬영 감독 | MI Creator Hub",
    )


@manager_bp.route("/experiments", methods=["GET", "POST"])
def experiments():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        variant_a = request.form.get("variant_a", "").strip()
        variant_b = request.form.get("variant_b", "").strip()
        channel = request.form.get("channel", "instagram")
        if not name or not variant_a or not variant_b:
            flash("실험명과 A안, B안을 모두 입력해 주세요.")
        else:
            exp = ABExperiment(
                name=name[:300],
                channel=channel if channel in CHANNELS else "instagram",
                variant_a=variant_a[:3000],
                variant_b=variant_b[:3000],
            )
            db.session.add(exp)
            db.session.commit()
            flash("A/B 실험을 만들었어요.")
        return redirect(url_for("manager_v10.experiments"))

    rows = [
        (exp, experiment_result(exp))
        for exp in ABExperiment.query.order_by(ABExperiment.created_at.desc()).all()
    ]

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div><h1>콘텐츠 실험실</h1><p class="lead">제목·훅·CTA 두 버전을 같은 기준으로 비교합니다.</p></div>
    <a class="btn gray" href="{{url_for('manager_v10.dashboard')}}">매니저 홈</a>
  </div>

  <form method="post">
    <label>실험 이름</label>
    <input name="name" required placeholder="예: 과자 슈링크플레이션 릴스 첫 훅">

    <label>채널</label>
    <select name="channel">{% for key,label in channels.items() %}<option value="{{key}}">{{label}}</option>{% endfor %}</select>

    <div class="grid">
      <div><label>A안</label><textarea name="variant_a" rows="5" required></textarea></div>
      <div><label>B안</label><textarea name="variant_b" rows="5" required></textarea></div>
    </div>

    <div class="actions"><button class="btn" type="submit">실험 만들기</button></div>
  </form>
  <p class="notice">A와 B는 가능한 한 업로드 시간·주제·길이를 비슷하게 맞춰야 비교가 의미 있습니다.</p>
</section>

<section class="card">
  <h2>실험 목록</h2>
  {% for exp,result in rows %}
  <div class="calendar-item" style="margin-bottom:16px">
    <div class="actions" style="justify-content:space-between;margin-top:0">
      <div><strong>{{exp.name}}</strong> <span class="status">{{result.winner}}</span></div>
      <span class="small">{{channels.get(exp.channel, exp.channel)}} · {{exp.created_at.strftime('%Y-%m-%d')}}</span>
    </div>

    <div class="grid">
      <div>
        <h3>A안 · {{'%.1f'|format(result.score_a)}}점</h3>
        <div class="calendar-item" style="white-space:pre-wrap">{{exp.variant_a}}</div>
      </div>
      <div>
        <h3>B안 · {{'%.1f'|format(result.score_b)}}점</h3>
        <div class="calendar-item" style="white-space:pre-wrap">{{exp.variant_b}}</div>
      </div>
    </div>

    <form method="post" action="{{url_for('manager_v10.update_experiment', experiment_id=exp.id)}}">
      <div class="grid">
        <div>
          <h3>A 성과</h3>
          <label>조회수</label><input type="number" min="0" name="views_a" value="{{exp.views_a}}">
          <label>반응 합계</label><input type="number" min="0" name="reactions_a" value="{{exp.reactions_a}}">
          <label>클릭</label><input type="number" min="0" name="clicks_a" value="{{exp.clicks_a}}">
        </div>
        <div>
          <h3>B 성과</h3>
          <label>조회수</label><input type="number" min="0" name="views_b" value="{{exp.views_b}}">
          <label>반응 합계</label><input type="number" min="0" name="reactions_b" value="{{exp.reactions_b}}">
          <label>클릭</label><input type="number" min="0" name="clicks_b" value="{{exp.clicks_b}}">
        </div>
      </div>
      <div class="actions">
        <button class="btn" type="submit">성과 저장</button>
        <button class="btn gray" name="finish" value="1" type="submit">실험 종료</button>
      </div>
    </form>

    <form method="post" action="{{url_for('manager_v10.delete_experiment', experiment_id=exp.id)}}" onsubmit="return confirm('실험을 삭제할까요?')">
      <button class="btn red" type="submit">삭제</button>
    </form>
  </div>
  {% else %}<p class="small">아직 실험이 없습니다.</p>{% endfor %}
</section>
""",
        rows=rows,
        channels=CHANNELS,
        page_title="콘텐츠 실험실 | MI Creator Hub",
    )


@manager_bp.post("/experiments/<int:experiment_id>/update")
def update_experiment(experiment_id):
    exp = db.session.get(ABExperiment, experiment_id)
    if not exp:
        flash("실험을 찾을 수 없습니다.")
        return redirect(url_for("manager_v10.experiments"))

    try:
        exp.views_a = nonnegative_int("views_a")
        exp.reactions_a = nonnegative_int("reactions_a")
        exp.clicks_a = nonnegative_int("clicks_a")
        exp.views_b = nonnegative_int("views_b")
        exp.reactions_b = nonnegative_int("reactions_b")
        exp.clicks_b = nonnegative_int("clicks_b")
        if request.form.get("finish") == "1":
            exp.status = "completed"
        db.session.commit()
        flash("실험 성과를 저장했어요.")
    except (TypeError, ValueError):
        db.session.rollback()
        flash("성과 수치는 0 이상의 숫자로 입력해 주세요.")

    return redirect(url_for("manager_v10.experiments"))


@manager_bp.post("/experiments/<int:experiment_id>/delete")
def delete_experiment(experiment_id):
    exp = db.session.get(ABExperiment, experiment_id)
    if exp:
        db.session.delete(exp)
        db.session.commit()
        flash("실험을 삭제했어요.")
    return redirect(url_for("manager_v10.experiments"))
