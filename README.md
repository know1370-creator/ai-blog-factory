# AI Blog Factory V3 Mobile

휴대폰 업로드를 쉽게 하려고 폴더 없이 4개 파일만 사용합니다.

## Render
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- 필수 환경변수: `OPENAI_API_KEY`
- 선택 환경변수: `OPENAI_TEXT_MODEL=gpt-4.1-mini`

Blogger 자동 발행 연결은 첫 배포 후 `BLOGGER_BLOG_ID`, `BLOGGER_ACCESS_TOKEN`을 추가합니다.
API 키와 토큰은 GitHub 파일에 넣지 말고 Render 환경변수에만 저장하세요.
