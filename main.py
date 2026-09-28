
import html
import re
from datetime import date

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ==================================================
# 기본 설정
# ==================================================
st.set_page_config(
    page_title="학교 급식 찾아보기",
    page_icon="🍱",
    layout="wide",
)

SCHOOL_API_URL = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

DEFAULT_START_DATE = date(2025, 9, 1)
TODAY = date.today()

# 송탄고등학교 기본 정보
DEFAULT_SCHOOL = {
    "ATPT_OFCDC_SC_CODE": "J10",
    "SD_SCHUL_CODE": "7530480",
    "SCHUL_NM": "송탄고등학교",
    "LCTN_SC_NM": "경기",
    "ORG_RDNMA": "평택시",
}


# ==================================================
# 공통 함수
# ==================================================
def get_api_key():
    """Streamlit Secrets에서 나이스 인증키를 가져옵니다."""
    return st.secrets.get("NEIS_API_KEY", "").strip()


def school_key(school):
    """학교를 구분하는 고유 키"""
    return (
        f"{school['ATPT_OFCDC_SC_CODE']}_"
        f"{school['SD_SCHUL_CODE']}"
    )


def school_label(school):
    """학교 선택 목록에 표시할 이름"""
    name = school.get("SCHUL_NM", "학교명 없음")
    region = school.get("LCTN_SC_NM", "")
    code = school.get("SD_SCHUL_CODE", "")

    parts = [name]

    if region:
        parts.append(region)

    if code:
        parts.append(code)

    return " · ".join(parts)


