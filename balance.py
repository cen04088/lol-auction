"""솔로랭크 티어/LP 기반 점수 산정 + 포지션을 고려한 최적 5:5 팀 분할."""
from itertools import combinations, permutations

TIER_ORDER = ["아이언", "브론즈", "실버", "골드", "플래티넘", "에메랄드", "다이아", "마스터", "그랜드마스터", "챌린저"]
RANK_ORDER = {"IV": 0, "III": 1, "II": 2, "I": 3}
POSITIONS = ["탑", "정글", "미드", "원딜", "서폿"]


def tier_score(tier_ko: str, rank: str | None = None, lp: int = 0) -> int:
    """티어(한글) + division(IV~I) + LP → 단일 정수 실력 점수."""
    if tier_ko not in TIER_ORDER:
        return 0
    idx = TIER_ORDER.index(tier_ko)
    if tier_ko in ("마스터", "그랜드마스터", "챌린저"):
        return (idx + 1) * 400 + lp
    return idx * 400 + RANK_ORDER.get(rank or "III", 1) * 100 + lp


def _best_position_assignment(members: list[dict]) -> tuple[int, list[str]]:
    """5명에게 5개 포지션을 배정해 선호 불일치가 최소가 되는 조합을 찾는다.
    반환: (불일치 수, 각 member 순서에 대응하는 배정 포지션 리스트)"""
    best_cost = None
    best_assign = None
    for perm in permutations(POSITIONS):
        cost = sum(
            1 for m, pos in zip(members, perm)
            if m["position"] != "미정" and m["position"] != pos
        )
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_assign = list(perm)
    return best_cost, best_assign


def find_best_teams(players: list[dict]) -> dict:
    """players: [{name, position, score}, ...] 정확히 10명.
    반환: 포지션 불일치가 가장 적고, 그 안에서 실력 차이가 가장 작은 5:5 분할."""
    if len(players) != 10:
        raise ValueError("정확히 10명이 필요합니다.")

    idxs = list(range(10))
    best = None  # (mismatches, score_diff, team_a_idx, team_b_idx, assign_a, assign_b)

    # players[0]을 항상 팀A에 고정해 대칭(A/B 반전) 중복 계산을 절반으로 줄인다.
    for combo in combinations(idxs[1:], 4):
        team_a_idx = [0] + list(combo)
        team_b_idx = [i for i in idxs if i not in team_a_idx]

        team_a = [players[i] for i in team_a_idx]
        team_b = [players[i] for i in team_b_idx]

        cost_a, assign_a = _best_position_assignment(team_a)
        cost_b, assign_b = _best_position_assignment(team_b)

        score_a = sum(p["score"] for p in team_a)
        score_b = sum(p["score"] for p in team_b)
        score_diff = abs(score_a - score_b)

        key = (cost_a + cost_b, score_diff)
        if best is None or key < best[0]:
            best = (key, team_a_idx, team_b_idx, assign_a, assign_b)

    (mismatches, score_diff), team_a_idx, team_b_idx, assign_a, assign_b = best

    def build(team_idx, assign):
        members = [players[i] for i in team_idx]
        out = []
        for m, pos in zip(members, assign):
            out.append({**m, "assigned_position": pos})
        out.sort(key=lambda p: POSITIONS.index(p["assigned_position"]))
        return out

    team_a = build(team_a_idx, assign_a)
    team_b = build(team_b_idx, assign_b)

    return {
        "team_a": team_a,
        "team_b": team_b,
        "score_a": sum(p["score"] for p in team_a),
        "score_b": sum(p["score"] for p in team_b),
        "mismatches": mismatches,
    }
