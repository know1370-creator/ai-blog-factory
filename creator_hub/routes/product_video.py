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
import re
import subprocess
import tempfile
import textwrap
import uuid
from pathlib import Path
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from openai import OpenAI
from google import genai
from google.genai import types as genai_types
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

# ffmpeg/음성 관련 헬퍼는 legacy_app.py에 이미 있는 것을 그대로 재사용합니다.
from ..legacy_app import (
    MEDIA_DIR, BASE_DIR,
    ffmpeg_binary, media_duration_seconds, safe_float,
    allowed_bgm_file, MAX_BGM_BYTES,
    ensure_bundled_korean_font,
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
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}

# 대본에서 "장면 N: 대사" 패턴을 기준으로 대사를 나눕니다.
SCENE_MARKER_RE = re.compile(r"(?:^|\n)\s*장면\s*\d+[^:\n：]*[:：]\s*")


def parse_scene_lines(script_text):
    """대본 텍스트를 장면별 대사 목록으로 쪼갭니다. 장면 표시가 없으면
    통째로 한 장면짜리 목록으로 취급합니다."""
    text = (script_text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in SCENE_MARKER_RE.split(text) if p.strip()]
    return parts if parts else [text]


def wrap_caption(text, width=15, max_lines=3):
    """자막이 화면 폭을 안 넘게 줄바꿈합니다."""
    if not text:
        return ""
    lines = textwrap.wrap(text, width=width, break_long_words=True)
    return "\n".join(lines[:max_lines])


def extract_hook_line(text, max_chars=32):
    """대본의 첫 장면 대사에서 짧은 후킹 한 줄만 뽑아냅니다."""
    if not text:
        return ""
    first_sentence = re.split(r"(?<=[.!?？！])\s", text.strip())[0]
    return first_sentence[:max_chars]


