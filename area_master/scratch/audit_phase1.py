import pandas as pd
from pathlib import Path

def audit():
    # 1. PENDING 감사
    pending_path = Path("data/review/area_master_pending.csv")
    df_pending = pd.read_csv(pending_path)
    print("========================================")
    print("PHASE 2 PENDING AUDIT")
    print("========================================")
    print(f"Total pending rows in CSV : {len(df_pending)}")
    print(f"Unique kapt_codes         : {df_pending['kapt_code'].nunique()}")
    
    # reason_code 분포
    counts = df_pending['reason_code'].value_counts()
    print("\nReason code breakdown:")
    for code, cnt in counts.items():
        print(f"  {code:<25}: {cnt}")
    print(f"\nReason total              : {counts.sum()}")
    
    # 198 vs 197 원인 파악:
    # 1차 완료 보고서에서 출력했던 수치:
    # KB_COMPLEX_NOT_FOUND: 70
    # RENTAL_COMPLEX: 49
    # MIXED_RENTAL_COMPLEX: 37
    # LOW_MATCH_CONFIDENCE: 27
    # HOUSEHOLDS_MISMATCH: 14
    # 합계 = 70 + 49 + 37 + 27 + 14 = 197
    # 그리고 누락되었던 1건:
    # KB_COMPLEX_AMBIGUOUS: 1건 !
    # 197 + 1 = 198!
    ambiguous = df_pending[df_pending['reason_code'] == 'KB_COMPLEX_AMBIGUOUS']
    print("\nKB_COMPLEX_AMBIGUOUS item:")
    for _, r in ambiguous.iterrows():
        print(f"  kapt_code={r['kapt_code']}, kapt_name={r['kapt_name']}, reason={r['reason']}")

    # phase2_pending_audit.csv 저장
    audit_df = df_pending.copy()
    Path("data/review").mkdir(parents=True, exist_ok=True)
    audit_df.to_csv("data/review/phase2_pending_audit.csv", index=False, encoding="utf-8-sig")
    print("\nSaved: data/review/phase2_pending_audit.csv")

    # 2. 2309 vs 2306 merge 3건 감사
    raw_path = Path("data/raw/kb/kb_area_types.csv")
    master_path = Path("config/market_cap_area_master.csv")
    df_raw = pd.read_csv(raw_path)
    df_master = pd.read_csv(master_path)
    print("\n========================================")
    print("PHASE 1 AREA MERGE AUDIT (2309 vs 2306)")
    print("========================================")
    print(f"KB raw rows               : {len(df_raw)}")
    print(f"Master rows               : {len(df_master)}")
    print(f"Difference                : {len(df_raw) - len(df_master)} rows")

    # 단지별 raw 개수 vs master 개수 비교
    raw_counts = df_raw.groupby('kapt_code').size()
    master_counts = df_master.groupby('kapt_code').size()
    diff_complexes = []
    for k in master_counts.index:
        rc = raw_counts.get(k, 0)
        mc = master_counts.get(k, 0)
        if rc != mc:
            diff_complexes.append((k, rc, mc))

    print(f"\nComplexes with row difference: {len(diff_complexes)}")
    merge_audit_rows = []
    for k, rc, mc in diff_complexes:
        sub_raw = df_raw[df_raw['kapt_code'] == k]
        sub_master = df_master[df_master['kapt_code'] == k]
        kname = sub_raw.iloc[0]['kapt_name']
        print(f"\n단지 [{k}] {kname}: Raw {rc} -> Master {mc}")
        print("Raw types:")
        for _, r in sub_raw.iterrows():
            print(f"  type={r['type_name']}, ex_sqm={r['exclusive_area_sqm']}, hh={r['households']}")
        print("Master rows:")
        for _, m in sub_master.iterrows():
            print(f"  type={m['type_name']}, ex_sqm={m['exclusive_area_sqm']}, hh={m['households']}")

        # 동일 전용면적 그룹핑 확인
        for ex, group in sub_raw.groupby('exclusive_area_sqm'):
            if len(group) > 1:
                types_before = "/".join(group['type_name'].astype(str))
                hh_before = "/".join(group['households'].astype(str))
                merged_hh = group['households'].sum()
                merge_audit_rows.append({
                    "kapt_code": k,
                    "kapt_name": kname,
                    "exclusive_area_sqm": ex,
                    "types_before": types_before,
                    "households_before": hh_before,
                    "merged_households": merged_hh,
                    "count_merged": len(group),
                    "merge_reason": "동일 전용면적(exclusive_area_sqm) A/B 타입 합산",
                    "precision_source": "KB mpriByType"
                })

    df_merge_audit = pd.DataFrame(merge_audit_rows)
    df_merge_audit.to_csv("data/review/phase1_area_merge_audit.csv", index=False, encoding="utf-8-sig")
    print(f"\nSaved: data/review/phase1_area_merge_audit.csv ({len(df_merge_audit)} merge cases)")

if __name__ == "__main__":
    audit()
