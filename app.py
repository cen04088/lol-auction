import streamlit as st
import random
import pandas as pd
import time

# 1. 페이지 설정 및 LoL 마법공학 테마 (CSS)
st.set_page_config(page_title="LoL 내전 드래프트", layout="wide", page_icon="⚔️")

st.markdown("""
    <style>
    .stApp { background: linear-gradient(to bottom, #091428, #0A0A0C); color: #F0E6D2; }
    h1, h2, h3, h4, span { color: #C89B3C !important; text-shadow: 1px 1px 2px black; }
    p, label, .stMarkdown { color: #C89B3C !important; font-weight: 600 !important; font-size: 1.1rem !important; }

    div[data-testid="stMetric"] {
        background-color: rgba(1, 10, 19, 0.9);
        border: 2px solid #C89B3C;
        padding: 10px;
        border-radius: 8px;
    }

    .lol-card { padding: 12px; border-radius: 5px; margin-bottom: 8px; font-weight: bold; display: flex; align-items: center; }
    .card-a { border: 2px solid #0AC8B9; background: rgba(10, 200, 185, 0.1); color: #0AC8B9 !important; }
    .card-b { border: 2px solid #E91E63; background: rgba(233, 30, 99, 0.1); color: #E91E63 !important; }
    .card-empty { border: 1px dashed #555; color: #777 !important; justify-content: center; font-style: italic; }

    .auction-target-box { background: radial-gradient(circle, rgba(200, 155, 60, 0.1) 0%, rgba(9, 20, 40, 0) 70%); padding: 20px; text-align: center; border-bottom: 3px solid #C89B3C; margin-bottom: 20px; }
    .auction-target-name { font-size: 4em; font-weight: 800; color: #C89B3C; text-shadow: 0 0 20px rgba(200, 155, 60, 0.8); }

    div[data-testid="stForm"] { background-color: rgba(1, 10, 19, 0.8); border: 1px solid #C89B3C; padding: 25px; border-radius: 15px; }
    
    div.stButton > button {
        background-color: #1E2328 !important; color: #C89B3C !important;
        border: 2px solid #C89B3C !important; font-size: 1.2rem !important;
        font-weight: 800 !important; height: 3.5em !important; width: 100%;
        transition: all 0.3s ease;
    }
    div.stButton > button:hover { background-color: #C89B3C !important; color: #1E2328 !important; box-shadow: 0 0 20px rgba(200, 155, 60, 0.6); }
    
    .swap-section {
        background-color: rgba(200, 155, 60, 0.05);
        border: 1px dashed #C89B3C;
        padding: 20px;
        border-radius: 10px;
        margin-top: 30px;
    }
    </style>
    """, unsafe_allow_html=True)

# 2. 세션 상태 초기화
if 'phase' not in st.session_state:
    st.session_state.phase = 'setup'
    st.session_state.team_a = {"name": "BLUE", "members": [], "points": 100, "leader": ""}
    st.session_state.team_b = {"name": "RED", "members": [], "points": 100, "leader": ""}
    st.session_state.pool = []
    st.session_state.last_msg = "드래프트를 시작하세요."

# 3. 로직 함수
def start_auction_process(names, leader_a, leader_b):
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if len(name_list) < 10:
        st.error("최소 10명이 필요합니다.")
        return

    remaining = [n for n in name_list if n != leader_a and n != leader_b]
    random.shuffle(remaining)
    
    st.session_state.team_a["leader"] = leader_a
    st.session_state.team_b["leader"] = leader_b
    st.session_state.team_a["members"] = [leader_a]
    st.session_state.team_b["members"] = [leader_b]
    st.session_state.pool = remaining
    st.session_state.phase = 'auction'

def handle_bid(val_a, val_b):
    if not (0 <= val_a <= 100) or not (0 <= val_b <= 100):
        st.toast("⚠️ 입찰액은 0~100 사이여야 합니다!", icon="❌")
        return
    if val_a > st.session_state.team_a["points"] or val_b > st.session_state.team_b["points"]:
        st.toast("❌ 포인트 부족!", icon="🚫")
        return

    player = st.session_state.pool[0]

    if val_a == val_b:
        tied_player = st.session_state.pool.pop(0)
        st.session_state.pool.append(tied_player)
        st.session_state.last_msg = f"⚠️ 동점({val_a}pt)! {tied_player}님은 명단 맨 뒤로 이동합니다."
        return

    if val_a > val_b:
        winner = st.session_state.pool.pop(0)
        st.session_state.team_a["members"].append(winner)
        st.session_state.team_a["points"] -= val_a
        st.session_state.last_msg = f"🔵 블루팀, {winner} 영입! ({val_a}pt)"
    else:
        winner = st.session_state.pool.pop(0)
        st.session_state.team_b["members"].append(winner)
        st.session_state.team_b["points"] -= val_b
        st.session_state.last_msg = f"🔴 레드팀, {winner} 영입! ({val_b}pt)"

    if len(st.session_state.team_a["members"]) == 5 or len(st.session_state.team_b["members"]) == 5:
        remaining_pool = list(st.session_state.pool)
        for p in remaining_pool:
            if len(st.session_state.team_a["members"]) < 5: st.session_state.team_a["members"].append(p)
            else: st.session_state.team_b["members"].append(p)
        st.session_state.pool = []
        st.session_state.phase = 'result'

