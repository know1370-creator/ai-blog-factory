"""
제품 홍보 영상 제작기 (제품 정보 -> 대본 -> 사진 -> 더빙 -> 영상)

"콘텐츠 공장"(블로그용, /content-factory/)과는 완전히 별개의 독립 도구입니다.
쿠팡/스마트스토어 등에서 파는 제품 하나를 입력하면 아래 순서로 진행됩니다:

  1) 제품 정보 입력 -> 홍보 대본 자동 생성 (텍스트, OpenAI)
  2) 사진 준비
       - 직접 업로드: 실제 제품 사진을 그대로 사용 (비용 없음, 기본 추천)
       - AI로 새로 생성: 나노바나나(Gemini 2.5 Flash Image)로 장면 생성 (호출당 비용 발생)
  3) 더빙(TTS) 생성 (OpenAI TTS)
  4) 사진 + 더빙(+선택: 배경음악)을 합쳐 세로(9:16) 숏폼 영상 제작 (ffmpeg)

파일 위치: creator_hub/routes/product_video.py

* requirements.txt는 그대로 사용 가능합니다 (openai, Pillow, imageio-ffmpeg,
  google-genai 모두 content_factory에서 이미 추가되어 있어야 함).
* Render 환경변수에 GEMINI_API_KEY가 있어야 "AI로 새로 생성" 기능이 동작합니다
  (직접 업로드만 쓸 거라면 없어도 됩니다).
"""

import os
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from openai import OpenAI
from google import genai
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

# ffmpeg/음성 관련 헬퍼는 legacy_app.py에 이미 있는 것을 그대로 재사용합니다.
from ..legacy_app import (
    MEDIA_DIR,
    ffmpeg_binary, media_duration_seconds, safe_float,
    allowed_bgm_file, MAX_BGM_BYTES,
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TEXT_MODEL = "gpt-4o-mini"
IMAGE_MODEL = "gemini-2.5-flash-image"  # 나노바나나
TTS_MODEL = "tts-1"

VOICE_MAP = {
    "차분한 여성 (기본)": "nova",
    "밝은 여성": "shimmer",
    "차분한 남성": "onyx",
    "신뢰감 있는 남성": "echo",
}

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024

product_video_bp = Blueprint(
    "product_video", __name__, url_prefix="/product-video"
)


@product_video_bp.route("/")
def index():
    return render_template("product_video.html")


@product_video_bp.route("/api/generate-script", methods=["POST"])
def generate_script_route():
    """제품명·설명으로 30초 안팎의 홍보 대본을 생성합니다."""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    desc = (data.get("description") or "").strip()

    if not name:
        return jsonify({"error": "제품명을 입력하세요."}), 400

    prompt = (
        "너는 쇼츠·릴스용 제품 홍보 대본을 쓰는 카피라이터야.\n"
        f"제품명: {name}\n"
    )
    if desc:
        prompt += f"제품 설명: {desc}\n"
    prompt += (
        "조건: 30초 안팎 분량, '장면 N: 내레이션 대사' 형식으로 4~5개 장면을 만들어줘. "
        "첫 장면은 3초 안에 시선을 끄는 훅(문제 제기나 놀라운 사실)으로 시작하고, "
        "마지막 장면은 구매를 유도하는 CTA로 끝내줘. 과장 광고 문구(효과 보장, "
        "최고, 무조건 등)는 피하고, 친근한 구어체로 자연스럽게 써줘. "
        "화면 지시나 괄호 설명 없이 실제로 읽을 대사만 순서대로 적어줘."
    )

    try:
        resp = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            temperature=0.8,
        )
        text = resp.choices[0].message.content.strip()
        return jsonify({"result": text})
    except Exception as e:
        return jsonify({"error": f"대본 생성 중 오류: {e}"}), 500


