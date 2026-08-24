"""
콘텐츠 공장 (애드센스 원본 글 -> 네이버 -> 스레드 -> 쇼츠 -> 이미지 프롬프트)

기존 프로젝트에 추가하는 방법:
1. 이 파일을 blueprints/content_factory.py 로 저장 (이미 있는 blueprints 폴더 안에)
2. templates/content_factory.html 파일도 templates 폴더 안에 저장
3. 메인 앱 파일(예: legacy_app.py) 맨 위쪽 import 부분에 아래 한 줄 추가:
       from blueprints.content_factory import content_factory_bp
4. app = Flask(__name__) 만든 다음 어딘가에 아래 한 줄 추가:
       app.register_blueprint(content_factory_bp)
5. 기존 루틴대로: Codespace에 두 파일 덮어쓰기 -> git add . -> git commit -m "콘텐츠 공장 추가" -> git push origin main -> Render Events에서 "Deploy live" 확인

* MODEL 이름은 기존 사이트 다른 기능에서 쓰시던 것과 다를 수 있어요. 아래 MODEL 변수를
  기존 코드에서 쓰시는 모델명과 같은 값으로 맞춰주세요 (예: "gpt-4o-mini", "gpt-4o" 등).
* OPENAI_API_KEY는 이미 Render 환경변수에 등록되어 있는 걸 그대로 씁니다.
"""

import os
from flask import Blueprint, render_template, request, jsonify
from openai import OpenAI

content_factory_bp = Blueprint(
    "content_factory", __name__, url_prefix="/content-factory"
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"  # 필요하면 기존 코드에서 쓰는 모델명으로 교체하세요


def ask_ai(prompt, max_tokens=900):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.8,
    )
    return resp.choices[0].message.content.strip()


def build_prompt(step, data):
    keyword = (data.get("keyword") or "").strip()
    extra_info = (data.get("extraInfo") or "").strip()
    original = (data.get("original") or "").strip()
    naver = (data.get("naver") or "").strip()
    shorts = (data.get("shorts") or "").strip()
    product_desc = (data.get("productDesc") or "").strip()

    if step == "original":
        if not keyword:
            raise ValueError("키워드를 입력하세요.")
        prompt = (
            "너는 한국어 애드센스 블로그 원고를 쓰는 SEO 라이터야. "
            "아래 키워드로 검색하는 사람이 실제로 헷갈려하는 지점을 짚어주는 글을 써줘.\n"
            f"키워드: {keyword}\n"
        )
        if extra_info:
            prompt += f"최신 참고 정보(가능하면 반영): {extra_info}\n"
        prompt += (
            "조건: 제목 1줄 + 소제목 2~3개로 구성, 총 600~900자 내외, "
            "과장 광고 문구 금지, 정보 제공 목적이라는 문장을 마지막에 짧게 포함. "
            "마크다운 소제목(##) 사용."
        )
        return prompt

    if step == "naver":
        if not original:
            raise ValueError("원본 글이 먼저 필요합니다.")
        return (
            "아래 글을 네이버 블로그 스타일로 다시 써줘. 문단을 짧게 끊고, "
            "친근한 구어체를 쓰고, 소제목 앞에 어울리는 이모지를 하나씩만 붙여줘. "
            "원문의 핵심 정보는 유지해.\n\n" + original
        )

    if step == "thread":
        base = naver or original
        if not base:
            raise ValueError("원본 글이 먼저 필요합니다.")
        return (
            "아래 내용을 스레드(Threads) 게시글로 압축해줘. 5~7줄, 첫 줄은 강한 훅, "
            "마지막 줄은 질문이나 공감 유도 문장으로 끝내줘. 해시태그는 2개까지만.\n\n"
            + base
        )

    if step == "shorts":
        if not original:
            raise ValueError("원본 글이 먼저 필요합니다.")
        return (
            "아래 글을 30초 안팎 쇼츠 대본으로 기획해줘. "
            "'장면 N (초 구간): 대사 / 화면 지시' 형식으로 4~5개 장면을 만들어줘. "
            "첫 장면은 3초 안에 시선을 잡는 훅으로.\n\n" + original
        )

    if step == "image":
        base = shorts or original
        if not base and not product_desc:
            raise ValueError("원본 글이나 참고 설명 중 하나는 필요합니다.")
        prompt = (
            "아래 내용에 맞춰 이미지 생성 프롬프트 3개를 만들어줘. 각 프롬프트는 "
            "어떤 장면인지 한 줄로 먼저 쓰고, 그 아래 한국어 프롬프트, 그 아래 영어 프롬프트를 "
            "붙여줘. 사실적인 사진 톤, 인물 얼굴 특정 묘사 금지.\n"
        )
        if product_desc:
            prompt += f"참고할 제품/상황 설명: {product_desc}\n"
        prompt += "\n" + base
        return prompt

    raise ValueError("알 수 없는 단계입니다.")


@content_factory_bp.route("/")
def index():
    return render_template("content_factory.html")


@content_factory_bp.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True, silent=True) or {}
    step = data.get("step")
    try:
        prompt = build_prompt(step, data)
        text = ask_ai(prompt)
        return jsonify({"result": text})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # 크레딧 소진(429) 등 OpenAI 쪽 오류도 여기로 걸러져서 화면에 표시됩니다.
        return jsonify({"error": f"생성 중 오류가 발생했습니다: {e}"}), 500
