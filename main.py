from datetime import dateimport re
import html
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="날짜별 중식 단백질 함량",
    page_icon="🥚",
    layout="wide"
)

st.title("🥚 나는 어느 날에 단백질 함량이 높을까?")
st.write(
    "송탄고등학교의 날짜별 중식 단백질 함량을 비교해 보세요."
)

API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

OFFICE_CODE = "J10"
SCHOOL_CODE = "7530480"

KOREA_TZ = ZoneInfo("Asia/Seoul")
TODAY = datetime.now(KOREA_TZ).date()

TIMEOUT = 20


# ==========================================
# 날짜와 영양정보 처리
# ==========================================

def parse_protein(nutrition_text):
    """
    NTR_INFO에서 단백질(g) 값을 추출한다.
    예: 단백질(g) : 48.5
    """

    if not nutrition_text:
        return None

    text = html.unescape(str(nutrition_text))

    # 영양정보 항목을 줄 단위로 분리
    text = re.sub(
        r"(?i)<br\s*/?>",
        "\n",
        text
    )

    text = re.sub(
        r"<[^>]*>",
        "",
        text
    )

    for line in text.splitlines():

        if "단백질" not in line:
            continue

        match = re.search(
            r"단백질\s*\(\s*g\s*\)\s*:\s*([0-9]+(?:\.[0-9]+)?)",
            line
        )

        if match:
            return float(match.group(1))

    return None


def parse_menu(menu_text):
    """
    메뉴 문자열을 줄 단위로 나눈다.
    """

    if not menu_text:
        return []

    text = html.unescape(str(menu_text))

    text = re.sub(
        r"(?i)<br\s*/?>",
        "\n",
        text
    )

    text = re.sub(
        r"<[^>]*>",
        "",
        text
    )

    return [
        item.strip()
        for item in text.splitlines()
        if item.strip()
    ]