def execute_manual_swap(line1, line2):
    try:
        # 두 라인이 다를 때만 스왑 진행
        lines_to_swap = list(set([line1, line2])) # 중복 제거
        
        for idx in lines_to_swap:
            p_a = st.session_state.team_a["members"][idx]
            p_b = st.session_state.team_b["members"][idx]
            st.session_state.team_a["members"][idx] = p_b
            st.session_state.team_b["members"][idx] = p_a
        
        st.success(f"🔄 트레이드 완료: {', '.join([str(l)+'번' for l in lines_to_swap])} 픽 라인이 교체되었습니다.")
    except Exception as e:
        st.error(f"트레이드 중 오류가 발생했습니다: {e}")

# --- 4. 메인 UI ---
st.markdown("<h1 style='text-align: center;'>⚔️ 마법공학 내전 경매 시스템 ⚔️</h1>", unsafe_allow_html=True)
st.write("---")

if st.session_state.phase == 'setup':
    col_empty1, col_form, col_empty2 = st.columns([1, 2, 1])
    with col_form:
        st.markdown("### 📝 드래프트 설정")
        names_input = st.text_area("1. 소환사 명단 입력 (쉼표 구분)", "팀원1, 팀원2, 팀원3, 팀원4, 팀원5, 팀원6, 팀원7, 팀원8, 팀원9, 팀원10")
        
        if names_input:
            name_list = [n.strip() for n in names_input.split(",") if n.strip()]
            if len(name_list) >= 2:
                c1, c2 = st.columns(2)
                l_a = c1.selectbox("🔵 블루팀 팀장 선택", name_list, index=0)
                l_b = c2.selectbox("🔴 레드팀 팀장 선택", [n for n in name_list if n != l_a], index=0)
                
                if st.button("드래프트 시작 (LOCK IN)"):
                    start_auction_process(names_input, l_a, l_b)
                    st.rerun()

else:
    col_left, col_mid, col_right = st.columns([1, 1.5, 1])

    with col_left:
        st.markdown("### <span style='color:#0AC8B9'>🔵 BLUE TEAM</span>", unsafe_allow_html=True)
        st.metric("GOLD", f"{st.session_state.team_a['points']} G")
        for i, m in enumerate(st.session_state.team_a["members"]):
            icon = "👑" if i == 0 else f"{i}픽"
            st.markdown(f'<div class="lol-card card-a">{icon} | {m}</div>', unsafe_allow_html=True)
        for _ in range(5 - len(st.session_state.team_a["members"])):
            st.markdown('<div class="lol-card card-empty">Empty</div>', unsafe_allow_html=True)

    with col_mid:
        if st.session_state.phase == 'auction':
            player = st.session_state.pool[0]
            st.markdown(f'<div class="auction-target-box"><h4>NEXT CHAMPION</h4><div class="auction-target-name">{player}</div></div>', unsafe_allow_html=True)
            st.markdown(f"<p style='text-align:center; color:#888;'>최근 결과: {st.session_state.last_msg}</p>", unsafe_allow_html=True)

            with st.form("bid_form", clear_on_submit=True):
                st.markdown("<p style='text-align:center;'>입찰 범위: 0 ~ 100 Gold</p>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                b_a_raw = c1.text_input("🔵 블루팀 입찰", type="password")
                b_b_raw = c2.text_input("🔴 레드팀 입찰", type="password")
                
                if st.form_submit_button("낙찰 확정"):
                    val_a = int(b_a_raw) if b_a_raw.strip().isdigit() else 0
                    val_b = int(b_b_raw) if b_b_raw.strip().isdigit() else 0
                    handle_bid(val_a, val_b)
                    st.rerun()
        else:
            st.markdown("<h2 style='text-align: center; color: #C89B3C;'>🏆 드래프트 완료! 🏆</h2>", unsafe_allow_html=True)
            st.markdown('<div class="swap-section">', unsafe_allow_html=True)
            st.markdown("#### 🔄 밸런스 조정: 트레이드 실행")
            
            swap_cols = st.columns(2)
            options = { "1번째 픽": 1, "2번째 픽": 2, "3번째 픽": 3, "4번째 픽": 4 }
            line_1 = swap_cols[0].selectbox("첫 번째 교체 라인", list(options.keys()), index=1)
            line_2 = swap_cols[1].selectbox("두 번째 교체 라인", list(options.keys()), index=3)
            
            # 버튼 클릭 전 중복 체크
            if line_1 == line_2:
                st.warning("동일한 라인을 선택했습니다. 서로 다른 라인을 선택해야 트레이드가 가능합니다.")
            
            if st.button("🔄 트레이드 실행", disabled=(line_1 == line_2)):
                execute_manual_swap(options[line_1], options[line_2])
                st.rerun()
                
            st.markdown('</div>', unsafe_allow_html=True)
            if st.button("전체 초기화 (새 게임)"): st.session_state.clear(); st.rerun()

    with col_right:
        st.markdown("### <span style='color:#E91E63'>🔴 RED TEAM </span>", unsafe_allow_html=True)
        st.metric("GOLD", f"{st.session_state.team_b['points']} G")
        for i, m in enumerate(st.session_state.team_b["members"]):
            icon = "👑" if i == 0 else f"{i}픽"
            st.markdown(f'<div class="lol-card card-b">{icon} | {m}</div>', unsafe_allow_html=True)
        for _ in range(5 - len(st.session_state.team_b["members"])):
            st.markdown('<div class="lol-card card-empty">Empty</div>', unsafe_allow_html=True)

