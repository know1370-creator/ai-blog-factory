"""V18.5 easy command center for MI Creator OS."""
from datetime import date, timedelta

from flask import Blueprint, render_template_string, redirect, request, url_for
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

@home_bp.post("/quick-command")
def quick_command():
    prompt = request.form.get("prompt", "").strip()

    if not prompt:
        return redirect(url_for("home_v16.dashboard"))

    return redirect(
        url_for(
            "assistant_v92.dashboard",
            prompt=prompt,
        )
    )


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

    progress_weights = {
        "기획": 25,
        "제작 중": 50,
        "검토": 75,
        "예약": 90,
    }

    if active_items:
        progress = round(
            sum(
                progress_weights.get(item.status, 0)
                for item in active_items
            ) / len(active_items)
        )
    else:
        progress = 0

    return page("""

<style>
.hero-top{
display:flex;
flex-wrap:wrap;
align-items:flex-start;
justify-content:space-between;
gap:20px;
margin-bottom:22px;
}

.hero-ai-btn{
display:inline-flex;
align-items:center;
justify-content:center;
min-width:160px;
padding:13px 18px;
border-radius:14px;
background:#352c54; color:#fff;
text-decoration:none;
font-weight:800;
border:none;
box-shadow:0 14px 32px rgba(75,63,114,.28);
transition:.2s ease; }

.hero-ai-btn:hover{
transform:translateY(-2px);
box-shadow:0 18px 36px rgba(75,63,114,.36); }

.stat{
position:relative;
overflow:hidden;
background:rgba(255,255,255,.92);
border:1px solid rgba(255,255,255,.7);
box-shadow:0 12px 30px rgba(43,32,74,.08);
}

.stat strong{
color:#4b3f72;
}

.stat-icon{
display:inline-flex;
align-items:center;
justify-content:center;
width:38px;
height:38px;
margin-bottom:12px;
border-radius:12px;
background:#f4f1fb;
font-size:20px; }

.workflow{
  display:grid;
  grid-template-columns:repeat(4,1fr);
  gap:12px;
  margin-top:20px;
}

.workflow a{
  display:flex;
  flex-direction:column;
  justify-content:center;
  align-items:center;
  text-decoration:none;
  background:#ffffff;
  border:1px solid #e8e3ee;
  border-radius:16px;
  padding:16px;
  color:#222;
  font-weight:700;
  transition:.25s;
}

.workflow a:hover{
  transform:translateY(-3px);
  border-color:#b8925a;
  box-shadow:0 12px 30px rgba(75,63,114,.18);
}

.workflow a span{
  color:#b8925a;
  font-size:13px;
  font-weight:800;
  margin-bottom:6px;
}

body{
  background:
    #faf8f4;
}

.home-page{
  min-height:100vh;
  padding:24px;
  border-radius:28px;
  background:
    #faf8f4;
}

.command-hero{
  border:1px solid #e8e3ee;
  border-radius:24px;
  padding:25px;
  background:#fdf9f2;
  box-shadow:0 16px 40px rgba(43,32,74,.12);
  margin-bottom:16px;
}

.command-grid{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(235px,1fr));
  gap:14px;
}

.command-card{
  display:block;
  text-decoration:none;
  color:inherit;
  border:1px solid #e8e3ee;
  border-radius:19px;
  padding:18px;
  background:#fff;
  transition:.16s;
}

.command-card:hover{
  transform:translateY(-2px);
  border-color:#e8e3ee;
  box-shadow:0 12px 30px rgba(75,63,114,.12);
}

.command-icon{
  font-size:1.7rem;
}

.command-title{
  font-weight:850;
  font-size:1.08rem;
  margin:7px 0 4px;
}

.task-row{
  padding:12px 0;
  border-bottom:1px solid #edf0f4;
}

.task-row:last-child{
  border-bottom:0;
}

.section-label{
  font-size:.8rem;
  font-weight:800;
  letter-spacing:.04em;
  color:#b8925a;
  text-transform:uppercase;
}

.ai-recommend-card{
  position:relative;
  overflow:hidden;
  margin-bottom:16px;
  padding:22px;
  border:1px solid #e8e3ee;
  border-radius:22px;
  background:#ffffff;
  box-shadow:0 14px 35px rgba(75,63,114,.10);
}

.ai-recommend-card::after{
  content:"✨";
  position:absolute;
  right:22px;
  top:18px;
  font-size:34px;
  opacity:.25;
}

.ai-recommend-title{
  margin:8px 0 5px;
  font-size:1.18rem;
  font-weight:850;
  color:#221f2b;
}

.ai-recommend-text{
  margin:0 0 15px;
  color:#7a7488;
  line-height:1.6;
}

.ai-recommend-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:11px 16px;
  border-radius:13px;
  background:#352c54;
  color:#fff;
  text-decoration:none;
  font-weight:800;
  box-shadow:0 10px 24px rgba(75,63,114,.20);
}

.ai-recommend-btn:hover{
  transform:translateY(-2px);
}

.progress-dashboard{
  margin-bottom:16px;
  padding:22px;
  border:1px solid #e8e3ee;
  border-radius:22px;
  background:#ffffff;
  box-shadow:0 14px 34px rgba(75,63,114,.09);
}

.progress-header{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:16px;
  margin-bottom:14px;
}

.progress-title{
  margin:5px 0 0;
  font-size:1.2rem;
  font-weight:850;
}

.progress-number{
  font-size:1.6rem;
  font-weight:900;
  color:#b8925a;
}

.progress-track{
  width:100%;
  height:16px;
  overflow:hidden;
  border-radius:999px;
  background:#f4f1fb;
}

.progress-fill{
  height:100%;
  border-radius:999px;
  background:#4b3f72;
  transition:width .5s ease;
}

.progress-description{
  margin:12px 0 0;
  color:#7a7488;
  font-size:.9rem;
  line-height:1.5;
}

.ai-command-box{
  position:relative;
  isolation:isolate;
  z-index:2;
  overflow:visible;
  margin-bottom:18px;
  padding:26px;
  border:1px solid #e8e3ee;
  border-radius:24px;
  background:#ffffff;
  box-shadow:0 16px 38px rgba(75,63,114,.11);
}

.ai-command-box::after{
  content:"🤖";
  position:absolute;
  right:24px;
  top:18px;
  z-index:-1;
  font-size:42px;
  opacity:.12;
  pointer-events:none;
}

.ai-command-title{
  margin:7px 0 5px;
  font-size:1.25rem;
  font-weight:900;
  color:#221f2b;
}

.ai-command-description{
  margin:0 0 16px;
  color:#7a7488;
  line-height:1.55;
}

.ai-command-form{
  position:relative;
  z-index:3;
  display:grid;
  grid-template-columns:minmax(0,1fr) 180px;
  gap:12px;
  align-items:stretch;
}

.ai-command-input{
  display:block;
  width:100%;
  min-width:0;
  min-height:88px;
  padding:17px 18px;
  border:2px solid #e8e3ee;
  border-radius:16px;
  background:#ffffff;
  color:#221f2b;
  font:inherit;
  font-size:1rem;
  line-height:1.55;
  resize:vertical;
  outline:none;
  cursor:text;
  pointer-events:auto!important;
}

.ai-command-input:focus{
  border-color:#b8925a;
  box-shadow:0 0 0 4px rgba(75,63,114,.10);
}

.ai-command-actions{
  display:grid;
  grid-template-rows:1fr 1fr;
  gap:10px;
}

.ai-command-submit{
  width:100%;
  min-height:44px;
  padding:13px 16px;
  border:0;
  border-radius:14px;
  background:#352c54;
  color:#ffffff;
  font-weight:850;
  cursor:pointer;
  box-shadow:0 11px 26px rgba(75,63,114,.20);
  transition:.2s;
  pointer-events:auto!important;
}

.ai-command-submit.secondary{
  background:#ffffff;
  color:#4b3f72;
  border:1px solid #e8e3ee;
  box-shadow:none;
}

.ai-command-submit:hover{
  transform:translateY(-2px);
}

.quick-prompts{
  position:relative;
  z-index:3;
  display:flex;
  flex-wrap:wrap;
  gap:9px;
  margin-top:14px;
}

.quick-prompt-btn{
  padding:10px 14px;
  border:1px solid #e8e3ee;
  border-radius:999px;
  background:#ffffff;
  color:#b8925a;
  font-size:.86rem;
  font-weight:800;
  cursor:pointer;
  transition:.2s;
  pointer-events:auto!important;
}

.quick-prompt-btn:hover{
  transform:translateY(-2px);
  border-color:#e8e3ee;
  background:#f4f1fb;
  box-shadow:0 8px 18px rgba(75,63,114,.12);
}

@media(max-width:700px){
  .home-page{
    padding:14px;
  }

  .hero-top{
    flex-direction:column;
  }

  .hero-ai-btn{
    width:100%;
  }

  .workflow{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }

  .ai-command-form{
    grid-template-columns:1fr;
  }

  .ai-command-actions{
    grid-template-columns:1fr 1fr;
    grid-template-rows:auto;
  }
}

@media(max-width:480px){
  .workflow{
    grid-template-columns:1fr;
  }
  .ai-command-actions{
    grid-template-columns:1fr;
  }
}
</style>

<div class="home-page">

<section class="command-hero">
<div class="section-label">MI CREATOR OS V18.5</div>

<div class="hero-top">
<div>
<h1>안녕하세요, 미경님 👋</h1>
<p class="lead">오늘의 콘텐츠, 고객관리, 수익 흐름을 한눈에 확인하세요.</p>
</div>

<a class="hero-ai-btn" href="{{url_for('assistant_v92.dashboard')}}">
✨ AI 비서 시작
</a>
</div>

<div class="stat-grid">
<div class="stat">
<span class="stat-icon">📝</span>
<strong>{{stats.active_content}}</strong>
<span class="small">진행 중 콘텐츠</span>
</div>

<div class="stat">
<span class="stat-icon">🏭</span>
<strong>{{stats.factory}}</strong>
<span class="small">제작 중 패키지</span>
</div>

<div class="stat">
<span class="stat-icon">💡</span>
<strong>{{stats.ideas}}</strong>
<span class="small">대기 아이디어</span>
</div>

<div class="stat">
<span class="stat-icon">💬</span>
<strong>{{stats.messages}}</strong>
<span class="small">응대할 메시지</span>
</div>
</div>

<div class="workflow">
<a href="{{url_for('marketing_v14.ideas')}}">
<span>01</span>
아이디어 찾기
</a>

<a href="{{url_for('factory_v15.dashboard')}}">
<span>02</span>
콘텐츠 만들기
</a>

<a href="{{url_for('pipeline_v13.board')}}">
<span>03</span>
진행 관리
</a>

<a href="{{url_for('marketing_v14.dashboard')}}">
<span>04</span>
성과 확인
</a>
</div>
</section>

<section class="ai-recommend-card">
<div class="section-label">오늘의 AI 추천</div>

{% if daily_tasks %}
<div class="ai-recommend-title">
{{daily_tasks[0].item.title}}
</div>

<p class="ai-recommend-text">
오늘은 이 작업부터 시작해 보세요.
{{daily_tasks[0].action}}
{% if daily_tasks[0].due_text %}
· {{daily_tasks[0].due_text}}
{% endif %}
</p>

<a class="ai-recommend-btn" href="{{url_for('pipeline_v13.board')}}">
지금 작업 시작하기
</a>

{% else %}
<div class="ai-recommend-title">
새 콘텐츠 아이디어를 골라보세요
</div>

<p class="ai-recommend-text">
현재 진행 중인 작업이 없습니다. 새로운 아이디어를 선택해 첫 작업을 만들어보세요.
</p>

<a class="ai-recommend-btn" href="{{url_for('marketing_v14.ideas')}}">
아이디어 보러 가기
</a>
{% endif %}
</section>

<section class="progress-dashboard">
<div class="progress-header">
<div>
<div class="section-label">오늘의 진행률</div>
<div class="progress-title">콘텐츠 작업 흐름</div>
</div>

<div class="progress-number">{{progress}}%</div>
</div>

<div class="progress-track">
<div class="progress-fill" style="width:{{progress}}%;"></div>
</div>

<p class="progress-description">
기획, 제작, 검토, 예약 상태를 기준으로 진행률을 자동 계산합니다.
현재 진행 중인 콘텐츠는 {{stats.active_content}}개입니다.
</p>
</section>

<section class="ai-command-box">
<div class="section-label">MI AI QUICK COMMAND</div>

<div class="ai-command-title">오늘 무엇을 만들어볼까요?</div>

<p class="ai-command-description">
만들고 싶은 내용을 편하게 적어주세요. 입력창을 크게 바꾸고, 버튼은 자바스크립트 없이도 바로 작동하도록 고쳤습니다.
</p>

<form class="ai-command-form" method="post" action="{{url_for('home_v16.quick_command')}}">
  <textarea
    class="ai-command-input"
    name="prompt"
    placeholder="예: 말썽쟁이 딸 경제 인스타툰 8컷 만들어줘"
    required
    autofocus
  ></textarea>

  <div class="ai-command-actions">
    <button class="ai-command-submit" type="submit">✨ AI에게 요청</button>
    <button class="ai-command-submit secondary" type="submit">🚀 원클릭 생성</button>
  </div>
</form>

<form class="quick-prompts" method="post" action="{{url_for('home_v16.quick_command')}}">
  <button class="quick-prompt-btn" type="submit" name="prompt" value="오늘 올릴 릴스 대본과 촬영 순서, 자막, CTA를 만들어줘">🎬 릴스</button>
  <button class="quick-prompt-btn" type="submit" name="prompt" value="말썽쟁이 딸과 경제 주제로 인스타툰 8컷을 만들어줘">📝 인스타툰</button>
  <button class="quick-prompt-btn" type="submit" name="prompt" value="오늘 사용할 블로그 글 초안을 제목과 목차까지 만들어줘">📖 블로그</button>
  <button class="quick-prompt-btn" type="submit" name="prompt" value="보험 상담 고객에게 보낼 자연스러운 안내 문구를 만들어줘">📈 보험</button>
  <button class="quick-prompt-btn" type="submit" name="prompt" value="애터미 생필품을 자연스럽게 소개하는 릴스 대본을 만들어줘">🛒 애터미</button>
  <button class="quick-prompt-btn" type="submit" name="prompt" value="쿠팡 파트너스 상품 리뷰 콘텐츠와 캡션을 만들어줘">💰 쿠팡</button>
</form>
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
<a class="command-card" href="{{url_for('generator_v12.dashboard')}}">
<div class="command-title">AI 프로젝트 생성기</div><div class="small">한 주제로 멀티채널 프로젝트 생성</div></a>
<a class="command-card" href="{{url_for('assistant_v92.dashboard')}}">
<div class="command-title">AI 콘텐츠 비서</div><div class="small">블로그와 SNS 초안 제작</div></a>
<a class="command-card" href="{{url_for('planner_v93.dashboard')}}"><div class="command-title">주간 플래너</div><div class="small">7일 콘텐츠 계획</div></a>
<a class="command-card" href="{{url_for('calendar_v94.dashboard')}}"><div class="command-title">월간 캘린더</div><div class="small">게시 일정과 상태 관리</div></a>
<a class="command-card" href="{{url_for('analytics_v95.dashboard')}}"><div class="command-title">성과 입력</div><div class="small">플랫폼 실제 수치 기록</div></a>
<a class="command-card" href="{{url_for('social_v96.dashboard')}}"><div class="command-title">댓글·DM 응대</div><div class="small">답변 초안과 승인 관리</div>
</a>
<a class="command-card" href="{{url_for('business_v91.dashboard')}}"><div class="command-title">수익·비용</div><div class="small">사업 손익 기록</div></a>
<a class="command-card" href="{{url_for('diagnostics_v95.dashboard')}}">
<div class="command-title">시스템 점검</div>
<div class="small">DB와 환경 상태 확인</div>
</a>

</div>
</section>



</div>
""", stats=stats, 
daily_tasks=daily_tasks, 
due_rows=due_rows, 
today=today,
progress=progress,
page_title="홈 | MI Creator OS V18.5")