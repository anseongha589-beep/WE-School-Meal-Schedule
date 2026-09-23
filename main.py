import datetime
import requests
import streamlit as st


# =========================================================
# 기본 설정
# =========================================================

st.set_page_config(
    page_title="학교 급식 찾아보기",
    page_icon="🍚",
    layout="wide",
)

st.title("🍚 학교 급식 찾아보기")
st.write("학교를 3곳 이상 선택하고 같은 날짜의 급식을 비교해 보세요.")


# =========================================================
# API 주소
# =========================================================

SCHOOL_API_URL = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"


# =========================================================
# 한국 시간 기준 오늘 날짜
# =========================================================

def korea_today():
    utc_now = datetime.datetime.utcnow()
    korea_now = utc_now + datetime.timedelta(hours=9)
    return korea_now.date()


# =========================================================
# 학교 검색
# =========================================================

@st.cache_data(ttl=3600)
def search_schools(query):
    """학교 이름으로 학교를 검색한다."""

    response = requests.get(
        SCHOOL_API_URL,
        params={
            "Type": "json",
            "SCHUL_NM": query,
        },
        timeout=10,
    )

    response.raise_for_status()
    data = response.json()

    if "schoolInfo" in data:
        try:
            return data["schoolInfo"][1]["row"]
        except (IndexError, KeyError):
            return []

    result = data.get("RESULT", {})

    if result.get("CODE") == "INFO-200":
        return []

    return []


# =========================================================
# 줄임말을 정식 학교 이름으로 바꾸어 다시 검색
# =========================================================

def search_schools_with_short_name(query):
    schools = search_schools(query)

    if schools:
        return schools

    replacements = [
        ("여고", "여자고등학교"),
        ("남고", "남자고등학교"),
        ("고", "고등학교"),
        ("여중", "여자중학교"),
        ("남중", "남자중학교"),
        ("중", "중학교"),
        ("여상", "여자상업고등학교"),
        ("상고", "상업고등학교"),
        ("초", "초등학교"),
    ]

    for short_name, full_name in replacements:
        if query.endswith(short_name):
            new_query = query[:-len(short_name)] + full_name
            schools = search_schools(new_query)

            if schools:
                return schools

    return []


# =========================================================
# 급식 조회
# =========================================================

@st.cache_data(ttl=3600)
def get_meal(school_office_code, school_code, selected_date):
    """선택한 학교의 해당 날짜 중식을 조회한다."""

    ymd = selected_date.strftime("%Y%m%d")

    response = requests.get(
        MEAL_API_URL,
        params={
            "Type": "json",
            "ATPT_OFCDC_SC_CODE": school_office_code,
            "SD_SCHUL_CODE": school_code,
            "MMEAL_SC_CODE": "2",
            "MLSV_FROM_YMD": ymd,
            "MLSV_TO_YMD": ymd,
        },
        timeout=10,
    )

    response.raise_for_status()
    data = response.json()

    if "mealServiceDietInfo" not in data:
        result = data.get("RESULT", {})

        if result.get("CODE") == "INFO-200":
            return None

        return None

    try:
        rows = data["mealServiceDietInfo"][1]["row"]

        if not rows:
            return None

        return rows[0]

    except (IndexError, KeyError):
        return None


# =========================================================
# 학교 검색 화면
# =========================================================

st.subheader("🔎 학교 검색")

search_name = st.text_input(
    "학교 이름을 입력하세요",
    placeholder="예: 송탄고등학교",
)

search_button = st.button(
    "학교 검색",
    type="primary",
)


# =========================================================
# 검색 결과
# =========================================================

if search_button:

    if not search_name.strip():
        st.warning("학교 이름을 입력해 주세요.")

    else:
        with st.spinner("학교를 검색하고 있습니다..."):
            try:
                found_schools = search_schools_with_short_name(
                    search_name.strip()
                )

                if not found_schools:
                    st.warning(
                        "그 이름의 학교를 찾지 못했습니다. "
                        "정식 학교 이름으로 다시 검색해 주세요."
                    )
                else:
                    # 검색 결과를 session_state에 저장
                    st.session_state["school_results"] = found_schools

            except requests.RequestException:
                st.error(
                    "학교 정보를 불러오지 못했습니다. "
                    "잠시 후 다시 시도해 주세요."
                )


# =========================================================
# 검색 결과 표시
# =========================================================

