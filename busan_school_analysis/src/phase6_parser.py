"""Reusable Phase 6 catchment grammar.

The functions return evidence structures.  They never turn a partial parse into
an official assignment; callers must apply exclusions before inclusions.
"""
from __future__ import annotations

import re
import unicodedata


RANGE_SEP = r"[~～∼\-]"


def _ints(value: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", value)]


def parse_dong(text: str) -> dict:
    names = re.findall(r"([가-힣0-9]+(?:동|읍|면|리))", str(text))
    return {"dong_names": list(dict.fromkeys(names)), "raw_dong_expression": str(text)}


def _number_unit(text: str, unit: str) -> dict:
    raw = str(text)
    result = {f"raw_{unit}_expression": raw, f"{unit}_type": None,
              f"{unit}_values": [], f"{unit}_start": None, f"{unit}_end": None,
              f"exclude_{unit}_values": []}
    patterns = re.findall(rf"(\d+(?:\s*{RANGE_SEP}\s*\d+)?(?:\s*,\s*\d+)*)\s*{unit}", raw)
    if not patterns:
        return result
    values: list[int] = []
    ranges: list[tuple[int, int]] = []
    excludes: list[int] = []
    for expression in patterns:
        nums = _ints(expression)
        pos = raw.find(expression)
        tail = raw[pos:pos + len(expression) + len(unit) + 12]
        is_exclusion = "제외" in tail or "중" in raw[max(0, pos - 4):pos]
        if re.search(RANGE_SEP, expression) and len(nums) >= 2:
            expanded = list(range(nums[0], nums[1] + 1))
            ranges.append((nums[0], nums[1]))
        else:
            expanded = nums
        (excludes if is_exclusion else values).extend(expanded)
    values = list(dict.fromkeys(values))
    excludes = list(dict.fromkeys(excludes))
    result[f"exclude_{unit}_values"] = excludes
    if len(ranges) == 1 and not ("," in patterns[0]) and not excludes:
        result.update({f"{unit}_type": "range", f"{unit}_start": ranges[0][0],
                       f"{unit}_end": ranges[0][1]})
    elif ranges or len(patterns) > 1:
        result.update({f"{unit}_type": "mixed", f"{unit}_values": values})
    else:
        result.update({f"{unit}_type": "list", f"{unit}_values": values})
    return result


def parse_tong(text: str) -> dict:
    return _number_unit(text, "통")


def parse_ban(text: str) -> dict:
    return _number_unit(text, "반")


def parse_lot_number(text: str) -> dict:
    raw = str(text)
    out = {"raw_lot_expression": None, "lot_main": None, "lot_sub": None,
           "lot_range_start": None, "lot_range_end": None, "lot_exclusion": False}
    match = re.search(r"(산\s*)?(\d+)(?:-(\d+))?\s*번지", raw)
    range_match = re.search(r"(산\s*)?(\d+)\s*[~～∼]\s*(\d+)\s*번지", raw)
    if range_match:
        out.update(raw_lot_expression=range_match.group(0),
                   lot_range_start=int(range_match.group(2)), lot_range_end=int(range_match.group(3)),
                   lot_exclusion="제외" in raw[range_match.start():range_match.end() + 8])
    elif match:
        out.update(raw_lot_expression=match.group(0), lot_main=int(match.group(2)),
                   lot_sub=int(match.group(3)) if match.group(3) else None,
                   lot_exclusion="제외" in raw[match.start():match.end() + 8])
    return out


def parse_road_address(text: str) -> dict:
    match = re.search(r"[가-힣0-9·.\- ]+(?:로|길)\s*\d+(?:-\d+)?", str(text))
    return {"road_address_pattern": match.group(0).strip() if match else None}


def parse_apartment_clause(text: str) -> dict:
    raw = str(text).strip()
    parenthesized = re.findall(r"\(([^()]*(?:아파트|빌라|타워|캐슬|파크|더샵|래미안|위브|자이|스위첸)[^()]*)\)", raw)
    candidates = parenthesized
    status = "parsed" if candidates else None
    if not candidates:
        # Consume the text following the final tong/ban expression.  Keeping it
        # as a candidate prevents an ambiguous Korean noun from confirming a match.
        tail = re.split(r"\d+\s*(?:통|반)", raw)[-1].strip(" ,;()")
        if tail and not re.search(r"번지|제외|포함|일원|전역", tail):
            if re.search(r"아파트|빌라|타워|캐슬|파크|더샵|래미안|위브|자이|스위첸|\d+\s*차", tail):
                candidates = [tail]
                status = "candidate"
    return {"apartment_name_patterns": candidates, "apartment_parse_status": status,
            "manual_review": status == "candidate"}


def parse_exclusion_clause(text: str) -> list[dict]:
    raw = str(text)
    if "제외" not in raw:
        return []
    return [{"boundary_action": "EXCLUDE", "condition_text": x.strip(" ,;()")}
            for x in re.findall(r"(?:단[, ]*)?([^.;]+?제외)", raw)]


def parse_inclusion_clause(text: str) -> list[dict]:
    return [{"boundary_action": "INCLUDE", "condition_text": str(text).strip()}]


def parse_exception_clause(text: str) -> list[dict]:
    return parse_exclusion_clause(text)


def parse_shared_catchment(text: str) -> dict:
    return {"shared_catchment": "공동통학" in str(text) or "공동학구" in str(text)}


def parse_condition(text: str) -> dict:
    raw = str(text)
    return {"condition_text": raw if re.search(r"중|일부|한함|가능|예정", raw) else None,
            "boundary_action": "CONDITIONAL" if re.search(r"중|일부|한함|가능|예정", raw) else "INCLUDE"}


def parse_rule(text: str) -> list[dict]:
    base = {}
    for parser in (parse_dong, parse_tong, parse_ban, parse_lot_number,
                   parse_road_address, parse_apartment_clause, parse_shared_catchment, parse_condition):
        base.update(parser(text))
    rows = [dict(base, raw_catchment_text=str(text))]
    exclusions = parse_exclusion_clause(text)
    if exclusions:
        rows += [dict(base, **rule, raw_catchment_text=str(text)) for rule in exclusions]
    recognized = any((base.get("tong_type"), base.get("ban_type"), base.get("lot_main"),
                      base.get("lot_range_start"), base.get("road_address_pattern"),
                      base.get("apartment_name_patterns"), base.get("dong_names")))
    for row in rows:
        row["parse_status"] = "PARTIAL" if not recognized or row.get("manual_review") else "PARSED"
        row["confidence"] = 1.0 if row["parse_status"] == "PARSED" else 0.5
        row["manual_review"] = bool(row.get("manual_review") or row["parse_status"] != "PARSED")
    return rows


def boundary_decision(rules: list[dict]) -> str:
    actions = {r.get("boundary_action") for r in rules}
    return "EXCLUDE" if "EXCLUDE" in actions else ("CONDITIONAL" if "CONDITIONAL" in actions else "INCLUDE")


def normalize_name_literal(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", unicodedata.normalize("NFKC", str(value)).lower())


BRANDS = {"삼성래미안": "래미안", "포스코더샵": "더샵", "롯데 캐슬": "롯데캐슬"}


def normalize_brand(value: str, aliases: dict | None = None) -> str:
    out = str(value)
    for alias, canonical in {**BRANDS, **(aliases or {})}.items():
        out = out.replace(alias, canonical)
    return out


def normalize_phase(value: str) -> str:
    return re.sub(r"\s*(\d+)\s*차", r"\1차", str(value))


def normalize_alias(value: str, aliases: dict | None = None) -> str:
    return normalize_name_literal(normalize_phase(normalize_brand(value, aliases)))
