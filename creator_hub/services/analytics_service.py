"""Dashboard analytics helpers."""
from datetime import datetime, timedelta
from ..models import Article, PublishLog


def dashboard_snapshot():
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return {
        "articles_total": Article.query.count(),
        "articles_this_month": Article.query.filter(Article.created_at >= month_start).count(),
        "publish_success_total": PublishLog.query.filter_by(status="success").count(),
        "scheduled_total": Article.query.filter(Article.scheduled_at.isnot(None)).count(),
    }
