# ⚔️ 롤옥션 (LoL Auction)

내전(custom game) 팀 구성을 위한 실시간 선수 경매 웹앱입니다. 팀장 두 명이 포인트를 걸고 번갈아 입찰하는 방식으로 10명을 공정하게 2팀으로 나누고, 라이엇 API 기반 자동 밸런싱 모드도 함께 제공합니다.

---

## ✨ 주요 기능

### 1. 실시간 경매 드래프트
- 방장이 참가자 10명 + 양팀 팀장을 등록하면 자동으로 경매 풀 구성
- 블루/레드 팀장이 보유 포인트(기본 100pt) 내에서 번갈아 입찰, 상대가 포기하면 그 시점 입찰가로 낙찰
- 라운드마다 선입찰 팀이 교대되어 유불리를 완화
- 동시 접속자 전원(양 팀장 + 관전자)에게 WebSocket으로 상태를 브로드캐스트, 입찰 타이머·포기·유찰(맨 뒤로 이동)까지 서버가 판정

### 2. 진행 편의 기능
- 타이머 일시정지/재개 (화장실 등 긴급 상황 대응)
- 경매 종료 후 팀 간 선수 트레이드
- 서버 재시작 시 진행 중이던 방 상태를 JSON 스냅샷에서 복구 (경매 중이던 라운드는 안전하게 초기화 후 일시정지)
- 1시간 이상 비어 있는 방은 자동 정리

### 3. 라이엇 API 자동 밸런싱 모드
- 참가자의 라이엇ID(`게임명#태그`)로 솔로랭크 티어·LP·최근 주 포지션을 자동 조회
- 티어+LP를 단일 실력 점수로 환산 후, 10명을 5:5로 나누는 126가지(₁₀C₄ 절반) 조합을 모두 계산해 **포지션 불일치가 가장 적고, 그 안에서 팀 간 실력 차가 가장 작은 조합**을 자동 추천
- 개인 API 키의 초당/2분당 레이트리밋을 넘지 않도록 자체 레이트 리미터로 요청을 페이싱, 결과는 30분 캐시

---

## 🛠️ 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | Python, FastAPI, WebSocket (`fastapi.WebSocket`), `httpx` |
| Frontend | 단일 정적 페이지(Vanilla JS/CSS), Hextech 스타일 UI |
| 외부 API | Riot Games API (Account-v1, League-v4, Match-v5) |
| 배포 | Railway (`Procfile` + `uvicorn`) |

서버가 방(Room) 상태를 메모리 + JSON 스냅샷으로 직접 관리하는 경량 구조로, 별도 DB 없이 동작합니다.

---

## 📁 프로젝트 구조

```
lol-auction/
├── main.py           # FastAPI 앱 — 방 관리, 경매 상태 머신, WebSocket 핸들러, REST API
├── riot_api.py         # 라이엇 API 클라이언트 (계정/티어/최근 포지션 조회, 레이트리밋, 캐시)
├── balance.py           # 티어 점수화 + 포지션을 고려한 최적 5:5 분할 알고리즘
└── static/index.html    # 프론트엔드 전체 (경매 화면 + 밸런싱 모드 화면)
```

---

## 🚀 로컬 실행

```bash
git clone https://github.com/cen04088/lol-auction.git
cd lol-auction
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt

# .env 생성 후 RIOT_API_KEY 입력 (밸런싱 모드에만 필요)
uvicorn main:app --reload
```

필요한 환경 변수:

```ini
RIOT_API_KEY=your_riot_api_key   # https://developer.riotgames.com 발급, 밸런싱 모드 전용
```

경매 드래프트 기능은 라이엇 API 키 없이도 바로 사용할 수 있습니다.

---

## ☁️ 배포

- **플랫폼:** Railway (`Procfile`: `uvicorn main:app --host 0.0.0.0 --port $PORT`)