@product_video_bp.route("/api/upload-image", methods=["POST"])
def upload_image_route():
    """실제 제품 사진을 그대로 업로드합니다. AI 호출이 없어 비용이 들지 않습니다."""
    file_storage = request.files.get("image")
    if not file_storage or not file_storage.filename:
        return jsonify({"error": "업로드할 이미지가 없습니다."}), 400

    safe_name = secure_filename(file_storage.filename)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if extension not in ALLOWED_IMAGE_EXT:
        return jsonify({"error": "PNG, JPG, WEBP 파일만 업로드할 수 있습니다."}), 400

    try:
        raw_bytes = file_storage.read()
        if not raw_bytes:
            return jsonify({"error": "업로드한 파일이 비어 있습니다."}), 400
        if len(raw_bytes) > MAX_IMAGE_BYTES:
            return jsonify({"error": "이미지 파일은 15MB 이하만 업로드할 수 있습니다."}), 400

        filename = f"product_video_upload_{int(datetime.utcnow().timestamp() * 1000)}.{extension}"
        output_path = MEDIA_DIR / filename
        output_path.write_bytes(raw_bytes)

        # 깨진 파일이 아닌지 확인
        with Image.open(output_path) as img:
            img.verify()

        return jsonify({"url": f"/media/{filename}"})
    except Exception as e:
        return jsonify({"error": f"이미지 업로드 중 오류: {e}"}), 500


@product_video_bp.route("/api/generate-image", methods=["POST"])
def generate_image_route():
    """나노바나나(Gemini 2.5 Flash Image)로 새 제품 장면 이미지를 생성합니다.
    호출될 때마다 비용이 발생하므로, 실제 사진이 없을 때만 사용하세요."""
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

        filename = f"product_video_ai_{int(datetime.utcnow().timestamp() * 1000)}.png"
        (MEDIA_DIR / filename).write_bytes(image_bytes)
        return jsonify({"url": f"/media/{filename}"})
    except Exception as e:
        return jsonify({"error": f"이미지 생성 중 오류: {e}"}), 500


@product_video_bp.route("/api/upload-bgm", methods=["POST"])
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

        filename = f"product_video_bgm_{int(datetime.utcnow().timestamp() * 1000)}.{extension}"
        output_path = MEDIA_DIR / filename
        output_path.write_bytes(raw_bytes)
        media_duration_seconds(output_path)  # 정상 오디오인지 확인

        return jsonify({"filename": filename})
    except Exception as e:
        return jsonify({"error": f"배경음악 업로드 중 오류: {e}"}), 500


@product_video_bp.route("/api/generate-audio", methods=["POST"])
def generate_audio_route():
    """대본 텍스트를 TTS 음성 파일(mp3)로 변환합니다."""
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    voice_label = (data.get("voice") or "").strip()
    speed = data.get("speed")

    if not text:
        return jsonify({"error": "변환할 대본이 없습니다. 대본을 먼저 만들어 주세요."}), 400

    voice = VOICE_MAP.get(voice_label, "nova")
    speed = safe_float(speed, default=1.0, minimum=0.9, maximum=1.5)
    text = text[:4000]

    try:
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
            speed=speed,
        )
        filename = f"product_video_tts_{int(datetime.utcnow().timestamp() * 1000)}.mp3"
        output_path = MEDIA_DIR / filename
        response.stream_to_file(str(output_path))

        duration = media_duration_seconds(output_path)
        return jsonify({"url": f"/media/{filename}", "duration": duration})
    except Exception as e:
        return jsonify({"error": f"음성 생성 중 오류: {e}"}), 500


@product_video_bp.route("/api/render-video", methods=["POST"])
def render_video_route():
    """사진들 + 더빙(+선택: 배경음악)을 합쳐서 세로(9:16) 제품 홍보 영상(mp4)을 만듭니다."""
    data = request.get_json(force=True, silent=True) or {}
    image_urls = data.get("images") or []
    audio_url = (data.get("audioUrl") or "").strip()
    bgm_filename = (data.get("bgmFilename") or "").strip()
    bgm_volume = data.get("bgmVolume")

    image_filenames = [u.rsplit("/", 1)[-1] for u in image_urls if u]
    if not image_filenames:
        return jsonify({"error": "사진을 먼저 준비해 주세요 (업로드 또는 AI 생성)."}), 400

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
        # 더빙 없이 만들 때는 이미지당 3.5초 고정
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

            output_filename = f"product_video_{int(datetime.utcnow().timestamp() * 1000)}.mp4"
            output_path = MEDIA_DIR / output_filename

            has_bgm = bool(bgm_filename) and (MEDIA_DIR / bgm_filename).exists()
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
