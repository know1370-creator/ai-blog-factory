"""V9.5 safe diagnostics without exposing secret values."""
import os
from datetime import datetime

from flask import Blueprint, render_template_string, send_file
from markupsafe import Markup
from sqlalchemy import text

from ..legacy_app import BASE_DIR, BASE_HTML, Article, db
from .business import FinanceEntry
from .planner import WeeklyPlanItem
from .analytics import ContentMetric
from .social import SocialInteraction
from .manager import HookPack, ReelPlan, ABExperiment
from .library import ContentLibraryItem
from .pipeline import PipelineMeta
from .marketing import MarketingIdea, ShootingChecklist
from .factory import ContentFactoryProject, ContentFactoryOutput, ContentFactoryTemplate


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
        ("콘텐츠 팩토리 프로젝트 테이블", ContentFactoryProject),
        ("콘텐츠 팩토리 결과물 테이블", ContentFactoryOutput),
        ("콘텐츠 팩토리 템플릿 테이블", ContentFactoryTemplate),
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
        ("쿠팡파트너스 API 키", configured("COUPANG_ACCESS_KEY") and configured("COUPANG_SECRET_KEY"), "설정됨" if configured("COUPANG_ACCESS_KEY") and configured("COUPANG_SECRET_KEY") else "미설정 (수동 입력으로 대체됨)"),
        ("인스타그램 자동 게시", configured("INSTAGRAM_ACCESS_TOKEN") and configured("INSTAGRAM_ACCOUNT_ID"), "연결됨" if configured("INSTAGRAM_ACCESS_TOKEN") and configured("INSTAGRAM_ACCOUNT_ID") else "미연결 (토큰 60일마다 재발급 필요)"),
        ("Blogger Client ID", configured("GOOGLE_CLIENT_ID"), "설정됨" if configured("GOOGLE_CLIENT_ID") else "미설정"),
        ("Blogger Client Secret", configured("GOOGLE_CLIENT_SECRET"), "설정됨" if configured("GOOGLE_CLIENT_SECRET") else "미설정"),
        ("앱 Secret Key", configured("SECRET_KEY"), "설정됨" if configured("SECRET_KEY") else "서버 재시작 시 세션이 바뀔 수 있음"),
        ("Database URL", configured("DATABASE_URL"), "외부 DB 설정됨" if configured("DATABASE_URL") else "기본 SQLite 사용"),
    ])

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = len(checks) - passed

    sqlite_path = BASE_DIR / "creator.db"
    using_sqlite = not configured("DATABASE_URL")
    sqlite_exists = sqlite_path.exists()
    sqlite_size_mb = round(sqlite_path.stat().st_size / (1024 * 1024), 2) if sqlite_exists else 0

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>시스템 점검 <span class="status">V9.5</span></h1>
      <p class="lead">비밀값은 보여주지 않고 연결과 설정 여부만 확인합니다.</p>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{passed}}</strong><span class="small">정상 항목</span></div>
    <div class="stat"><strong>{{failed}}</strong><span class="small">확인 필요</span></div>
    <div class="stat"><strong>{{checked_at}}</strong><span class="small">점검 시각</span></div>
  </div>
</section>

<section class="card">
  <h2>데이터 백업</h2>
  {% if using_sqlite %}
    {% if sqlite_exists %}
      <p class="small">
        지금 기본 SQLite 파일을 쓰고 있어요 (현재 크기: {{sqlite_size_mb}}MB).
        서버가 재배포되면 이 파일이 초기화될 수 있으니, 중요한 작업을 마친 뒤에는
        가끔 눌러서 내려받아 두는 걸 추천해요.
      </p>
      <div class="actions">
        <a class="btn" href="{{url_for('diagnostics_v95.download_backup')}}">💾 지금 백업 다운로드</a>
      </div>
      <p class="notice" style="margin-top:12px">
        가장 확실한 방법은 Render에서 PostgreSQL 데이터베이스를 하나 만들어 연결하는
        거예요. 그러면 재배포돼도 데이터가 안전하게 유지돼요. 원하시면 이 전환도
        도와드릴게요.
      </p>
    {% else %}
      <p class="small">아직 데이터베이스 파일이 생성되지 않았어요.</p>
    {% endif %}
  {% else %}
    <p class="small">
      외부 데이터베이스(Postgres 등)를 사용 중이에요. 재배포돼도 데이터가
      사라지지 않는 구조라, 지금은 별도 다운로드 백업이 꼭 필요하진 않아요.
    </p>
  {% endif %}
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
<p class="small">V16 확인 경로: /home/ · /factory/ · /marketing/ · /generator/ · 생성 결과는 자동 게시되지 않고 콘텐츠 라이브러리에 저장됩니다.</p>
</section>
""",
        checks=checks,
        passed=passed,
        failed=failed,
        checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        using_sqlite=using_sqlite,
        sqlite_exists=sqlite_exists,
        sqlite_size_mb=sqlite_size_mb,
        page_title="시스템 점검 | MI Creator OS",
    )


@diagnostics_bp.get("/backup-download")
def download_backup():
    sqlite_path = BASE_DIR / "creator.db"
    if not sqlite_path.exists():
        return "백업할 데이터베이스 파일을 찾을 수 없습니다.", 404

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        sqlite_path,
        as_attachment=True,
        download_name=f"mi_creator_backup_{timestamp}.db",
    )
