from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.detail_navigation import open_detail, school_ranking_table


def test_detail_navigation_rejects_stale_selection():
    state = {"tab": "ranking", "selected": "a"}
    open_detail(state, "missing", ["a", "b"], "tab", "selected", "detail")
    assert state == {"tab": "ranking", "selected": "a"}
    open_detail(state, "b", ["a", "b"], "tab", "selected", "detail")
    assert state == {"tab": "detail", "selected": "b"}


def test_sorted_school_component_routes_by_id():
    view = pd.DataFrame({"school": ["same name", "same name"], "score": [98, 40]}, index=[5, 2])
    state = {"ranking": {"opened": "school-b"}}
    with patch("src.detail_navigation.st.session_state", state), patch("src.detail_navigation.st.caption"), patch("src.detail_navigation._school_table") as component:
        school_ranking_table(view, ["school-b", "school-a"], key="ranking", tab_key="tab", selection_key="selected")
        args = component.call_args.kwargs
        assert args["data"]["rows"][0] == {"id": "school-b", "values": ["same name", 98]}
        args["on_opened_change"]()
    assert state["selected"] == "school-b"
    assert state["tab"] == "학교 상세"


@pytest.mark.parametrize("module,prefix,id_column,loader", [
    ("elementary_demand", "elementary", "elementary_school_id", "load_elementary_demand_data"),
    ("middle_school_score", "middle", "middle_school_id", "load_middle_school_scores"),
])
def test_school_detail_state_and_filter_fallback(module, prefix, id_column, loader):
    import importlib
    from src.config import ROOT
    dashboard = importlib.import_module(f"src.{module}_dashboard")
    data = getattr(dashboard, loader)(str(ROOT))
    if isinstance(data, tuple):
        data = data[0]
    score_column = "elementary_demand_score" if prefix == "elementary" else "middle_school_score"
    target = str(data[data[score_column].notna()].iloc[-1][id_column])
    # Each AppTest owns a new component registry; register inside that runtime.
    app = AppTest.from_string(f"import importlib\nimport src.detail_navigation\nimportlib.reload(src.detail_navigation)\nfrom src.{module}_dashboard import render_{module}_dashboard\nrender_{module}_dashboard()")
    app.session_state[f"{prefix}_detail"] = target
    app.session_state[f"{prefix}_tabs"] = "학교 상세"
    app.run(timeout=30)
    assert not app.exception
    assert app.selectbox(key=f"{prefix}_detail").value == target
    assert app.session_state[f"{prefix}_tabs"] == "학교 상세"
    district_column = "sigungu_requested" if prefix == "elementary" else "sigungu"
    target_district = data.loc[data[id_column].astype(str).eq(target), district_column].iloc[0]
    other_district = next(value for value in data[district_column].dropna().unique() if value != target_district)
    app.multiselect[0].set_value([other_district])
    app.run(timeout=30)
    assert not app.exception
    assert app.selectbox(key=f"{prefix}_detail").value in set(data[id_column].astype(str))
    assert app.selectbox(key=f"{prefix}_detail").value != target


def test_apartment_selection_callback():
    from src.final_value_dashboard import _display_table
    state = {"core_candidates": {"selection": {"rows": [1]}}}
    data = pd.DataFrame({"apartment_id": ["b", "a"], "apartment_name": ["same", "same"]})
    with patch("src.final_value_dashboard.st.session_state", state), patch("src.final_value_dashboard.st.caption"), patch("src.final_value_dashboard.st.dataframe") as table:
        _display_table(data, ["apartment_name"], selectable=True)
        table.call_args.kwargs["on_select"]()
    assert state["premium_detail"] == "a"
    assert state["premium_tabs"] == "단지 상세"


def test_premium_detail_renders_selected_apartment():
    from src.config import ROOT
    from src.final_value_dashboard import load_frozen_data
    master, *_ = load_frozen_data(str(ROOT))
    target = str(master[master.final_review_class.eq("CORE_CANDIDATE")].iloc[-1].apartment_id)
    app = AppTest.from_string("from src.final_value_dashboard import render_final_value_dashboard\nrender_final_value_dashboard()")
    app.session_state["premium_detail"] = target
    app.session_state["premium_tabs"] = "단지 상세"
    app.run(timeout=30)
    assert not app.exception
    assert app.selectbox(key="premium_detail").value == target
    assert app.session_state["premium_tabs"] == "단지 상세"
    assert all(widget.proto.placeholder == "선택" for widget in app.multiselect)
