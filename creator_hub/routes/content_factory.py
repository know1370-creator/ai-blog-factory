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
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, url_for
from openai import OpenAI
from google import genai
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

# 텍스트 생성용 (기존과 동일하게 OpenAI 텍스트 모델 사용)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"  # 필요하면 기존 코드에서 쓰는 모델명으로 교체하세요

# 더빙(TTS)용 모델 - OpenAI 텍스트-음성 변환
TTS_MODEL = "tts-1"
# 화면의 한글 목소리 이름 -> OpenAI TTS 목소리 이름 매핑
VOICE_MAP = {
    "차분한 여성 (기본)": "nova",
    "밝은 여성": "shimmer",
    "차분한 남성": "onyx",
    "신뢰감 있는 남성": "echo",
}

# 이미지 생성 파일을 기존 사이트와 같은 폴더에 저장해서 /media/<filename> 으로 바로 보이게 합니다.
# ffmpeg/음성 관련 헬퍼는 legacy_app.py에 이미 있는 것을 그대로 재사용합니다
# (운세 릴스 영상 만들 때 오디오 트랙/9:16/faststart 문제를 이미 해결해둔 코드입니다).
from ..legacy_app import (
    MEDIA_DIR, Article, db, analyze_seo,
    ffmpeg_binary, ffprobe_binary, media_duration_seconds, safe_float,
    allowed_bgm_file, MAX_BGM_BYTES,
)

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
    brand = (data.get("brand") or "기본 브랜드").strip()
    article_type = (data.get("articleType") or "정보형").strip()
    length = (data.get("length") or "약 2,500자").strip()

    if step == "original":
        if not keyword:
            raise ValueError("키워드를 입력하세요.")
        prompt = (
            "너는 한국어 애드센스 블로그 원고를 쓰는 SEO 라이터야. "
            "아래 키워드로 검색하는 사람이 실제로 헷갈려하는 지점을 짚어주는 글을 써줘.\n"
            f"키워드: {keyword}\n"
            f"브랜드/주제 분야: {brand}\n글 유형: {article_type}\n분량: {length}\n"
        )
        if extra_info:
            prompt += f"최신 참고 정보(가능하면 반영): {extra_info}\n"
        prompt += (
            "조건: 제목 1줄, 메타 설명 1줄, 소제목과 본문, 마지막에 태그 5개를 포함하고 "
            f"전체 분량은 {length}에 맞춰 작성. "
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
            "아래 내용으로 SNS 묶음을 만들어줘. 반드시 [인스타그램], [Threads] 두 구역으로 나누고, "
            "인스타그램은 훅·본문·CTA·해시태그를 포함해줘. Threads는 5~7줄, 첫 줄은 강한 훅, "
            "친한 친구에게 말하듯 자연스러운 반말로 쓰고 존댓말과 '~요', '~습니다' 종결은 사용하지 마. "
            "무례하거나 공격적인 표현은 피하고, 마지막 줄은 질문이나 공감 유도로 끝내고 해시태그는 2개까지만.\n\n"
            + base
        )

    if step == "shorts":
        if not original:
            raise ValueError("원본 글이 먼저 필요합니다.")
        return (
            "아래 글을 30초 안팎 쇼츠 대본과 업로드 정보를 한 번에 만들어줘. "
            "'장면 N (초 구간): 대사 / 화면 지시' 형식으로 4~5개 장면을 만들어줘. "
            "첫 장면은 3초 안에 시선을 잡는 훅으로. 대본 뒤에 [유튜브 제목], [유튜브 설명], "
            "[유튜브 태그], [틱톡 캡션] 구역을 추가해줘.\n\n" + original
        )

    if step == "seo":
        if not original:
            raise ValueError("원본 글이 먼저 필요합니다.")
        return (
            "아래 글을 SEO 관점에서 점검해줘. 100점 만점 예상 점수, 잘된 점 3개, "
            "수정할 점 3개, 추천 제목 3개, 메타 설명 1개, 핵심 키워드와 태그 5개를 "
            "한국어로 간결하게 정리해줘.\n\n" + original
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


@content_factory_bp.route("/api/save", methods=["POST"])
def save_to_library():
    data = request.get_json(force=True, silent=True) or {}
    content = data.get("content") or {}
    original = (content.get("original") or "").strip()
    keyword = (content.get("keyword") or "").strip()
    if not original or not keyword:
        return jsonify({"error": "키워드와 원본 글을 먼저 만들어 주세요."}), 400
    try:
        first_line = next((line.strip("# ") for line in original.splitlines() if line.strip()), keyword)
        article = Article(
            keyword=keyword,
            title=first_line[:200],
            meta_description=(content.get("seo") or "")[:500],
            body_html=original,
            brand_style=(content.get("brand") or "기본 브랜드"),
            article_type=(content.get("articleType") or "정보형"),
            audience="콘텐츠 공장에서 선택한 주제의 독자",
            notes=(content.get("extraInfo") or ""),
            tags="",
        )
        article.instagram_caption = content.get("thread") or ""
        article.threads_text = content.get("thread") or ""
        article.shorts_script = content.get("shorts") or ""
        db.session.add(article)
        db.session.flush()
        article.seo_score, report = analyze_seo(article)
        import json
        article.seo_report = json.dumps(report, ensure_ascii=False)
        db.session.commit()
        return jsonify({"url": url_for("edit_article", article_id=article.id)})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"완성본 저장 중 오류가 발생했습니다: {e}"}), 500


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


