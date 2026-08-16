"""Riot Games API 클라이언트 — 라이엇ID로 솔로랭크 티어/LP 조회."""
import os
import asyncio
import httpx

REGIONAL_HOST = "https://asia.api.riotgames.com"   # account-v1 (라이엇ID → puuid)
PLATFORM_HOST = "https://kr.api.riotgames.com"      # summoner-v4, league-v4

TIER_KO = {
    "UNRANKED": "언랭", "IRON": "아이언", "BRONZE": "브론즈", "SILVER": "실버",
    "GOLD": "골드", "PLATINUM": "플래티넘", "EMERALD": "에메랄드", "DIAMOND": "다이아",
    "MASTER": "마스터", "GRANDMASTER": "그랜드마스터", "CHALLENGER": "챌린저",
}

# 조회 동시 요청 수 제한 (개인 키 레이트리밋 보호)
_SEM = asyncio.Semaphore(4)


def api_key() -> str:
    key = os.environ.get("RIOT_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RIOT_API_KEY 환경변수가 설정되지 않았습니다.")
    return key


async def _get(client: httpx.AsyncClient, url: str) -> dict | None:
    headers = {"X-Riot-Token": api_key()}
    async with _SEM:
        for attempt in range(3):
            resp = await client.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return None
            if resp.status_code == 429 and attempt < 2:
                wait = float(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
    return None


async def lookup_player(client: httpx.AsyncClient, riot_id: str) -> dict:
    """'게임명#태그' 형식의 라이엇ID로 솔로랭크 정보를 조회한다."""
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

        summoner = await _get(
            client, f"{PLATFORM_HOST}/lol/summoner/v4/summoners/by-puuid/{puuid}"
        )
        if summoner is None:
            return {"ok": False, "error": "소환사 정보를 찾을 수 없습니다."}

        entries = await _get(
            client, f"{PLATFORM_HOST}/lol/league/v4/entries/by-puuid/{puuid}"
        )
        solo = next((e for e in (entries or []) if e.get("queueType") == "RANKED_SOLO_5x5"), None)

        if solo is None:
            return {
                "ok": True, "tier": "UNRANKED", "tier_ko": TIER_KO["UNRANKED"],
                "rank": None, "lp": 0, "wins": 0, "losses": 0,
                "summoner_level": summoner.get("summonerLevel"),
            }

        return {
            "ok": True,
            "tier": solo["tier"], "tier_ko": TIER_KO.get(solo["tier"], solo["tier"]),
            "rank": solo.get("rank"), "lp": solo.get("leaguePoints", 0),
            "wins": solo.get("wins", 0), "losses": solo.get("losses", 0),
            "summoner_level": summoner.get("summonerLevel"),
        }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"Riot API 오류 ({e.response.status_code})"}
    except Exception as e:
        return {"ok": False, "error": f"조회 실패: {e}"}


async def lookup_players(riot_ids: list[str]) -> list[dict]:
    api_key()  # 키가 없으면 개별 조회 대신 한 번에 실패시킨다
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[lookup_player(client, rid) for rid in riot_ids])
    return list(results)
