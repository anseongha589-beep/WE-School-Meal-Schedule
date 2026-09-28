
import streamlit as st
import requests
import re
from datetime import datetime, date
from zoneinfo import ZoneInfo
from html import unescape


# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="학교 급식 찾아보기",
    page_icon="🍱",
    layout="centered"
)

st.title("🍱 학교 급식 찾아보기")
st.write("학교를 검색하고 날짜를 선택하면 그날의 중식 메뉴를 확인할 수 있어요.")

BASE_URL = "https://open.neis.go.kr/hub"

SCHOOL_API = f"{BASE_URL}/schoolInfo"
MEAL_API = f"{BASE_URL}/mealServiceDietInfo"

KOREA_TZ = ZoneInfo("Asia/Seoul")

# 한국 시간 기준 오늘
TODAY = datetime.now(KOREA_TZ).date()

# 요청 시간 초과 방지
TIMEOUT = 15


# ==========================================
# API 공통 함수
# ==========================================

def request_api(url, params):
    """
    나이스 API를 호출하고 JSON 응답을 반환한다.
    """
    try:
        response = requests.get(
            url,
            params=params,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        return response.json()

    except requests.exceptions.Timeout:
        st.error("서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
        return None

    except requests.exceptions.RequestException:
        st.error("나이스 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
        return None

    except ValueError:
        st.error("서버에서 올바른 데이터를 받지 못했습니다.")
        return None


def get_api_result(data, api_name):
    """
    API 응답의 RESULT 정보를 확인한다.
    정상적인 데이터가 있으면 None을 반환한다.
    """
    if not data:
        return "데이터를 불러오지 못했습니다."

    result = data.get("RESULT")

    if result:
        code = result.get("CODE", "")

        if code == "INFO-200":
            return "조회 결과가 없습니다."

        if code:
            message = result.get("MESSAGE", "알 수 없는 오류")
            return f"{api_name} 조회 오류: {message} ({code})"

    return None


# ==========================================
# 학교 이름 보정
# ==========================================

def normalize_school_name(name):
    """
    학교 이름의 앞뒤 공백을 제거하고
    여고, 고 등의 줄임말을 정식 명칭으로 바꾼다.
    """
    name = name.strip()

    # 연속된 공백 정리
    name = re.sub(r"\s+", "", name)

    # 학교 이름 끝에 있는 줄임말을 정식 명칭으로 변환
    if name.endswith("여고"):
        name = name[:-2] + "여자고등학교"

    elif name.endswith("고") and not name.endswith("등학교"):
        name = name[:-1] + "고등학교"

    return name


# ==========================================
# 학교 검색
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def search_schools(school_name):
    """
    학교 이름으로 검색한다.
    검색 결과가 없으면 줄임말을 정식 명칭으로 바꿔 재검색한다.
    """

    def call_school_api(keyword):
        params = {
            "Type": "json",
            "SCHUL_NM": keyword
        }

        data = request_api(SCHOOL_API, params)

        if not data:
            return None

        error = get_api_result(data, "학교 정보")

        if error:
            if error == "조회 결과가 없습니다.":
                return []

            return None

        school_info = data.get("schoolInfo", [])

        if len(school_info) < 2:
            return []

        return school_info[1].get("row", [])

    # 1차 검색: 사용자가 입력한 학교 이름
    schools = call_school_api(school_name)

    if schools is None:
        return None

    if schools:
        return schools

    # 2차 검색: 줄임말을 정식 이름으로 바꿔 검색
    normalized_name = normalize_school_name(school_name)

    if normalized_name == school_name:
        return []

    return call_school_api(normalized_name)


# ==========================================
# 급식 메뉴 조회
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_meal(
    office_code,
    school_code,
    selected_date
):
    """
    선택한 학교의 특정 날짜 중식 정보를 조회한다.
    """

    date_string = selected_date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": office_code,
        "SD_SCHUL_CODE": school_code,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_string,
        "MLSV_TO_YMD": date_string,
        "pSize": "1000",
        "pIndex": "1"
    }

    data = request_api(MEAL_API, params)

    if not data:
        return None

    error = get_api_result(data, "급식")

    if error:
        if error == "조회 결과가 없습니다.":
            return []

        return None

    meal_info = data.get("mealServiceDietInfo", [])

    if len(meal_info) < 2:
        return []

    rows = meal_info[1].get("row", [])

    # 선택한 날짜의 중식만 반환
    return [
        row for row in rows
        if row.get("MLSV_YMD") == date_string
        and row.get("MMEAL_SC_CODE") == "2"
    ]


# ==========================================
# 메뉴 표시 함수
# ==========================================

def clean_menu_text(menu_text):
    """
    메뉴 문자열의 HTML 줄바꿈을 실제 줄바꿈으로 바꾼다.
    """
    if not menu_text:
        return ""

    menu_text = unescape(menu_text)

    menu_text = re.sub(
        r"(?i)<br\s*/?>",
        "\n",
        menu_text
    )

    # 그 외 HTML 태그 제거
    menu_text = re.sub(r"<[^>]*>", "", menu_text)

    return menu_text.strip()


def split_menu(menu_text):
    """
    메뉴를 줄 단위로 나눈다.
    """
    menu_text = clean_menu_text(menu_text)

    return [
        item.strip()
        for item in menu_text.splitlines()
        if item.strip()
    ]


# ==========================================
# 화면
# ==========================================

st.divider()

st.subheader("1. 학교 선택")

school_name = st.text_input(
    "학교 이름",
    placeholder="예: 수도여고, 서울고등학교",
    help="학교 이름 일부를 입력해도 검색할 수 있어요."
)

search_button = st.button(
    "학교 검색",
    type="primary",
    use_container_width=True
)

# 검색 결과를 세션에 저장
if search_button:
    if not school_name.strip():
        st.warning("학교 이름을 입력해 주세요.")

    else:
        with st.spinner("학교를 검색하고 있어요..."):
            schools = search_schools(school_name.strip())

        st.session_state["schools"] = schools
        st.session_state["school_search_name"] = school_name.strip()
        st.session_state.pop("selected_school", None)


# ==========================================
# 검색 결과 표시
# ==========================================

if "schools" in st.session_state:

    schools = st.session_state["schools"]

    if schools is None:
        st.info("학교 정보를 불러오지 못했습니다. 잠시 후 다시 검색해 주세요.")

    elif not schools:
        st.info(
            "학교를 찾을 수 없습니다. 학교 이름을 확인하거나 "
            "정식 학교 이름으로 다시 검색해 주세요."
        )

    else:
        st.success(f"학교 {len(schools)}곳을 찾았습니다.")

        # 학교명과 지역을 함께 표시
        school_options = []

        for school in schools:
            school_name_full = school.get("SCHUL_NM", "")
            location = school.get("LCTN_SC_NM", "지역 정보 없음")
            office_code = school.get("ATPT_OFCDC_SC_CODE", "")
            school_code = school.get("SD_SCHUL_CODE", "")

            label = f"{school_name_full} ({location})"

            school_options.append({
                "label": label,
                "name": school_name_full,
                "location": location,
                "office_code": office_code,
                "school_code": school_code
            })

        selected_label = st.selectbox(
            "검색된 학교 목록",
            options=[school["label"] for school in school_options],
            index=0
        )

        selected_school = next(
            school for school in school_options
            if school["label"] == selected_label
        )

        st.session_state["selected_school"] = selected_school

        st.caption(
            f"선택한 학교: {selected_school['name']} / "
            f"{selected_school['location']}"
        )

        st.divider()

        # ==========================================
        # 날짜 선택
        # ==========================================

        st.subheader("2. 급식 날짜 선택")

        selected_date = st.date_input(
            "날짜",
            value=TODAY,
            max_value=TODAY,
            format="YYYY-MM-DD"
        )

        st.caption("날짜는 한국 시간 기준 오늘까지 선택할 수 있어요.")

        # ==========================================
        # 급식 조회
        # ==========================================

        if st.button(
            "중식 메뉴 조회",
            type="primary",
            use_container_width=True
        ):
            with st.spinner("급식 메뉴를 불러오고 있어요..."):
                meal_rows = get_meal(
                    selected_school["office_code"],
                    selected_school["school_code"],
                    selected_date
                )

            st.session_state["meal_rows"] = meal_rows
            st.session_state["meal_date"] = selected_date
            st.session_state["meal_school"] = selected_school

        # ==========================================
        # 급식 결과 표시
        # ==========================================

        if "meal_rows" in st.session_state:

            meal_rows = st.session_state["meal_rows"]

            # 현재 선택한 학교의 결과만 표시
            same_school = (
                st.session_state.get("meal_school")
                == selected_school
            )

            same_date = (
                st.session_state.get("meal_date")
                == selected_date
            )

            if same_school and same_date:

                st.divider()
                st.subheader("🍚 오늘의 중식" if selected_date == TODAY
                             else "🍚 선택한 날짜의 중식")

                st.write(
                    f"**{selected_school['name']}**"
                )

                st.write(
                    selected_date.strftime("%Y년 %m월 %d일")
                )

                if meal_rows is None:
                    st.info(
                        "급식 정보를 불러오지 못했습니다. "
                        "잠시 후 다시 조회해 주세요."
                    )

                elif not meal_rows:
                    st.info(
                        "선택한 날짜에는 등록된 중식 급식이 없습니다."
                    )

                else:
                    meal = meal_rows[0]

                    menu_text = meal.get("DDISH_NM", "")
                    calorie = meal.get("CAL_INFO", "")

                    menu_items = split_menu(menu_text)

                    st.markdown("### 메뉴")

                    if menu_items:
                        for item in menu_items:
                            st.markdown(f"- {item}")
                    else:
                        st.info("등록된 메뉴가 없습니다.")

                    st.divider()

                    st.markdown("### 칼로리")

                    if calorie:
                        st.metric(
                            label="중식 열량",
                            value=calorie
                        )
                    else:
                        st.info("칼로리 정보가 등록되어 있지 않습니다.")

                    st.caption(
                        "※ 메뉴 뒤 괄호의 숫자는 알레르기 유발 식품 번호입니다."
                    )

st.divider()

st.caption(
    "자료 출처: 나이스 교육정보 개방 포털 "
    "(학교기본정보 및 급식식단정보)"
)
