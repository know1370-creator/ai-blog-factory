"""V9.1 revenue, AI-cost, and ROI dashboard."""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template_string, request, url_for
from sqlalchemy import func

from ..legacy_app import BASE_HTML, Article, db, get_ai_usage_this_month
from markupsafe import Markup


business_bp = Blueprint("business_v91", __name__, url_prefix="/business")


class FinanceEntry(db.Model):
    __tablename__ = "finance_entry"

    id = db.Column(db.Integer, primary_key=True)
    entry_date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date(), index=True)
    category = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    memo = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


INCOME_CATEGORIES = {
    "adsense": "애드센스",
    "coupang": "쿠팡",
    "atomy": "애터미",
    "toss": "토스쇼핑",
    "other_income": "기타 수익",
}
COST_CATEGORIES = {
    "openai": "OpenAI 비용",
    "hosting": "호스팅 비용",
    "other_cost": "기타 비용",
}
ALL_CATEGORIES = {**INCOME_CATEGORIES, **COST_CATEGORIES}


def page(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)


def won(value):
    return f"{int(value or 0):,}원"


@business_bp.get("/")
def dashboard():
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)

    rows = (
        db.session.query(FinanceEntry.category, func.coalesce(func.sum(FinanceEntry.amount), 0))
        .filter(FinanceEntry.entry_date >= month_start, FinanceEntry.entry_date <= today)
        .group_by(FinanceEntry.category)
        .all()
    )
    totals = {category: float(amount) for category, amount in rows}

    income = sum(totals.get(key, 0) for key in INCOME_CATEGORIES)
    costs = sum(totals.get(key, 0) for key in COST_CATEGORIES)
    net_profit = income - costs
    article_count = Article.query.filter(Article.created_at >= datetime.combine(month_start, datetime.min.time())).count()
    avg_cost = costs / article_count if article_count else 0

    recent_entries = FinanceEntry.query.order_by(
        FinanceEntry.entry_date.desc(), FinanceEntry.id.desc()
    ).limit(30).all()

    ai_usage = get_ai_usage_this_month()
    ai_usage_labels = {"text": "글·아이디어 생성", "image": "이미지 생성", "audio": "음성 생성"}

    return page("""
<section class="card">
  <div class="actions" style="justify-content:space-between;margin-top:0">
    <div>
      <h1>수익 대시보드 <span class="status">V9.1</span></h1>
      <p class="lead">이번 달 콘텐츠 수익, 운영비, 순이익을 한 화면에서 확인해요.</p>
    </div>
    <a class="btn gray" href="{{url_for('home')}}">홈으로</a>
  </div>

  <div class="stat-grid">
    <div class="stat"><strong>{{won(income)}}</strong><span class="small">이번 달 총수익</span></div>
    <div class="stat"><strong>{{won(costs)}}</strong><span class="small">이번 달 총비용</span></div>
    <div class="stat"><strong>{{won(net_profit)}}</strong><span class="small">이번 달 순이익</span></div>
    <div class="stat"><strong>{{won(avg_cost)}}</strong><span class="small">글 1개당 평균비용</span></div>
  </div>
</section>

<section class="card">
  <h2>이번 달 AI 사용 현황 <span class="small">(자동 집계)</span></h2>
  <p class="small">
    OpenAI를 호출할 때마다 자동으로 횟수를 세요. 모델별 가격이 자주 바뀌어
    정확한 달러 금액은 추정하지 않아요 — 실제 청구 금액은
    <a href="https://platform.openai.com/usage" target="_blank">OpenAI 사용량 페이지</a>에서
    확인하신 뒤, 왼쪽 "OpenAI 비용" 항목에 그 금액을 입력해 주세요.
  </p>
  <div class="stat-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
    {% for key,label in ai_usage_labels.items() %}
    <div class="stat">
      <strong>{{ai_usage.get(key, 0)}}</strong>
      <span class="small">{{label}}</span>
    </div>
    {% endfor %}
  </div>
</section>

<div class="grid">
<section class="card">
  <h2>수익·비용 입력</h2>
  <form method="post" action="{{url_for('business_v91.add_entry')}}">
    <label>날짜</label>
    <input type="date" name="entry_date" value="{{today.isoformat()}}" required>

    <label>구분</label>
    <select name="category" required>
      <optgroup label="수익">
      {% for key,label in income_categories.items() %}<option value="{{key}}">{{label}}</option>{% endfor %}
      </optgroup>
      <optgroup label="비용">
      {% for key,label in cost_categories.items() %}<option value="{{key}}">{{label}}</option>{% endfor %}
      </optgroup>
    </select>

    <label>금액</label>
    <input type="number" name="amount" min="0" step="1" placeholder="예: 12500" required>

    <label>메모</label>
    <input name="memo" maxlength="500" placeholder="예: 7월 쿠팡 정산금">

    <div class="actions"><button class="btn" type="submit">내역 저장</button></div>
  </form>
  <p class="notice">OpenAI 비용은 실제 결제 내역을 입력하는 방식이에요. 임의 가격을 만들어 계산하지 않습니다.</p>
</section>

<section class="card">
  <h2>이번 달 항목별 합계</h2>
  {% for key,label in all_categories.items() %}
    <div class="calendar-item">
      <strong>{{label}}</strong>
      <span style="float:right">{{won(totals.get(key,0))}}</span>
    </div>
  {% endfor %}
  <div class="calendar-item">
    <strong>이번 달 생성 글</strong>
    <span style="float:right">{{article_count}}개</span>
  </div>
</section>
</div>

<section class="card">
  <h2>최근 입력 내역</h2>
  {% if recent_entries %}
  <table>
    <thead><tr><th>날짜</th><th>구분</th><th>금액</th><th>메모</th><th></th></tr></thead>
    <tbody>
    {% for item in recent_entries %}
      <tr>
        <td>{{item.entry_date.strftime('%Y-%m-%d')}}</td>
        <td>{{all_categories.get(item.category,item.category)}}</td>
        <td><strong>{{won(item.amount)}}</strong></td>
        <td>{{item.memo or '-'}}</td>
        <td>
          <form method="post" action="{{url_for('business_v91.delete_entry',entry_id=item.id)}}" onsubmit="return confirm('이 내역을 삭제할까요?')">
            <button class="btn red" style="padding:7px 10px" type="submit">삭제</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="small">아직 입력한 수익·비용 내역이 없습니다.</p>
  {% endif %}
</section>
""",
        today=today,
        income=income,
        costs=costs,
        net_profit=net_profit,
        avg_cost=avg_cost,
        totals=totals,
        article_count=article_count,
        recent_entries=recent_entries,
        income_categories=INCOME_CATEGORIES,
        cost_categories=COST_CATEGORIES,
        all_categories=ALL_CATEGORIES,
        won=won,
        ai_usage=ai_usage,
        ai_usage_labels=ai_usage_labels,
        page_title="MI Creator OS · 수익 대시보드",
    )


