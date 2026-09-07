"""Build 부산 official administrative/legal-dong tables from MOIS KiKmix."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import pandas as pd
from .config import ROOT, write_parquet

SOURCE_NAME="행정안전부 행정기관 및 관할구역 코드(KiKmix)"
SOURCE_DATE="2025-11-03"

def _date(value):
    parsed=pd.to_datetime(value,format="%Y%m%d",errors="coerce")
    return parsed.dt.date.astype("string")

def build_admin_crosswalk(*, root=ROOT):
    root=Path(root); archive=root/"data/raw/admin_codes/2025/jscode20251103.zip"
    if not archive.exists(): raise FileNotFoundError("Run collect-admin-codes first")
    with ZipFile(archive) as z:
        mix=pd.read_excel(BytesIO(z.read("KIKmix.20251103.xlsx")),dtype=str)
    mix=mix[(mix["시도명"]=="부산광역시") & mix["읍면동명"].notna() & mix["법정동코드"].str.startswith("26")].copy()
    mix=mix[mix["말소일자"].isna()].drop_duplicates(["행정동코드","법정동코드"])
    cross=pd.DataFrame({"admin_dong_code":mix["행정동코드"],"admin_dong_name":mix["읍면동명"],
                        "legal_dong_code":mix["법정동코드"],"legal_dong_name":mix["동리명"],
                        "relation_type":"OFFICIAL_JURISDICTION","effective_from":_date(mix["생성일자"]),
                        "effective_to":_date(mix["말소일자"]),"source_name":SOURCE_NAME})
    master=pd.DataFrame({"sido_code":"26","sido_name":"부산광역시",
                         "sigungu_code":mix["행정동코드"].str[:5],"sigungu_name":mix["시군구명"],
                         "legal_dong_code":mix["법정동코드"],"legal_dong_name":mix["동리명"],
                         "admin_dong_code":mix["행정동코드"],"admin_dong_name":mix["읍면동명"],
                         "effective_from":_date(mix["생성일자"]),"effective_to":_date(mix["말소일자"]),
                         "source_name":SOURCE_NAME,"source_date":SOURCE_DATE})
    p1=root/"data/processed/busan_admin_area_master.parquet"; p2=root/"data/processed/busan_admin_legal_crosswalk.parquet"
    write_parquet(p1,master); write_parquet(p2,cross)
    many=int(cross.groupby("legal_dong_code").admin_dong_code.nunique().gt(1).sum())
    return {"master_rows":len(master),"crosswalk_rows":len(cross),"many_to_many_legal_dongs":many,"master":str(p1),"crosswalk":str(p2)}
