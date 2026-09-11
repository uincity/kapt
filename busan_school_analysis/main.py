import argparse
import json
import sys

from src.collect_schoolinfo import collect_schools
from src.inspect_apartments import inspect_apartments


def main(argv=None):
    parser = argparse.ArgumentParser(description='부산 학군 데이터 검증: Phase 1-10')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect-apartments')
    collect = sub.add_parser('collect-schools')
    collect.add_argument('--year', type=int, required=True)
    collect.add_argument('--force', action='store_true')
    advancement = sub.add_parser('collect-advancement')
    advancement.add_argument('--years', type=int, nargs='+', required=True)
    advancement.add_argument('--force', action='store_true')
    sub.add_parser('score-middle-schools')
    sub.add_parser('report')
    sub.add_parser('collect-admin-codes')
    sub.add_parser('build-admin-crosswalk')
    sub.add_parser('phase6-foundations')
    sub.add_parser('phase6-report')
    sub.add_parser('phase6-middle-report')
    schoolzone_collect = sub.add_parser('collect-schoolzone')
    schoolzone_collect.add_argument('--year', type=int, required=True)
    schoolzone_collect.add_argument('--force', action='store_true')
    schoolzone_build = sub.add_parser('build-schoolzone')
    schoolzone_build.add_argument('--year', type=int, required=True)
    sub.add_parser('phase65-audit')
    phase65_geocode = sub.add_parser('phase65-geocode')
    phase65_geocode.add_argument('--retry-failed', action='store_true')
    sub.add_parser('phase65-build')
    sub.add_parser('phase7-audit')
    phase7_build_parser = sub.add_parser('phase7-build')
    phase7_build_parser.add_argument('--assignment-year', type=int, choices=[2025, 2026], default=2025)
    sub.add_parser('phase8-build')
    phase9_collect = sub.add_parser('phase9-collect')
    phase9_collect.add_argument('--years', type=int, nargs='+', default=[2024, 2025, 2026])
    phase9_collect.add_argument('--force', action='store_true')
    sub.add_parser('phase9-build')
    sub.add_parser('phase95-build')
    sub.add_parser('phase10-build')
    sub.add_parser('phase11-build')
    sub.add_parser('phase115-build')
    relation_export = sub.add_parser('export-relation-review')
    relation_export.add_argument('--output', default='em_school/초중배정관계_일괄검토_2026.csv')
    relation_import = sub.add_parser('import-relation-review')
    relation_import.add_argument('--csv', required=True)
    relation_import.add_argument('--rebuild', action='store_true')
    sub.add_parser('phase7-auto-exact')
    sub.add_parser('phase12-build')
    sub.add_parser('phase125-build')
    sub.add_parser('phase13-build')
    sub.add_parser('phase135-145-build')
    review = sub.add_parser('import-advancement')
    review.add_argument('--csv', required=True)
    geo = sub.add_parser('geocode-schools')
    geo.add_argument('--retry-failed', action='store_true')
    for name in ['collect-catchments', 'collect-middle-assignment', 'parse-catchments',
                 'parse-middle-assignment', 'validate-school-zone', 'validate-centum']:
        command = sub.add_parser(name)
        command.add_argument('--office', required=True)
        command.add_argument('--year', type=int, required=True)
        if name.startswith('collect-'):
            command.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect-apartments':
            result = inspect_apartments()
        elif args.command == 'collect-schools':
            result = collect_schools(args.year, force=args.force)
        elif args.command == 'collect-advancement':
            from src.collect_advancement import collect_advancement
            result = collect_advancement(args.years, force=args.force)
        elif args.command == 'score-middle-schools':
            from src.score_middle_school import build_middle_scores
            result = build_middle_scores()
        elif args.command == 'report':
            from src.visualization import ranking_report
            result = ranking_report()
        elif args.command == 'phase6-foundations':
            from src.phase6_build import build_phase6_foundations
            result = build_phase6_foundations()
        elif args.command == 'phase6-report':
            from src.phase6_build import phase6_report
            result = phase6_report()
        elif args.command == 'phase6-middle-report':
            from src.phase6_middle import validate_middle_tables
            result = validate_middle_tables().to_dict('records')
        elif args.command == 'collect-schoolzone':
            from src.collect_schoolzone import collect_schoolzone
            result = collect_schoolzone(args.year, force=args.force)
        elif args.command == 'build-schoolzone':
            from src.build_schoolzone import build_schoolzone
            result = build_schoolzone(args.year)
        elif args.command == 'phase65-audit':
            from src.phase65_coordinates import phase65_audit
            result = phase65_audit()
        elif args.command == 'phase65-geocode':
            from src.phase65_coordinates import phase65_geocode
            result = phase65_geocode(retry_failed=args.retry_failed)
        elif args.command == 'phase65-build':
            from src.phase65_coordinates import phase65_build
            result = phase65_build()
        elif args.command == 'phase7-audit':
            from src.phase7_scoring import phase7_audit
            result = phase7_audit()
        elif args.command == 'phase7-build':
            if args.assignment_year == 2026:
                from src.phase7_assignment_2026 import build_assignment_2026
                result = build_assignment_2026()
            else:
                from src.phase7_scoring import phase7_build
                result = phase7_build()
        elif args.command == 'phase8-build':
            from src.phase8_analysis import build_phase8
            result = build_phase8()
        elif args.command == 'phase9-collect':
            from src.phase9_elementary_demand import collect_phase9_schoolinfo
            result = collect_phase9_schoolinfo(args.years, force=args.force)
        elif args.command == 'phase9-build':
            from src.phase9_elementary_demand import build_phase9
            result = build_phase9()
        elif args.command == 'phase95-build':
            from src.phase95_school_score_integration import build_phase95
            result = build_phase95()
        elif args.command == 'phase10-build':
            from src.phase10_incremental_price_validation import build_phase10
            result = build_phase10()
        elif args.command == 'phase11-build':
            from src.phase11_middle_catchment_demand import build_phase11
            result = build_phase11()
        elif args.command == 'phase115-build':
            from src.phase115_middle_migration_mechanism import build_phase115
            result = build_phase115()
        elif args.command == 'export-relation-review':
            from src.relation_override_batch import export_relation_review
            result = export_relation_review(output=args.output)
        elif args.command == 'import-relation-review':
            from src.relation_override_batch import import_relation_review
            result = import_relation_review(args.csv, rebuild=args.rebuild)
        elif args.command == 'phase7-auto-exact':
            from src.phase7_auto_exact import apply_official_exact_candidates
            result = apply_official_exact_candidates()
        elif args.command == 'phase12-build':
            from src.phase12_elementary_first import build_phase12
            result = build_phase12()
        elif args.command == 'phase125-build':
            from src.phase125_middle_incremental import build_phase125
            result = build_phase125()
        elif args.command == 'phase13-build':
            from src.phase13_school_premium import build_phase13
            result = build_phase13()
        elif args.command == 'phase135-145-build':
            from src.phase135_145_school_value import build_phase135_145
            result = build_phase135_145()
        elif args.command == 'collect-admin-codes':
            from src.collect_admin_codes import collect_admin_codes
            result = collect_admin_codes()
        elif args.command == 'build-admin-crosswalk':
            from src.build_admin_crosswalk import build_admin_crosswalk
            result = build_admin_crosswalk()
        elif args.command == 'import-advancement':
            from src.import_advancement import import_advancement
            result = import_advancement(args.csv)
        elif args.command == 'geocode-schools':
            from src.geocode_school import geocode_schools
            result = geocode_schools(retry_failed=args.retry_failed)
        elif args.command == 'collect-catchments':
            if args.office == 'all':
                from src.phase6_collect import collect_all_catchments
                result = collect_all_catchments(args.year, force=args.force)
            elif args.office == 'haeundae':
                from src.collect_catchment import collect_catchments
                result = collect_catchments(args.office, args.year, force=args.force)
            else:
                from src.phase6_collect import collect_office_catchment
                result = collect_office_catchment(args.office, args.year, force=args.force)
        elif args.command == 'collect-middle-assignment':
            if args.office == 'all':
                from src.phase6_middle import collect_phase6_middle
                result = {office: collect_phase6_middle(office,args.year,force=args.force)
                          for office in ('dongnae','nambu','bukbu','seobu')}
                result['haeundae'] = {'status':'cached_phase4_source'}
            elif args.office in {'dongnae','nambu','bukbu','seobu'}:
                from src.phase6_middle import collect_phase6_middle
                result = collect_phase6_middle(args.office,args.year,force=args.force)
            else:
                from src.collect_middle_assignment import collect_middle_assignment
                result = collect_middle_assignment(args.office, args.year, force=args.force)
        elif args.command == 'parse-catchments':
            from src.parse_catchment import parse_catchments
            result = parse_catchments(args.office, args.year)
        elif args.command == 'parse-middle-assignment':
            from src.parse_middle_assignment import parse_middle_assignment
            result = parse_middle_assignment(args.office, args.year)
        elif args.command == 'validate-centum':
            from src.build_phase5 import build_phase5
            result = build_phase5(args.office, args.year)
        else:
            from src.validate_school_zone import validate_school_zone
            result = validate_school_zone(args.office, args.year)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
