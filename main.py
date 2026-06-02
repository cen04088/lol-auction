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
                "sp": 100, "tie": "random",
                "timer": 30, "bluff": False,
            },
            "dd_a": False, "dd_b": False,
            "bid": {
                "a": None, "b": None,
                "dd_a": False, "dd_b": False,
                "a_done": False, "b_done": False,
            },
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
        """역할별 클라이언트 뷰 (상대방 입찰 숨김)"""
        v = {k: self.s[k] for k in self.s if k not in ("bid", "t0")}
        b = self.s["bid"]
        v["bid_a_done"] = b["a_done"]
        v["bid_b_done"] = b["b_done"]
        both = b["a_done"] and b["b_done"]
        if both:
            v["reveal"]   = True
            v["bid_a_val"] = b["a"]
            v["bid_b_val"] = b["b"]
            v["bid_dd_a"]  = b["dd_a"]
            v["bid_dd_b"]  = b["dd_b"]
        else:
            v["reveal"] = False
            if role == "blue":
                v["my_val"] = b["a"]; v["my_dd"] = b["dd_a"]
            elif role == "red":
                v["my_val"] = b["b"]; v["my_dd"] = b["dd_b"]
        v["connected"] = list(self.ws.keys())
        v["timer"]     = self._rem()
        v["room_id"]   = self.id
        return v

    async def _push(self):
        for role in list(self.ws):
            await self._emit(role, {"type": "state", "d": self._view(role), "role": role})

    # ── 타이머 ───────────────────────────────────────────────────────────────
    def _rem(self) -> int:
        if not self.s.get("t0"):
            return self.s["cfg"]["timer"]
        return max(0, self.s["cfg"]["timer"] - int(time.time() - self.s["t0"]))

    async def _start_timer(self):
        if self.tick and not self.tick.done():
            self.tick.cancel()
        self.s["t0"] = time.time()
        self.tick = asyncio.create_task(self._ticker())

    async def _ticker(self):
        """0.5초마다 체크 → 표시값이 바뀔 때만 push (Windows sleep 부정확 대응)"""
        try:
            last_rem = self._rem()
            while self.s["phase"] == "auction":
                await asyncio.sleep(0.5)
                rem = self._rem()
                if rem != last_rem:
                    last_rem = rem
                    await self._push()
                if rem <= 0:
                    b = self.s["bid"]
                    if not b["a_done"]: b["a"], b["a_done"] = 0, True
                    if not b["b_done"]: b["b"], b["b_done"] = 0, True
                    await self._push()
                    await asyncio.sleep(1.2)
                    await self._resolve()
                    return
        except asyncio.CancelledError:
            pass

    # ── 낙찰 처리 ────────────────────────────────────────────────────────────
    async def _resolve(self):
        if self.tick and not self.tick.done():
            self.tick.cancel()

        b  = self.s["bid"]
        va, vb = b["a"] or 0, b["b"] or 0
        pa = self.s["team_a"]["points"]
        pb = self.s["team_b"]["points"]

        # 더블다운
        aa, ua = va, False
        ab, ub = vb, False
        if b["dd_a"] and not self.s["dd_a"]: aa, ua = min(va * 2, pa), True
        if b["dd_b"] and not self.s["dd_b"]: ab, ub = min(vb * 2, pb), True
        if ua: self.s["dd_a"] = True
        if ub: self.s["dd_b"] = True

        # 블러핑
        blf = self.s["cfg"]["bluff"]
        def bluff(v):
            return max(0, v + random.randint(-3, 3)) if blf else v
        da, db = bluff(aa), bluff(ab)
        bt = " 🎭" if blf else ""
        ia = "💥" if ua else ""
        ib = "💥" if ub else ""

        player = self.s["pool"][0]

        if aa == ab:
            if self.s["cfg"]["tie"] == "random":
                nm = self.s["pool"].pop(0)
                if random.choice([True, False]):
                    self.s["team_a"]["members"].append(nm)
                    self.s["team_a"]["points"] -= aa
                    msg, ht = f"⚔️ 동점→랜덤: 🔵{ia} 블루팀이 {nm} 영입! ({da}pt vs {db}pt){bt}", "blue"
                else:
                    self.s["team_b"]["members"].append(nm)
                    self.s["team_b"]["points"] -= ab
                    msg, ht = f"⚔️ 동점→랜덤: 🔴{ib} 레드팀이 {nm} 영입! ({db}pt vs {da}pt){bt}", "red"
            else:
                nm = self.s["pool"].pop(0)
                self.s["pool"].append(nm)
                msg, ht = f"⚠️ 동점({da}pt)! {nm}님은 맨 뒤로.", "tie"
        elif aa > ab:
            nm = self.s["pool"].pop(0)
            self.s["team_a"]["members"].append(nm)
            self.s["team_a"]["points"] -= aa
            msg, ht = f"🔵{ia} 블루팀, {nm} 영입! ({da}pt vs {db}pt){bt}", "blue"
        else:
            nm = self.s["pool"].pop(0)
            self.s["team_b"]["members"].append(nm)
            self.s["team_b"]["points"] -= ab
            msg, ht = f"🔴{ib} 레드팀, {nm} 영입! ({db}pt vs {da}pt){bt}", "red"

        self.s["last_msg"] = msg
        self.s["history"].append({"result": msg, "type": ht})
        self.s["bid"] = {"a": None, "b": None, "dd_a": False, "dd_b": False,
                          "a_done": False, "b_done": False}

        # 완료 체크
        if (len(self.s["team_a"]["members"]) == 5 or
                len(self.s["team_b"]["members"]) == 5):
            for pp in list(self.s["pool"]):
                t = self.s["team_a"] if len(self.s["team_a"]["members"]) < 5 \
                    else self.s["team_b"]
                t["members"].append(pp)
            self.s["pool"] = []
            self.s["phase"] = "result"
        else:
            await self._start_timer()

        await self._push()

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
                "dd_a": False, "dd_b": False,
                "bid": {"a": None, "b": None, "dd_a": False, "dd_b": False,
                         "a_done": False, "b_done": False},
                "cfg": {
                    "sp":    sp,
                    "tie":   cfg.get("tie", "random"),
                    "timer": int(cfg.get("timer", 30)),
                    "bluff": bool(cfg.get("bluff", False)),
                },
            })
            await self._start_timer()
            await self._push()

        elif t == "submit_bid":
            if self.s["phase"] != "auction":
                return
            amt = int(data.get("amount", 0))
            dd  = bool(data.get("use_dd", False))
            b   = self.s["bid"]

            if role == "blue" and not b["a_done"]:
                b["a"], b["dd_a"], b["a_done"] = amt, dd, True
            elif role == "red" and not b["b_done"]:
                b["b"], b["dd_b"], b["b_done"] = amt, dd, True
            else:
                return

            await self._push()
            if b["a_done"] and b["b_done"]:
                await asyncio.sleep(1.5)
                await self._resolve()

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
