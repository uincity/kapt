"""Official 2025 middle-assignment source collection and table validation."""
from __future__ import annotations
import hashlib, json, re, zipfile
from xml.etree import ElementTree
from pathlib import Path
from urllib.parse import urljoin
import pandas as pd
import requests
from .config import ROOT, atomic_bytes, now, write_csv
from .collect_middle_assignment import _safe_name, _validate_attachment
from .phase6_build import infer_columns
from .parsers.pdf_parser import parse_pdf
import yaml

POSTS={
 "nambu":{"bbs":"3852","mi":"13804","ntt":"880109"},
 "seobu":{"bbs":"3614","mi":"9580","ntt":"881942"},
 "dongnae":{"bbs":"3779","mi":"11537","ntt":"881059"},
 "bukbu":{"bbs":"3735","mi":"12915","ntt":"880905"},
}

def collect_phase6_middle(office,year=2025,*,force=False,root=ROOT,session=requests):
    if year!=2025 or office not in POSTS: raise ValueError("Supported offices: nambu, seobu, dongnae, bukbu; year 2025")
    c=POSTS[office]; base=Path(root)/f"data/raw/education_office/{office}/{year}/middle_assignment"; meta=base/"attachments_metadata.csv"
    if meta.exists() and not force: return {"status":"cached","attachments":len(pd.read_csv(meta))}
    host="https://home.pen.go.kr"; post=f"{host}/{office}/na/ntt/selectNttInfo.do?mi={c['mi']}&bbsId={c['bbs']}&nttSn={c['ntt']}"
    page=session.get(post,timeout=30); page.raise_for_status()
    api=session.get(f"{host}/{office}/na/ntt/fileDownChk.do",params={"bbsId":c["bbs"],"mi":c["mi"],"nttSn":c["ntt"]},timeout=30); api.raise_for_status()
    rows=[]; stamp=now(); atomic_bytes(base/f"post_{c['ntt']}.html",page.content)
    for i,a in enumerate(api.json().get("nttFileList") or [],1):
        remote=a.get("flpth") or a.get("filePath"); url=urljoin(host,remote); response=session.get(url,timeout=60); response.raise_for_status()
        ext=(a.get("extsn") or Path(remote).suffix).lstrip('.').lower(); _validate_attachment(response.content,ext)
        original=a.get("fileNm") or Path(remote).name; name=_safe_name(original,f"{c['ntt']}_{i}.{ext}")
        if not Path(name).suffix:name += "."+ext
        atomic_bytes(base/name,response.content)
        rows.append({"post_title":"2025학년도 중학교 입학 배정 시행계획","data_year":2025,"education_office":office,"post_url":post,"attachment_name":original,"attachment_url":url,"attachment_type":ext,"downloaded_at":stamp,"sha256":hashlib.sha256(response.content).hexdigest(),"local_file":name})
    if not rows: raise ValueError("Official post has no downloadable attachments")
    write_csv(meta,pd.DataFrame(rows)); return {"status":"downloaded","attachments":len(rows),"types":sorted({x['attachment_type'] for x in rows})}

def validate_middle_tables(*,root=ROOT):
    aliases=yaml.safe_load((Path(root)/"config/middle_assignment_column_aliases.yaml").read_text(encoding="utf-8")); rows=[]
    for office in ("haeundae","dongnae","nambu","bukbu","seobu"):
        base=Path(root)/f"data/raw/education_office/{office}/2025/middle_assignment"; meta=base/"attachments_metadata.csv"
        if not meta.exists(): rows.append({"office":office,"documents":0,"table_detected":False,"status":"SOURCE_MISSING"}); continue
        docs=pd.read_csv(meta); detected=False; supported=0; reason="NO_STRUCTURED_ATTACHMENT"
        for item in docs.to_dict("records"):
            path=base/item["local_file"]; ext=str(item.get("attachment_type","")).lower()
            if ext=="xlsx":
                frame=pd.read_excel(path,header=None); supported+=1
                for i in range(min(20,len(frame))):
                    columns=infer_columns(frame.iloc[i].fillna("").astype(str).tolist(),aliases)
                    if "elementary_school" in columns and ("middle_school" in columns or "school_group" in columns): detected=True; reason="HEADER_ALIASES"
            elif ext=="pdf":
                supported+=1; text=parse_pdf(path).text
                for line in text.splitlines():
                    cells=[x.strip() for x in re.split(r"\s{2,}",line) if x.strip()]
                    columns=infer_columns(cells,aliases)
                    if "elementary_school" in columns and ("middle_school" in columns or "school_group" in columns):
                        detected=True; reason="PDF_LAYOUT_HEADER_ALIASES"; break
            elif ext=="hwpx":
                supported+=1
                try:
                    with zipfile.ZipFile(path) as z:
                        for name in z.namelist():
                            if not re.search(r"Contents/section\d+\.xml$",name,re.I): continue
                            xml=ElementTree.fromstring(z.read(name))
                            for table in [n for n in xml.iter() if n.tag.endswith('}tbl')]:
                                cells=[]
                                for cell in [n for n in table.iter() if n.tag.endswith('}tc')]:
                                    cells.append(''.join(t.text or '' for t in cell.iter() if t.tag.endswith('}t')))
                                columns=infer_columns(cells[:12],aliases)
                                if "elementary_school" in columns and ("middle_school" in columns or "school_group" in columns):
                                    detected=True; reason="HWPX_TABLE_HEADER_ALIASES"; break
                except (zipfile.BadZipFile,ElementTree.ParseError): reason="INVALID_HWPX"
        rows.append({"office":office,"documents":len(docs),"supported_documents":supported,"table_detected":detected,"status":"VALIDATED" if detected else "MANUAL_REVIEW","reason":reason})
    out=pd.DataFrame(rows); write_csv(Path(root)/"reports/phase6_middle_parser_quality.csv",out); return out
