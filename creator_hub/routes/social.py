"""V9.6 AI engagement assistant with approval-only workflow."""
import json
import re
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from markupsafe import Markup

from ..legacy_app import BASE_HTML, db, openai_client, OPENAI_MODEL, strip_code_fence


social_bp = Blueprint("social_v96", __name__, url_prefix="/social")


class SocialInteraction(db.Model):
    __tablename__ = "social_interaction"

    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(30), nullable=False, default="instagram")
    interaction_type = db.Column(db.String(20), nullable=False, default="comment")
    sender_name = db.Column(db.String(120), nullable=False, default="알 수 없음")
    message_text = db.Column(db.Text, nullable=False)
    post_title = db.Column(db.String(300), default="")
    category = db.Column(db.String(30), nullable=False, default="general")
    priority = db.Column(db.String(20), nullable=False, default="normal")
    draft_1 = db.Column(db.Text, default="")
    draft_2 = db.Column(db.Text, default="")
    draft_3 = db.Column(db.Text, default="")
    selected_draft = db.Column(db.Integer, nullable=True)
    approved_reply = db.Column(db.Text, default="")
    status = db.Column(db.String(20), nullable=False, default="new")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


PLATFORMS = {
    "instagram": "인스타그램",
    "threads": "Threads",
    "youtube": "유튜브",
    "blog": "블로그",
}

TYPES = {
    "comment": "댓글",
    "dm": "DM·문의",
}

CATEGORIES = {
    "purchase": "구매·상담 문의",
    "collaboration": "협찬·광고",
    "question": "질문",
    "compliment": "칭찬·공감",
    "complaint": "불만",
    "spam": "스팸 의심",
    "general": "일반",
}

PRIORITIES = {
    "high": "우선 답변",
    "normal": "일반",
    "low": "낮음",
}


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def local_classification(message):
    """Cheap fallback classification when AI is unavailable."""
    text = (message or "").lower()
    if any(word in text for word in ["가격", "얼마", "구매", "링크", "어디서", "상담", "가입", "주문"]):
        return "purchase", "high"
    if any(word in text for word in ["협찬", "광고", "제휴", "콜라보"]):
        return "collaboration", "high"
    if any(word in text for word in ["싫", "별로", "불편", "환불", "문제", "화나"]):
        return "complaint", "high"
    if any(word in text for word in ["http://", "https://", "홍보합니다", "팔로우해"]):
        return "spam", "low"
    if "?" in text or any(word in text for word in ["어떻게", "왜", "뭐", "무엇", "궁금"]):
        return "question", "normal"
    if any(word in text for word in ["공감", "귀여", "좋아요", "멋져", "예뻐", "재밌"]):
        return "compliment", "normal"
    return "general", "normal"