def clean_html(value):
    """급식 메뉴의 HTML 줄바꿈 태그를 보기 좋게 바꿉니다."""
    if not value:
        return ""

    text = html.unescape(str(value))
    text = re.sub(r"<br\s*/?>", " / ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    return re.sub(r"\s+", " ", text).strip()


def parse_protein(ntr_info):
    """영양정보에서 단백질(g) 수치를 추출합니다."""
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


def get_json_response(url, params):
    """나이스 API 요청 및 JSON 응답 확인"""
    try:
        response = requests.get(
            url,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(
            f"나이스 API에 연결하지 못했습니다: {error}"
        ) from error

    response_text = response.text.strip()

    if not response_text:
        raise RuntimeError(
            "나이스 API가 빈 응답을 반환했습니다. "
            "인증키와 API 주소를 확인해 주세요."
        )

    try:
        return response.json()
    except ValueError as error:
        raise RuntimeError(
            "나이스 API 응답을 JSON으로 읽을 수 없습니다. "
            "인증키 또는 API 응답을 확인해 주세요."
        ) from error


# ==================================================
# 학교 검색
# ==================================================
@st.cache_data(ttl=3600, show_spinner=False)
def search_schools(keyword, api_key):
    params = {
        "KEY": api_key,
        "Type": "json",
        "SCHUL_NM": keyword,
        "pIndex": 1,
        "pSize": 100,
    }

    result = get_json_response(SCHOOL_API_URL, params)
    school_info = result.get("schoolInfo")

    if not school_info or len(school_info) < 2:
        result_info = result.get("RESULT", {})

        if result_info.get("CODE") == "INFO-200":
            return []

        if result_info:
            raise RuntimeError(
                "학교 검색 API 오류: "
                f"{result_info.get('CODE', '')} - "
                f"{result_info.get('MESSAGE', '')}"
            )

        return []

    rows = school_info[1].get("row", [])

    schools = []

    for row in rows:
        school = {
            "ATPT_OFCDC_SC_CODE": row.get(
                "ATPT_OFCDC_SC_CODE", ""
            ),
            "SD_SCHUL_CODE": row.get("SD_SCHUL_CODE", ""),
            "SCHUL_NM": row.get("SCHUL_NM", ""),
            "LCTN_SC_NM": row.get("LCTN_SC_NM", ""),
            "ORG_RDNMA": row.get("ORG_RDNMA", ""),
        }

        if (
            school["ATPT_OFCDC_SC_CODE"]
            and school["SD_SCHUL_CODE"]
            and school["SCHUL_NM"]
        ):
            schools.append(school)

    return schools


# ==================================================
# 학교별 급식 영양정보
# ==================================================
@st.cache_data(ttl=3600, show_spinner=False)
def load_school_meals(
    school_office_code,
    school_code,
    start_date,
    end_date,
    api_key,
):
    all_rows = []
    page = 1
    page_size = 1000

    while True:
        params = {
            "KEY": api_key,
            "Type": "json",
            "ATPT_OFCDC_SC_CODE": school_office_code,
            "SD_SCHUL_CODE": school_code,
            "MLSV_FROM_YMD": start_date.strftime("%Y%m%d"),
            "MLSV_TO_YMD": end_date.strftime("%Y%m%d"),
            "MMEAL_SC_CODE": "2",
            "pIndex": page,
            "pSize": page_size,
        }

        result = get_json_response(MEAL_API_URL, params)
        meal_info = result.get("mealServiceDietInfo")

        if not meal_info:
            result_info = result.get("RESULT", {})

            if result_info.get("CODE") == "INFO-200":
                break

            if result_info:
                raise RuntimeError(
                    "급식 API 오류: "
                    f"{result_info.get('CODE', '')} - "
                    f"{result_info.get('MESSAGE', '')}"
                )

            break

        if len(meal_info) < 2:
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
        if row.get("MMEAL_SC_CODE") != "2":
            continue

        protein = parse_protein(row.get("NTR_INFO"))

        meal_date = row.get("MLSV_YMD")

        if not meal_date:
            continue

        parsed_date = pd.to_datetime(
            meal_date,
            format="%Y%m%d",
            errors="coerce",
        )

        if pd.isna(parsed_date):
            continue

        records.append(
            {
                "날짜": parsed_date,
                "단백질(g)": protein,
                "메뉴": clean_html(row.get("DDISH_NM", "")),
                "칼로리": clean_html(row.get("CAL_INFO", "")),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=["날짜", "단백질(g)", "메뉴", "칼로리"]
        )

    df = pd.DataFrame(records)

    # 단백질 정보가 없는 날짜는 그래프 비교에서 제외
    df = df.dropna(subset=["단백질(g)", "날짜"])

    # 학교별·날짜별로 정리
    df = (
        df.groupby("날짜", as_index=False)
        .agg(
            {
                "단백질(g)": "mean",
                "메뉴": lambda values: " / ".join(
                    str(value) for value in values if value
                ),
                "칼로리": lambda values: " / ".join(
                    str(value) for value in values if value
                ),
            }
        )
        .sort_values("날짜")
    )

    return df


# ==================================================
# 세션 상태 초기화
# ==================================================
if "school_candidates" not in st.session_state:
    st.session_state.school_candidates = {
        school_key(DEFAULT_SCHOOL): DEFAULT_SCHOOL
    }

if "selected_school_labels" not in st.session_state:
    st.session_state.selected_school_labels = [
        school_label(DEFAULT_SCHOOL)
    ]


# ==================================================
# 화면 제목
# ==================================================
st.title("🍱 학교 급식 찾아보기")
st.caption(
    "학교를 검색해 급식을 확인하고, "
    "여러 학교의 중식 단백질 함량을 비교할 수 있습니다."
)


# ==================================================
# 학교 검색 및 후보 추가
# ==================================================
st.header("🏫 학교 선택")

st.write(
    "학교 이름을 검색해 후보 목록에 추가한 뒤, "
    "비교할 학교를 여러 곳 선택하세요."
)

with st.form("school_search_form"):
    school_keyword = st.text_input(
        "학교 이름 검색",
        placeholder="예: 송탄고등학교, 평택고등학교",
    )

    search_clicked = st.form_submit_button(
        "학교 검색 및 후보 추가",
        use_container_width=True,
    )

if search_clicked:
    keyword = school_keyword.strip()

    if not keyword:
        st.warning("검색할 학교 이름을 입력해 주세요.")
    else:
        api_key = get_api_key()

        if not api_key:
            st.error(
                "Streamlit Secrets에서 NEIS_API_KEY를 찾을 수 없습니다. "
                "앱 설정의 Secrets에 인증키를 등록해 주세요."
            )
        else:
            try:
                with st.spinner("학교를 검색하고 있습니다..."):
                    found_schools = search_schools(
                        keyword,
                        api_key,
                    )

                if not found_schools:
                    st.info("검색된 학교가 없습니다.")
                else:
                    added_count = 0

                    for school in found_schools:
                        key = school_key(school)

                        if key not in st.session_state.school_candidates:
                            st.session_state.school_candidates[key] = school
                            added_count += 1

                    st.success(
                        f"{len(found_schools)}개 학교를 찾았습니다. "
                        f"새 후보 {added_count}개를 추가했습니다."
                    )

            except RuntimeError as error:
                st.error(str(error))


# 후보 목록 구성
candidate_schools = list(
    st.session_state.school_candidates.values()
)

label_to_school = {
    school_label(school): school
    for school in candidate_schools
}

school_labels = list(label_to_school.keys())

# 송탄고등학교를 기본 선택 상태로 유지
default_label = school_label(DEFAULT_SCHOOL)

if (
    default_label in school_labels
    and not st.session_state.selected_school_labels
):
    st.session_state.selected_school_labels = [default_label]

selected_labels = st.multiselect(
    "비교할 학교 선택",
    options=school_labels,
    key="selected_school_labels",
    help="송탄고등학교를 포함해 여러 학교를 선택할 수 있습니다.",
)

selected_schools = [
    label_to_school[label]
    for label in selected_labels
    if label in label_to_school
]

if selected_schools:
    st.caption(
        "선택한 학교: "
        + ", ".join(
            school.get("SCHUL_NM", "")
            for school in selected_schools
        )
    )
else:
    st.info("학교를 한 곳 이상 선택해 주세요.")


# ==================================================
# 조회 기간
# ==================================================
st.header("🗓️ 조회 기간")

date_range = st.date_input(
    "분석할 날짜 범위를 선택하세요.",
    value=(DEFAULT_START_DATE, TODAY),
    min_value=DEFAULT_START_DATE,
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

if not selected_schools:
    st.stop()


# ==================================================
# 선택한 학교 급식 자료 불러오기
# ==================================================
api_key = get_api_key()

if not api_key:
    st.error(
        "Streamlit Secrets에 NEIS_API_KEY를 등록해 주세요."
    )
    st.stop()

all_school_data = []
load_errors = []

with st.spinner("선택한 학교의 급식 영양정보를 불러오는 중입니다..."):
    for school in selected_schools:
        try:
            school_df = load_school_meals(
                school["ATPT_OFCDC_SC_CODE"],
                school["SD_SCHUL_CODE"],
                start_date,
                end_date,
                api_key,
            )

            if not school_df.empty:
                school_df = school_df.copy()
                school_df["학교"] = school["SCHUL_NM"]
                all_school_data.append(school_df)

        except RuntimeError as error:
            load_errors.append(
                f"{school['SCHUL_NM']}: {error}"
            )

if load_errors:
    with st.expander("일부 학교의 자료를 불러오지 못했습니다."):
        for error in load_errors:
            st.warning(error)

if not all_school_data:
    st.warning(
        "선택한 기간에 단백질 함량이 확인되는 중식 자료가 없습니다."
    )
    st.stop()

combined_df = pd.concat(
    all_school_data,
    ignore_index=True,
)

combined_df = combined_df.sort_values(
    ["날짜", "학교"]
)


# ==================================================
# 탭
# ==================================================
tab_meal, tab_compare = st.tabs(
    ["📋 급식 정보", "📊 학교 비교"]
)


# ==================================================
# 탭 1: 급식 정보
# ==================================================
with tab_meal:
    st.subheader("날짜별 급식 영양정보")

    st.caption(
        f"조회 기간: {start_date:%Y-%m-%d} ~ {end_date:%Y-%m-%d}"
    )

    school_for_table = st.selectbox(
        "표를 볼 학교 선택",
        options=[
            school["SCHUL_NM"]
            for school in selected_schools
        ],
        key="table_school",
    )

    table_df = combined_df[
        combined_df["학교"] == school_for_table
    ].copy()

    if table_df.empty:
        st.info("선택한 학교의 자료가 없습니다.")
    else:
        table_df["날짜"] = table_df["날짜"].dt.strftime(
            "%Y-%m-%d"
        )
        table_df["단백질(g)"] = table_df["단백질(g)"].round(1)

        st.dataframe(
            table_df[
                ["날짜", "학교", "단백질(g)", "메뉴", "칼로리"]
            ].sort_values("날짜", ascending=False),
            use_container_width=True,
            hide_index=True,
        )


# ==================================================
# 탭 2: 학교 비교
# ==================================================
with tab_compare:
    st.subheader("📊 여러 학교의 단백질 함량 비교")

    if len(selected_schools) < 3:
        st.info(
            "학교를 3곳 이상 선택하면 학교 비교 그래프를 확인할 수 있습니다. "
            "위의 학교 검색에서 다른 학교를 추가해 주세요."
        )
    else:
        st.success(
            f"현재 {len(selected_schools)}개 학교를 비교하고 있습니다."
        )

    # 학교별 평균 단백질
    school_summary = (
        combined_df.groupby("학교", as_index=False)
        .agg(
            평균_단백질=("단백질(g)", "mean"),
            급식_날짜수=("날짜", "nunique"),
            최고_단백질=("단백질(g)", "max"),
        )
        .sort_values("평균_단백질", ascending=False)
    )

    school_summary["평균_단백질"] = (
        school_summary["평균_단백질"].round(1)
    )
    school_summary["최고_단백질"] = (
        school_summary["최고_단백질"].round(1)
    )

    # 그래프 1: 학교별 평균 단백질 함량
    st.markdown("### 그래프 1. 학교별 평균 단백질 함량")

    average_fig = px.bar(
        school_summary,
        x="학교",
        y="평균_단백질",
        color="학교",
        text="평균_단백질",
        title="선택한 학교의 중식 평균 단백질 함량",
        hover_data={
            "급식_날짜수": True,
            "최고_단백질": True,
            "평균_단백질": ":.1f",
        },
    )

    average_fig.update_traces(
        texttemplate="%{y:.1f} g",
        textposition="outside",
        hovertemplate=(
            "학교: %{x}<br>"
            "평균 단백질: %{y:.1f} g"
            "<extra></extra>"
        ),
    )

    average_fig.update_layout(
        xaxis_title="학교",
        yaxis_title="평균 단백질(g)",
        showlegend=False,
    )

    st.plotly_chart(
        average_fig,
        use_container_width=True,
    )

    st.caption(
        "평균은 조회 기간에 단백질 영양정보가 제공된 중식 날짜를 기준으로 계산합니다."
    )

    # 그래프 2: 날짜별 학교 단백질 함량
    st.markdown("### 그래프 2. 날짜별 단백질 함량 비교")

    line_fig = px.line(
        combined_df,
        x="날짜",
        y="단백질(g)",
        color="학교",
        markers=True,
        title="학교별 날짜에 따른 중식 단백질 함량",
        hover_data={
            "학교": True,
            "날짜": "|%Y-%m-%d",
            "단백질(g)": ":.1f",
        },
    )

    line_fig.update_traces(
        hovertemplate=(
            "학교: %{fullData.name}<br>"
            "날짜: %{x|%Y-%m-%d}<br>"
            "단백질: %{y:.1f} g"
            "<extra></extra>"
        )
    )

    line_fig.update_layout(
        xaxis_title="날짜",
        yaxis_title="단백질(g)",
        hovermode="x unified",
        legend_title="학교",
    )

    st.plotly_chart(
        line_fig,
        use_container_width=True,
    )

    # 비교 요약표
    st.markdown("### 학교별 비교표")

    st.dataframe(
        school_summary.rename(
            columns={
                "평균_단백질": "평균 단백질(g)",
                "급식_날짜수": "자료가 있는 급식 날짜",
                "최고_단백질": "최고 단백질(g)",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "※ 학교마다 급식일과 영양정보 제공 여부가 다를 수 있습니다. "
        "평균값은 각 학교에서 자료가 확인된 날짜를 기준으로 계산합니다."
    )


# ==================================================
# 앱 사용 안내
# ==================================================
st.divider()

st.markdown(
    """
    **사용 방법**
    1. 학교 이름을 검색하고 후보 목록에 추가합니다.
    2. 비교할 학교를 3곳 이상 선택합니다.
    3. 조회 기간을 선택합니다.
    4. 학교 비교 탭에서 평균 단백질 함량과 날짜별 변화를 확인합니다.
    """
)
