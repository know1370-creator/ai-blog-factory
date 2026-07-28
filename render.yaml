# MI Creator Hub V4

이번 버전에서 실제로 되는 기능:

- 키워드로 한국어 SEO 블로그 초안 생성
- 제목, 메타 설명, HTML 본문 수정 및 미리보기
- Google OAuth로 Blogger 연결
- 내 Blogger 목록 자동 불러오기
- 선택한 Blogger에 초안 또는 공개 발행

## Render 환경변수

필수:

- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `SECRET_KEY`

선택:

- `OPENAI_TEXT_MODEL` 기본값 `gpt-4.1-mini`
- `GOOGLE_REDIRECT_URI` 기본값은 현재 사이트의 `/oauth2callback`
- `DB_PATH` 기본값 `/tmp/mi_creator_hub.db`

## Render 명령어

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

## Google Cloud 리디렉션 URI

현재 Render 주소가 `https://ai-blog-factory.onrender.com`이라면:

`https://ai-blog-factory.onrender.com/oauth2callback`

## 주의

기본 DB는 `/tmp`라 Render가 재시작되면 글과 Google 연결이 초기화될 수 있습니다. 기능 테스트가 끝난 뒤 Render Disk 또는 외부 DB를 붙이는 V4.1 단계로 업그레이드합니다.