def generate_reply_package(interaction):
    prompt = f"""
당신은 한국어 SNS 고객 소통 비서입니다.
아래 메시지에 답할 짧고 자연스러운 답변 초안 3개를 만드세요.

플랫폼: {PLATFORMS.get(interaction.platform, interaction.platform)}
유형: {TYPES.get(interaction.interaction_type, interaction.interaction_type)}
보낸 사람: {interaction.sender_name}
연결된 게시물: {interaction.post_title or '없음'}
메시지: {interaction.message_text}

규칙:
1. 과장, 허위 사실, 확정적 효능 표현을 쓰지 않습니다.
2. 보험·건강·가격 문의는 구체 정보를 지어내지 말고 추가 확인 질문을 합니다.
3. 구매 문의에는 부담스럽지 않은 상담 유도 문장을 포함할 수 있습니다.
4. 불만에는 먼저 공감하고 공개 댓글에서 개인정보를 요구하지 않습니다.
5. 답변은 각각 1~3문장으로 짧게 작성합니다.
6. 자동 발송을 전제로 하지 말고 사람이 검토하기 좋은 초안으로 작성합니다.
7. category는 purchase, collaboration, question, compliment, complaint, spam, general 중 하나입니다.
8. priority는 high, normal, low 중 하나입니다.

JSON 하나만 출력하세요.
{{
  "category": "question",
  "priority": "normal",
  "drafts": ["초안1", "초안2", "초안3"]
}}
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    raw = strip_code_fence(response.output_text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise RuntimeError("AI 답변을 읽지 못했습니다.")
        data = json.loads(match.group(0))

    drafts = data.get("drafts") or []
    if len(drafts) < 3:
        raise RuntimeError("AI가 답변 초안 3개를 만들지 못했습니다.")

    category = data.get("category", "general")
    priority = data.get("priority", "normal")
    if category not in CATEGORIES:
        category = "general"
    if priority not in PRIORITIES:
        priority = "normal"

    return category, priority, [str(item).strip()[:1200] for item in drafts[:3]]


@social_bp.get("/")
def dashboard():
    status = request.args.get("status", "all")
    query = SocialInteraction.query
    if status in {"new", "drafted", "approved", "completed"}:
        query = query.filter_by(status=status)

    interactions = query.order_by(
        db.case(
            (SocialInteraction.priority == "high", 1),
            (SocialInteraction.priority == "normal", 2),
            else_=3,
        ),
        SocialInteraction.created_at.desc(),
    ).all()

    counts = {
        "new": SocialInteraction.query.filter_by(status="new").count(),
        "drafted": SocialInteraction.query.filter_by(status="drafted").count(),
        "approved": SocialInteraction.query.filter_by(status="approved").count(),
        "high": SocialInteraction.query.filter_by(priority="high").filter(
            SocialInteraction.status.in_(["new", "drafted"])
        ).count(),
    }

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>AI 소통 비서 <span class="status">V9.6</span></h1>
      <p class="lead">댓글과 문의를 정리하고 답변 초안 3개를 만든 뒤, 미경님 승인 후에만 사용합니다.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('diagnostics_v95.dashboard')}}">시스템 점검</a>
      <a class="btn gray" href="{{url_for('home')}}">홈으로</a>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{counts.high}}</strong><span class="small">우선 답변</span></div>
    <div class="stat"><strong>{{counts.new}}</strong><span class="small">새 메시지</span></div>
    <div class="stat"><strong>{{counts.drafted}}</strong><span class="small">초안 생성됨</span></div>
    <div class="stat"><strong>{{counts.approved}}</strong><span class="small">승인 대기·완료</span></div>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>댓글·DM 등록</h2>
  <form method="post" action="{{url_for('social_v96.add_interaction')}}">
    <div class="grid">
      <div>
        <label>플랫폼</label>
        <select name="platform">
          {% for key,label in platforms.items() %}<option value="{{key}}">{{label}}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label>유형</label>
        <select name="interaction_type">
          {% for key,label in types.items() %}<option value="{{key}}">{{label}}</option>{% endfor %}
        </select>
      </div>
    </div>

    <label>보낸 사람</label>
    <input name="sender_name" maxlength="120" placeholder="예: happy_mom23">

    <label>연결된 게시물</label>
    <input name="post_title" maxlength="300" placeholder="예: 과자 봉지가 반이나 비어 있어">

    <label>댓글 또는 문의 내용</label>
    <textarea name="message_text" rows="5" required placeholder="내용을 붙여 넣어 주세요."></textarea>

    <div class="actions">
      <button class="btn" type="submit">등록하고 분류하기</button>
    </div>
  </form>
  <p class="notice">현재 버전은 수동 등록 방식입니다. 계정 비밀번호를 저장하거나 비공식 자동 로그인을 하지 않습니다.</p>
</section>

<section class="card">
  <h2>안전한 운영 흐름</h2>
  <div class="calendar-item"><strong>1. 등록</strong><br><span class="small">댓글이나 DM 내용을 붙여 넣습니다.</span></div>
  <div class="calendar-item"><strong>2. AI 초안</strong><br><span class="small">분류와 답변 3개를 생성합니다.</span></div>
  <div class="calendar-item"><strong>3. 승인</strong><br><span class="small">미경님이 문구를 선택하거나 직접 수정합니다.</span></div>
  <div class="calendar-item"><strong>4. 직접 발송</strong><br><span class="small">현재는 복사해서 플랫폼에 붙여 넣습니다. 자동 발송은 하지 않습니다.</span></div>
</section>
</div>

<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <h2>소통함</h2>
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('social_v96.dashboard', status='all')}}">전체</a>
      <a class="btn gray" href="{{url_for('social_v96.dashboard', status='new')}}">새 메시지</a>
      <a class="btn gray" href="{{url_for('social_v96.dashboard', status='drafted')}}">초안</a>
      <a class="btn gray" href="{{url_for('social_v96.dashboard', status='approved')}}">승인</a>
      <a class="btn gray" href="{{url_for('social_v96.dashboard', status='completed')}}">완료</a>
    </div>
  </div>

  {% if interactions %}
    {% for item in interactions %}
    <div class="calendar-item" style="margin-bottom:14px">
      <div class="actions" style="justify-content:space-between;margin-top:0">
        <div>
          {% if item.priority == 'high' %}<span class="tag">우선 답변</span>{% endif %}
          <span class="status">{{categories.get(item.category, item.category)}}</span>
          <strong>{{item.sender_name}}</strong>
          <span class="small">· {{platforms.get(item.platform, item.platform)}} {{types.get(item.interaction_type, item.interaction_type)}}</span>
        </div>
        <span class="small">{{item.created_at.strftime('%Y-%m-%d %H:%M')}}</span>
      </div>

      {% if item.post_title %}<p class="small">게시물: {{item.post_title}}</p>{% endif %}
      <p style="white-space:pre-wrap">{{item.message_text}}</p>

      {% if item.draft_1 %}
      <form method="post" action="{{url_for('social_v96.approve', interaction_id=item.id)}}">
        {% for number,text in [(1,item.draft_1),(2,item.draft_2),(3,item.draft_3)] %}
        <label class="calendar-item" style="display:block;cursor:pointer">
          <input type="radio" name="selected_draft" value="{{number}}" {% if item.selected_draft == number %}checked{% endif %}>
          <strong>답변 {{number}}</strong><br>
          <span>{{text}}</span>
        </label>
        {% endfor %}
        <label>승인 전 직접 수정 가능</label>
        <textarea name="custom_reply" rows="3" placeholder="선택한 문구 대신 직접 작성해도 됩니다.">{{item.approved_reply if item.status == 'approved' else ''}}</textarea>
        <div class="actions">
          <button class="btn" type="submit">답변 승인</button>
          {% if item.status == 'approved' %}
          <button class="btn gray" formaction="{{url_for('social_v96.complete', interaction_id=item.id)}}" type="submit">직접 발송 완료 표시</button>
          {% endif %}
        </div>
      </form>
      {% else %}
      <form method="post" action="{{url_for('social_v96.generate_drafts', interaction_id=item.id)}}">
        <button class="btn" type="submit">AI 답변 3개 만들기</button>
      </form>
      {% endif %}

      <div class="actions">
        <form method="post" action="{{url_for('social_v96.delete', interaction_id=item.id)}}" onsubmit="return confirm('이 항목을 삭제할까요?')">
          <button class="btn red" type="submit">삭제</button>
        </form>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <p class="small">조건에 맞는 메시지가 없습니다.</p>
  {% endif %}
</section>
""",
        interactions=interactions,
        counts=counts,
        platforms=PLATFORMS,
        types=TYPES,
        categories=CATEGORIES,
        page_title="AI 소통 비서 | MI Creator OS",
    )


