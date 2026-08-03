"""
SQLite -> PostgreSQL 데이터 이전 스크립트

사용 시점: Render에서 PostgreSQL 데이터베이스를 새로 만들고,
지금까지 SQLite에 쌓아둔 글/기록을 그대로 옮기고 싶을 때 딱 한 번 실행합니다.

사용 방법:
1. Render 대시보드에서 PostgreSQL 인스턴스를 만들고 "External Database URL"을 복사해둡니다.
   (반드시 External URL을 쓰세요 — Internal URL은 Render 서버 밖에서는 접속이 안 됩니다.)
2. 이 스크립트와 같은 폴더에 있는 creator.db 파일이 최신 상태인지 확인합니다.
   (Codespace/로컬에 최신 creator.db가 없다면, Render 서비스의 Shell 탭에서
   이 스크립트를 실행하는 것이 제일 확실합니다 — 그러면 운영 중인 최신 SQLite
   파일을 그대로 쓸 수 있습니다.)
3. 터미널에서 실행:

   pip install psycopg2-binary --break-system-packages
   python migrate_sqlite_to_postgres.py "postgresql://사용자:비밀번호@호스트/DB이름"

4. 마이그레이션이 끝나면, Render 웹 서비스의 환경변수 DATABASE_URL에
   같은 Postgres 주소를 등록하고 서버를 재배포합니다.
   그 순간부터 앱은 SQLite 대신 Postgres를 사용하게 됩니다.

주의:
- 이 스크립트는 "복사"만 합니다. 원본 SQLite 파일은 건드리지 않으니,
  옮긴 뒤에도 실수 대비용으로 당분간 보관해두세요.
- 이미 Postgres에 데이터가 있는 상태에서 다시 실행하면 중복이 생길 수 있으니,
  Postgres가 완전히 비어있는 상태에서 한 번만 실행하는 것을 권장합니다.
"""

import sys
from pathlib import Path

import sqlalchemy
from sqlalchemy import create_engine, inspect, text


def main():
    if len(sys.argv) < 2:
        print("사용법: python migrate_sqlite_to_postgres.py <postgres-url>")
        sys.exit(1)

    postgres_url = sys.argv[1]
    if postgres_url.startswith("postgres://"):
        postgres_url = postgres_url.replace("postgres://", "postgresql://", 1)

    sqlite_path = Path(__file__).resolve().parent / "creator.db"
    if not sqlite_path.exists():
        print(f"SQLite 파일을 찾을 수 없습니다: {sqlite_path}")
        print("이 스크립트를 creator.db가 있는 폴더에서 실행해 주세요.")
        sys.exit(1)

    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    postgres_engine = create_engine(postgres_url)

    # legacy_app.py 등에서 정의한 모델들이 먼저 create_all()로 Postgres에
    # 테이블을 만들어둔 상태여야 합니다(서버를 Postgres로 한 번 띄우면
    # ensure_schema()가 자동으로 만들어줍니다). 여기서는 이미 존재하는
    # 테이블에 데이터만 복사합니다.
    sqlite_inspector = inspect(sqlite_engine)
    postgres_inspector = inspect(postgres_engine)

    sqlite_tables = set(sqlite_inspector.get_table_names())
    postgres_tables = set(postgres_inspector.get_table_names())
    common_tables = sqlite_tables & postgres_tables

    if not common_tables:
        print(
            "Postgres 쪽에 아직 테이블이 없어요. 먼저 DATABASE_URL을 이 "
            "Postgres 주소로 설정한 상태로 서버를 한 번 켰다 꺼서 테이블을 "
            "만들어준 다음, 이 스크립트를 다시 실행해 주세요."
        )
        sys.exit(1)

    print(f"옮길 테이블 {len(common_tables)}개 발견: {', '.join(sorted(common_tables))}")

    with sqlite_engine.connect() as sqlite_conn, postgres_engine.connect() as postgres_conn:
        for table_name in sorted(common_tables):
            rows = sqlite_conn.execute(text(f"SELECT * FROM {table_name}")).mappings().all()
            if not rows:
                print(f"  - {table_name}: 옮길 데이터 없음")
                continue

            columns = rows[0].keys()
            postgres_table = sqlalchemy.Table(
                table_name, sqlalchemy.MetaData(), autoload_with=postgres_engine
            )

            with postgres_conn.begin():
                for row in rows:
                    values = {col: row[col] for col in columns}
                    postgres_conn.execute(postgres_table.insert().values(**values))

            print(f"  - {table_name}: {len(rows)}개 행 복사 완료")

    print("\n마이그레이션 완료! Render 환경변수 DATABASE_URL을 이 Postgres 주소로")
    print("등록하고 서버를 재배포하면 앞으로 이 데이터베이스를 사용합니다.")


if __name__ == "__main__":
    main()
