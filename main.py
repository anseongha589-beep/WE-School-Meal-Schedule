
import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import re
import html
import time
from datetime import date


# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="우리 학교 메뉴별 급식",
    page_icon="🍱",
    layout="wide"
)

st.title("🍱 우리 학교 메뉴별 급식")
st.write(
    "송탄고등학교에서 2025년 9월부터 2026년 9월까지 "
    "가장 자주 나온 중식 메뉴를 알아봅니다."
)

SCHOOL_NAME = "송탄고등학교"

ATPT_OFCDC_SC_CODE = "J10"
SD_SCHUL_CODE = "7530480"

MEAL_API = (
    "https://open.neis.go.kr/hub/mealServiceDietInfo"
)

START_DATE = "20250901"
END_DATE = "20260930"

# 한 번에 요청할 행 수
PAGE_SIZE = 1000

TIMEOUT = 30


# ==========================================
# 메뉴 이름 정리
# ==========================================

def clean_menu_name(menu):
    """
    메뉴 이름에서 HTML 태그와 알레르기 번호를 제거한다.
    """

    if not menu:
        return ""

    menu = html.unescape(str(menu))

    # HTML 태그 제거
    menu = re.sub(
        r"<[^>]*>",
        "",
        menu
    )

    menu = menu.strip()

    # 메뉴 뒤에 붙은 알레르기 번호 제거
    # 예: 달걀말이(1.2.5) -> 달걀말이
    menu = re.sub(
        r"\s*\(\s*\d+(?:\.\d+)*\s*\)\s*$",
        "",
        menu
    ).strip()

    return menu


def split_menu(menu_text):
    """
    <br/> 기준으로 메뉴를 나눈다.
    """

    if not menu_text:
        return []

    menu_text = html.unescape(str(menu_text))

    menu_text = re.sub(
        r"(?i)<br\s*/?>",
        "\n",
        menu_text
    )

    items = []

    for item in menu_text.splitlines():

        cleaned = clean_menu_name(item)

        if cleaned:
            items.append(cleaned)

    return items


# ==========================================
# 나이스 API 호출
# ==========================================

