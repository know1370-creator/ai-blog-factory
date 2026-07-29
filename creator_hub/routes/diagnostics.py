"""V9.5 safe diagnostics without exposing secret values."""
import os
from datetime import datetime

from flask import Blueprint, render_template_string
from markupsafe import Markup
from sqlalchemy import text

from ..legacy_app import BASE_HTML, Article, db
from .business import FinanceEntry
from .planner import WeeklyPlanItem
from .analytics import ContentMetric
from .social import SocialInteraction
from .manager import HookPack, ReelPlan, ABExperiment
from .library import ContentLibraryItem
from .pipeline import PipelineMeta
from .marketing import MarketingIdea, ShootingChecklist


diagnostics_bp = Blueprint("diagnostics_v95", __name__, url_prefix="/diagnostics")


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def configured(name):
    return bool(os.getenv(name, "").strip())


@diagnostics_bp.get("/")
def dashboard():
    checks = []

    try:
        db.session.execute(text("SELECT 1"))
        checks.append(("데이터베이스 연결", True, "정상적으로 응답했습니다."))
    except Exception as exc:
        checks.append(("데이터베이스 연결", False, str(exc)[:180]))

    model_checks = [
        ("콘텐츠 테이블", Article),
        ("수익 테이블", FinanceEntry),
        ("주간 플래너 테이블", WeeklyPlanItem),
        ("성과 분석 테이블", ContentMetric),
        ("소통 비서 테이블", SocialInteraction),
        ("훅 생성 테이블", HookPack),
        ("릴스 기획 테이블", ReelPlan),
        ("A/B 실험 테이블", ABExperiment),
        ("콘텐츠 라이브러리 테이블", ContentLibraryItem),
        ("파이프라인 설정 테이블", PipelineMeta),
        ("마케팅 아이디어 테이블", MarketingIdea),
        ("촬영 체크리스트 테이블", ShootingChecklist),
    ]
    for label, model in model_checks:
        try:
            model.query.limit(1).all()
            checks.append((label, True, "조회 가능"))
        except Exception as exc:
            db.session.rollback()
            checks.append((label, False, str(exc)[:180]))

    checks.extend([
        ("OpenAI 키", configured("OPENAI_API_KEY"), "설정됨" if configured("OPENAI_API_KEY") else "미설정"),
        ("Blogger Client ID", configured("GOOGLE_CLIENT_ID"), "설정됨" if configured("GOOGLE_CLIENT_ID") else "미설정"),
        ("Blogger Client Secret", configured("GOOGLE_CLIENT_SECRET"), "설정됨" if configured("GOOGLE_CLIENT_SECRET") else "미설정"),
        ("앱 Secret Key", configured("SECRET_KEY"), "설정됨" if configured("SECRET_KEY") else "서버 재시작 시 세션이 바뀔 수 있음"),
        ("Database URL", configured("DATABASE_URL"), "외부 DB 설정됨" if configured("DATABASE_URL") else "기본 SQLite 사용"),
    ])

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = len(checks) - passed

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>시스템 점검 <span class="status">V9.5</span></h1>
      <p class="lead">비밀값은 보여주지 않고 연결과 설정 여부만 확인합니다.</p>
    </div>
    <div class="actions" style="margin-top:0">
      <a class="btn gray" href="{{url_for('analytics_v95.dashboard')}}">성과 분석</a>
      <a class="btn gray" href="{{url_for('home')}}">홈으로</a>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{passed}}</strong><span class="small">정상 항목</span></div>
    <div class="stat"><strong>{{failed}}</strong><span class="small">확인 필요</span></div>
    <div class="stat"><strong>{{checked_at}}</strong><span class="small">점검 시각</span></div>
  </div>
</section>

<section class="card">
  <h2>점검 결과</h2>
  <table>
    <thead><tr><th>항목</th><th>상태</th><th>설명</th></tr></thead>
    <tbody>
    {% for label,ok,message in checks %}
    <tr>
      <td><strong>{{label}}</strong></td>
      <td>{% if ok %}<span class="status">정상</span>{% else %}<span class="tag">확인 필요</span>{% endif %}</td>
      <td>{{message}}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  <p class="notice">이 화면은 OpenAI 생성 테스트를 실행하지 않으므로 API 비용이 발생하지 않습니다.</p>
<p class="small">V14 확인 경로: /marketing/ · /generator/ · 생성 결과는 자동 게시되지 않고 콘텐츠 라이브러리에 저장됩니다.</p>
</section>
""",
        checks=checks,
        passed=passed,
        failed=failed,
        checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        page_title="시스템 점검 | MI Creator Hub",
    )
