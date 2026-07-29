# MI Creator Hub V17.1

## 변경 사항
- 기본 주소(`/`) 접속 시 쉬운 홈(`/home/`)으로 즉시 이동
- 상단에 기능 버튼을 전부 늘어놓지 않음
- 상단에는 `홈`과 `☰ 전체 메뉴`만 표시
- 기존 기능은 하나도 삭제하지 않고 전체 메뉴 안에 업무별로 정리
- 모바일에서는 메뉴가 한 줄 목록으로 표시
- 메뉴 창은 화면 높이를 넘으면 내부 스크롤

# MI Creator Hub V17.0

V17.0 is the navigation-stability and usability release.

## Main improvements

### Easy command center
- `/home/`
- Four-step workflow: idea → create → manage → measure
- “What should I do today?” priority list
- Seven-day deadline summary
- Four clear quick actions

### Grouped global navigation
- Content creation
- Operations
- Marketing and business
- Tools

### BuildError prevention
The application validates every navigation endpoint during startup.
If a menu endpoint is missing, startup fails with a clear endpoint list instead of showing users a broken page.

### Corrected endpoints
All V17 navigation links use verified route function names:
- `generator_v12.dashboard`
- `assistant_v92.dashboard`
- `planner_v93.dashboard`
- `calendar_v94.dashboard`
- `library_v11.dashboard`
- `analytics_v95.dashboard`
- `social_v96.dashboard`
- `business_v91.dashboard`
- `manager_v10.dashboard`
- `diagnostics_v95.dashboard`

## Main routes
- `/home/`
- `/factory/`
- `/marketing/`
- `/pipeline/`
- `/library/`
- `/diagnostics/`

## Safety
- No automatic external publishing
- External replies remain approval-only
- No invented products, prices, links, income, statistics, or performance
