import urllib.request
import urllib.parse
import json
import sys

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://kbland.kr/"
}

def get_json(url):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    complex_no = "31369"
    q_param = urllib.parse.quote("단지기본일련번호")
    # 1. 단지 메인
    main_url = f"https://api.kbland.kr/land-complex/complex/complexMain?{q_param}={complex_no}"
    main_data = get_json(main_url)
    base_info = main_data.get("dataBody", {}).get("data", {}).get("baseInfo", {})
    print("단지명:", base_info.get("단지명"))
    print("총세대수:", base_info.get("총세대수"))
    print("사용승인일자:", base_info.get("사용승인일자"))
    print("주소:", base_info.get("새주소기본주소"))

    # 2. mpriByType
    mpri_url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{q_param}={complex_no}"
    mpri_list = get_json(mpri_url).get("dataBody", {}).get("data", [])

    print(f"\n총 {len(mpri_list)}개 평형 타입:")
    total_hh = 0
    for item in mpri_list:
        hh = item.get("세대수", 0)
        total_hh += hh
        t_name = item.get("주택형타입내용") or "-"
        sup_m2 = item.get("공급면적")
        sup_p = item.get("공급면적평")
        ex_m2 = item.get("전용면적")
        p_sale = item.get("매매일반거래가")
        p_jeonse = item.get("전세일반거래가")
        rent_dep = item.get("월세보증금액")
        rent_low = item.get("월임대최저금액")
        rent_high = item.get("월임대최고금액")
        area_no = item.get("면적일련번호")
        print(f"[{area_no}] {t_name}타입 | 공급: {sup_m2}㎡ ({sup_p}평) | 전용: {ex_m2}㎡ | 세대수: {hh:3d} | 매매: {p_sale}만 | 전세: {p_jeonse}만 | 월세: {rent_dep}/{rent_low}~{rent_high}")

    print(f"\n타입별 세대수 합계: {total_hh}")
    kapt_hh = 994
    print(f"K-apt 총세대수(대연SK뷰힐스): {kapt_hh}")
    print(f"세대수 일치 여부: {total_hh == kapt_hh} (차이: {abs(total_hh - kapt_hh)})")

if __name__ == "__main__":
    main()
