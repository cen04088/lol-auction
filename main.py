from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import asyncio, json, logging, os, random, string, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("lol_auction")

load_dotenv()

import balance as balance_mod
import riot_api

app = FastAPI()

STATE_FILE = os.environ.get("STATE_FILE", "rooms_state.json")

# ── 유틸 ──────────────────────────────────────────────────────────────────────
def gen_id():
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(chars, k=6))

# ── 방(Room) ──────────────────────────────────────────────────────────────────
class Room:
    def __init__(self, rid: str):
        self.id   = rid
        self.ws: dict[str, WebSocket] = {}   # role → WebSocket
        self.s    = self._fresh()
        self.tick: asyncio.Task | None = None
        self.last_activity = time.time()

    # ── 상태 초기화 ──────────────────────────────────────────────────────────
    def _fresh(self):
        return {
            "phase": "lobby",
            "team_a": {"members": [], "points": 100},
            "team_b": {"members": [], "points": 100},
            "pool": [],
            "history": [],
            "all_players": {},
            "cfg": {
                "sp": 100, "tie": "random", "timer": 30,
            },
            "bid_first": "blue",
            "bid": {
                "turn":     "blue",
                "a":        None,   # 블루 최근 입찰액
                "b":        None,   # 레드 최근 입찰액
                "a_passed": False,
                "b_passed": False,
            },
            "paused": False,
            "paused_rem": 0,
            "resolving": False,           # 이중 resolve 방지
            "trade": False,
            "sel_a": [], "sel_b": [],
            "last_msg": "",
            "t0": None,
        }

    # ── 통신 ─────────────────────────────────────────────────────────────────
    async def _emit(self, role: str, msg: dict):
        ws = self.ws.get(role)
        if ws:
            try:
                await ws.send_text(json.dumps(msg, ensure_ascii=False))
            except Exception as e:
                logger.warning("room=%s role=%s emit failed: %s", self.id, role, e)

    def _view(self, role: str) -> dict:
        """공개 번갈아 입찰 — 양팀 입찰액 항상 공개"""
        v = {k: self.s[k] for k in self.s if k not in ("bid", "t0")}
        b = self.s["bid"]
        v["bid_turn"]     = b["turn"]
        v["bid_a"]        = b["a"]
        v["bid_b"]        = b["b"]
        v["bid_a_passed"] = b["a_passed"]
        v["bid_b_passed"] = b["b_passed"]
        v["connected"]    = list(self.ws.keys())
        v["timer"]        = self._rem()
        v["room_id"]      = self.id
        return v

    async def _push(self, timer_only: bool = False):
        for role in list(self.ws):
            msg = {"type": "state", "d": self._view(role), "role": role}
            if timer_only:
                msg["timer_only"] = True
            await self._emit(role, msg)
        if not timer_only:
            _save_state()

    # ── 타이머 ───────────────────────────────────────────────────────────────
    def _rem(self) -> int:
        if self.s.get("paused"):
            return self.s.get("paused_rem", self.s["cfg"]["timer"])
        if not self.s.get("t0"):
            return self.s["cfg"]["timer"]
        return max(0, self.s["cfg"]["timer"] - int(time.time() - self.s["t0"]))

    async def _start_timer(self):
        if self.tick and not self.tick.done():
            self.tick.cancel()
        self.s["t0"] = time.time()
        self.tick = asyncio.create_task(self._ticker())

    async def _ticker(self):
        """0.5초마다 체크 → 값 바뀔 때만 push, 일시정지 중엔 건너뜀"""
        try:
            last_rem = self._rem()
            while self.s["phase"] == "auction":
                await asyncio.sleep(0.5)
                if self.s.get("paused"):
                    continue
                rem = self._rem()
                if rem != last_rem:
                    last_rem = rem
                    await self._push(timer_only=True)
                if rem <= 0:
                    b = self.s["bid"]
                    turn = b["turn"]
                    if (turn == "blue" and not b["a_passed"]) or \
                       (turn == "red"  and not b["b_passed"]):
                        await self._push()
                        await asyncio.sleep(0.8)
                        await self._do_pass(turn)
                    return
        except asyncio.CancelledError:
            pass

    async def _do_pass(self, role: str):
        """포기 처리: 상대 입찰 있으면 종료, 없으면 턴 전환"""
        b = self.s["bid"]
        if role == "blue":
            b["a_passed"] = True
            opp_bid    = b["b"]
            opp_passed = b["b_passed"]
            opp_role   = "red"
        else:
            b["b_passed"] = True
            opp_bid    = b["a"]
            opp_passed = b["a_passed"]
            opp_role   = "blue"

        if opp_bid is not None or opp_passed:
            # 상대가 입찰했거나 상대도 이미 포기 → 종료
            await self._start_resolve()
        else:
            # 상대에게 아직 기회가 없었음 → 턴 전환
            b["turn"] = opp_role
            await self._push()
            await self._start_timer()

    async def _start_resolve(self):
        if self.s.get("resolving"):
            return
        self.s["resolving"] = True
        await self._push()
        asyncio.create_task(self._finish_resolve())

    async def _finish_resolve(self):
        await asyncio.sleep(1.5)
        if self.tick and not self.tick.done():
            self.tick.cancel()
        await self._resolve()

    # ── 낙찰 처리 ────────────────────────────────────────────────────────────
    async def _resolve(self):
        b        = self.s["bid"]
        va       = b["a"]          # None 이면 미입찰
        vb       = b["b"]
        a_passed = b["a_passed"]
        b_passed = b["b_passed"]
        player   = self.s["pool"][0]
        next_first = "red" if self.s["bid_first"] == "blue" else "blue"

        if a_passed and b_passed:
            self.s["pool"].pop(0)
            if not self.s["pool"]:
                t = random.choice([self.s["team_a"], self.s["team_b"]])
                t["members"].append(player)
                msg, ht = f"⚠️ 마지막 선수 {player}님 랜덤 배정!", "tie"
            else:
                self.s["pool"].append(player)
                msg, ht = f"⚠️ 양팀 모두 포기! {player}님은 맨 뒤로.", "tie"
        elif a_passed:              # 블루 포기 → 레드 낙찰
            nm = self.s["pool"].pop(0)
            self.s["team_b"]["members"].append(nm)
            self.s["team_b"]["points"] -= vb
            msg, ht = f"🔴 레드팀, {nm} 영입! (블루 포기 / {vb}pt)", "red"
        elif b_passed:              # 레드 포기 → 블루 낙찰
            nm = self.s["pool"].pop(0)
            self.s["team_a"]["members"].append(nm)
            self.s["team_a"]["points"] -= va
            msg, ht = f"🔵 블루팀, {nm} 영입! ({va}pt / 레드 포기)", "blue"
        else:                       # 양팀 모두 입찰 (동점 처리)
            if va == vb:
                if self.s["cfg"]["tie"] == "random":
                    nm = self.s["pool"].pop(0)
                    if random.choice([True, False]):
                        self.s["team_a"]["members"].append(nm)
                        self.s["team_a"]["points"] -= va
                        msg, ht = f"⚔️ 동점→랜덤: 🔵 블루팀이 {nm} 영입! ({va}pt)", "blue"
                    else:
                        self.s["team_b"]["members"].append(nm)
                        self.s["team_b"]["points"] -= vb
                        msg, ht = f"⚔️ 동점→랜덤: 🔴 레드팀이 {nm} 영입! ({vb}pt)", "red"
                else:
                    nm = self.s["pool"].pop(0)
                    self.s["pool"].append(nm)
                    msg, ht = f"⚠️ 동점({va}pt)! {nm}님은 맨 뒤로.", "tie"
            elif va > vb:
                nm = self.s["pool"].pop(0)
                self.s["team_a"]["members"].append(nm)
                self.s["team_a"]["points"] -= va
                msg, ht = f"🔵 블루팀, {nm} 영입! ({va}pt vs {vb}pt)", "blue"
            else:
                nm = self.s["pool"].pop(0)
                self.s["team_b"]["members"].append(nm)
                self.s["team_b"]["points"] -= vb
                msg, ht = f"🔴 레드팀, {nm} 영입! ({vb}pt vs {va}pt)", "red"

        self.s["last_msg"] = msg
        self.s["history"].append({"result": msg, "type": ht})
        self.s["bid_first"] = next_first
        self.s["bid"] = {
            "turn": next_first,
            "a": None, "b": None,
            "a_passed": False, "b_passed": False,
        }
        self.s["resolving"] = False
        self.s["paused"]    = False

        if len(self.s["team_a"]["members"]) >= 5 or len(self.s["team_b"]["members"]) >= 5:
            for pp in list(self.s["pool"]):
                t = self.s["team_a"] if len(self.s["team_a"]["members"]) < 5 else self.s["team_b"]
                t["members"].append(pp)
            self.s["pool"]  = []
            self.s["phase"] = "result"
            await self._push()
        else:
            await self._push()
            await self._start_timer()

    # ── 메시지 처리 ──────────────────────────────────────────────────────────
    async def handle(self, role: str, data: dict):
        self.last_activity = time.time()
        t = data.get("type")

        if t == "start_game":
            if role != "blue":
                return
            players  = data.get("players", [])
            leader_a = data.get("leader_a", "")
            leader_b = data.get("leader_b", "")
            cfg      = data.get("cfg", {})

            if len(players) != 10 or not leader_a or not leader_b:
                await self._emit(role, {"type": "error", "msg": "10명 + 팀장 2명 필요"})
                return

            sp = int(cfg.get("sp", 100))
            self.s["all_players"] = {
                p["name"]: {"tier": p["tier"], "position": p["position"]}
                for p in players
            }
            pool = [p["name"] for p in players
                    if p["name"] not in (leader_a, leader_b)]
            random.shuffle(pool)

            self.s.update({
                "phase":   "auction",
                "team_a":  {"members": [leader_a], "points": sp},
                "team_b":  {"members": [leader_b], "points": sp},
                "pool":    pool,
                "history": [],
                "last_msg": "경매 시작!",
                "bid_first": "blue",
                "resolving": False,
                "bid": {
                    "turn": "blue",
                    "a": None, "b": None,
                    "a_passed": False, "b_passed": False,
                },
                "cfg": {
                    "sp":    sp,
                    "tie":   cfg.get("tie", "random"),
                    "timer": int(cfg.get("timer", 30)),
                },
            })
            await self._start_timer()
            await self._push()

        elif t == "submit_bid":
            if self.s["phase"] != "auction" or self.s.get("resolving"):
                return
            b = self.s["bid"]
            if b["turn"] != role:
                return
            if (role == "blue" and b["a_passed"]) or (role == "red" and b["b_passed"]):
                return

            try:
                amt = int(data.get("amount", 0))
            except (TypeError, ValueError):
                await self._emit(role, {"type": "error", "msg": "입찰액은 숫자여야 합니다."})
                return
            if role == "blue":
                pts     = self.s["team_a"]["points"]
                opp_bid = b["b"]
                min_bid = (opp_bid + 1) if opp_bid is not None else 1
                if amt < min_bid or amt > pts:
                    await self._emit(role, {"type": "error", "msg": f"입찰액은 {min_bid}~{pts}pt 범위여야 합니다."})
                    return
                b["a"] = amt
                opp_passed = b["b_passed"]
                opp_role   = "red"
            else:
                pts     = self.s["team_b"]["points"]
                opp_bid = b["a"]
                min_bid = (opp_bid + 1) if opp_bid is not None else 1
                if amt < min_bid or amt > pts:
                    await self._emit(role, {"type": "error", "msg": f"입찰액은 {min_bid}~{pts}pt 범위여야 합니다."})
                    return
                b["b"] = amt
                opp_passed = b["a_passed"]
                opp_role   = "blue"

            if opp_passed:
                # 상대가 이미 포기 → 내가 낙찰
                await self._start_resolve()
            else:
                b["turn"] = opp_role
                await self._push()
                await self._start_timer()

        elif t == "pass_bid":
            if self.s["phase"] != "auction" or self.s.get("resolving"):
                return
            b = self.s["bid"]
            if b["turn"] != role:
                return
            if (role == "blue" and b["a_passed"]) or (role == "red" and b["b_passed"]):
                return
            await self._do_pass(role)

        elif t == "trade_toggle":
            pl   = data.get("player")
            team = data.get("team")
            if team not in ("a", "b"):
                return
            sel  = self.s[f"sel_{team}"]
            if pl in sel:
                sel.remove(pl)
            else:
                sel.append(pl)
            await self._push()

        elif t == "trade_start":
            self.s.update({"trade": True, "sel_a": [], "sel_b": []})
            await self._push()

        elif t == "trade_cancel":
            self.s.update({"trade": False, "sel_a": [], "sel_b": []})
            await self._push()

        elif t == "trade_confirm":
            sa = self.s["sel_a"]
            sb = self.s["sel_b"]
            if len(sa) != len(sb) or not sa:
                return
            ma = self.s["team_a"]["members"]
            mb = self.s["team_b"]["members"]
            try:
                ia = sorted([ma.index(n) for n in sa])
                ib = sorted([mb.index(n) for n in sb])
            except ValueError:
                logger.warning("room=%s trade_confirm: stale selection", self.id)
                return
            va = [ma[i] for i in ia]
            vb = [mb[i] for i in ib]
            for i, v in zip(ia, vb): ma[i] = v
            for i, v in zip(ib, va): mb[i] = v
            self.s.update({"trade": False, "sel_a": [], "sel_b": []})
            await self._push()

        elif t == "pause_timer":
            if role not in ("blue", "red"): return
            self.s["paused"]     = True
            self.s["paused_rem"] = self._rem()
            await self._push()

        elif t == "resume_timer":
            if role not in ("blue", "red"): return
            self.s["t0"]     = time.time()   # 해제 시 최대 시간부터 재시작
            self.s["paused"] = False
            if not self.tick or self.tick.done():   # 재시작 복구 등으로 ticker가 없을 수 있음
                self.tick = asyncio.create_task(self._ticker())
            await self._push()

        elif t == "reset":
            if self.tick and not self.tick.done():
                self.tick.cancel()
            self.s = self._fresh()
            await self._push()


