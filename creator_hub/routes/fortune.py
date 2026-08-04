"""V1.0 방문자용 유료 개인 운세 서비스 (토스페이먼츠 가상계좌 결제).

관리자 화면과 완전히 분리된, 로그인 없이 누구나 접속하는 공개 페이지입니다.
BASE_HTML(관리자용 전체 메뉴)을 쓰지 않고 이 파일 안에 자체 디자인을 갖습니다.
"""
import base64
import os
import uuid
from datetime import date, datetime

import requests
from flask import Blueprint, jsonify, redirect, render_template_string, request, url_for
from markupsafe import Markup

from ..legacy_app import OPENAI_MODEL, db, log_ai_usage, openai_client, strip_code_fence

fortune_bp = Blueprint("fortune_v1", __name__, url_prefix="/fortune")

# 토스페이먼츠 공식 "누구나 쓸 수 있는 테스트 키"가 기본값입니다.
# 실제 결제를 받으려면 Render 환경변수에 본인의 클라이언트 키/시크릿 키를
# TOSS_CLIENT_KEY, TOSS_SECRET_KEY 로 등록해 주세요 (토스페이먼츠 개발자센터
# > API 키 메뉴에서 확인).
TOSS_CLIENT_KEY = os.getenv("TOSS_CLIENT_KEY", "test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq")
TOSS_SECRET_KEY = os.getenv("TOSS_SECRET_KEY", "test_sk_zXLkKEypNArWmo50nX3lmeaxYG5R")
FORTUNE_PRICE = 3000


class FortuneOrder(db.Model):
    __tablename__ = "fortune_order"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    birth_date = db.Column(db.Date, nullable=False)
    birth_time = db.Column(db.String(20), default="")
    gender = db.Column(db.String(10), default="")
    amount = db.Column(db.Integer, nullable=False, default=FORTUNE_PRICE)
    status = db.Column(db.String(20), nullable=False, default="pending")
    # pending(주문만 생성) -> waiting_deposit(가상계좌 발급, 입금 대기)
    # -> paid(입금 완료, 운세 생성됨) / failed
    payment_key = db.Column(db.String(200), default="")
    virtual_account_number = db.Column(db.String(60), default="")
    virtual_account_bank = db.Column(db.String(40), default="")
    virtual_account_due_date = db.Column(db.String(40), default="")
    reading_text = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)


