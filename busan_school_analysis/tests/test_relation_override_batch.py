import pandas as pd
import pytest

from src.relation_override_batch import _selected_review


BASE={"수정적용":"Y","수정가능":"Y","초등학교ID":"E1","초등학교":"테스트초",
      "중학교ID":"M1","중학교":"테스트중","수정관계유형":"확정 배정","수정반영상태":"점수 반영",
      "실제배정비율":"1.0","수정근거":"2026 실제배정 확인","근거자료":"공식문서 1쪽"}


def test_batch_review_accepts_audited_exact(tmp_path):
    path=tmp_path/"review.csv"; pd.DataFrame([BASE]).to_csv(path,index=False,encoding="utf-8-sig")
    out,_=_selected_review(path)
    assert out.iloc[0].relation_type=="EXACT"
    assert out.iloc[0].relation_status=="ACTIVE"


def test_batch_review_rejects_exact_without_full_share(tmp_path):
    row={**BASE,"실제배정비율":"0.5"}; path=tmp_path/"review.csv"
    pd.DataFrame([row]).to_csv(path,index=False,encoding="utf-8-sig")
    with pytest.raises(ValueError,match="1.0"): _selected_review(path)


def test_batch_review_rejects_unresolved_selected_row(tmp_path):
    row={**BASE,"수정가능":"N","중학교ID":""}; path=tmp_path/"review.csv"
    pd.DataFrame([row]).to_csv(path,index=False,encoding="utf-8-sig")
    with pytest.raises(ValueError,match="ID 미해결"): _selected_review(path)