# ── 방 저장소 ──────────────────────────────────────────────────────────────────
rooms: dict[str, Room] = {}


def _save_state():
    """방 상태 스냅샷 저장 (서버 프로세스 재시작 시 복구용, 최소 구현).
    디스크가 영구적이지 않은 환경(예: 컨테이너 재배포)에서는 살아남지 않는다."""
    try:
        data = {
            rid: {"s": rm.s, "last_activity": rm.last_activity}
            for rid, rm in rooms.items()
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        logger.warning("state save failed: %s", e)


def _load_state():
    """이전 스냅샷 복구. 경매 진행 중이던 방은 안전하게 일시정지 + 현재 라운드 초기화."""
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for rid, saved in data.items():
            rm = Room(rid)
            rm.s = saved["s"]
            rm.last_activity = saved.get("last_activity", time.time())
            if rm.s.get("phase") == "auction":
                rm.s["paused"]     = True
                rm.s["paused_rem"] = rm.s["cfg"]["timer"]
                rm.s["resolving"]  = False
                rm.s["bid"] = {
                    "turn": rm.s.get("bid_first", "blue"),
                    "a": None, "b": None,
                    "a_passed": False, "b_passed": False,
                }
            rooms[rid] = rm
        logger.info("restored %d room(s) from %s", len(rooms), STATE_FILE)
    except Exception as e:
        logger.warning("state load failed: %s", e)


async def _cleanup_rooms():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        expired = [rid for rid, rm in list(rooms.items())
                   if not rm.ws and now - rm.last_activity > 3600]
        for rid in expired:
            rm = rooms.pop(rid, None)
            if rm and rm.tick and not rm.tick.done():
                rm.tick.cancel()
        if expired:
            logger.info("cleaned up %d expired room(s): %s", len(expired), expired)
            _save_state()

@app.on_event("startup")
async def _startup():
    _load_state()
    asyncio.create_task(_cleanup_rooms())


# ── API ───────────────────────────────────────────────────────────────────────
@app.post("/api/room")
async def create_room():
    rid = gen_id()
    while rid in rooms:
        rid = gen_id()
    rooms[rid] = Room(rid)
    logger.info("room=%s created", rid)
    _save_state()
    return {"room_id": rid}


@app.websocket("/ws/{room_id}/{role}")
async def ws_endpoint(ws: WebSocket, room_id: str, role: str):
    if role not in {"blue", "red", "spectator"}:
        await ws.close(4000)
        return

    await ws.accept()

    if room_id not in rooms:
        await ws.send_text(json.dumps(
            {"type": "error", "msg": "방을 찾을 수 없습니다."}, ensure_ascii=False))
        await ws.close()
        return

    room = rooms[room_id]

    if role in ("blue", "red") and role in room.ws:
        await ws.send_text(json.dumps(
            {"type": "error", "msg": "이미 해당 역할이 접속 중입니다."}, ensure_ascii=False))
        await ws.close()
        return

    room.ws[role] = ws
    await room._push()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                await room.handle(role, data)
            except Exception as e:
                logger.warning("room=%s role=%s message handling failed: %s", room_id, role, e)
    except WebSocketDisconnect:
        room.ws.pop(role, None)
        await room._push()
        if not room.ws:
            if room.tick and not room.tick.done():
                room.tick.cancel()
            rooms.pop(room_id, None)
            logger.info("room=%s closed (empty)", room_id)
            _save_state()


# ── 밸런싱 모드 (라이엇 API 기반 자동 팀 구성) ────────────────────────────────
class LookupPlayer(BaseModel):
    name: str
    riot_id: str


class LookupRequest(BaseModel):
    players: list[LookupPlayer]


class ComputePlayer(BaseModel):
    name: str
    position: str
    tier_ko: str
    rank: str | None = None
    lp: int = 0


class ComputeRequest(BaseModel):
    players: list[ComputePlayer]


@app.post("/api/balance/lookup")
async def balance_lookup(req: LookupRequest):
    try:
        results = await riot_api.lookup_players([p.riot_id for p in req.players])
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {
        "players": [
            {"name": p.name, "riot_id": p.riot_id, **r}
            for p, r in zip(req.players, results)
        ]
    }


@app.post("/api/balance/compute")
async def balance_compute(req: ComputeRequest):
    if len(req.players) != 10:
        raise HTTPException(400, "정확히 10명이 필요합니다.")
    names = [p.name for p in req.players]
    if len(set(names)) != 10:
        raise HTTPException(400, "소환사명이 중복되었습니다.")

    enriched = [
        {
            "name": p.name,
            "position": p.position,
            "tier_ko": p.tier_ko,
            "rank": p.rank,
            "lp": p.lp,
            "score": balance_mod.tier_score(p.tier_ko, p.rank, p.lp),
        }
        for p in req.players
    ]
    return balance_mod.find_best_teams(enriched)


@app.get("/")
async def index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
