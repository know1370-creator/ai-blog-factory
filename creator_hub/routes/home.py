"""V17.0 easy command center for MI Creator Hub."""
from datetime import date, timedelta

from flask import Blueprint, render_template_string
from markupsafe import Markup

from ..legacy_app import BASE_HTML
from .library import ContentLibraryItem
from .pipeline import PipelineMeta, build_daily_tasks
from .factory import ContentFactoryProject
from .marketing import MarketingIdea
from .social import SocialInteraction


home_bp = Blueprint("home_v16", __name__, url_prefix="/home")


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


@home_bp.get("/")
def dashboard():
    today = date.today()
    soon = today + timedelta(days=7)

    active_items = ContentLibraryItem.query.filter(
        ContentLibraryItem.status.in_(["기획", "제작 중", "검토", "예약"])
    ).all()
    daily_tasks = build_daily_tasks(active_items)[:5]

    due_rows = (
        PipelineMeta.query
        .filter(PipelineMeta.due_date.isnot(None))
        .filter(PipelineMeta.due_date <= soon)
        .order_by(PipelineMeta.due_date.asc())
        .limit(6)
        .all()
    )

    stats = {
        "active_content": len(active_items),
        "factory": ContentFactoryProject.query.filter(
            ContentFactoryProject.publishing_done.is_(False)
        ).count(),
        "ideas": MarketingIdea.query.filter(
            MarketingIdea.status.in_(["아이디어", "선정", "제작 전"])
        ).count(),
        "messages": SocialInteraction.query.filter(
            SocialInteraction.status.in_(["new", "drafted", "approved"])
        ).count(),
    }

    return page("""
<style>
.command-hero{border:1px solid #ddd6fe;border-radius:24px;padding:25px;background:linear-gradient(135deg,#eef2ff,#faf5ff);margin-bottom:16px}
.command-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:14px}
.command-card{display:block;text-decoration:none;color:inherit;border:1px solid #e5e7eb;border-radius:19px;padding:18px;background:#fff;transition:.16s}
.command-card:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(15,23,42,.09)}
.command-icon{font-size:1.7rem}.command-title{font-weight:850;font-size:1.08rem;margin:7px 0 4px}
.workflow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:15px}
.workflow a{text-align:center;text-decoration:none;color:inherit;border-radius:13px;padding:11px 6px;background:#fff;border:1px solid #e5e7eb;font-size:.86rem;font-weight:700}
.task-row{padding:12px 0;border-bottom:1px solid #edf0f4}
.task-row:last-child{border-bottom:0}
.section-label{font-size:.8rem;font-weight:800;letter-spacing:.04em;color:#6366f1;text-transform:uppercase}
@media(max-width:720px){.workflow{grid-template-columns:1fr 1fr}}
</style>

<section class="command-hero">
  <div class="section-label">MI CREATOR HUB V17</div>
  <h1>오늘은 무엇부터 할까요?</h1>
  <p class="lead">기능 이름을 외우지 않아도 됩니다. 하고 싶은 일을 누르면 필요한 화면으로 바로 이동해요.</p>
  <div class="stat-grid">
    <div class="stat"><strong>{{stats.active_content}}</strong><span class="small">진행 중 콘텐츠</span></div>
    <div class="stat"><strong>{{stats.factory}}</strong><span class="small">제작 중 패키지</span></div>
    <div class="stat"><strong>{{stats.ideas}}</strong><span class="small">대기 아이디어</span></div>
    <div class="stat"><strong>{{stats.messages}}</strong><span class="small">응대할 메시지</span></div>
  </div>
  <div class="workflow">
    <a href="{{url_for('marketing_v14.ideas')}}">① 아이디어</a>
    <a href="{{url_for('factory_v15.dashboard')}}">② 만들기</a>
    <a href="{{url_for('pipeline_v13.board')}}">③ 진행 관리</a>
    <a href="{{url_for('marketing_v14.dashboard')}}">④ 성과 확인</a>
  </div>
</section>

<section class="card">
  <div class="section-label">빠른 실행</div>
  <h2>무엇을 하려고 들어왔나요?</h2>
  <div class="command-grid">
    <a class="command-card" href="{{url_for('factory_v15.dashboard')}}">
      <div class="command-icon">🏭</div><div class="command-title">콘텐츠를 만들어요</div>
      <div class="small">릴스, 인스타툰, 블로그 등 여러 형식의 초안을 한곳에서 제작</div>
    </a>
    <a class="command-card" href="{{url_for('pipeline_v13.board')}}">
      <div class="command-icon">📌</div><div class="command-title">진행 상황을 봐요</div>
      <div class="small">기획, 제작, 검토, 예약, 게시 상태를 한눈에 관리</div>
    </a>
    <a class="command-card" href="{{url_for('marketing_v14.dashboard')}}">
      <div class="command-icon">📈</div><div class="command-title">성과를 확인해요</div>
      <div class="small">실제 입력한 조회, 저장, 클릭, 수익 데이터 비교</div>
    </a>
    <a class="command-card" href="{{url_for('library_v11.dashboard')}}">
      <div class="command-icon">🗂️</div><div class="command-title">만든 콘텐츠를 찾아요</div>
      <div class="small">완성본, 시리즈, 예전 초안을 검색하고 다시 사용</div>
    </a>
  </div>
</section>

<div class="grid">
<section class="card">
  <div class="section-label">오늘 뭐 하지?</div>
  <h2>우선 처리할 작업</h2>
  {% for task in daily_tasks %}
    <div class="task-row">
      <strong>{{loop.index}}. {{task.item.title}}</strong>
      <div class="small">{{task.action}}{% if task.due_text %} · {{task.due_text}}{% endif %}</div>
    </div>
  {% else %}
    <p class="small">현재 진행 중인 작업이 없습니다. 아이디어 하나를 골라 새 콘텐츠를 시작해 보세요.</p>
  {% endfor %}
  <div class="actions">
    <a class="btn" href="{{url_for('pipeline_v13.brief')}}">오늘의 운영 브리핑</a>
    <a class="btn gray" href="{{url_for('marketing_v14.ideas')}}">아이디어 보기</a>
  </div>
</section>

<section class="card">
  <div class="section-label">마감 알림</div>
  <h2>7일 안에 마감</h2>
  {% for row in due_rows %}
    <div class="task-row">
      <strong>{{row.item.title if row.item else '연결된 콘텐츠 없음'}}</strong>
      <div class="small">{{row.due_date.strftime('%m/%d')}}
        {% if row.due_date < today %} · 마감 지남{% elif row.due_date == today %} · 오늘 마감{% endif %}
      </div>
    </div>
  {% else %}
    <p class="small">7일 안에 등록된 마감이 없습니다.</p>
  {% endfor %}
  <a class="btn gray" href="{{url_for('calendar_v94.dashboard')}}">캘린더 열기</a>
</section>
</div>

<section class="card">
  <div class="section-label">전체 도구</div>
  <h2>업무별로 모아보기</h2>
  <div class="command-grid">
    <a class="command-card" href="{{url_for('generator_v12.dashboard')}}"><div class="command-title">AI 프로젝트 생성기</div><div class="small">한 주제로 멀티채널 프로젝트 생성</div></a>
    <a class="command-card" href="{{url_for('assistant_v92.dashboard')}}"><div class="command-title">AI 콘텐츠 비서</div><div class="small">블로그와 SNS 초안 제작</div></a>
    <a class="command-card" href="{{url_for('planner_v93.dashboard')}}"><div class="command-title">주간 플래너</div><div class="small">7일 콘텐츠 계획</div></a>
    <a class="command-card" href="{{url_for('calendar_v94.dashboard')}}"><div class="command-title">월간 캘린더</div><div class="small">게시 일정과 상태 관리</div></a>
    <a class="command-card" href="{{url_for('analytics_v95.dashboard')}}"><div class="command-title">성과 입력</div><div class="small">플랫폼 실제 수치 기록</div></a>
    <a class="command-card" href="{{url_for('social_v96.dashboard')}}"><div class="command-title">댓글·DM 응대</div><div class="small">답변 초안과 승인 관리</div></a>
    <a class="command-card" href="{{url_for('business_v91.dashboard')}}"><div class="command-title">수익·비용</div><div class="small">사업 손익 기록</div></a>
    <a class="command-card" href="{{url_for('diagnostics_v95.dashboard')}}"><div class="command-title">시스템 점검</div><div class="small">DB와 환경 상태 확인</div></a>
  </div>
</section>
""", stats=stats, daily_tasks=daily_tasks, due_rows=due_rows, today=today,
        page_title="홈 | MI Creator Hub V17")
