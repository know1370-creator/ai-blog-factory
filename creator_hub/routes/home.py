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
.hero{background:linear-gradient(135deg,#6d5dfc,#8b7cff);color:white;border-radius:24px;padding:28px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:22px 0}
.c{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px}
.ai{margin-top:18px;background:#fff;border-radius:18px;padding:18px;color:#222}
input.aii{width:100%;padding:14px;border-radius:12px;border:1px solid #ddd}
.todo li{margin:8px 0}
</style>
<div class='hero'>
<h1>👋 안녕하세요, 미경님</h1>
<p>오늘의 콘텐츠를 AI와 함께 시작하세요.</p>
<div class='ai'>
<h3>무엇을 만들까요?</h3>
<input class='aii' placeholder='예: 엄마! 왜 과자 봉지는 반이나 비어 있어?'>
<div style='margin-top:12px'><a class='btn' href='/generator/'>AI 생성 시작</a></div>
</div>
</div>
<div class='cards'>
<div class='c'><h3>✅ 오늘 해야 할 일</h3><ul class='todo'><li>릴스 제작</li><li>인스타툰</li><li>블로그</li></ul></div>
<div class='c'><h3>🎬 빠른 실행</h3><a class='btn' href='/generator/'>콘텐츠 생성</a></div>
<div class='c'><h3>🔥 추천 주제</h3><p>슈링크플레이션</p></div>
<div class='c'><h3>📚 최근 작업</h3><p>EP10 · 릴스 · 블로그</p></div>
</div>
""")