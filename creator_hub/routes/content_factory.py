"""
콘텐츠 공장 (애드센스 원본 글 -> 네이버 -> 스레드 -> 쇼츠 -> 이미지 -> 발행)

v3 변경사항:
- 이미지 생성을 나노바나나(Gemini 2.5 Flash Image, 모델명 gemini-2.5-flash-image)로 연결
- 카드 1개당 버튼 1번 눌러야 이미지 1장이 생성되도록 설계 (한꺼번에 8장 자동생성 금지 -> 비용 통제)
- 텍스트 생성(원본글/네이버/스레드/쇼츠/이미지 프롬프트)은 기존과 동일하게 OpenAI 텍스트 모델 사용

파일 위치: creator_hub/routes/content_factory.py

* requirements.txt 에 아래 한 줄이 추가되어 있어야 합니다:
      google-genai
* Render 환경변수에 GEMINI_API_KEY 가 등록되어 있어야 합니다.
"""

import os
import base64
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from openai import OpenAI
from google import genai

# 텍스트 생성용 (기존과 동일하게 OpenAI 텍스트 모델 사용)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"  # 필요하면 기존 코드에서 쓰는 모델명으로 교체하세요

# 이미지 생성 파일을 기존 사이트와 같은 폴더에 저장해서 /media/<filename> 으로 바로 보이게 합니다.
from ..legacy_app import MEDIA_DIR

IMAGE_MODEL = "gemini-2.5-flash-image"  # 나노바나나

content_factory_bp = Blueprint(
    "content_factory", __name__, url_prefix="/content-factory"
)


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
        return jsonify({"error": f"생성 중 오류가 발생했습니다: {e}"}), 500


@content_factory_bp.route("/api/generate-image", methods=["POST"])
def generate_image_route():
    """나노바나나(Gemini 2.5 Flash Image)로 카드 1개 분량의 실제 이미지 1장을 생성합니다.
    호출될 때마다 비용이 발생하므로, 프론트엔드는 사용자가 카드별 버튼을 눌렀을 때만 호출합니다."""
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "이미지 설명을 먼저 입력하세요."}), 400

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({"error": "Render 환경변수에 GEMINI_API_KEY가 없습니다."}), 500

    try:
        gclient = genai.Client(api_key=api_key)
        response = gclient.models.generate_content(
            model=IMAGE_MODEL,
            contents=[prompt],
        )
        image_bytes = None
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                image_bytes = part.inline_data.data
                break
        if not image_bytes:
            raise RuntimeError("이미지 데이터가 반환되지 않았습니다.")

        filename = f"content_factory_{int(datetime.utcnow().timestamp() * 1000)}.png"
        (MEDIA_DIR / filename).write_bytes(image_bytes)
        return jsonify({"url": f"/media/{filename}"})
    except Exception as e:
        return jsonify({"error": f"이미지 생성 중 오류: {e}"}), 500
