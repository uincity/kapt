"""Configuration-only adapters for 부산 education offices."""
from __future__ import annotations
from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class OfficeSource:
    office: str
    catchment_urls: tuple[str, ...]
    middle_board_url: str | None = None


SOURCES = {
    "haeundae": OfficeSource("haeundae", ("https://home.pen.go.kr/haeundae/cm/cntnts/cntntsView.do?cntntsId=311&mi=11750",)),
    "dongnae": OfficeSource("dongnae", tuple(f"https://home.pen.go.kr/dongnae/cm/cntnts/cntntsView.do?cntntsId={n}&mi={m}" for n, m in ((2018,14061),(2019,14062),(2020,14063)))),
    "nambu": OfficeSource("nambu", ("https://home.pen.go.kr/nambu/cm/cntnts/cntntsView.do?cntntsId=100&mi=12307",)),
    "bukbu": OfficeSource("bukbu", ("https://home.pen.go.kr/bukbu/cm/cntnts/cntntsView.do?cntntsId=166&mi=13616",)),
    "seobu": OfficeSource("seobu", tuple(f"https://home.pen.go.kr/seobu/cm/cntnts/cntntsView.do?cntntsId={n}&mi={m}" for n, m in ((49,9972),(50,9974),(51,9975),(52,9976)))),
}


class EducationOfficeAdapter(ABC):
    office = ""
    def collect_elementary_catchment(self, year, **kwargs):
        from .phase6_collect import collect_office_catchment
        return collect_office_catchment(self.office, year, **kwargs)
    def parse_elementary_catchment(self, year, **kwargs):
        from .phase6_build import parse_office_catchment
        return parse_office_catchment(self.office, year, **kwargs)
    def collect_middle_assignment(self, year, **kwargs):
        from .collect_middle_assignment import collect_middle_assignment
        return collect_middle_assignment(self.office, year, **kwargs)
    def parse_middle_assignment(self, year, **kwargs):
        from .parse_middle_assignment import parse_middle_assignment
        return parse_middle_assignment(self.office, year, **kwargs)
    def collect_middle_school_groups(self, year, **kwargs):
        return self.collect_middle_assignment(year, **kwargs)


class HaeundaeAdapter(EducationOfficeAdapter): office = "haeundae"
class DongnaeAdapter(EducationOfficeAdapter): office = "dongnae"
class NambuAdapter(EducationOfficeAdapter): office = "nambu"
class BukbuAdapter(EducationOfficeAdapter): office = "bukbu"
class SeobuAdapter(EducationOfficeAdapter): office = "seobu"

ADAPTERS = {c.office: c() for c in (HaeundaeAdapter, DongnaeAdapter, NambuAdapter, BukbuAdapter, SeobuAdapter)}
