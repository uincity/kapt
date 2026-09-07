import pandas as pd
from src.education_offices import ADAPTERS, EducationOfficeAdapter
from src.phase6_build import infer_columns
from src.phase6_collect import detect_data_year
from src.phase6_identity import build_address_history, build_school_name_mapping, scores_by_id, validate_admin_area
from src.phase6_parser import parse_tong,parse_ban,parse_lot_number,parse_rule,boundary_decision,parse_apartment_clause,normalize_brand,normalize_phase
from src.build_admin_crosswalk import build_admin_crosswalk
from src.phase6_middle import validate_middle_tables
from zipfile import ZipFile
from pathlib import Path

def test_tong_discrete_list(): assert parse_tong("1,3,5통")["통_values"] == [1,3,5]
def test_tong_range_exclusion(): assert 3 in parse_tong("1~5통 중 3통 제외")["exclude_통_values"]
def test_ban_range_exclusion(): assert parse_ban("5통 중 2~4반 제외")["exclude_반_values"] == [2,3,4]
def test_lot_number(): assert parse_lot_number("123-4번지")["lot_sub"] == 4
def test_lot_range(): assert parse_lot_number("123~130번지")["lot_range_end"] == 130
def test_lot_exclusion(): assert parse_lot_number("123번지 제외")["lot_exclusion"]
def test_boundary_exclude_priority(): assert boundary_decision(parse_rule("1~5통 단 3통 제외")) == "EXCLUDE"
def test_parenthesisless_apartment_clause(): assert parse_apartment_clause("19~22통 센텀파크 1차 2차")["apartment_parse_status"] == "candidate"
def test_parenthesisless_ambiguous_review(): assert parse_apartment_clause("19통 센텀파크")["manual_review"]
def test_brand_alias_not_confirmation(): assert normalize_brand("포스코더샵") == "더샵"
def test_phase_difference(): assert normalize_phase("센텀파크 1 차") != normalize_phase("센텀파크 2 차")
def test_school_name_to_id():
 s=pd.DataFrame([{"school_name":"가초등학교","school_id":"S1","school_level":"elementary","education_office":"동래"}]); assert build_school_name_mapping(pd.DataFrame([{"school_name":"가초등학교","school_level":"elementary","education_office":"동래"}]),s,2025).school_id.iloc[0]=="S1"
def test_duplicate_school_name():
 s=pd.DataFrame([{"school_name":"가초등학교","school_id":"S1","school_level":"elementary","education_office":"동래"},{"school_name":"가초등학교","school_id":"S2","school_level":"elementary","education_office":"동래"}]); assert build_school_name_mapping(pd.DataFrame([{"school_name":"가초등학교","school_level":"elementary","education_office":"동래"}]),s,2025).manual_review.iloc[0]
def test_school_id_score_join():
 a=pd.DataFrame([{"middle_school_id":"S1","middle_school_name":"가중학교","data_year":2025,"middle_school_score":1,"busan_rank":1,"sigungu_rank":1}]); assert scores_by_id(a,pd.DataFrame({"school_id":["S1"]})).join_status.iloc[0]=="MATCHED"
def test_school_name_not_score_join():
 a=pd.DataFrame([{"middle_school_id":"OLD","middle_school_name":"가중학교","data_year":2025,"middle_school_score":1,"busan_rank":1,"sigungu_rank":1}]); assert scores_by_id(a,pd.DataFrame({"school_id":["NEW"]})).join_status.iloc[0]=="ID_NOT_FOUND"
def test_pdf_header_detection(): assert infer_columns(["출신초","배정중학교"],{"elementary_school":["출신초"],"middle_school":["배정중학교"]})=={"elementary_school":0,"middle_school":1}
def test_pdf_dynamic_column_order(): assert infer_columns(["성별","중학교","초등학교"],{"elementary_school":["초등학교"],"middle_school":["중학교"],"gender":["성별"]})["elementary_school"]==2
def test_pdf_unknown_structure_review(): assert infer_columns(["비고"],{"middle_school":["중학교"]})=={}
def test_school_group_year_unknown(): assert detect_data_year("학교군 안내")[0] is None
def test_group_membership_not_exact(): assert "GROUP_MEMBERSHIP" != "EXACT"
def test_office_adapter_interface(): assert all(isinstance(x,EducationOfficeAdapter) for x in ADAPTERS.values())
def test_five_office_fixture(): assert set(ADAPTERS)=={"haeundae","dongnae","nambu","bukbu","seobu"}
def test_historical_address_flag(): assert build_address_history(pd.DataFrame([{"internal_complex_id":"1"}])).source_year.isna().all()
def test_spatial_admin_validation(): assert validate_admin_area("1","2","1","3")["admin_area_conflict"]
def test_school_year_detection(): assert detect_data_year("기준 2025학년도")[0] == 2025
def test_admin_legal_crosswalk(tmp_path):
 import io
 root=Path(tmp_path); p=root/"data/raw/admin_codes/2025"; p.mkdir(parents=True)
 d=pd.DataFrame([{"행정동코드":"2614051000","시도명":"부산광역시","시군구명":"서구","읍면동명":"동대신1동","법정동코드":"2614010100","동리명":"동대신동1가","생성일자":"20000101","말소일자":None}])
 b=io.BytesIO(); d.to_excel(b,index=False)
 with ZipFile(p/"jscode20251103.zip","w") as z:z.writestr("KIKmix.20251103.xlsx",b.getvalue())
 assert build_admin_crosswalk(root=root)["crosswalk_rows"]==1
def test_admin_legal_many_to_many(tmp_path):
 import io
 root=Path(tmp_path); p=root/"data/raw/admin_codes/2025"; p.mkdir(parents=True)
 d=pd.DataFrame([{"행정동코드":"2614051000","시도명":"부산광역시","시군구명":"서구","읍면동명":"가동","법정동코드":"2614010100","동리명":"가동","생성일자":"20000101","말소일자":None},{"행정동코드":"2614052000","시도명":"부산광역시","시군구명":"서구","읍면동명":"나동","법정동코드":"2614010100","동리명":"가동","생성일자":"20000101","말소일자":None}])
 b=io.BytesIO(); d.to_excel(b,index=False)
 with ZipFile(p/"jscode20251103.zip","w") as z:z.writestr("KIKmix.20251103.xlsx",b.getvalue())
 assert build_admin_crosswalk(root=root)["many_to_many_legal_dongs"]==1