school_results = st.session_state.get("school_results", [])


if school_results:

    st.markdown("### 🏫 검색 결과")

    st.caption(
        "학교명과 지역을 확인한 뒤, 비교할 학교를 선택하세요."
    )

    # 학교 표시 이름
    school_labels = []

    for school in school_results:

        school_name = school.get("SCHUL_NM", "")
        location = school.get("LCTN_SC_NM", "")

        label = f"{school_name} ({location})"

        school_labels.append(label)

    # 선택
    selected_labels = st.multiselect(
        "비교할 학교를 선택하세요. (최소 3곳)",
        options=school_labels,
        default=[],
    )

    # 선택된 학교 객체 찾기
    selected_schools = []

    for label in selected_labels:
        index = school_labels.index(label)
        selected_schools.append(school_results[index])


else:
    selected_schools = []


# =========================================================
# 날짜 선택
# =========================================================

st.divider()

st.subheader("📅 급식 날짜")

today = korea_today()

selected_date = st.date_input(
    "날짜를 선택하세요",
    value=today,
    max_value=today,
)


# =========================================================
# 학교 선택 개수 확인
# =========================================================

st.divider()

if len(selected_schools) == 0:

    st.info(
        "먼저 위에서 비교할 학교를 선택해 주세요. "
        "학교는 최소 3곳을 선택해야 합니다."
    )

elif len(selected_schools) < 3:

    st.warning(
        f"현재 {len(selected_schools)}곳을 선택했습니다. "
        "학교를 3곳 이상 선택해 주세요."
    )

else:

    st.success(
        f"총 {len(selected_schools)}곳의 학교를 선택했습니다."
    )

    st.subheader(
        f"🍚 {selected_date.strftime('%Y년 %m월 %d일')} 중식 비교"
    )

    # =====================================================
    # 선택한 모든 학교의 급식 조회
    # =====================================================

    meal_results = []

    with st.spinner("선택한 학교의 급식 정보를 불러오는 중..."):

        for school in selected_schools:

            school_name = school.get("SCHUL_NM", "")
            location = school.get("LCTN_SC_NM", "")
            office_code = school.get("ATPT_OFCDC_SC_CODE", "")
            school_code = school.get("SD_SCHUL_CODE", "")

            try:
                meal = get_meal(
                    office_code,
                    school_code,
                    selected_date,
                )

            except requests.RequestException:
                meal = None

            meal_results.append(
                {
                    "school_name": school_name,
                    "location": location,
                    "meal": meal,
                }
            )

    # =====================================================
    # 학교별 급식 카드
    # =====================================================

    # 학교가 많아도 한 줄에 최대 4개씩 표시
    for start in range(0, len(meal_results), 4):

        row_results = meal_results[start:start + 4]

        columns = st.columns(len(row_results))

        for column, result in zip(columns, row_results):

            with column:

                school_name = result["school_name"]
                location = result["location"]
                meal = result["meal"]

                st.markdown(
                    f"### 🏫 {school_name}"
                )

                st.caption(location)

                if meal is None:

                    st.info(
                        "이날은 급식이 없습니다."
                    )

                else:

                    # -------------------------------------
                    # 메뉴
                    # -------------------------------------

                    st.markdown("**🍽️ 중식 메뉴**")

                    menu_text = meal.get("DDISH_NM", "")

                    if menu_text:

                        menus = menu_text.split("<br/>")

                        for menu in menus:

                            menu = menu.strip()

                            if menu:
                                st.markdown(
                                    f"- {menu}"
                                )

                    else:

                        st.write(
                            "메뉴 정보가 없습니다."
                        )

                    # -------------------------------------
                    # 칼로리
                    # -------------------------------------

                    calorie = meal.get(
                        "CAL_INFO",
                        "정보 없음",
                    )

                    st.metric(
                        "🔥 칼로리",
                        calorie,
                    )

                    # -------------------------------------
                    # 원산지 정보가 있다면 표시
                    # -------------------------------------

                    origin = meal.get(
                        "ORPLC_INFO",
                        "",
                    )

                    if origin:
                        with st.expander("원산지 정보"):
                            st.write(origin)


# =========================================================
# 하단 안내
# =========================================================

st.divider()

st.caption(
    "※ 급식 정보는 나이스 교육정보 개방 포털의 급식식단정보를 이용합니다."
)
