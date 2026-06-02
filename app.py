import streamlit as st
import random
import pandas as pd
import time as _time

st.set_page_config(page_title="롤 내전 경매 시스템", layout="wide", page_icon="⚔️")

st.markdown("""
    <style>
    .stApp { background: linear-gradient(to bottom, #091428, #0A0A0C); color: #F0E6D2; }
    h1, h2, h3, h4, span { color: #C89B3C !important; text-shadow: 1px 1px 2px black; }
    p, label, .stMarkdown { color: #C89B3C !important; font-weight: 600 !important; font-size: 1.05rem !important; }

    div[data-testid="stMetric"] {
        background-color: rgba(1, 10, 19, 0.9);
        border: 2px solid #C89B3C; padding: 10px; border-radius: 8px;
    }
    .lol-card {
        padding: 10px 14px; border-radius: 5px; margin-bottom: 6px;
        font-weight: bold; display: flex; align-items: center;
    }
    .card-a   { border: 2px solid #0AC8B9; background: rgba(10,200,185,0.1); color: #0AC8B9 !important; }
    .card-b   { border: 2px solid #E91E63; background: rgba(233,30,99,0.1);  color: #E91E63 !important; }
    .card-empty { border: 1px dashed #555; color: #777 !important; justify-content: center; font-style: italic; }

    .auction-target-box {
        background: radial-gradient(circle, rgba(200,155,60,0.12) 0%, rgba(9,20,40,0) 70%);
        padding: 16px; text-align: center;
        border-bottom: 3px solid #C89B3C; margin-bottom: 10px;
    }
    .auction-target-name {
        font-size: 2.6em; font-weight: 800; color: #C89B3C;
        text-shadow: 0 0 20px rgba(200,155,60,0.8);
    }
    .timer-box {
        border-radius: 8px; padding: 10px 16px;
        text-align: center; margin-bottom: 10px;
    }
    .bid-area {
        background: rgba(1,10,19,0.8); border: 1px solid #C89B3C;
        padding: 16px; border-radius: 12px; margin-bottom: 10px;
    }
    .dd-badge {
        border-radius: 6px; padding: 6px 10px; text-align: center;
        font-size: 0.85em; font-weight: bold; margin-bottom: 8px;
    }
    div.stButton > button {
        background-color: #1E2328 !important; color: #C89B3C !important;
        border: 2px solid #C89B3C !important; font-size: 1.0rem !important;
        font-weight: 800 !important; min-height: 3.0em !important; width: 100%;
        transition: all 0.3s ease; text-align: left !important;
    }
    div.stButton > button:hover {
        background-color: #C89B3C !important; color: #1E2328 !important;
        box-shadow: 0 0 20px rgba(200,155,60,0.6);
    }
    .swap-section {
        background-color: rgba(200,155,60,0.05);
        border: 1px dashed #C89B3C; padding: 20px;
        border-radius: 10px; margin-top: 20px;
    }
    .history-item {
        padding: 5px 10px; border-radius: 4px; margin-bottom: 4px;
        font-size: 0.85em; font-weight: 600; border-left: 3px solid;
        color: #C89B3C !important;
    }
    .hist-blue { border-color: #0AC8B9 !important; background: rgba(10,200,185,0.07) !important; }
    .hist-red  { border-color: #E91E63 !important; background: rgba(233,30,99,0.07) !important; }
    .hist-tie  { border-color: #C89B3C !important; background: rgba(200,155,60,0.07) !important; }
    .trade-status {
        text-align: center; padding: 14px 10px; border-radius: 10px;
        border: 2px solid #C89B3C; background: rgba(200,155,60,0.08);
        margin-bottom: 14px;
    }
    </style>
""", unsafe_allow_html=True)

# ── 상수 ──────────────────────────────────────────────────────────────────────
TIERS = ["언랭", "아이언", "브론즈", "실버", "골드", "플래티넘", "에메랄드", "다이아", "마스터", "그랜드마스터", "챌린저"]
TIER_COLORS = {
    "언랭": "#888888", "아이언": "#8B6355", "브론즈": "#AD5600",
    "실버": "#A0A9B8", "골드": "#C89B3C", "플래티넘": "#00B4A0",
    "에메랄드": "#00C060", "다이아": "#576BCE", "마스터": "#9D4DC3",
    "그랜드마스터": "#CF3F3F", "챌린저": "#F4C874",
}
POSITIONS = ["미정", "탑", "정글", "미드", "원딜", "서폿"]
POS_ICON  = {"미정": "❓", "탑": "🛡️", "정글": "🌿", "미드": "⚡", "원딜": "🏹", "서폿": "💙"}