def request_meal_page(api_key, page_index):
    """
    급식 API의 특정 페이지를 요청한다.
    """

    params = {
        "KEY": api_key,
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": ATPT_OFCDC_SC_CODE,
        "SD_SCHUL_CODE": SD_SCHUL_CODE,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": START_DATE,
        "MLSV_TO_YMD": END_DATE,
        "pSize": str(PAGE_SIZE),
        "pIndex": str(page_index)
    }

    response = requests.get(
        MEAL_API,
        params=params,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    # 조회 결과가 없는 경우
    result = data.get("RESULT", {})

    if result.get("CODE") == "INFO-200":
        return [], 0

    # 다른 API 오류
    if result.get("CODE"):
        raise RuntimeError(
            f"{result.get('MESSAGE', '나이스 API 오류')} "
            f"({result.get('CODE')})"
        )

    meal_info = data.get(
        "mealServiceDietInfo",
        []
    )

    if not meal_info:
        return [], 0

    # 전체 건수 확인
    head = meal_info[0].get("head", [])

    total_count = 0

    for item in head:
        if "list_total_count" in item:
            total_count = int(
                item["list_total_count"]
            )
            break

    # 급식 행 데이터
    rows = []

    if len(meal_info) >= 2:
        rows = meal_info[1].get("row", [])

    return rows, total_count


# ==========================================
# 전체 급식 데이터 수집
# ==========================================

@st.cache_data(
    ttl=3600,
    show_spinner=False
)
def load_all_meals(api_key):
    """
    전체 건수만큼 모든 페이지를 요청한다.
    """

    all_rows = []
    page_index = 1
    total_count = None

    while True:

        rows, current_total = request_meal_page(
            api_key,
            page_index
        )

        if total_count is None:
            total_count = current_total

        # 데이터가 없는 경우
        if not rows:
            break

        all_rows.extend(rows)

        # 전체 건수를 모두 받았으면 종료
        if len(all_rows) >= total_count:
            break

        # 다음 페이지
        page_index += 1

        # API 요청 간 짧은 간격
        time.sleep(0.1)

    return all_rows, total_count or 0


# ==========================================
# 데이터 집계
# ==========================================

def make_statistics(rows):
    """
    같은 날짜에 같은 메뉴가 여러 번 있어도
    하루에 한 번만 집계한다.
    """

    records = []

    for row in rows:

        # 중식만 집계
        if row.get("MMEAL_SC_CODE") != "2":
            continue

        meal_date = row.get("MLSV_YMD", "")
        menu_text = row.get("DDISH_NM", "")

        if not meal_date:
            continue

        menus = split_menu(menu_text)

        # 같은 날짜의 중복 메뉴 제거
        unique_menus = set(menus)

        for menu in unique_menus:

            records.append({
                "날짜": meal_date,
                "메뉴": menu
            })

    if not records:
        return pd.DataFrame(), 0

    df = pd.DataFrame(records)

    # 같은 날짜와 같은 메뉴가 중복되지 않도록 처리
    df = df.drop_duplicates(
        subset=["날짜", "메뉴"]
    )

    # 급식이 등록된 날짜 수
    total_days = df["날짜"].nunique()

    # 메뉴별 등장 일수
    stats = (
        df.groupby("메뉴")["날짜"]
        .nunique()
        .reset_index(name="등장 일수")
    )

    # 전체 급식일 대비 비율
    stats["비율"] = (
        stats["등장 일수"] / total_days * 100
    )

    # 등장 일수 내림차순
    stats = stats.sort_values(
        ["등장 일수", "메뉴"],
        ascending=[False, True]
    ).reset_index(drop=True)

    stats["순위"] = range(1, len(stats) + 1)

    return stats, total_days


# ==========================================
# API 인증키 확인
# ==========================================

try:
    API_KEY = st.secrets["NEIS_API_KEY"]

except Exception:
    API_KEY = None


if not API_KEY:

    st.error(
        "NEIS_API_KEY를 Streamlit Secrets에 설정해 주세요."
    )

    st.info(
        "Streamlit Cloud의 앱 설정에서 "
        "NEIS_API_KEY를 등록하면 됩니다."
    )

    st.stop()


# ==========================================
# 데이터 불러오기
# ==========================================

st.subheader("📊 메뉴별 등장 횟수 분석")

st.caption(
    "분석 기간: 2025년 9월 1일 ~ 2026년 9월 30일"
)

try:

    with st.spinner(
        "송탄고등학교의 전체 중식 데이터를 불러오는 중입니다..."
    ):

        rows, total_count = load_all_meals(
            API_KEY
        )

except requests.exceptions.Timeout:

    st.error(
        "나이스 서버 응답 시간이 초과되었습니다. "
        "잠시 후 다시 시도해 주세요."
    )

    st.stop()

except requests.exceptions.RequestException:

    st.error(
        "나이스 서버에 연결할 수 없습니다. "
        "인터넷 연결을 확인해 주세요."
    )

    st.stop()

except Exception as e:

    st.error(
        f"급식 데이터를 불러오는 중 오류가 발생했습니다: {e}"
    )

    st.stop()


if not rows:

    st.info(
        "선택한 기간에 등록된 중식 급식 데이터가 없습니다."
    )

    st.stop()


# ==========================================
# 집계 결과 만들기
# ==========================================

stats, total_days = make_statistics(rows)

if stats.empty:

    st.info(
        "집계할 수 있는 중식 메뉴가 없습니다."
    )

    st.stop()


# ==========================================
# TOP 메뉴 슬라이더
# ==========================================

max_rank = min(50, len(stats))

selected_rank = st.slider(
    "그래프에 표시할 메뉴 순위",
    min_value=1,
    max_value=max_rank,
    value=min(10, max_rank),
    step=1
)

top_menus = stats.head(
    selected_rank
).copy()


# ==========================================
# 큰 숫자 카드
# ==========================================

first_menu = stats.iloc[0]

first_menu_name = first_menu["메뉴"]
first_menu_days = int(first_menu["등장 일수"])
first_menu_ratio = float(first_menu["비율"])

st.subheader("🏆 분석 결과")

metric1, metric2, metric3 = st.columns(3)

with metric1:
    st.metric(
        "집계한 날수",
        f"{total_days:,}일"
    )

with metric2:
    st.metric(
        "1위 메뉴",
        first_menu_name
    )

with metric3:
    st.metric(
        "1위 메뉴 비율",
        f"{first_menu_ratio:.1f}%"
    )


st.divider()


# ==========================================
# 가로 막대그래프
# ==========================================

st.subheader(
    f"🥇 자주 나온 메뉴 TOP {selected_rank}"
)

# 그래프는 1위가 위에 오도록 순서를 뒤집는다.
chart_df = top_menus.sort_values(
    "등장 일수",
    ascending=True
).copy()

chart_df["순위 메뉴"] = (
    chart_df["순위"].astype(str)
    + "위 "
    + chart_df["메뉴"]
)

# 값이 클수록 진한 색
fig = px.bar(
    chart_df,
    x="등장 일수",
    y="순위 메뉴",
    orientation="h",
    color="등장 일수",
    color_continuous_scale="Blues",
    text="등장 일수",
    hover_data={
        "메뉴": True,
        "등장 일수": True,
        "비율": ":.1f",
        "순위 메뉴": False
    },
    labels={
        "등장 일수": "등장 일수",
        "순위 메뉴": "메뉴"
    }
)

fig.update_traces(
    texttemplate="%{text}일",
    textposition="outside",
    cliponaxis=False
)

fig.update_layout(
    height=max(450, selected_rank * 42),
    coloraxis_showscale=False,
    yaxis={
        "title": "",
        "categoryorder": "array",
        "categoryarray": chart_df["순위 메뉴"].tolist()
    },
    xaxis={
        "title": "등장 일수",
        "rangemode": "tozero"
    },
    margin={
        "l": 20,
        "r": 60,
        "t": 20,
        "b": 20
    }
)

st.plotly_chart(
    fig,
    use_container_width=True
)


# ==========================================
# 메뉴별 등장 일수와 비율
# ==========================================

st.subheader("📋 메뉴별 등장 일수와 비율")

display_df = top_menus[
    ["순위", "메뉴", "등장 일수", "비율"]
].copy()

display_df["비율"] = display_df["비율"].map(
    lambda value: f"{value:.1f}%"
)

display_df = display_df.rename(
    columns={
        "순위": "순위",
        "메뉴": "메뉴 이름",
        "등장 일수": "등장 일수",
        "비율": "비율"
    }
)

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True
)


# ==========================================
# 안내
# ==========================================

st.divider()

st.caption(
    "※ 같은 날 같은 메뉴가 여러 번 기록되어도 하루로 계산합니다."
)

st.caption(
    "※ 비율은 해당 기간에 급식이 등록된 날짜 수를 기준으로 계산합니다."
)

st.caption(
    "※ 메뉴 이름 뒤 괄호 속 알레르기 번호는 집계에서 제거합니다."
)

st.caption(
    "자료 출처: 나이스 교육정보 개방 포털"
)
