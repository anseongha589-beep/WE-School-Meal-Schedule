
import html
import re
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# --------------------------------------------------
# 기본 설정
# --------------------------------------------------
st.set_page_config(
    page_title="날짜별 중식 단백질 분석",
    page_icon="🥗",
    layout="wide",
)

st.title("🥗 날짜별 중식 단백질 함량")
st.caption("송탄고등학교의 날짜별 중식 단백질 함량을 비교해 보세요.")

# 송탄고등학교
ATPT_OFCDC_SC_CODE = "J10"
SD_SCHUL_CODE = "7530480"

API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

TODAY = date.today()
DEFAULT_START = date(2025, 9, 1)


# --------------------------------------------------
# 단백질 함량 추출
# --------------------------------------------------
def parse_protein(ntr_info):
    """
    NEIS 영양정보에서 단백질(g) 수치를 추출합니다.
    예: 단백질(g) : 48.5
    """
    if not ntr_info:
        return None

    text = html.unescape(str(ntr_info))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)

    pattern = (
        r"단백질\s*\(\s*g\s*\)\s*[:：]\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE)

    if match:
        return float(match.group(1))

    return None


# --------------------------------------------------
# NEIS 급식 영양정보 조회
# --------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_protein_data(start_date, end_date):
    all_rows = []
    page = 1
    page_size = 1000

    while True:
        params = {
            "ATPT_OFCDC_SC_CODE": ATPT_OFCDC_SC_CODE,
            "SD_SCHUL_CODE": SD_SCHUL_CODE,
            "MLSV_FROM_YMD": start_date.strftime("%Y%m%d"),
            "MLSV_TO_YMD": end_date.strftime("%Y%m%d"),
            "pIndex": page,
            "pSize": page_size,
        }

        try:
            response = requests.get(
                API_URL,
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as error:
            raise RuntimeError(
                f"나이스 API에 연결하지 못했습니다.\n{error}"
            ) from error
        except ValueError as error:
            raise RuntimeError(
                "나이스 API 응답을 읽을 수 없습니다."
            ) from error

        meal_info = result.get("mealServiceDietInfo")

        # 급식 정보가 없거나 API가 오류를 반환한 경우
        if not meal_info or len(meal_info) < 2:
            break

        rows = meal_info[1].get("row", [])
        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < page_size:
            break

        page += 1

    records = []

    for row in all_rows:
        # 중식만 분석
        if row.get("MMEAL_SC_CODE") != "2":
            continue

        protein = parse_protein(row.get("NTR_INFO"))

        # 단백질 수치가 없는 식단은 분석에서 제외
        if protein is None:
            continue

        meal_date = row.get("MLSV_YMD")
        if not meal_date:
            continue

        records.append(
            {
                "날짜": pd.to_datetime(
                    meal_date,
                    format="%Y%m%d",
                    errors="coerce",
                ),
                "단백질(g)": protein,
                "메뉴": row.get("DDISH_NM", ""),
                "칼로리": row.get("CAL_INFO", ""),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=["날짜", "단백질(g)", "메뉴", "칼로리"]
        )

    df = pd.DataFrame(records)
    df = df.dropna(subset=["날짜"])

    # 같은 날짜에 자료가 여러 개 있으면 단백질 함량을 합산
    df = (
        df.groupby("날짜", as_index=False)
        .agg(
            {
                "단백질(g)": "sum",
                "메뉴": lambda values: " / ".join(
                    str(value)
                    for value in values
                    if value
                ),
                "칼로리": lambda values: " / ".join(
                    str(value)
                    for value in values
                    if value
                ),
            }
        )
        .sort_values("날짜")
    )

    return df


# --------------------------------------------------
# 조회 기간 선택
# --------------------------------------------------
st.header("🗓️ 조회 기간")

date_range = st.date_input(
    "분석할 날짜 범위를 선택하세요.",
    value=(DEFAULT_START, TODAY),
    min_value=DEFAULT_START,
    max_value=TODAY,
    format="YYYY-MM-DD",
)

if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
    st.info("시작 날짜와 종료 날짜를 모두 선택해 주세요.")
    st.stop()

start_date, end_date = date_range

if start_date > end_date:
    st.error("시작 날짜는 종료 날짜보다 늦을 수 없습니다.")
    st.stop()


# --------------------------------------------------
# 데이터 불러오기
# --------------------------------------------------
with st.spinner("급식 영양정보를 불러오는 중입니다..."):
    try:
        df = load_protein_data(start_date, end_date)
    except RuntimeError as error:
        st.error(str(error))
        st.stop()

if df.empty:
    st.warning(
        "선택한 기간에 단백질 함량이 확인되는 중식 자료가 없습니다."
    )
    st.stop()


# --------------------------------------------------
# 주요 수치
# --------------------------------------------------
st.subheader("📌 조회 결과")

average_protein = df["단백질(g)"].mean()
max_index = df["단백질(g)"].idxmax()
max_row = df.loc[max_index]

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "중식 평균 단백질",
        f"{average_protein:.1f} g",
    )

with col2:
    st.metric(
        "가장 높은 단백질 함량",
        f"{max_row['단백질(g)']:.1f} g",
    )

with col3:
    st.metric(
        "분석한 급식 날짜",
        f"{len(df)}일",
    )

st.caption(
    f"조회 기간: {start_date.strftime('%Y-%m-%d')} ~ "
    f"{end_date.strftime('%Y-%m-%d')}"
)


# --------------------------------------------------
# 그래프 1: 날짜별 단백질 함량
# --------------------------------------------------
st.subheader("📈 날짜별 중식 단백질 함량")

line_fig = px.line(
    df,
    x="날짜",
    y="단백질(g)",
    markers=True,
    title="날짜에 따른 중식 단백질 함량",
    hover_data={
        "날짜": "|%Y-%m-%d",
        "단백질(g)": ":.1f",
    },
)

line_fig.update_traces(
    line=dict(width=3),
    marker=dict(size=7),
    hovertemplate=(
        "날짜: %{x|%Y-%m-%d}<br>"
        "단백질: %{y:.1f} g"
        "<extra></extra>"
    ),
)

line_fig.update_layout(
    xaxis_title="날짜",
    yaxis_title="단백질(g)",
    hovermode="x unified",
)

st.plotly_chart(line_fig, use_container_width=True)


# --------------------------------------------------
# 그래프 2: 단백질 함량이 높은 날짜 TOP 10
# --------------------------------------------------
st.subheader("🏆 단백질 함량이 높은 날짜 TOP 10")

top10 = (
    df.sort_values("단백질(g)", ascending=False)
    .head(10)
    .sort_values("단백질(g)", ascending=True)
    .copy()
)

top10["날짜 표시"] = top10["날짜"].dt.strftime("%Y-%m-%d")

bar_fig = px.bar(
    top10,
    x="단백질(g)",
    y="날짜 표시",
    orientation="h",
    text="단백질(g)",
    title="중식 단백질 함량 TOP 10",
    hover_data={
        "날짜 표시": False,
        "단백질(g)": ":.1f",
        "메뉴": True,
    },
)

bar_fig.update_traces(
    texttemplate="%{x:.1f} g",
    textposition="outside",
    hovertemplate=(
        "날짜: %{y}<br>"
        "단백질: %{x:.1f} g"
        "<extra></extra>"
    ),
)

bar_fig.update_layout(
    xaxis_title="단백질(g)",
    yaxis_title="날짜",
)

st.plotly_chart(bar_fig, use_container_width=True)


# --------------------------------------------------
# 날짜별 자료 표
# --------------------------------------------------
st.subheader("📋 날짜별 급식 영양정보")

table_df = df.copy()
table_df["날짜"] = table_df["날짜"].dt.strftime("%Y-%m-%d")
table_df["단백질(g)"] = table_df["단백질(g)"].round(1)

st.dataframe(
    table_df[
        ["날짜", "단백질(g)", "메뉴", "칼로리"]
    ].sort_values("날짜", ascending=False),
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "※ 단백질 함량은 나이스 급식 영양정보에 표시된 값을 사용합니다. "
    "영양정보가 없는 날짜는 그래프와 표에서 제외됩니다."
)
