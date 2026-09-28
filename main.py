
import streamlit as st
import requests
import re
import html
from datetime import datetime
from zoneinfo import ZoneInfo


# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="우리 학교 달력별 급식",
    page_icon="🍱",
    layout="wide"
)

st.title("🍱 우리 학교 달력별 급식")
st.caption("송탄고등학교의 날짜별 중식 메뉴를 확인해 보세요.")

# 송탄고등학교 학교 정보
SCHOOL_NAME = "송탄고등학교"
ATPT_OFCDC_SC_CODE = "J10"
SD_SCHUL_CODE = "7530480"

MEAL_API = (
    "https://open.neis.go.kr/hub/mealServiceDietInfo"
)

KOREA_TZ = ZoneInfo("Asia/Seoul")

TODAY = datetime.now(KOREA_TZ).date()


# ==========================================
# 급식 API 조회
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_meal(selected_date):
    """
    선택한 날짜의 송탄고등학교 중식 정보를 조회한다.
    """

    date_string = selected_date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": ATPT_OFCDC_SC_CODE,
        "SD_SCHUL_CODE": SD_SCHUL_CODE,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_string,
        "MLSV_TO_YMD": date_string,
        "pSize": "1000",
        "pIndex": "1"
    }

    try:
        response = requests.get(
            MEAL_API,
            params=params,
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

    except requests.exceptions.Timeout:
        return None, "timeout"

    except requests.exceptions.RequestException:
        return None, "connection"

    except ValueError:
        return None, "json"

    # 데이터가 없는 경우
    result = data.get("RESULT", {})

    if result.get("CODE") == "INFO-200":
        return [], None

    # 그 외 API 오류
    if result.get("CODE"):
        return None, result.get("MESSAGE", "API 오류")

    meal_info = data.get("mealServiceDietInfo", [])

    if len(meal_info) < 2:
        return [], None

    rows = meal_info[1].get("row", [])

    # 선택 날짜의 중식만 반환
    date_rows = [
        row for row in rows
        if row.get("MLSV_YMD") == date_string
        and row.get("MMEAL_SC_CODE") == "2"
    ]

    return date_rows, None


# ==========================================
# 메뉴 정리
# ==========================================

def parse_menu(menu_text):
    """
    메뉴 문자열을 메뉴별로 나눈다.
    <br/> 태그를 줄바꿈으로 바꾸고
    HTML 태그를 제거한다.
    """

    if not menu_text:
        return []

    menu_text = html.unescape(menu_text)

    menu_text = re.sub(
        r"(?i)<br\s*/?>",
        "\n",
        menu_text
    )

    menu_text = re.sub(
        r"<[^>]*>",
        "",
        menu_text
    )

    return [
        item.strip()
        for item in menu_text.splitlines()
        if item.strip()
    ]


def remove_allergy_numbers(menu):
    """
    메뉴 뒤 괄호 속 알레르기 번호를 제거한다.

    예:
    달걀말이(1.2.5) -> 달걀말이
    우유(2) -> 우유
    """

    return re.sub(
        r"\s*\(\s*\d+(?:\.\d+)*\s*\)",
        "",
        menu
    ).strip()


# ==========================================
# 화면 구성
# ==========================================

st.subheader("📅 날짜별 급식 확인")

# 날짜 선택과 알레르기 스위치를 나란히 배치
date_col, allergy_col = st.columns([2, 1])

with date_col:
    selected_date = st.date_input(
        "급식 날짜",
        value=TODAY,
        max_value=TODAY,
        format="YYYY-MM-DD"
    )

with allergy_col:
    st.write("")
    st.write("")

    show_allergy = st.toggle(
        "알레르기 정보 보기",
        value=True
    )

st.caption(
    f"선택한 날짜: {selected_date.strftime('%Y년 %m월 %d일')}"
)

st.divider()


# ==========================================
# 급식 조회
# ==========================================

with st.spinner("급식 메뉴를 불러오는 중입니다..."):
    meal_rows, error = get_meal(selected_date)


# ==========================================
# 오류 및 급식 없음 안내
# ==========================================

if error:

    if error == "timeout":
        st.error("서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")

    elif error == "connection":
        st.error("급식 정보를 불러올 수 없습니다. 인터넷 연결을 확인해 주세요.")

    elif error == "json":
        st.error("급식 정보를 읽을 수 없습니다. 잠시 후 다시 시도해 주세요.")

    else:
        st.error(f"급식 정보를 조회하는 중 오류가 발생했습니다: {error}")

elif not meal_rows:

    st.info("급식이 없는 날입니다")

else:

    # 해당 날짜의 중식 정보
    meal = meal_rows[0]

    menu_text = meal.get("DDISH_NM", "")
    calorie = meal.get("CAL_INFO", "")

    menus = parse_menu(menu_text)

    # 알레르기 번호 표시 여부
    if not show_allergy:
        menus = [
            remove_allergy_numbers(menu)
            for menu in menus
        ]

    # 빈 메뉴 제거
    menus = [
        menu for menu in menus
        if menu
    ]

    # ==========================================
    # 메뉴 가짓수와 칼로리 카드
    # ==========================================

    st.subheader("🍚 오늘의 중식")

    st.markdown(
        f"### {SCHOOL_NAME}"
    )

    st.caption(
        selected_date.strftime("%Y년 %m월 %d일")
    )

    metric_col1, metric_col2 = st.columns(2)

    with metric_col1:
        st.metric(
            label="🍽️ 메뉴 가짓수",
            value=f"{len(menus)}가지"
        )

    with metric_col2:
        st.metric(
            label="🔥 총 칼로리",
            value=calorie if calorie else "정보 없음"
        )

    st.divider()

    # ==========================================
    # 메뉴 카드
    # ==========================================

    st.subheader("오늘의 메뉴")

    if menus:

        # 한 줄에 카드 3개씩 배치
        columns_per_row = 3

        for start in range(
            0,
            len(menus),
            columns_per_row
        ):

            row_menus = menus[
                start:start + columns_per_row
            ]

            cols = st.columns(columns_per_row)

            for col, menu in zip(cols, row_menus):

                with col:
                    with st.container(
                        border=True
                    ):
                        st.markdown(
                            f"### {menu}"
                        )

    else:
        st.info("등록된 메뉴가 없습니다.")

    # ==========================================
    # 알레르기 안내
    # ==========================================

    if show_allergy:
        st.divider()

        st.caption(
            "※ 메뉴 이름 뒤 괄호의 숫자는 알레르기 유발 식품 번호입니다."
        )

        st.caption(
            "알레르기 번호는 나이스 급식 정보에 등록된 내용을 표시합니다."
        )

# ==========================================
# 하단 안내
# ==========================================

st.divider()

st.caption(
    "자료 출처: 나이스 교육정보 개방 포털"
)
