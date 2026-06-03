from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio, json, random, string, time

app = FastAPI()

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
                "turn": "blue",
                "a": None, "b": None,
                "a_done": False, "b_done": False,
                "a_passed": False, "b_passed": False,
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
            except Exception:
                pass

    def _view(self, role: str) -> dict:
        """역할별 클라이언트 뷰 (턴제 입찰)"""
        v = {k: self.s[k] for k in self.s if k not in ("bid", "t0")}
        b = self.s["bid"]
        v["bid_turn"]     = b["turn"]
        v["bid_a_done"]   = b["a_done"]
        v["bid_b_done"]   = b["b_done"]
        v["bid_a_passed"] = b.get("a_passed", False)
        v["bid_b_passed"] = b.get("b_passed", False)

        both = b["a_done"] and b["b_done"]
        if both:
            v["reveal"]    = True
            v["bid_a_val"] = b["a"] or 0
            v["bid_b_val"] = b["b"] or 0
        else:
            v["reveal"] = False
            first = self.s.get("bid_first", "blue")
            if first == "blue" and b["a_done"]:
                v["first_acted"]  = True
                v["first_team"]   = "blue"
                v["first_val"]    = b["a"] or 0
                v["first_passed"] = b.get("a_passed", False)
            elif first == "red" and b["b_done"]:
                v["first_acted"]  = True
                v["first_team"]   = "red"
                v["first_val"]    = b["b"] or 0
                v["first_passed"] = b.get("b_passed", False)
            else:
                v["first_acted"] = False

            if role == "blue":
                v["my_val"]    = b["a"]
                v["my_passed"] = b.get("a_passed", False)
            elif role == "red":
                v["my_val"]    = b["b"]
                v["my_passed"] = b.get("b_passed", False)

        v["connected"] = list(self.ws.keys())
        v["timer"]     = self._rem()
        v["room_id"]   = self.id
        return v

    async def _push(self, timer_only: bool = False):
        for role in list(self.ws):
            msg = {"type": "state", "d": self._view(role), "role": role}
            if timer_only:
                msg["timer_only"] = True
            await self._emit(role, msg)

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
                    # 현재 차례 팀 자동 포기
                    if b["turn"] == "blue" and not b["a_done"]:
                        b["a_passed"], b["a_done"] = True, True
                    elif b["turn"] == "red" and not b["b_done"]:
                        b["b_passed"], b["b_done"] = True, True
                    else:
                        return  # 이미 처리됨
                    await self._push()
                    await asyncio.sleep(0.8)
                    await self._after_act()
                    return
        except asyncio.CancelledError:
            pass

    async def _after_act(self):
        """한 팀이 행동한 후 처리: 턴 전환 or 최종 resolve 예약"""
        b = self.s["bid"]
        if b["a_done"] and b["b_done"]:
            if self.s.get("resolving"):
                return
            self.s["resolving"] = True
            await self._push()
            asyncio.create_task(self._finish_resolve())
        else:
            # 후공 팀 턴으로 전환
            b["turn"] = "red" if b["turn"] == "blue" else "blue"
            await self._push()
            await self._start_timer()

    async def _finish_resolve(self):
        """비동기 resolve (self-cancel 방지용 별도 태스크)"""
        await asyncio.sleep(1.5)
        if self.tick and not self.tick.done():
            self.tick.cancel()
        await self._resolve()

    # ── 낙찰 처리 ────────────────────────────────────────────────────────────
    async def _resolve(self):
        b  = self.s["bid"]
        va, vb = b["a"] or 0, b["b"] or 0
        pa = self.s["team_a"]["points"]
        pb = self.s["team_b"]["points"]
        a_passed = b.get("a_passed", False)
        b_passed = b.get("b_passed", False)

        # 다음 라운드 선공 전환
        cur_first = self.s.get("bid_first", "blue")
        next_first = "red" if cur_first == "blue" else "blue"

        player = self.s["pool"][0]

        if a_passed and b_passed:
            # 양팀 모두 포기 → 맨 뒤로
            self.s["pool"].pop(0)
            if len(self.s["pool"]) == 0:
                # 마지막 선수인데 둘 다 포기 → 랜덤 배정
                t = random.choice([self.s["team_a"], self.s["team_b"]])
                t["members"].append(player)
                msg, ht = f"⚠️ 마지막 선수 {player}님 랜덤 배정!", "tie"
            else:
                self.s["pool"].append(player)
                msg, ht = f"⚠️ 양팀 모두 포기! {player}님은 맨 뒤로.", "tie"
        else:
            if a_passed:
                nm = self.s["pool"].pop(0)
                self.s["team_b"]["members"].append(nm)
                self.s["team_b"]["points"] -= vb
                msg, ht = f"🔴 레드팀, {nm} 영입! (블루 포기 / {vb}pt)", "red"
            elif b_passed:
                nm = self.s["pool"].pop(0)
                self.s["team_a"]["members"].append(nm)
                self.s["team_a"]["points"] -= va
                msg, ht = f"🔵 블루팀, {nm} 영입! ({va}pt / 레드 포기)", "blue"
            elif va == vb:
                if self.s["cfg"]["tie"] == "random":
                    nm = self.s["pool"].pop(0)
                    if random.choice([True, False]):
                        self.s["team_a"]["members"].append(nm)
                        self.s["team_a"]["points"] -= va
                        msg, ht = f"⚔️ 동점→랜덤: 🔵 블루팀이 {nm} 영입! ({va}pt vs {vb}pt)", "blue"
                    else:
                        self.s["team_b"]["members"].append(nm)
                        self.s["team_b"]["points"] -= vb
                        msg, ht = f"⚔️ 동점→랜덤: 🔴 레드팀이 {nm} 영입! ({vb}pt vs {va}pt)", "red"
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

        # 다음 라운드 bid 초기화
        self.s["bid_first"] = next_first
        self.s["bid"] = {
            "turn": next_first,
            "a": None, "b": None,
            "a_done": False, "b_done": False,
            "a_passed": False, "b_passed": False,
        }
        self.s["resolving"] = False
        self.s["paused"] = False

        # 완료 체크
        if (len(self.s["team_a"]["members"]) >= 5 or
                len(self.s["team_b"]["members"]) >= 5):
            for pp in list(self.s["pool"]):
                t = self.s["team_a"] if len(self.s["team_a"]["members"]) < 5 \
                    else self.s["team_b"]
                t["members"].append(pp)
            self.s["pool"] = []
            self.s["phase"] = "result"
            await self._push()
        else:
            await self._push()
            await self._start_timer()

    # ── 메시지 처리 ──────────────────────────────────────────────────────────
    async def handle(self, role: str, data: dict):
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
                    "a_done": False, "b_done": False,
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
            if self.s["phase"] != "auction":
                return
            amt = int(data.get("amount", 0))
            b   = self.s["bid"]

            if role == "blue" and b["turn"] == "blue" and not b["a_done"]:
                pts = self.s["team_a"]["points"]
                amt = max(1, min(amt, pts))
                b["a"], b["a_done"], b["a_passed"] = amt, True, False
            elif role == "red" and b["turn"] == "red" and not b["b_done"]:
                pts = self.s["team_b"]["points"]
                amt = max(1, min(amt, pts))
                b["b"], b["b_done"], b["b_passed"] = amt, True, False
            else:
                return

            await self._after_act()

        elif t == "pass_bid":
            if self.s["phase"] != "auction":
                return
            b = self.s["bid"]
            if role == "blue" and b["turn"] == "blue" and not b["a_done"]:
                b["a_passed"], b["a_done"], b["a"] = True, True, None
            elif role == "red" and b["turn"] == "red" and not b["b_done"]:
                b["b_passed"], b["b_done"], b["b"] = True, True, None
            else:
                return

            await self._after_act()

        elif t == "trade_toggle":
            pl   = data.get("player")
            team = data.get("team")
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
            ia = sorted([ma.index(n) for n in sa])
            ib = sorted([mb.index(n) for n in sb])
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
            await self._push()

        elif t == "reset":
            if self.tick and not self.tick.done():
                self.tick.cancel()
            self.s = self._fresh()
            await self._push()


# ── 방 저장소 ──────────────────────────────────────────────────────────────────
rooms: dict[str, Room] = {}


# ── API ───────────────────────────────────────────────────────────────────────
@app.post("/api/room")
async def create_room():
    rid = gen_id()
    while rid in rooms:
        rid = gen_id()
    rooms[rid] = Room(rid)
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
            raw  = await ws.receive_text()
            data = json.loads(raw)
            await room.handle(role, data)
    except WebSocketDisconnect:
        room.ws.pop(role, None)
        await room._push()
        if not room.ws:
            if room.tick and not room.tick.done():
                room.tick.cancel()
            rooms.pop(room_id, None)


@app.get("/")
async def index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
