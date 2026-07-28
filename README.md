# MI Creator Hub V4.1

V4 기능에 **AI 썸네일 자동 생성**을 추가한 버전입니다.

## 새 기능

- 글 수정 화면에서 썸네일 문구 입력
- 분위기 선택 후 AI 가로형 대표 이미지 생성
- 썸네일 미리보기 및 크게 보기
- Blogger 발행 시 생성된 이미지를 본문 맨 위에 자동 삽입
- 긴 AI 작업을 위해 Gunicorn 타임아웃 300초 설정용 `Procfile` 포함

## Render 환경변수

필수:

- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `SECRET_KEY`

선택:

- `OPENAI_TEXT_MODEL` 기본값 `gpt-4.1-mini`
- `OPENAI_IMAGE_MODEL` 기본값 `gpt-image-1`
- `GOOGLE_REDIRECT_URI`
- `DB_PATH` 기본값 `/tmp/mi_creator_hub.db`
- `MEDIA_DIR` 기본값 `/tmp/mi_creator_hub_media`

## Render 설정

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --timeout 300`

GitHub에 `Procfile`을 올려도 기존 Render Start Command가 따로 지정되어 있으면 Render 설정값이 우선할 수 있습니다. 그 경우 Start Command를 위 명령으로 직접 바꿔 주세요.

## 주의

현재 기본 DB와 이미지는 Render의 `/tmp`에 저장되므로 서비스가 재시작되면 사라질 수 있습니다. 기능 확인 후 영구 저장소를 붙이는 다음 버전으로 확장하는 것이 좋습니다.