@social_bp.post("/add")
def add_interaction():
    message = request.form.get("message_text", "").strip()
    if not message:
        flash("댓글이나 문의 내용을 입력해 주세요.")
        return redirect(url_for("social_v96.dashboard"))

    platform = request.form.get("platform", "instagram")
    interaction_type = request.form.get("interaction_type", "comment")
    if platform not in PLATFORMS:
        platform = "instagram"
    if interaction_type not in TYPES:
        interaction_type = "comment"

    category, priority = local_classification(message)
    item = SocialInteraction(
        platform=platform,
        interaction_type=interaction_type,
        sender_name=request.form.get("sender_name", "").strip()[:120] or "알 수 없음",
        post_title=request.form.get("post_title", "").strip()[:300],
        message_text=message[:5000],
        category=category,
        priority=priority,
        status="new",
    )
    db.session.add(item)
    db.session.commit()
    flash("메시지를 등록하고 기본 분류를 완료했어요.")
    return redirect(url_for("social_v96.dashboard"))


@social_bp.post("/<int:interaction_id>/generate")
def generate_drafts(interaction_id):
    item = db.session.get(SocialInteraction, interaction_id)
    if not item:
        flash("메시지를 찾을 수 없습니다.")
        return redirect(url_for("social_v96.dashboard"))

    try:
        category, priority, drafts = generate_reply_package(item)
        item.category = category
        item.priority = priority
        item.draft_1, item.draft_2, item.draft_3 = drafts
        item.status = "drafted"
        db.session.commit()
        flash("AI 답변 초안 3개를 만들었어요.")
    except Exception as exc:
        db.session.rollback()
        flash(f"AI 초안 생성 실패: {exc}")

    return redirect(url_for("social_v96.dashboard", status="drafted"))


@social_bp.post("/<int:interaction_id>/approve")
def approve(interaction_id):
    item = db.session.get(SocialInteraction, interaction_id)
    if not item:
        flash("메시지를 찾을 수 없습니다.")
        return redirect(url_for("social_v96.dashboard"))

    custom = request.form.get("custom_reply", "").strip()
    selected_raw = request.form.get("selected_draft", "").strip()

    selected = None
    if selected_raw in {"1", "2", "3"}:
        selected = int(selected_raw)

    draft_map = {1: item.draft_1, 2: item.draft_2, 3: item.draft_3}
    reply = custom or draft_map.get(selected, "")
    if not reply:
        flash("답변을 선택하거나 직접 작성해 주세요.")
        return redirect(url_for("social_v96.dashboard", status="drafted"))

    item.selected_draft = selected
    item.approved_reply = reply[:3000]
    item.status = "approved"
    db.session.commit()
    flash("답변을 승인했어요. 복사해 직접 발송한 뒤 완료 표시를 눌러 주세요.")
    return redirect(url_for("social_v96.dashboard", status="approved"))


@social_bp.post("/<int:interaction_id>/complete")
def complete(interaction_id):
    item = db.session.get(SocialInteraction, interaction_id)
    if not item:
        flash("메시지를 찾을 수 없습니다.")
        return redirect(url_for("social_v96.dashboard"))

    custom = request.form.get("custom_reply", "").strip()
    if custom:
        item.approved_reply = custom[:3000]
    if not item.approved_reply:
        flash("먼저 답변을 승인해 주세요.")
        return redirect(url_for("social_v96.dashboard"))

    item.status = "completed"
    db.session.commit()
    flash("직접 발송 완료로 표시했어요.")
    return redirect(url_for("social_v96.dashboard", status="completed"))


@social_bp.post("/<int:interaction_id>/delete")
def delete(interaction_id):
    item = db.session.get(SocialInteraction, interaction_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        flash("소통 항목을 삭제했어요.")
    return redirect(url_for("social_v96.dashboard"))
