"""Riot Games API 클라이언트 — 라이엇ID로 소환사명/솔로랭크 티어·LP/최근 포지션을 조회."""
import os
import time
import asyncio
import httpx

REGIONAL_HOST = "https://asia.api.riotgames.com"   # account-v1, match-v5
PLATFORM_HOST = "https://kr.api.riotgames.com"      # league-v4

TIER_KO = {
    "UNRANKED": "언랭", "IRON": "아이언", "BRONZE": "브론즈", "SILVER": "실버",
    "GOLD": "골드", "PLATINUM": "플래티넘", "EMERALD": "에메랄드", "DIAMOND": "다이아",
    "MASTER": "마스터", "GRANDMASTER": "그랜드마스터", "CHALLENGER": "챌린저",
}

POSITION_KO = {
    "TOP": "탑", "JUNGLE": "정글", "MIDDLE": "미드", "BOTTOM": "원딜", "UTILITY": "서폿",
}

# 포지션 감지용으로 확인할 최근 솔로랭크 게임 수 (많을수록 정확하지만 API 호출이 늘어남)
MATCH_HISTORY_COUNT = 5

# 같은 라이엇ID 재조회 시 API 호출 없이 바로 응답하기 위한 캐시
_CACHE_TTL = 1800  # 30분
_cache: dict[str, tuple[float, dict]] = {}


class _RateLimiter:
    """개인 키 레이트리밋(기본 20req/1s, 100req/2min)을 넘지 않도록 요청을 미리 페이싱한다.
    세마포어는 '동시 요청 수'만 제한할 뿐 '시간당 요청 수'는 제한하지 못해서,
    다수 선수를 병렬 조회하면 순식간에 2분 한도를 넘겨 긴 429 백오프가 겹겹이 쌓이는 문제가 있었다."""
    def __init__(self, limits: list[tuple[int, float]]):
        self._limits = limits
        self._history: dict[float, list[float]] = {window: [] for _, window in limits}
        self._lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self._lock:
                now = time.monotonic()
                wait = 0.0
                for max_req, window in self._limits:
                    hist = self._history[window]
                    while hist and now - hist[0] > window:
                        hist.pop(0)
                    if len(hist) >= max_req:
                        wait = max(wait, window - (now - hist[0]) + 0.02)
                if wait <= 0:
                    for _, window in self._limits:
                        self._history[window].append(now)
                    return
            await asyncio.sleep(wait)


# 실제 한도(20/1s, 100/120s)보다 살짝 여유를 둔다
_LIMITER = _RateLimiter([(18, 1.0), (95, 120.0)])
_SEM = asyncio.Semaphore(6)  # 동시 소켓 수 자체도 과도하게 늘어나지 않도록 보조 제한


def api_key() -> str:
    key = os.environ.get("RIOT_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RIOT_API_KEY 환경변수가 설정되지 않았습니다.")
    return key


async def _get(client: httpx.AsyncClient, url: str) -> dict | None:
    headers = {"X-Riot-Token": api_key()}
    async with _SEM:
        for attempt in range(3):
            await _LIMITER.acquire()
            resp = await client.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return None
            if resp.status_code == 429 and attempt < 2:
                wait = float(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(min(wait, 5))
                continue
            resp.raise_for_status()
    return None


async def _detect_position(client: httpx.AsyncClient, puuid: str) -> str:
    """최근 솔로랭크 전적에서 가장 많이 플레이한 포지션을 추정한다."""
    ids = await _get(
        client,
        f"{REGIONAL_HOST}/lol/match/v5/matches/by-puuid/{puuid}/ids"
        f"?queue=420&start=0&count={MATCH_HISTORY_COUNT}",
    )
    if not ids:
        return "미정"

    matches = await asyncio.gather(
        *[_get(client, f"{REGIONAL_HOST}/lol/match/v5/matches/{mid}") for mid in ids]
    )

    counts: dict[str, int] = {}
    for match in matches:
        if not match:
            continue
        me = next(
            (p for p in match.get("info", {}).get("participants", []) if p.get("puuid") == puuid),
            None,
        )
        pos = me.get("teamPosition") if me else None
        if pos in POSITION_KO:
            counts[pos] = counts.get(pos, 0) + 1

    if not counts:
        return "미정"
    return POSITION_KO[max(counts, key=counts.get)]


async def _lookup_player_uncached(client: httpx.AsyncClient, riot_id: str) -> dict:
    if "#" not in riot_id:
        return {"ok": False, "error": "라이엇ID 형식은 '게임명#태그' 여야 합니다."}
    game_name, tag_line = riot_id.split("#", 1)
    game_name, tag_line = game_name.strip(), tag_line.strip()
    if not game_name or not tag_line:
        return {"ok": False, "error": "라이엇ID 형식은 '게임명#태그' 여야 합니다."}

    try:
        account = await _get(
            client, f"{REGIONAL_HOST}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        )
        if account is None:
            return {"ok": False, "error": "해당 라이엇ID를 찾을 수 없습니다."}
        puuid = account["puuid"]
        display_name = account.get("gameName") or game_name

        entries, detected_position = await asyncio.gather(
            _get(client, f"{PLATFORM_HOST}/lol/league/v4/entries/by-puuid/{puuid}"),
            _detect_position(client, puuid),
        )

        solo = next((e for e in (entries or []) if e.get("queueType") == "RANKED_SOLO_5x5"), None)

        if solo is None:
            return {
                "ok": True, "name": display_name,
                "tier": "UNRANKED", "tier_ko": TIER_KO["UNRANKED"],
                "rank": None, "lp": 0, "wins": 0, "losses": 0,
                "detected_position": detected_position,
            }

        return {
            "ok": True, "name": display_name,
            "tier": solo["tier"], "tier_ko": TIER_KO.get(solo["tier"], solo["tier"]),
            "rank": solo.get("rank"), "lp": solo.get("leaguePoints", 0),
            "wins": solo.get("wins", 0), "losses": solo.get("losses", 0),
            "detected_position": detected_position,
        }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"Riot API 오류 ({e.response.status_code})"}
    except Exception as e:
        return {"ok": False, "error": f"조회 실패: {e}"}


async def lookup_player(client: httpx.AsyncClient, riot_id: str) -> dict:
    """'게임명#태그' 형식의 라이엇ID로 소환사명, 솔로랭크 정보, 최근 주 포지션을 조회한다.
    최근 조회 결과는 30분간 캐시해 반복 조회를 즉시 응답한다."""
    key = riot_id.strip().lower()
    cached = _cache.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]

    result = await _lookup_player_uncached(client, riot_id)
    if result.get("ok"):
        _cache[key] = (time.time(), result)
    return result


async def lookup_players(riot_ids: list[str]) -> list[dict]:
    api_key()  # 키가 없으면 개별 조회 대신 한 번에 실패시킨다
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[lookup_player(client, rid) for rid in riot_ids])
    return list(results)