def get_korean_font_path():
    """자막에 쓸 한글 폰트 파일 경로를 찾습니다. legacy_app에서 이미
    검증된 폰트 다운로드/탐색 로직을 그대로 재사용합니다."""
    ensure_bundled_korean_font()
    candidates = [
        BASE_DIR / "static" / "fonts" / "NanumGothic-Bold.ttf",
        Path("/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf"),
        BASE_DIR / "static" / "fonts" / "NanumBarunGothicBold.ttf",
        BASE_DIR / "static" / "fonts" / "NotoSansKR-Bold.ttf",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


# Veo(AI 영상 생성) 관련 설정
VEO_MODEL_MAP = {
    "lite": "veo-3.1-lite-generate-preview",
    "fast": "veo-3.1-fast-generate-preview",
    "standard": "veo-3.1-generate-preview",
}
# 진행 중인 Veo 작업을 메모리에 잠깐 보관합니다 (서버가 재시작되면 사라짐).
VEO_JOBS = {}

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


@product_video_bp.route("/api/generate-veo-clip", methods=["POST"])
def generate_veo_clip_route():
    """Veo(AI 영상 생성 모델)에게 사진 한 장을 보고 움직이는 영상을 만들어달라고
    요청합니다. 실제 영상 생성은 1~3분 정도 걸리므로, 여기서는 작업을 시작만
    시키고 job_id를 돌려줍니다. 진행 상태는 /api/veo-status/<job_id>로 확인하세요.

    비용 주의: 나노바나나(이미지)와는 비교가 안 되게 비쌉니다.
    (라이트 8초 기준 약 500~800원, 고화질은 4천원대까지도 갑니다.)
    """
    data = request.get_json(force=True, silent=True) or {}
    image_url = (data.get("imageUrl") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    tier = (data.get("tier") or "fast").strip()
    duration = data.get("durationSeconds") or 8
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 8
    if duration not in (4, 6, 8):
        duration = 8

    if not image_url:
        return jsonify({"error": "먼저 기준이 될 사진을 골라주세요."}), 400

    image_filename = image_url.rsplit("/", 1)[-1]
    image_path = MEDIA_DIR / image_filename
    if not image_path.exists():
        return jsonify({"error": "이미지 파일을 찾을 수 없습니다."}), 400

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({"error": "Render 환경변수에 GEMINI_API_KEY가 없습니다."}), 500

    model_id = VEO_MODEL_MAP.get(tier, VEO_MODEL_MAP["fast"])

    try:
        gclient = genai.Client(api_key=api_key)
        veo_image = genai_types.Image.from_file(str(image_path))
        operation = gclient.models.generate_videos(
            model=model_id,
            prompt=prompt or "이 제품 사진을 자연스럽게 움직이는 짧은 홍보 영상으로 만들어줘",
            image=veo_image,
            config=genai_types.GenerateVideosConfig(
                number_of_videos=1,
                duration_seconds=duration,
                aspect_ratio="9:16",
            ),
        )
        job_id = uuid.uuid4().hex
        VEO_JOBS[job_id] = {
            "client": gclient,
            "operation": operation,
            "status": "pending",
            "url": None,
            "error": None,
        }
        return jsonify({"jobId": job_id})
    except Exception as e:
        return jsonify({"error": f"AI 영상 생성 요청 중 오류: {e}"}), 500


@product_video_bp.route("/api/veo-status/<job_id>")
def veo_status_route(job_id):
    """Veo 작업 진행 상태를 확인합니다. 프론트엔드가 몇 초마다 이 주소를 다시 호출합니다."""
    job = VEO_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "작업을 찾을 수 없습니다. 다시 시도해 주세요."}), 404

    if job["status"] == "done":
        return jsonify({"status": "done", "url": job["url"]})
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job["error"]})

    try:
        gclient = job["client"]
        operation = gclient.operations.get(job["operation"])
        job["operation"] = operation
        if not operation.done:
            return jsonify({"status": "pending"})

        generated_video = operation.response.generated_videos[0]
        gclient.files.download(file=generated_video.video)
        filename = f"product_video_veo_{int(datetime.utcnow().timestamp() * 1000)}.mp4"
        output_path = MEDIA_DIR / filename
        generated_video.video.save(str(output_path))

        job["status"] = "done"
        job["url"] = f"/media/{filename}"
        return jsonify({"status": "done", "url": job["url"]})
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        return jsonify({"status": "error", "error": str(e)})


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
    """사진들 + 더빙(+선택: 배경음악)을 합쳐서 세로(9:16) 제품 홍보 영상(mp4)을 만듭니다.
    대본이 함께 오면, 후킹 문구 인트로(2초)와 흰색 글씨+검은 테두리 자막을 자동으로 넣습니다."""
    data = request.get_json(force=True, silent=True) or {}
    image_urls = data.get("images") or []
    audio_url = (data.get("audioUrl") or "").strip()
    bgm_filename = (data.get("bgmFilename") or "").strip()
    bgm_volume = data.get("bgmVolume")
    script_text = (data.get("script") or "").strip()

    image_filenames = [u.rsplit("/", 1)[-1] for u in image_urls if u]
    if not image_filenames:
        return jsonify({"error": "사진을 먼저 준비해 주세요 (업로드 또는 AI 생성)."}), 400

    for filename in image_filenames:
        if not (MEDIA_DIR / filename).exists():
            return jsonify({"error": f"이미지 파일을 찾을 수 없습니다: {filename}"}), 400

    scene_lines = parse_scene_lines(script_text)
    hook_text = extract_hook_line(scene_lines[0]) if scene_lines else ""
    font_path = get_korean_font_path() if (scene_lines or hook_text) else None

    audio_path = None
    # Veo로 만든 영상 클립은 고유 재생 길이가 있으므로, 나머지 "사진"들에만
    # 대본 길이를 나눠서 적용합니다.
    static_image_count = sum(
        1 for f in image_filenames if (MEDIA_DIR / f).suffix.lower() not in VIDEO_EXTENSIONS
    )
    if audio_url:
        audio_filename = audio_url.rsplit("/", 1)[-1]
        audio_path = MEDIA_DIR / audio_filename
        if not audio_path.exists():
            return jsonify({"error": "음성 파일을 찾을 수 없습니다. 음성을 다시 만들어 주세요."}), 400
        try:
            narration_seconds = media_duration_seconds(audio_path)
        except Exception as e:
            return jsonify({"error": f"음성 길이를 읽지 못했습니다: {e}"}), 500
        seconds_per_image = max(narration_seconds / static_image_count, 1.0) if static_image_count else 3.5
    else:
        # 더빙 없이 만들 때는 이미지당 3.5초 고정
        seconds_per_image = 3.5

    target_size = (1080, 1920)
    fps = 24
    intro_seconds = 2
    # 케번즈(줌인) 효과를 넣기 위해, 실제 출력 크기보다 크게 캔버스를 잡아서
    # 확대해도 빈 여백이 안 생기게 합니다.
    zoom_canvas = (int(target_size[0] * 1.15), int(target_size[1] * 1.15))

    def caption_filter_suffix(tmp_path, index, box_bottom_margin=260):
        """이 장면(index)에 넣을 자막 drawtext 필터 문자열을 만듭니다.
        자막이 없거나 폰트를 못 찾으면 빈 문자열을 돌려줍니다."""
        if not font_path or not scene_lines:
            return ""
        caption_text = wrap_caption(scene_lines[index % len(scene_lines)])
        if not caption_text:
            return ""
        caption_path = tmp_path / f"caption_{index:02d}.txt"
        caption_path.write_text(caption_text, encoding="utf-8")
        return (
            f",drawtext=fontfile='{font_path}':textfile='{caption_path}':"
            "fontcolor=white:fontsize=50:bordercolor=black:borderw=4:"
            f"line_spacing=10:x=(w-text_w)/2:y=h-{box_bottom_margin}"
        )

    try:
        ffmpeg = ffmpeg_binary()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 1) 장면마다 짧은 영상 클립을 하나씩 만듭니다.
            #    - AI(Veo)로 만든 영상은 화면 비율만 맞춰서 그대로 사용
            #    - 일반 사진은 천천히 확대되는 케번즈 효과를 넣어서 사용
            #    - 대본이 있으면 각 장면 대사를 흰색 글씨+검은 테두리 자막으로 붙임
            segment_paths = []
            for index, filename in enumerate(image_filenames):
                file_path = MEDIA_DIR / filename
                segment_path = tmp_path / f"segment_{index:02d}.mp4"
                caption_suffix = caption_filter_suffix(tmp_path, index)

                if file_path.suffix.lower() in VIDEO_EXTENSIONS:
                    subprocess.run(
                        [
                            ffmpeg, "-y",
                            "-i", str(file_path),
                            "-vf", (
                                f"scale={target_size[0]}:{target_size[1]}:"
                                "force_original_aspect_ratio=increase,"
                                f"crop={target_size[0]}:{target_size[1]},fps={fps}"
                                + caption_suffix
                            ),
                            "-an",
                            "-pix_fmt", "yuv420p",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                            "-threads", "1",
                            str(segment_path),
                        ],
                        check=True, capture_output=True, timeout=180,
                    )
                else:
                    with Image.open(file_path) as img:
                        fitted = ImageOps.pad(img.convert("RGB"), zoom_canvas, color=(0, 0, 0))
                        frame_path = tmp_path / f"frame_{index:02d}.png"
                        fitted.save(frame_path, "PNG")

                    frame_count = max(int(round(seconds_per_image * fps)), 1)
                    zoompan_filter = (
                        f"zoompan=z='min(zoom+0.0012,1.12)':d={frame_count}:"
                        f"s={target_size[0]}x{target_size[1]}:fps={fps}"
                        + caption_suffix
                    )
                    subprocess.run(
                        [
                            ffmpeg, "-y",
                            "-i", str(frame_path),
                            "-vf", zoompan_filter,
                            "-pix_fmt", "yuv420p",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                            "-threads", "1",
                            str(segment_path),
                        ],
                        check=True, capture_output=True, timeout=90,
                    )
                segment_paths.append(segment_path)

            # 1-1) 후킹 문구 인트로(2초)를 맨 앞에 붙입니다: 첫 장면의 첫 프레임을
            #      썸네일처럼 정지시켜 놓고, 그 위에 후킹 한 줄을 크게 띄웁니다.
            intro_added = False
            if hook_text and font_path and segment_paths:
                intro_frame_path = tmp_path / "intro_frame.png"
                subprocess.run(
                    [ffmpeg, "-y", "-i", str(segment_paths[0]), "-vframes", "1", str(intro_frame_path)],
                    check=True, capture_output=True, timeout=30,
                )
                hook_caption_path = tmp_path / "hook.txt"
                hook_caption_path.write_text(wrap_caption(hook_text, width=13, max_lines=2), encoding="utf-8")

                intro_path = tmp_path / "intro.mp4"
                intro_filter = (
                    f"fps={fps},drawtext=fontfile='{font_path}':textfile='{hook_caption_path}':"
                    "fontcolor=white:fontsize=64:bordercolor=black:borderw=6:"
                    "line_spacing=14:x=(w-text_w)/2:y=(h-text_h)/2"
                )
                subprocess.run(
                    [
                        ffmpeg, "-y",
                        "-loop", "1", "-i", str(intro_frame_path), "-t", str(intro_seconds),
                        "-vf", intro_filter,
                        "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                        "-threads", "1",
                        str(intro_path),
                    ],
                    check=True, capture_output=True, timeout=60,
                )
                segment_paths = [intro_path] + segment_paths
                intro_added = True

            # 2) 클립들을 순서대로 이어붙입니다.
            list_path = tmp_path / "list.txt"
            with open(list_path, "w") as f:
                for p in segment_paths:
                    f.write(f"file '{p.name}'\n")

            silent_video_path = tmp_path / "silent.mp4"
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "concat", "-safe", "0", "-i", str(list_path),
                    "-c", "copy",
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
            # 인트로를 붙였으면, 내레이션도 그만큼(2초) 늦게 시작해야 인트로 화면과
            # 겹치지 않고 자연스럽게 이어집니다.
            voice_delay_ms = intro_seconds * 1000 if intro_added else 0

            if has_bgm:
                bgm_path = MEDIA_DIR / bgm_filename
                bgm_volume = safe_float(bgm_volume, default=0.16, minimum=0.02, maximum=1.0)
                filter_complex = (
                    f"[1:a]volume=1.0,adelay={voice_delay_ms}|{voice_delay_ms},"
                    "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[voice];"
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
                filter_complex = f"[1:a]adelay={voice_delay_ms}|{voice_delay_ms}[outa]"
                cmd = [
                    ffmpeg, "-y",
                    "-i", str(silent_video_path),
                    *voice_input,
                    "-filter_complex", filter_complex,
                    "-map", "0:v:0", "-map", "[outa]",
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