@business_bp.post("/entries")
def add_entry():
    category = request.form.get("category", "").strip()
    if category not in ALL_CATEGORIES:
        flash("올바른 구분을 선택해 주세요.")
        return redirect(url_for("business_v91.dashboard"))

    try:
        amount = Decimal(request.form.get("amount", "0"))
        if amount < 0:
            raise InvalidOperation
        entry_date = datetime.strptime(request.form.get("entry_date", ""), "%Y-%m-%d").date()
    except (InvalidOperation, ValueError):
        flash("날짜와 금액을 다시 확인해 주세요.")
        return redirect(url_for("business_v91.dashboard"))

    entry = FinanceEntry(
        entry_date=entry_date,
        category=category,
        amount=amount,
        memo=request.form.get("memo", "").strip()[:500],
    )
    db.session.add(entry)
    db.session.commit()
    flash("수익·비용 내역을 저장했어요.")
    return redirect(url_for("business_v91.dashboard"))


@business_bp.post("/entries/<int:entry_id>/delete")
def delete_entry(entry_id):
    entry = db.session.get(FinanceEntry, entry_id)
    if not entry:
        flash("내역을 찾을 수 없습니다.")
        return redirect(url_for("business_v91.dashboard"))

    db.session.delete(entry)
    db.session.commit()
    flash("내역을 삭제했어요.")
    return redirect(url_for("business_v91.dashboard"))