# ==========================================
# 나이스 API 조회
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def load_meals(start_date, end_date, api_key):

    all_rows = []
    page = 1
    total_count = None
    page_size = 1000

    while True:

        params = {
            "KEY": api_key,
            "Type": "json",
            "pIndex": page,
            "pSize": page_size,
            "ATPT_OFCDC_SC_CODE": OFFICE_CODE,
            "SD_SCHUL_CODE": SCHOOL_CODE,
            "MMEAL_SC_CODE": "2",
            "MLSV_FROM_YMD": start_date,
            "MLSV_TO_YMD": end_date
        }

        response = requests.get(
            API_URL,
            params=params,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        # 조회 결과 없음
        result = data.get("RESULT", {})

        if result.get("CODE") == "INFO-200":
            return []

        if result.get("CODE"):
            raise ValueError(
                f"{result.get('MESSAGE', '나이스 API 오류')} "
                f"({result.get('CODE')})"
            )

        meal_info = data.get(
            "mealServiceDietInfo",
            []
        )

        if not meal_info:
            return all_rows

        # 첫 페이지에서 전체 건수 확인
        if total_count is None:

            head = meal_info[0].get("head", [])

            total_count = next(
                (
                    int(item["list_total_count"])
                    for item in head
                    if "list_total_count" in item
                ),
                0
            )

        if len(meal_info) < 2:
            break

        rows = meal_info[1].get("row", [])

        if not rows:
            break

        all_rows.extend(rows)

        # 전체 건수를 모두 받았으면 종료
        if len(all_rows) >= total_count:
            break

        page += 1

    return all_rows


# ==========================================
# 데이터프레임 만들기
# ==========================================

def make_dataframe(rows):

    records = []

    for row in rows:

        # 중식만 사용
        if row.get("MMEAL_SC_CODE") != "2":
            continue

        date_text = row.get("MLSV_YMD", "")
        protein = parse_protein(
            row.get("NTR_INFO", "")
        )

        if not date_text or protein is None:
            continue

        try:
            meal_date = pd.to_datetime(
                date_text,
                format="%Y%m%d"
            )
        except ValueError:
            continue

        menus = parse_menu(
            row.get("DDISH_NM", "")
        )

        records.append({
            "날짜": meal_date,
            "단백질 함량(g)": protein,
            "메뉴": ", ".join(menus)
        })

    df = pd.DataFrame(records)

    if df.empty:
        return df

    # 같은 날짜에 중식 데이터가 여러 건이면
    # 해당 날짜의 단백질 합계로 표시
    df = (
        df.groupby("날짜", as_index=False)
        .agg({
            "단백질 함량(g)": "sum",
            "메뉴": lambda values: " / ".join(values)
        })
    )

    df = df.sort_values("날짜")

    return df


# ==========================================
# 인증키 확인
# ==========================================

try:
    API_KEY = st.secrets["NEIS_API_KEY"]

except Exception:
    st.error(
        "Streamlit Secrets에 NEIS_API_KEY를 등록해 주세요."
    )
    st.stop()


# ==========================================
# 날짜 선택
# ==========================================

st.subheader("📅 조회 기간")

date_col1, date_col2 = st.columns(2)

with date_col1:
    start_date = st.date_input(
        "시작 날짜",
        value=date(2025, 9, 1),
        max_value=TODAY
    )

with date_col2:
    end_date = st.date_input(
        "끝 날짜",
        value=TODAY,
        min_value=start_date,
        max_value=TODAY
    )

if start_date > end_date:
    st.warning("시작 날짜가 끝 날짜보다 늦을 수 없습니다.")
    st.stop()


# ==========================================
# 데이터 조회
# ==========================================

try:

    with st.spinner("급식 영양정보를 불러오는 중입니다..."):

        rows = load_meals(
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            API_KEY
        )

except requests.exceptions.Timeout:
    st.error("나이스 서버 응답 시간이 초과되었습니다.")
    st.stop()

except requests.exceptions.RequestException:
    st.error("나이스 서버에 연결할 수 없습니다.")
    st.stop()

except Exception as error:
    st.error(f"데이터 조회 오류: {error}")
    st.stop()


df = make_dataframe(rows)

if df.empty:
    st.info(
        "선택한 기간에 단백질 영양정보가 등록된 중식이 없습니다."
    )
    st.stop()


# ==========================================
# 요약 카드
# ==========================================

highest = df.loc[
    df["단백질 함량(g)"].idxmax()
]

average_protein = df["단백질 함량(g)"].mean()

st.subheader("📊 단백질 함량 요약")

col1, col2, col3 = st.columns(3)

col1.metric(
    "집계한 급식일",
    f"{len(df)}일"
)

col2.metric(
    "평균 단백질 함량",
    f"{average_protein:.1f}g"
)

col3.metric(
    "단백질이 가장 높은 날",
    highest["날짜"].strftime("%Y-%m-%d"),
    f"{highest['단백질 함량(g)']:.1f}g"
)


# ==========================================
# 날짜별 선그래프
# ==========================================

st.divider()

st.subheader("📈 날짜별 중식 단백질 함량")

fig = px.line(
    df,
    x="날짜",
    y="단백질 함량(g)",
    markers=True,
    hover_data={
        "날짜": "|%Y-%m-%d",
        "단백질 함량(g)": ":.1f",
        "메뉴": True
    },
    labels={
        "날짜": "날짜",
        "단백질 함량(g)": "단백질 함량(g)"
    }
)

fig.update_traces(
    line_width=3,
    marker_size=6,
    hovertemplate=(
        "날짜: %{x|%Y-%m-%d}<br>"
        "단백질: %{y:.1f}g"
        "<extra></extra>"
    )
)

fig.update_layout(
    height=500,
    xaxis_title="날짜",
    yaxis_title="단백질 함량(g)",
    hovermode="x unified"
)

st.plotly_chart(
    fig,
    use_container_width=True
)


# ==========================================
# 단백질이 높은 날짜 TOP 10
# ==========================================

st.divider()

st.subheader("🏆 단백질 함량이 높은 날 TOP 10")

top10 = (
    df.sort_values(
        "단백질 함량(g)",
        ascending=False
    )
    .head(10)
    .copy()
)

top10["날짜"] = top10["날짜"].dt.strftime(
    "%Y-%m-%d"
)

fig_top = px.bar(
    top10.sort_values(
        "단백질 함량(g)",
        ascending=True
    ),
    x="단백질 함량(g)",
    y="날짜",
    orientation="h",
    color="단백질 함량(g)",
    color_continuous_scale="Greens",
    text="단백질 함량(g)",
    hover_data=["메뉴"]
)

fig_top.update_traces(
    texttemplate="%{text:.1f}g",
    textposition="outside"
)

fig_top.update_layout(
    height=450,
    coloraxis_showscale=False,
    xaxis_title="단백질 함량(g)",
    yaxis_title=""
)

st.plotly_chart(
    fig_top,
    use_container_width=True
)


# ==========================================
# 날짜별 메뉴와 단백질 표
# ==========================================

st.divider()

st.subheader("📋 날짜별 급식 영양정보")

display_df = df.copy()

display_df["날짜"] = display_df["날짜"].dt.strftime(
    "%Y-%m-%d"
)

display_df["단백질 함량(g)"] = (
    display_df["단백질 함량(g)"].round(1)
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
    "※ 단백질 함량은 나이스에 등록된 중식 영양정보 기준입니다."
)

st.caption(
    "※ 실제로 먹은 양에 따라 섭취한 단백질 양은 달라질 수 있습니다."
)

st.caption(
    "※ 영양정보가 등록되지 않은 날짜는 그래프에서 제외됩니다."
)

st.caption(
    "자료 출처: 나이스 교육정보 개방 포털"
)