# ── 세션 초기화 ────────────────────────────────────────────────────────────────
def _init():
    defaults = {
        'phase': 'setup',
        'team_a': {"members": [], "points": 100},
        'team_b': {"members": [], "points": 100},
        'pool': [],
        'last_msg': "드래프트를 시작하세요.",
        'history': [],
        'starting_points': 100,
        'tie_mode': 'random',
        'bid_mode': 'public',        # 공개 입찰 기본값
        'all_players': {},
        # 트레이드
        'trade_mode': False,
        'sel_a': [],
        'sel_b': [],
        # 타이머
        'bid_start_time': None,
        'last_bid_player': None,
        'timer_duration': 30,
        # 더블다운
        'dd_a_used': False,
        'dd_b_used': False,
        # 블러핑
        'bluff_mode': False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────
def pinfo(name):
    return st.session_state.all_players.get(name, {"tier": "언랭", "position": "미정"})

def card_html(name, team, idx):
    d   = pinfo(name)
    tc  = TIER_COLORS.get(d["tier"], "#888")
    pi  = POS_ICON.get(d["position"], "❓")
    icon = "👑" if idx == 0 else str(idx)
    css  = "card-a" if team == 'a' else "card-b"
    return (
        f'<div class="lol-card {css}" style="justify-content:space-between">'
        f'<span style="min-width:26px">{icon}</span>'
        f'<span style="flex:1;margin:0 8px">{name}</span>'
        f'<span style="color:{tc};font-size:0.8em;margin-right:6px">{d["tier"]}</span>'
        f'<span style="font-size:0.85em;color:#aaa">{pi} {d["position"]}</span>'
        f'</div>'
    )

def bluff(val):
    """블러핑 모드: 표시 금액을 ±3pt 범위로 왜곡"""
    if st.session_state.bluff_mode:
        return max(0, val + random.randint(-3, 3))
    return val

# ── 게임 로직 ──────────────────────────────────────────────────────────────────
def start_auction(players, leader_a, leader_b, sp, tie_mode, bid_mode,
                  timer_dur, bluff_mode):
    names = [p["name"] for p in players]
    if len(names) != 10 or len(set(names)) != 10:
        st.error("정확히 10명의 고유한 소환사명이 필요합니다."); return False
    if not leader_a or not leader_b or leader_a == leader_b:
        st.error("팀장을 올바르게 선택해주세요."); return False

    st.session_state.all_players = {
        p["name"]: {"tier": p["tier"], "position": p["position"]} for p in players
    }
    pool = [p["name"] for p in players if p["name"] not in (leader_a, leader_b)]
    random.shuffle(pool)

    st.session_state.team_a         = {"members": [leader_a], "points": sp}
    st.session_state.team_b         = {"members": [leader_b], "points": sp}
    st.session_state.pool           = pool
    st.session_state.starting_points = sp
    st.session_state.tie_mode       = tie_mode
    st.session_state.bid_mode       = bid_mode
    st.session_state.timer_duration = timer_dur
    st.session_state.bluff_mode     = bluff_mode
    st.session_state.phase          = 'auction'
    st.session_state.history        = []
    st.session_state.last_msg       = "첫 번째 경매를 시작합니다!"
    st.session_state.dd_a_used      = False
    st.session_state.dd_b_used      = False
    st.session_state.bid_start_time = _time.time()
    st.session_state.last_bid_player = pool[0] if pool else None
    return True


def _finish_if_needed():
    if len(st.session_state.team_a["members"]) == 5 or \
       len(st.session_state.team_b["members"]) == 5:
        for p in list(st.session_state.pool):
            if len(st.session_state.team_a["members"]) < 5:
                st.session_state.team_a["members"].append(p)
            else:
                st.session_state.team_b["members"].append(p)
        st.session_state.pool = []
        st.session_state.phase = 'result'


def handle_bid(val_a, val_b, dd_a=False, dd_b=False, timer_forced=False):
    pts_a = st.session_state.team_a["points"]
    pts_b = st.session_state.team_b["points"]

    # ── 더블다운 적용 ──────────────────────────────────────────────────────
    actual_a, used_dd_a = val_a, False
    actual_b, used_dd_b = val_b, False

    if dd_a and not st.session_state.dd_a_used:
        actual_a  = min(val_a * 2, pts_a)
        used_dd_a = True
    if dd_b and not st.session_state.dd_b_used:
        actual_b  = min(val_b * 2, pts_b)
        used_dd_b = True

    # ── 유효성 검사 (타이머 강제 제출은 건너뜀) ──────────────────────────
    if not timer_forced:
        if not (0 <= val_a <= pts_a):
            st.toast("❌ 블루팀 입찰 오류!", icon="🚫"); return
        if not (0 <= val_b <= pts_b):
            st.toast("❌ 레드팀 입찰 오류!", icon="🚫"); return
        if pts_a > 0 and actual_a == 0:
            st.toast("⚠️ 블루팀: 최소 1pt 이상 입찰해야 합니다!", icon="⚠️"); return
        if pts_b > 0 and actual_b == 0:
            st.toast("⚠️ 레드팀: 최소 1pt 이상 입찰해야 합니다!", icon="⚠️"); return

    if used_dd_a: st.session_state.dd_a_used = True
    if used_dd_b: st.session_state.dd_b_used = True

    # ── 블러핑 적용 (표시용) ──────────────────────────────────────────────
    disp_a   = bluff(actual_a)
    disp_b   = bluff(actual_b)
    bluff_tag   = " 🎭" if st.session_state.bluff_mode and not timer_forced else ""
    timer_tag   = "⏱️ 시간초과!  " if timer_forced else ""
    dd_icon_a   = "💥" if used_dd_a else ""
    dd_icon_b   = "💥" if used_dd_b else ""

    player = st.session_state.pool[0]

    # ── 낙찰 처리 ─────────────────────────────────────────────────────────
    if actual_a == actual_b:
        if st.session_state.tie_mode == 'random':
            p = st.session_state.pool.pop(0)
            if random.choice([True, False]):
                st.session_state.team_a["members"].append(p)
                st.session_state.team_a["points"] -= actual_a
                msg   = f"{timer_tag}⚔️ 동점→랜덤: 🔵{dd_icon_a} 블루팀이 {p} 영입! ({disp_a}pt vs {disp_b}pt){bluff_tag}"
                htype = "blue"
            else:
                st.session_state.team_b["members"].append(p)
                st.session_state.team_b["points"] -= actual_b
                msg   = f"{timer_tag}⚔️ 동점→랜덤: 🔴{dd_icon_b} 레드팀이 {p} 영입! ({disp_b}pt vs {disp_a}pt){bluff_tag}"
                htype = "red"
        else:
            p = st.session_state.pool.pop(0)
            st.session_state.pool.append(p)
            msg   = f"{timer_tag}⚠️ 동점({disp_a}pt)! {p}님은 맨 뒤로 이동합니다."
            htype = "tie"
    elif actual_a > actual_b:
        p = st.session_state.pool.pop(0)
        st.session_state.team_a["members"].append(p)
        st.session_state.team_a["points"] -= actual_a
        msg   = f"🔵{dd_icon_a} 블루팀, {p} 영입! ({disp_a}pt vs {disp_b}pt){bluff_tag}"
        htype = "blue"
    else:
        p = st.session_state.pool.pop(0)
        st.session_state.team_b["members"].append(p)
        st.session_state.team_b["points"] -= actual_b
        msg   = f"🔴{dd_icon_b} 레드팀, {p} 영입! ({disp_b}pt vs {disp_a}pt){bluff_tag}"
        htype = "red"

    st.session_state.last_msg = msg
    st.session_state.history.append({"result": msg, "type": htype})

    # 다음 선수용 타이머 리셋
    if st.session_state.pool:
        st.session_state.bid_start_time  = _time.time()
        st.session_state.last_bid_player = st.session_state.pool[0]

    _finish_if_needed()


def execute_multi_trade():
    sa = list(st.session_state.sel_a)
    sb = list(st.session_state.sel_b)
    ma = st.session_state.team_a["members"]
    mb = st.session_state.team_b["members"]
    idx_a  = sorted([ma.index(n) for n in sa])
    idx_b  = sorted([mb.index(n) for n in sb])
    vals_a = [ma[i] for i in idx_a]
    vals_b = [mb[i] for i in idx_b]
    for i, new in zip(idx_a, vals_b): ma[i] = new
    for i, new in zip(idx_b, vals_a): mb[i] = new
    st.session_state.trade_mode = False
    st.session_state.sel_a = []
    st.session_state.sel_b = []


def render_history():
    for h in reversed(st.session_state.history):
        css = {"blue": "hist-blue", "red": "hist-red", "tie": "hist-tie"}.get(h["type"], "hist-tie")
        st.markdown(f'<div class="history-item {css}">{h["result"]}</div>', unsafe_allow_html=True)


# ── 메인 UI ────────────────────────────────────────────────────────────────────
st.markdown("<h1 style='text-align:center'>⚔️ 롤 내전 경매 시스템 ⚔️</h1>", unsafe_allow_html=True)
st.write("---")

# ════════════════════════════════════════
#  SETUP
# ════════════════════════════════════════
if st.session_state.phase == 'setup':
    _, col_form, _ = st.columns([0.3, 3, 0.3])
    with col_form:
        st.markdown("### 📝 드래프트 설정")

        # 행 1: 기본 설정
        c1, c2, c3 = st.columns(3)
        sp       = c1.slider("💰 시작 포인트", 50, 200, 100, 10)
        tie_raw  = c2.radio("⚔️ 동점 처리", ["랜덤 결정", "뒤로 이동"], horizontal=True)
        bid_raw  = c3.radio("🎲 입찰 방식", ["공개", "비공개"], horizontal=True)
        tie_mode = "random" if tie_raw == "랜덤 결정" else "reshuffle"
        bid_mode = "public" if bid_raw == "공개"      else "sealed"

        # 행 2: 타이머 + 블러핑
        c4, c5 = st.columns(2)
        timer_dur  = c4.slider("⏱️ 입찰 타이머 (초)", 10, 60, 30, 5)
        bluff_mode = c5.toggle(
            "🎭 블러핑 모드",
            value=False,
            help="낙찰 후 표시되는 금액이 실제와 ±3pt 다르게 보입니다. 남은 포인트 추측을 방해합니다."
        )

        st.markdown("#### 👥 선수 등록 (정확히 10명)")
        default_df = pd.DataFrame({
            "소환사명": [""] * 10,
            "티어":    ["언랭"] * 10,
            "포지션":  ["미정"] * 10,
        })
        edited_df = st.data_editor(
            default_df,
            column_config={
                "소환사명": st.column_config.TextColumn("소환사명"),
                "티어":    st.column_config.SelectboxColumn("티어",   options=TIERS),
                "포지션":  st.column_config.SelectboxColumn("포지션", options=POSITIONS),
            },
            num_rows="fixed", use_container_width=True, height=420,
            key="player_editor",
        )

        valid      = edited_df[edited_df["소환사명"].notna() & (edited_df["소환사명"].str.strip() != "")]
        names_list = [n.strip() for n in valid["소환사명"]]
        n, has_dup = len(names_list), len(set(names_list)) < len(names_list)

        l_a = l_b = None
        if n >= 2:
            st.markdown("#### 🏆 팀장 선택")
            c1, c2 = st.columns(2)
            l_a    = c1.selectbox("🔵 블루팀 팀장", names_list)
            opts_b = [x for x in names_list if x != l_a]
            l_b    = c2.selectbox("🔴 레드팀 팀장", opts_b) if opts_b else None

        if n < 10:
            st.info(f"정확히 10명을 입력해주세요. ({n}/10명)")
        elif has_dup:
            st.warning("중복된 소환사명이 있습니다.")
        elif l_a and l_b:
            if st.button("🚀 드래프트 시작 (LOCK IN)", use_container_width=True):
                players_data = [{
                    "name":     row["소환사명"].strip(),
                    "tier":     row["티어"]   if pd.notna(row["티어"])   else "언랭",
                    "position": row["포지션"] if pd.notna(row["포지션"]) else "미정",
                } for _, row in valid.iterrows()]
                if start_auction(players_data, l_a, l_b, sp, tie_mode, bid_mode,
                                 timer_dur, bluff_mode):
                    st.rerun()

# ════════════════════════════════════════
#  AUCTION  +  RESULT
# ════════════════════════════════════════
else:
    sp         = st.session_state.starting_points
    ma         = st.session_state.team_a["members"]
    mb         = st.session_state.team_b["members"]
    trade_mode = st.session_state.trade_mode

    col_l, col_m, col_r = st.columns([1, 1.5, 1])

    # ── LEFT: BLUE TEAM ──────────────────────────────────────────────────────
    with col_l:
        na_sel  = len(st.session_state.sel_a)
        badge_a = f"  <span style='font-size:0.75em'>({na_sel}명 선택)</span>" if trade_mode else ""
        st.markdown(f"### <span style='color:#0AC8B9'>🔵 BLUE TEAM{badge_a}</span>",
                    unsafe_allow_html=True)
        pts_a   = st.session_state.team_a["points"]
        spent_a = sp - pts_a
        st.metric("GOLD", f"{pts_a} G", delta=f"-{spent_a} 소모" if spent_a else "0 소모")

        # 더블다운 상태 배지
        if st.session_state.phase == 'auction':
            if st.session_state.dd_a_used:
                st.markdown('<div class="dd-badge" style="border:1px solid #555;color:#555">💥 더블다운 사용됨</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown('<div class="dd-badge" style="border:1px solid #C89B3C;color:#C89B3C">💥 더블다운 대기 중</div>',
                            unsafe_allow_html=True)

        for i, m in enumerate(ma):
            if trade_mode:
                is_sel    = m in st.session_state.sel_a
                d         = pinfo(m)
                icon      = "👑" if i == 0 else str(i)
                pi        = POS_ICON.get(d["position"], "❓")
                indicator = "✅" if is_sel else "⬜"
                label     = f"{indicator}  {icon} │ {m}   {d['tier']}  {pi}{d['position']}"
                if st.button(label, key=f"sel_a_{i}", use_container_width=True):
                    if is_sel: st.session_state.sel_a.remove(m)
                    else:      st.session_state.sel_a.append(m)
                    st.rerun()
            else:
                st.markdown(card_html(m, 'a', i), unsafe_allow_html=True)

        if not trade_mode:
            for _ in range(5 - len(ma)):
                st.markdown('<div class="lol-card card-empty">Empty Slot</div>', unsafe_allow_html=True)

    # ── CENTER ───────────────────────────────────────────────────────────────
    with col_m:
        if st.session_state.phase == 'auction':
            player = st.session_state.pool[0]
            d      = pinfo(player)
            tc     = TIER_COLORS.get(d["tier"], "#888")
            pi     = POS_ICON.get(d["position"], "❓")

            # 타이머 초기화 (새 선수 등장 시)
            if st.session_state.get('last_bid_player') != player:
                st.session_state.bid_start_time  = _time.time()
                st.session_state.last_bid_player = player
            if st.session_state.bid_start_time is None:
                st.session_state.bid_start_time = _time.time()

            elapsed   = _time.time() - st.session_state.bid_start_time
            remaining = max(0, st.session_state.timer_duration - int(elapsed))
            pct       = int(100 * remaining / max(st.session_state.timer_duration, 1))

            # 타이머 색상: 초록 → 노란 → 빨강
            if remaining > st.session_state.timer_duration * 0.5:
                tcol = "#00C060"
            elif remaining > st.session_state.timer_duration * 0.2:
                tcol = "#C89B3C"
            else:
                tcol = "#CF3F3F"

            # ── 타이머 UI ──
            st.markdown(f"""
            <div class="timer-box" style="border:2px solid {tcol};background:rgba(0,0,0,0.35)">
                <span style="color:{tcol};font-size:2.2em;font-weight:900">⏱️ {remaining}s</span>
                <div style="background:#333;border-radius:3px;height:6px;margin-top:6px">
                    <div style="background:{tcol};width:{pct}%;height:100%;border-radius:3px"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ── 경매 대상 선수 ──
            st.markdown(f"""
            <div class="auction-target-box">
                <h4>NEXT CHAMPION</h4>
                <div class="auction-target-name">{player}</div>
                <div style="margin-top:8px">
                    <span style="color:{tc};font-size:1.1em;font-weight:bold">{d['tier']}</span>
                    &nbsp;&nbsp;
                    <span style="color:#aaa;font-size:1.1em">{pi} {d['position']}</span>
                </div>
                <div style="color:#666;font-size:0.85em;margin-top:4px">남은 선수: {len(st.session_state.pool)}명</div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(
                f"<p style='text-align:center;color:#888;font-size:0.88em'>최근: {st.session_state.last_msg}</p>",
                unsafe_allow_html=True,
            )

            # ── 입찰 영역 ──
            pts_a  = st.session_state.team_a["points"]
            pts_b  = st.session_state.team_b["points"]
            sealed = (st.session_state.bid_mode == 'sealed')
            itype  = "password" if sealed else "default"

            mode_tag = ("🔒 비공개" if sealed else "🔓 공개")
            if st.session_state.bluff_mode: mode_tag += " · 🎭 블러핑 ON"
            st.markdown(f"<p style='text-align:center;font-size:0.9em'>{mode_tag}</p>",
                        unsafe_allow_html=True)

            st.markdown('<div class="bid-area">', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            c1.markdown(f"<p style='color:#0AC8B9;text-align:center;margin:0'>🔵 잔여: {pts_a}G</p>",
                        unsafe_allow_html=True)
            c2.markdown(f"<p style='color:#E91E63;text-align:center;margin:0'>🔴 잔여: {pts_b}G</p>",
                        unsafe_allow_html=True)

            # 입찰값 입력 (form 밖: 1초 자동 갱신 시 입력값 유지)
            b_a = c1.text_input("🔵 블루팀 입찰", type=itype,
                                 placeholder=f"1 ~ {pts_a}", key="bid_val_a")
            b_b = c2.text_input("🔴 레드팀 입찰", type=itype,
                                 placeholder=f"1 ~ {pts_b}", key="bid_val_b")

            # ── 더블다운 체크박스 ──
            c1, c2 = st.columns(2)
            dd_a_lbl = "💥 더블다운 (사용됨)" if st.session_state.dd_a_used else "💥 더블다운 사용!"
            dd_b_lbl = "💥 더블다운 (사용됨)" if st.session_state.dd_b_used else "💥 더블다운 사용!"
            dd_a = c1.checkbox(dd_a_lbl, disabled=st.session_state.dd_a_used, key="dd_chk_a")
            dd_b = c2.checkbox(dd_b_lbl, disabled=st.session_state.dd_b_used, key="dd_chk_b")

            if dd_a:
                c1.caption(f"📢 실제 입찰액 × 2 (최대 {pts_a}G)")
            if dd_b:
                c2.caption(f"📢 실제 입찰액 × 2 (최대 {pts_b}G)")

            st.markdown('</div>', unsafe_allow_html=True)

            # ── 낙찰 확정 버튼 ──
            if st.button("⚡ 낙찰 확정", use_container_width=True):
                raw_a = st.session_state.get("bid_val_a", "")
                raw_b = st.session_state.get("bid_val_b", "")
                va = int(raw_a.strip()) if raw_a.strip().lstrip('-').isdigit() else -1
                vb = int(raw_b.strip()) if raw_b.strip().lstrip('-').isdigit() else -1
                handle_bid(va, vb, dd_a=dd_a, dd_b=dd_b)
                # 입력 초기화
                st.session_state.bid_val_a = ""
                st.session_state.bid_val_b = ""
                st.session_state.dd_chk_a  = False
                st.session_state.dd_chk_b  = False
                st.rerun()

            if st.session_state.history:
                with st.expander(f"📋 경매 기록 ({len(st.session_state.history)}건)"):
                    render_history()

            # ── 타이머 자동 처리 ──
            # 만료: 0pt 강제 제출 → 낙찰 처리
            # 진행 중: 1초 후 자동 갱신
            if remaining == 0:
                handle_bid(0, 0, timer_forced=True)
                st.session_state.bid_val_a = ""
                st.session_state.bid_val_b = ""
                st.rerun()
            else:
                _time.sleep(1)
                st.rerun()

        else:  # result
            st.markdown("<h2 style='text-align:center;color:#C89B3C'>🏆 드래프트 완료! 🏆</h2>",
                        unsafe_allow_html=True)

            if st.session_state.history:
                with st.expander("📋 전체 경매 기록"):
                    render_history()

            st.markdown('<div class="swap-section">', unsafe_allow_html=True)
            st.markdown("#### 🔄 밸런스 트레이드")

            if trade_mode:
                na_sel = len(st.session_state.sel_a)
                nb_sel = len(st.session_state.sel_b)
                can_swap     = (na_sel == nb_sel and na_sel > 0)
                border_color = "#00C060" if can_swap else "#C89B3C"
                status_txt   = (
                    f"🔵 {na_sel}명 ↔ 🔴 {nb_sel}명  ✅ 교환 가능!" if can_swap
                    else f"🔵 {na_sel}명 선택 ↔ 🔴 {nb_sel}명 선택  (수를 맞춰주세요)"
                )
                st.markdown(
                    f'<div class="trade-status" style="border-color:{border_color}">'
                    f'<span style="color:{border_color};font-size:1.05em">{status_txt}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.caption("양 팀 카드를 클릭해 선수를 선택하세요 (1:1, 2:2, 최대 5:5)")
                if st.button("✅ 교환 확정", disabled=not can_swap, use_container_width=True):
                    execute_multi_trade()
                    st.rerun()
                if st.button("❌ 취소", use_container_width=True):
                    st.session_state.trade_mode = False
                    st.session_state.sel_a = []
                    st.session_state.sel_b = []
                    st.rerun()
            else:
                st.caption("팀장 포함 원하는 선수를 클릭해 선택 후 교환")
                if st.button("🔄 트레이드 시작", use_container_width=True):
                    st.session_state.trade_mode = True
                    st.session_state.sel_a = []
                    st.session_state.sel_b = []
                    st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)
            st.write("")
            if not trade_mode:
                if st.button("🔁 전체 초기화 (새 게임)", use_container_width=True):
                    st.session_state.clear()
                    st.rerun()

    # ── RIGHT: RED TEAM ──────────────────────────────────────────────────────
    with col_r:
        nb_sel  = len(st.session_state.sel_b)
        badge_b = f"  <span style='font-size:0.75em'>({nb_sel}명 선택)</span>" if trade_mode else ""
        st.markdown(f"### <span style='color:#E91E63'>🔴 RED TEAM{badge_b}</span>",
                    unsafe_allow_html=True)
        pts_b   = st.session_state.team_b["points"]
        spent_b = sp - pts_b
        st.metric("GOLD", f"{pts_b} G", delta=f"-{spent_b} 소모" if spent_b else "0 소모")

        if st.session_state.phase == 'auction':
            if st.session_state.dd_b_used:
                st.markdown('<div class="dd-badge" style="border:1px solid #555;color:#555">💥 더블다운 사용됨</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown('<div class="dd-badge" style="border:1px solid #C89B3C;color:#C89B3C">💥 더블다운 대기 중</div>',
                            unsafe_allow_html=True)

        for i, m in enumerate(mb):
            if trade_mode:
                is_sel    = m in st.session_state.sel_b
                d         = pinfo(m)
                icon      = "👑" if i == 0 else str(i)
                pi        = POS_ICON.get(d["position"], "❓")
                indicator = "✅" if is_sel else "⬜"
                label     = f"{indicator}  {icon} │ {m}   {d['tier']}  {pi}{d['position']}"
                if st.button(label, key=f"sel_b_{i}", use_container_width=True):
                    if is_sel: st.session_state.sel_b.remove(m)
                    else:      st.session_state.sel_b.append(m)
                    st.rerun()
            else:
                st.markdown(card_html(m, 'b', i), unsafe_allow_html=True)

        if not trade_mode:
            for _ in range(5 - len(mb)):
                st.markdown('<div class="lol-card card-empty">Empty Slot</div>', unsafe_allow_html=True)
