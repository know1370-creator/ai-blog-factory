# MI Creator Hub V5

## 이번 버전 기능

- AI 한국어 SEO 블로그 글 생성
- 제목·메타 설명·본문 HTML 수정
- SEO 점수와 보완 항목 자동 분석
- AI 태그 자동 생성
- GPT 이미지 모델로 실제 썸네일 생성
- PostgreSQL 영구 저장 지원
- Google Blogger OAuth 연결
- Blogger 초안 또는 즉시 공개 발행
- 대표 이미지 자동 삽입

## GitHub에 올릴 파일

기존 저장소에서 아래 파일을 교체하거나 추가하세요.

- `app.py`
- `requirements.txt`
- `Procfile`
- `README.md`

`media` 폴더는 실행 중 자동 생성됩니다.

## Render 환경변수

필수:

- `OPENAI_API_KEY`
- `SECRET_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

권장:

- `DATABASE_URL`
- `OPENAI_MODEL` 기본값: `gpt-5-mini`
- `IMAGE_MODEL` 기본값: `gpt-image-1`

## PostgreSQL 연결

1. Render Dashboard에서 **New → PostgreSQL**을 선택합니다.
2. 데이터베이스를 생성합니다.
3. 생성된 **Internal Database URL**을 복사합니다.
4. 웹 서비스의 Environment에 아래처럼 추가합니다.

```text
DATABASE_URL = 복사한 Internal Database URL
```

앱은 시작 시 필요한 테이블을 자동 생성합니다.

## Google Cloud 설정

1. Google Cloud에서 Blogger API v3를 활성화합니다.
2. OAuth 클라이언트 유형은 **웹 애플리케이션**으로 만듭니다.
3. 승인된 리디렉션 URI에 아래 주소를 정확히 추가합니다.

```text
https://ai-blog-factory.onrender.com/oauth2callback
```

4. Render의 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`에는 반드시 같은 OAuth 클라이언트에서 복사한 값을 넣습니다.

## 배포

GitHub에 파일 업로드 후 Render에서:

```text
Manual Deploy → Deploy latest commit
```

배포 완료 후 `/health`에서 아래 응답이 보이면 정상입니다.

```json
{"status":"ok","version":"5.0"}
```

## 중요한 저장소 안내

PostgreSQL을 연결하면 글 데이터는 배포 후에도 유지됩니다.

현재 생성 이미지 파일은 Render의 로컬 디스크에 저장되므로 재배포 시 사라질 수 있습니다. 글과 썸네일 기록은 유지되지만 이미지까지 영구 보관하려면 다음 버전에서 Cloudinary 또는 S3를 연결하는 것이 안전합니다.