@content_factory_bp.route("/api/upload-bgm", methods=["POST"])
def upload_bgm_route():
    """배경음악 파일을 서버에 업로드합니다 (MP3/WAV/M4A/AAC/OGG, 25MB 이하)."""
    file_storage = request.files.get("bgm")
    if not file_storage or not file_storage.filename:
        return jsonify({"error": "업로드할 배경음악 파일이 없습니다."}), 400

    try:
        if not allowed_bgm_file(file_storage.filename):
            return jsonify({"error": "MP3, WAV, M4A, AAC, OGG 파일만 업로드할 수 있습니다."}), 400

        safe_name = secure_filename(file_storage.filename)
        extension = safe_name.rsplit(".", 1)[1].lower()
        raw_bytes = file_storage.read()

        if not raw_bytes:
            return jsonify({"error": "업로드한 파일이 비어 있습니다."}), 400
        if len(raw_bytes) > MAX_BGM_BYTES:
            return jsonify({"error": "배경음악 파일은 25MB 이하만 업로드할 수 있습니다."}), 400

        filename = f"content_factory_bgm_{int(datetime.utcnow().timestamp() * 1000)}.{extension}"
        output_path = MEDIA_DIR / filename
        output_path.write_bytes(raw_bytes)

        # ffprobe로 정상 오디오 파일인지 확인 (깨진 파일이면 여기서 에러가 남)
        media_duration_seconds(output_path)

        return jsonify({"filename": filename})
    except Exception as e:
        return jsonify({"error": f"배경음악 업로드 중 오류: {e}"}), 500


@content_factory_bp.route("/api/generate-audio", methods=["POST"])
def generate_audio_route():
    """대본 텍스트를 TTS 음성 파일(mp3)로 변환합니다. 6단계 '더빙 넣기'용."""
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    voice_label = (data.get("voice") or "").strip()
    speed = data.get("speed")

    if not text:
        return jsonify({"error": "변환할 대본이 없습니다. 4단계 쇼츠 대본이나 원본 글을 먼저 만들어 주세요."}), 400

    voice = VOICE_MAP.get(voice_label, "nova")
    speed = safe_float(speed, default=1.0, minimum=0.9, maximum=1.5)

    # OpenAI TTS는 한 번 호출에 4096자까지만 받으므로 너무 길면 앞부분만 사용합니다.
    text = text[:4000]

    try:
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
            speed=speed,
        )
        filename = f"content_factory_tts_{int(datetime.utcnow().timestamp() * 1000)}.mp3"
        output_path = MEDIA_DIR / filename
        response.stream_to_file(str(output_path))

        duration = media_duration_seconds(output_path)
        return jsonify({"url": f"/media/{filename}", "duration": duration})
    except Exception as e:
        return jsonify({"error": f"음성 생성 중 오류: {e}"}), 500