FORTUNE_HTML = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>오늘의 운세 보기</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" as="style" crossorigin
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<style>
:root{--ink:#221f2b;--muted:#7a7488;--line:#e8e3ee;--brand:#4b3f72;--brand-dark:#352c54;--brand-soft:#f4f1fb;--gold:#b8925a;--gold-soft:#faf3e6;--paper:#faf8f4;--bad:#c23b3b}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:'Pretendard Variable','Pretendard',-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif}
.wrap{max-width:520px;margin:0 auto;padding:32px 18px 60px}
.card{background:#fff;border:1px solid var(--line);border-radius:20px;padding:26px;margin-bottom:16px;box-shadow:0 12px 32px rgba(43,32,74,.08)}
h1{font-size:26px;margin:0 0 8px;color:var(--brand-dark)}
p.lead{color:var(--muted);margin:0 0 20px}
label{font-weight:700;display:block;margin:14px 0 7px}
input,select{width:100%;border:1.5px solid #e2dced;border-radius:12px;padding:12px 13px;font:inherit;background:#fff}
input:focus,select:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.btn{border:0;border-radius:11px;padding:14px 18px;background:var(--brand-dark);color:#fff;font-weight:700;cursor:pointer;width:100%;font-size:16px}
.btn:disabled{opacity:.5;cursor:not-allowed}
.price{font-size:28px;font-weight:900;color:var(--brand-dark)}
.notice{font-size:13px;color:var(--muted);background:var(--paper);border-radius:10px;padding:12px;margin-top:14px;line-height:1.6}
.reading{white-space:pre-wrap;line-height:1.85;font-size:16px}
.status-badge{display:inline-block;padding:6px 12px;border-radius:99px;font-weight:700;font-size:13px;margin-bottom:12px}
.status-waiting{background:var(--gold-soft);color:#8a6d3f}
.status-paid{background:#e7f5ee;color:#127a53}
.status-failed{background:#fbe9e9;color:var(--bad)}
.account-box{background:var(--brand-soft);border-radius:14px;padding:18px;margin-top:14px}
.account-box strong{font-size:20px;color:var(--brand-dark)}
</style>
</head>
<body>
<div class="wrap">
{{ body }}
</div>
</body>
</html>
"""


def page(body_template, **context):
    inner = render_template_string(body_template, **context)
    return render_template_string(FORTUNE_HTML, body=Markup(inner))


def generate_fortune_reading(name, birth_date, birth_time, gender):
    """생년월일 기반 개인 운세를 생성합니다. 재미로 보는 콘텐츠임을
    명시하고, 확정적인 의학·재정·법률 조언처럼 들리지 않게 안전장치를 둡니다."""
    prompt = f"""
당신은 따뜻하고 통찰력 있는 사주·운세 콘텐츠 작가입니다.
아래 정보를 참고해 개인 맞춤 운세를 한국어로 작성하세요.

이름: {name}
생년월일: {birth_date}
태어난 시간: {birth_time or "모름"}
성별: {gender or "밝히지 않음"}

작성 규칙:
- 총 6~8문단으로 구성: 전체 총운 / 애정운 / 재물운 / 건강운 / 조언 한마디
- 따뜻하고 희망적인 톤이되, 근거 없이 100% 확정적으로 단정하지 않는다.
- 의학적 진단, 특정 투자 종목, 확정 로또 번호, 법률 자문처럼 들리는
  표현은 절대 쓰지 않는다.
- 심각한 질병, 죽음, 이혼처럼 불안을 조장하는 단정적 표현은 쓰지 않는다.
- 마지막 문단에 "이 운세는 재미로 참고하는 콘텐츠이며, 중요한 결정은
  전문가와 상의하세요"라는 취지의 안내를 자연스럽게 포함한다.
- 광고나 상품 추천은 절대 넣지 않는다.

일반 텍스트로만 답하세요(JSON 아님).
"""
    response = openai_client().responses.create(model=OPENAI_MODEL, input=prompt)
    log_ai_usage("text")
    return strip_code_fence(response.output_text).strip()


def toss_auth_header():
    encoded = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def toss_confirm_payment(payment_key, order_id, amount):
    """토스페이먼츠 결제 승인 API를 호출합니다. 가상계좌는 승인 즉시
    WAITING_FOR_DEPOSIT 상태가 되고, 실제 입금 완료는 별도 웹훅으로 옵니다."""
    response = requests.post(
        "https://api.tosspayments.com/v1/payments/confirm",
        headers=toss_auth_header(),
        json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
        timeout=15,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"message": "토스페이먼츠 응답을 읽지 못했습니다."}
    return response.status_code, body


def fill_reading(order):
    if order.reading_text:
        return
    order.reading_text = generate_fortune_reading(
        order.name, order.birth_date, order.birth_time, order.gender
    )
    db.session.commit()


@fortune_bp.get("/")
def landing():
    return page("""
<div class="card" id="inapp_browser_notice" style="display:none;background:#fff3cd;border:1px solid #ffe08a">
  <p style="margin:0;font-weight:700;color:#7a5a00">
    ⚠️ 인스타그램 안에서 열려있어요
  </p>
  <p style="margin:8px 0 12px;font-size:14px;color:#7a5a00;line-height:1.6">
    결제창이 인스타그램 앱 안에서는 정상적으로 안 열릴 수 있어요.
    아래 버튼을 눌러서 다른 브라우저로 열어보세요.
  </p>
  <a id="open_external_btn" class="btn" style="text-decoration:none;display:block;text-align:center;background:#7a5a00" target="_blank" rel="noopener">
    다른 브라우저에서 열기
  </a>
  <button id="copy_link_btn" class="btn gray" type="button" style="margin-top:8px;width:100%">
    링크 복사하기 (자동으로 안 열리면 크롬에 붙여넣어 주세요)
  </button>
</div>
<script>
(function(){
  var ua = navigator.userAgent || "";
  var isInApp = /Instagram|FBAN|FBAV/i.test(ua);
  if (!isInApp) return;

  var el = document.getElementById('inapp_browser_notice');
  if (el) el.style.display = 'block';

  var pageUrl = window.location.href;
  var isAndroid = /Android/i.test(ua);
  var openBtn = document.getElementById('open_external_btn');
  if (openBtn) {
    if (isAndroid) {
      // 안드로이드는 intent 링크를 쓰면 크롬으로 바로 넘어가는 경우가
      // 많아서 이 방식을 우선 시도합니다.
      var cleanUrl = pageUrl.replace("https://", "").replace("http://", "");
      openBtn.href = "intent://" + cleanUrl + "#Intent;scheme=https;package=com.android.chrome;end";
    } else {
      openBtn.href = pageUrl;
    }
  }

  var copyBtn = document.getElementById('copy_link_btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function(){
      navigator.clipboard.writeText(pageUrl).then(function(){
        copyBtn.textContent = '복사 완료! 크롬 앱을 열어서 주소창에 붙여넣어 주세요';
      }).catch(function(){
        copyBtn.textContent = '복사 실패했어요. 주소를 직접 옮겨 적어주세요: ' + pageUrl;
      });
    });
  }
})();
</script>
<div class="card">
  <h1>🔮 오늘의 나의 운세</h1>
  <p class="lead">생년월일을 입력하면 AI가 나만의 운세를 읽어드려요.</p>
  <div class="price">3,000원</div>

  <form method="post" action="{{ url_for('fortune_v1.create_order') }}">
    <label>이름 (또는 별명)</label>
    <input name="name" required maxlength="80" placeholder="예: 미경">

    <label>생년월일</label>
    <input type="date" name="birth_date" required max="{{ today }}">

    <label>태어난 시간 (모르면 비워두세요)</label>
    <input type="time" name="birth_time">

    <label>성별 (선택)</label>
    <select name="gender">
      <option value="">선택 안 함</option>
      <option value="여성">여성</option>
      <option value="남성">남성</option>
    </select>

    <div style="margin-top:20px">
      <button class="btn" type="submit">3,000원 결제하고 운세 보기</button>
    </div>
  </form>

  <div class="notice">
    이 서비스는 재미로 참고하는 콘텐츠입니다. 의학·재정·법률적 조언을
    대신하지 않으며, 중요한 결정은 전문가와 상의해 주세요. 결제는
    계좌이체(가상계좌)로 진행되며, 입금 확인 후 자동으로 운세가
    표시됩니다.
  </div>
</div>
""", today=date.today().isoformat())


@fortune_bp.post("/order")
def create_order():
    name = request.form.get("name", "").strip()[:80]
    birth_date_raw = request.form.get("birth_date", "").strip()
    birth_time = request.form.get("birth_time", "").strip()
    gender = request.form.get("gender", "").strip()

    try:
        birth_date = datetime.strptime(birth_date_raw, "%Y-%m-%d").date()
    except ValueError:
        return page("""
<div class="card">
  <h1>입력 오류</h1>
  <p>생년월일을 다시 확인해 주세요.</p>
  <a class="btn" href="{{ url_for('fortune_v1.landing') }}" style="text-decoration:none;display:block;text-align:center">다시 입력하기</a>
</div>
""")

    if not name:
        return page("""
<div class="card">
  <h1>입력 오류</h1>
  <p>이름(또는 별명)을 입력해 주세요.</p>
  <a class="btn" href="{{ url_for('fortune_v1.landing') }}" style="text-decoration:none;display:block;text-align:center">다시 입력하기</a>
</div>
""")

    order = FortuneOrder(
        order_id=f"fortune{uuid.uuid4().hex[:20]}",
        name=name,
        birth_date=birth_date,
        birth_time=birth_time,
        gender=gender,
        amount=FORTUNE_PRICE,
        status="pending",
    )
    db.session.add(order)
    db.session.commit()

    # 여기서 바로 결제창 화면을 그려버리면, 주소창은 계속
    # "/fortune/order"(POST 전용 주소)로 남아있게 됩니다. 이 상태에서
    # 손님이 새로고침하거나 이 주소를 다시 열면 "GET은 지원 안 함"
    # 오류가 나요. 그래서 주문을 만든 뒤에는 새로고침해도 안전한 별도
    # 주소(/fortune/pay/<주문번호>)로 넘겨줍니다.
    return redirect(url_for("fortune_v1.payment_page", order_id=order.order_id))


@fortune_bp.get("/pay/<order_id>")
def payment_page(order_id):
    order = FortuneOrder.query.filter_by(order_id=order_id).first()
    if not order:
        return page("""<div class="card"><h1>주문을 찾을 수 없어요</h1></div>""")

    if order.status != "pending":
        return redirect(url_for("fortune_v1.result", order_id=order.order_id))

    return page("""
<div class="card" id="inapp_browser_notice" style="display:none;background:#fff3cd;border:1px solid #ffe08a">
  <p style="margin:0;font-weight:700;color:#7a5a00">
    ⚠️ 인스타그램 안에서 열려있어요
  </p>
  <p style="margin:8px 0 12px;font-size:14px;color:#7a5a00;line-height:1.6">
    결제창이 인스타그램 앱 안에서는 정상적으로 안 열릴 수 있어요.
    아래 버튼을 눌러서 다른 브라우저로 열어보세요.
  </p>
  <a id="open_external_btn" class="btn" style="text-decoration:none;display:block;text-align:center;background:#7a5a00" target="_blank" rel="noopener">
    다른 브라우저에서 열기
  </a>
  <button id="copy_link_btn" class="btn gray" type="button" style="margin-top:8px;width:100%">
    링크 복사하기 (자동으로 안 열리면 크롬에 붙여넣어 주세요)
  </button>
</div>
<script>
(function(){
  var ua = navigator.userAgent || "";
  var isInApp = /Instagram|FBAN|FBAV/i.test(ua);
  if (!isInApp) return;

  var el = document.getElementById('inapp_browser_notice');
  if (el) el.style.display = 'block';

  var pageUrl = window.location.href;
  var isAndroid = /Android/i.test(ua);
  var openBtn = document.getElementById('open_external_btn');
  if (openBtn) {
    if (isAndroid) {
      var cleanUrl = pageUrl.replace("https://", "").replace("http://", "");
      openBtn.href = "intent://" + cleanUrl + "#Intent;scheme=https;package=com.android.chrome;end";
    } else {
      openBtn.href = pageUrl;
    }
  }

  var copyBtn = document.getElementById('copy_link_btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function(){
      navigator.clipboard.writeText(pageUrl).then(function(){
        copyBtn.textContent = '복사 완료! 크롬 앱을 열어서 주소창에 붙여넣어 주세요';
      }).catch(function(){
        copyBtn.textContent = '복사 실패했어요. 주소를 직접 옮겨 적어주세요: ' + pageUrl;
      });
    });
  }
})();
</script>
<div class="card">
  <h1>결제하기</h1>
  <p class="lead">{{ order.name }}님의 운세 · {{ "{:,}".format(order.amount) }}원</p>
  <div id="payment-method"></div>
  <div id="agreement"></div>
  <button class="btn" id="pay-button" style="margin-top:16px">가상계좌로 결제하기</button>
  <div class="notice">
    결제창에서 은행을 선택하면 전용 가상계좌 번호가 발급돼요. 그 계좌로
    입금하시면 자동으로 확인되고, 이 페이지가 운세 결과로 바뀌어요.
  </div>
</div>

<script src="https://js.tosspayments.com/v2/standard"></script>
<script>
const clientKey = "{{ client_key }}";
const customerKey = "{{ order.order_id }}";

(async () => {
  try {
    const tossPayments = TossPayments(clientKey);
    const widgets = tossPayments.widgets({ customerKey });

    await widgets.setAmount({ currency: "KRW", value: {{ order.amount }} });
    await Promise.all([
      widgets.renderPaymentMethods({ selector: "#payment-method", variantKey: "DEFAULT" }),
      widgets.renderAgreement({ selector: "#agreement", variantKey: "AGREEMENT" }),
    ]);

    document.getElementById("pay-button").addEventListener("click", async () => {
      try {
        await widgets.requestPayment({
          orderId: "{{ order.order_id }}",
          orderName: "{{ order.name }}님의 오늘의 운세",
          successUrl: window.location.origin + "{{ url_for('fortune_v1.payment_success') }}",
          failUrl: window.location.origin + "{{ url_for('fortune_v1.payment_fail') }}",
        });
      } catch (err) {
        console.error("결제 요청 실패:", err);
        alert("결제 요청 중 문제가 발생했어요: " + (err.message || err));
      }
    });
  } catch (err) {
    // 여기서 실패하면 이전에는 "가상계좌로 결제하기" 버튼에 클릭
    // 이벤트가 아예 연결이 안 돼서, 눌러도 조용히 아무 일도 안
    // 일어났습니다. 이제는 화면에 에러를 직접 보여줘서 원인을 바로
    // 확인할 수 있게 합니다.
    console.error("결제창 초기화 실패:", err);
    const btn = document.getElementById("pay-button");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "결제창을 불러오지 못했어요";
    }
    const notice = document.createElement("div");
    notice.className = "notice";
    notice.style.color = "#c23b3b";
    notice.style.marginTop = "10px";
    notice.textContent = "결제창 로딩 오류: " + (err && (err.message || String(err)));
    document.getElementById("payment-method").after(notice);
  }
})();
</script>
""", order=order, client_key=TOSS_CLIENT_KEY)


@fortune_bp.get("/success")
def payment_success():
    payment_key = request.args.get("paymentKey", "")
    order_id = request.args.get("orderId", "")
    amount = request.args.get("amount", "")

    order = FortuneOrder.query.filter_by(order_id=order_id).first()
    if not order:
        return page("""<div class="card"><h1>주문을 찾을 수 없어요</h1></div>""")

    try:
        amount_int = int(amount)
    except ValueError:
        amount_int = order.amount

    status_code, payload = toss_confirm_payment(payment_key, order_id, amount_int)

    if status_code >= 400:
        order.status = "failed"
        db.session.commit()
        return page("""
<div class="card">
  <span class="status-badge status-failed">결제 실패</span>
  <h1>결제를 완료하지 못했어요</h1>
  <p>{{ message }}</p>
  <a class="btn" href="{{ url_for('fortune_v1.landing') }}" style="text-decoration:none;display:block;text-align:center;margin-top:14px">다시 시도하기</a>
</div>
""", message=payload.get("message", "알 수 없는 오류"))

    order.payment_key = payment_key
    method_status = payload.get("status", "")

    if method_status == "DONE":
        order.status = "paid"
        order.paid_at = datetime.utcnow()
        db.session.commit()
        try:
            fill_reading(order)
        except Exception:
            pass
    elif method_status == "WAITING_FOR_DEPOSIT":
        va = payload.get("virtualAccount", {}) or {}
        order.status = "waiting_deposit"
        order.virtual_account_number = va.get("accountNumber", "")
        order.virtual_account_bank = va.get("bankCode", "")
        order.virtual_account_due_date = va.get("dueDate", "")
        db.session.commit()
    else:
        order.status = "failed"
        db.session.commit()

    return redirect(url_for("fortune_v1.result", order_id=order.order_id))


@fortune_bp.get("/fail")
def payment_fail():
    order_id = request.args.get("orderId", "")
    message = request.args.get("message", "결제가 취소되었어요.")
    order = FortuneOrder.query.filter_by(order_id=order_id).first()
    if order:
        order.status = "failed"
        db.session.commit()
    return page("""
<div class="card">
  <span class="status-badge status-failed">결제 취소/실패</span>
  <h1>결제가 진행되지 않았어요</h1>
  <p>{{ message }}</p>
  <a class="btn" href="{{ url_for('fortune_v1.landing') }}" style="text-decoration:none;display:block;text-align:center;margin-top:14px">다시 시도하기</a>
</div>
""", message=message)


@fortune_bp.get("/result/<order_id>")
def result(order_id):
    order = FortuneOrder.query.filter_by(order_id=order_id).first()
    if not order:
        return page("""<div class="card"><h1>주문을 찾을 수 없어요</h1></div>""")

    if order.status == "paid":
        return page("""
<div class="card">
  <span class="status-badge status-paid">결제 완료</span>
  <h1>{{ order.name }}님의 오늘의 운세</h1>
  <div class="reading">{{ order.reading_text or "운세를 만드는 중이에요. 잠시 후 새로고침 해주세요." }}</div>
</div>
""", order=order)

    if order.status == "waiting_deposit":
        return page("""
<div class="card">
  <span class="status-badge status-waiting">입금 대기중</span>
  <h1>가상계좌로 입금해 주세요</h1>
  <div class="account-box">
    <div class="small">{{ order.virtual_account_bank }}</div>
    <strong>{{ order.virtual_account_number }}</strong>
    <div class="small" style="margin-top:6px">입금 기한: {{ order.virtual_account_due_date }}</div>
    <div class="small" style="margin-top:6px">입금 금액: {{ "{:,}".format(order.amount) }}원 (정확히 맞춰 입금해 주세요)</div>
  </div>
  <p class="notice">
    입금하시면 자동으로 확인되고 이 페이지가 운세 결과로 바뀌어요.
    이 페이지 주소를 저장해두셨다가 입금 후 새로고침 해보세요.
  </p>
  <button class="btn" onclick="location.reload()" style="margin-top:10px">새로고침</button>
</div>
""", order=order)

    return page("""
<div class="card">
  <span class="status-badge status-failed">결제 대기/실패</span>
  <h1>아직 결제가 완료되지 않았어요</h1>
  <a class="btn" href="{{ url_for('fortune_v1.landing') }}" style="text-decoration:none;display:block;text-align:center;margin-top:14px">처음부터 다시하기</a>
</div>
""")


@fortune_bp.post("/webhook")
def toss_webhook():
    """가상계좌 입금이 실제로 완료되면 토스페이먼츠가 이 주소로 알려줍니다.
    토스페이먼츠 개발자센터 > 웹훅 메뉴에서 아래 주소를 등록해 주세요:
    https://내도메인/fortune/webhook
    """
    payload = request.get_json(silent=True) or {}
    data = payload.get("data", {}) or {}

    if data.get("status") == "DONE":
        order_id = data.get("orderId", "")
        order = FortuneOrder.query.filter_by(order_id=order_id).first()
        if order and order.status != "paid":
            order.status = "paid"
            order.paid_at = datetime.utcnow()
            db.session.commit()
            try:
                fill_reading(order)
            except Exception:
                pass  # 운세 생성 실패해도 웹훅 응답은 성공으로 보내 재시도를 막습니다.

    return jsonify({"received": True})
