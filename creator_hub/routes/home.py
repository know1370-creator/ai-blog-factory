"""V16.0 simplified home hub and navigation guide."""
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template_string
from markupsafe import Markup

from ..legacy_app import BASE_HTML
from .library import ContentLibraryItem
from .pipeline import PipelineMeta
from .factory import ContentFactoryProject
from .marketing import MarketingIdea


home_bp = Blueprint("home_v16", __name__, url_prefix="/home")


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


@home_bp.get("/")
def dashboard():
    today = date.today()
    soon = today + timedelta(days=7)

    content_count = ContentLibraryItem.query.count()
    active_content = ContentLibraryItem.query.filter(
        ContentLibraryItem.status.in_(["기획", "제작 중", "검토", "예약"])
    ).count()
    factory_count = ContentFactoryProject.query.count()
    active_factory = ContentFactoryProject.query.filter(
        ContentFactoryProject.publishing_done.is_(False)
    ).count()
    idea_count = MarketingIdea.query.filter(
        MarketingIdea.status.in_(["아이디어", "선정", "제작 전"])
    ).count()

    due_rows = (
        PipelineMeta.query
        .filter(PipelineMeta.due_date.isnot(None))
        .filter(PipelineMeta.due_date <= soon)
        .order_by(PipelineMeta.due_date.asc())
        .limit(8)
        .all()
    )

    return page("""
<style>
.hub-hero{
  border-radius:22px;padding:24px;
  background:linear-gradient(135deg,#eef2ff,#faf5ff);
  border:1px solid #ddd6fe;margin-bottom:16px
}
.hub-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.hub-card{display:block;border:1px solid #e5e7eb;border-radius:18px;padding:18px;background:#fff;text-decoration:none;color:inherit;transition:.16s}
.hub-card:hover{transform:translateY(-2px);box-shadow:0 10px 26px rgba(15,23,42,.08)}
.hub-icon{font-size:1.8rem;margin-bottom:8px}
.hub-title{font-size:1.15rem;font-weight:800;margin-bottom:5px}
.hub-path{font-size:.78rem;color:#6b7280;margin-top:10px}
.guide-row{display:grid;grid-template-columns:80px 1fr;gap:12px;align-items:start;padding:11px 0;border-bottom:1px solid #eef0f4}
.guide-num{font-weight:800;color:#4f46e5}
</style>

<section class="hub-hero">
  <h1>MI Creator Hub 홈</h1>
  <p class="lead">종류가 많아도 길을 잃지 않도록, 자주 쓰는 기능을 4개 구역으로 정리했어요.</p>
  <div class="stat-grid">
    <div class="stat"><strong>{{active_content}}</strong><span class="small">진행 중 콘텐츠</span></div>
    <div class="stat"><strong>{{active_factory}}</strong><span class="small">제작 중 패키지</span></div>
    <div class="stat"><strong>{{idea_count}}</strong><span class="small">대기 아이디어</span></div>
    <div class="stat"><strong>{{content_count}}</strong><span class="small">전체 라이브러리</span></div>
  </div>
</section>

<section class="card">
  <h2>가장 많이 쓰는 4가지</h2>
  <div class="hub-grid">
    <a class="hub-card" href="{{url_for('factory_v15.dashboard')}}">
      <div class="hub-icon">🏭</div>
      <div class="hub-title">콘텐츠 만들기</div>
      <p class="small">블로그, 릴스, 인스타툰, Threads를 한 패키지로 만들고 편집해요.</p>
      <div class="hub-path">콘텐츠 팩토리</div>
    </a>

    <a class="hub-card" href="{{url_for('pipeline_v13.board')}}">
      <div class="hub-icon">🧩</div>
      <div class="hub-title">진행 상황 보기</div>
      <p class="small">기획부터 게시 완료까지 드래그하며 현재 상태를 관리해요.</p>
      <div class="hub-path">콘텐츠 파이프라인</div>
    </a>

    <a class="hub-card" href="{{url_for('marketing_v14.dashboard')}}">
      <div class="hub-icon">📊</div>
      <div class="hub-title">성과 확인하기</div>
      <p class="small">직접 입력한 조회, 저장, 클릭, 수익 데이터를 비교해요.</p>
      <div class="hub-path">마케팅 센터</div>
    </a>

    <a class="hub-card" href="{{url_for('library_v11.index')}}">
      <div class="hub-icon">🗂️</div>
      <div class="hub-title">완성본 찾기</div>
      <p class="small">만들어 둔 콘텐츠와 시리즈 결과물을 검색하고 다시 사용해요.</p>
      <div class="hub-path">콘텐츠 라이브러리</div>
    </a>
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>처음 사용할 때 순서</h2>
  <div class="guide-row"><div class="guide-num">1단계</div><div><strong>아이디어 저장</strong><div class="small">생각난 소재를 아이디어 뱅크에 적어요.</div></div></div>
  <div class="guide-row"><div class="guide-num">2단계</div><div><strong>콘텐츠 제작</strong><div class="small">콘텐츠 팩토리에서 여러 형식의 초안을 만들어요.</div></div></div>
  <div class="guide-row"><div class="guide-num">3단계</div><div><strong>촬영·편집 관리</strong><div class="small">촬영 체크리스트와 파이프라인에서 진행 상태를 확인해요.</div></div></div>
  <div class="guide-row"><div class="guide-num">4단계</div><div><strong>게시 후 성과 입력</strong><div class="small">마케팅 센터에서 실제 수치만 비교해요.</div></div></div>
  <div class="actions">
    <a class="btn" href="{{url_for('marketing_v14.ideas')}}">아이디어 뱅크</a>
    <a class="btn gray" href="{{url_for('marketing_v14.shooting')}}">촬영 체크리스트</a>
  </div>
</section>

<section class="card">
  <h2>7일 안에 마감</h2>
  {% for row in due_rows %}
  <div class="calendar-item">
    <strong>{{row.item.title if row.item else '연결된 콘텐츠 없음'}}</strong>
    <div class="small">
      {{row.due_date.strftime('%m/%d')}}
      {% if row.due_date < today %} · 마감 지남{% elif row.due_date == today %} · 오늘 마감{% endif %}
    </div>
  </div>
  {% else %}
  <p class="small">7일 안에 등록된 마감이 없습니다.</p>
  {% endfor %}
  <a class="btn gray" href="{{url_for('pipeline_v13.brief')}}">오늘의 운영 브리핑</a>
</section>
</div>

<section class="card">
  <h2>전체 기능</h2>
  <div class="hub-grid">
    <a class="hub-card" href="{{url_for('planner_v93.index')}}"><div class="hub-title">주간 플래너</div><p class="small">7일 콘텐츠 계획</p></a>
    <a class="hub-card" href="{{url_for('calendar_v94.index')}}"><div class="hub-title">월간 캘린더</div><p class="small">월별 일정 관리</p></a>
    <a class="hub-card" href="{{url_for('assistant_v92.index')}}"><div class="hub-title">AI 콘텐츠 도우미</div><p class="small">개별 콘텐츠 초안</p></a>
    <a class="hub-card" href="{{url_for('analytics_v95.index')}}"><div class="hub-title">성과 입력</div><p class="small">실제 플랫폼 수치 기록</p></a>
    <a class="hub-card" href="{{url_for('social_v96.index')}}"><div class="hub-title">소셜 응대</div><p class="small">댓글·DM 초안과 승인</p></a>
    <a class="hub-card" href="{{url_for('business_v91.index')}}"><div class="hub-title">수익·비용</div><p class="small">사업 손익 기록</p></a>
    <a class="hub-card" href="{{url_for('manager_v10.index')}}"><div class="hub-title">훅·릴스 실험</div><p class="small">훅팩과 A/B 실험</p></a>
    <a class="hub-card" href="{{url_for('diagnostics_v9.index')}}"><div class="hub-title">시스템 점검</div><p class="small">DB와 환경 진단</p></a>
  </div>
</section>
""",
        active_content=active_content,
        active_factory=active_factory,
        idea_count=idea_count,
        content_count=content_count,
        factory_count=factory_count,
        due_rows=due_rows,
        today=today,
        page_title="홈 | MI Creator Hub",
    )