@content_factory_bp.route("/api/render-video", methods=["POST"])
def render_video_route():
    """5단계에서 고른 이미지들 + TTS 음성(+선택: 배경음악)을 합쳐서
    세로(9:16) 숏폼 영상(mp4)을 만듭니다. 6단계 '숏폼 영상 초안 만들기' 버튼용.

    기존 운세 릴스 생성 로직과 같은 방식(ffmpeg concat + faststart)을 쓰되,
    화면 비율은 다이아몬드로 늘어지지 않도록 ImageOps.pad로 여백을 채웁니다.
    """
    data = request.get_json(force=True, silent=True) or {}
    image_urls = data.get("images") or []
    audio_url = (data.get("audioUrl") or "").strip()
    bgm_filename = (data.get("bgmFilename") or "").strip()
    bgm_volume = data.get("bgmVolume")

    image_filenames = [u.rsplit("/", 1)[-1] for u in image_urls if u]
    if not image_filenames:
        return jsonify({"error": "선택된 이미지가 없습니다. 5단계에서 이미지를 먼저 만들고 선택해 주세요."}), 400

    for filename in image_filenames:
        if not (MEDIA_DIR / filename).exists():
            return jsonify({"error": f"이미지 파일을 찾을 수 없습니다: {filename}"}), 400

    audio_path = None
    if audio_url:
        audio_filename = audio_url.rsplit("/", 1)[-1]
        audio_path = MEDIA_DIR / audio_filename
        if not audio_path.exists():
            return jsonify({"error": "음성 파일을 찾을 수 없습니다. 음성을 다시 만들어 주세요."}), 400
        try:
            narration_seconds = media_duration_seconds(audio_path)
        except Exception as e:
            return jsonify({"error": f"음성 길이를 읽지 못했습니다: {e}"}), 500
        seconds_per_image = max(narration_seconds / len(image_filenames), 1.0)
    else:
        # 더빙 없이 만들 때는 기존 운세 릴스와 같은 방식으로 이미지당 3.5초 고정
        seconds_per_image = 3.5

    target_size = (1080, 1920)

    try:
        ffmpeg = ffmpeg_binary()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            resized_paths = []
            for index, filename in enumerate(image_filenames):
                with Image.open(MEDIA_DIR / filename) as img:
                    # 비율을 유지하면서 여백을 채워 이미지가 다이아몬드로 늘어지지 않게 합니다.
                    fitted = ImageOps.pad(img.convert("RGB"), target_size, color=(0, 0, 0))
                    resized_path = tmp_path / f"frame_{index:02d}.png"
                    fitted.save(resized_path, "PNG")
                resized_paths.append(resized_path)

            list_path = tmp_path / "list.txt"
            with open(list_path, "w") as f:
                for p in resized_paths:
                    f.write(f"file '{p.name}'\n")
                    f.write(f"duration {seconds_per_image:.3f}\n")
                # ffmpeg concat 방식은 마지막 파일을 한 번 더 적어줘야 마지막 장면이 온전히 보입니다.
                f.write(f"file '{resized_paths[-1].name}'\n")

            silent_video_path = tmp_path / "silent.mp4"
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "concat", "-safe", "0", "-i", str(list_path),
                    "-vsync", "cfr", "-r", "24",
                    "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                    "-threads", "1",
                    str(silent_video_path),
                ],
                check=True, capture_output=True, timeout=120,
            )

            output_filename = f"content_factory_video_{int(datetime.utcnow().timestamp() * 1000)}.mp4"
            output_path = MEDIA_DIR / output_filename

            has_bgm = bool(bgm_filename) and (MEDIA_DIR / bgm_filename).exists()
            # 더빙이 없으면 무음 트랙(anullsrc)을 음성 자리에 대신 넣습니다.
            voice_input = ["-i", str(audio_path)] if audio_path else [
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"
            ]

            if has_bgm:
                bgm_path = MEDIA_DIR / bgm_filename
                bgm_volume = safe_float(bgm_volume, default=0.16, minimum=0.02, maximum=1.0)
                filter_complex = (
                    "[1:a]volume=1.0,aresample=44100,"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo[voice];"
                    f"[2:a]volume={bgm_volume:.3f},aresample=44100,"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo[bgm];"
                    "[voice][bgm]amix=inputs=2:duration=first:"
                    "dropout_transition=2,alimiter=limit=0.95[outa]"
                )
                cmd = [
                    ffmpeg, "-y",
                    "-i", str(silent_video_path),
                    *voice_input,
                    "-stream_loop", "-1", "-i", str(bgm_path),
                    "-filter_complex", filter_complex,
                    "-map", "0:v:0", "-map", "[outa]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart",
                    str(output_path),
                ]
            else:
                cmd = [
                    ffmpeg, "-y",
                    "-i", str(silent_video_path),
                    *voice_input,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart",
                    str(output_path),
                ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                return jsonify({"error": "영상 합성 실패: " + result.stderr[-1500:]}), 500

        return jsonify({"url": f"/media/{output_filename}"})
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", "ignore") if isinstance(e.stderr, bytes) else str(e.stderr)
        return jsonify({"error": "영상 합성 중 오류: " + stderr[-1500:]}), 500
    except Exception as e:
        return jsonify({"error": f"영상 합성 중 오류: {e}"}), 500
