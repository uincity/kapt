from pathlib import Path

p = Path(r"d:\90.invest\80.데이터수집\아파트정보수집\kapt\busan_apartment_analysis\src\market_cap_display.py")
text = p.read_text(encoding="utf-8")

if 'default=["A", "B"]' in text:
    text = text.replace('default=["A", "B"]', 'default=["A", "B", "C", "D"]')
    p.write_text(text, encoding="utf-8")
    print("Updated market_cap_display.py successfully!")
elif "default=['A', 'B']" in text:
    text = text.replace("default=['A', 'B']", "default=['A', 'B', 'C', 'D']")
    p.write_text(text, encoding="utf-8")
    print("Updated market_cap_display.py successfully!")
else:
    print("Target string not found in market_cap_display.py")
