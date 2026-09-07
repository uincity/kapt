import argparse
import json
import sys

from src.collect_schoolinfo import collect_schools
from src.inspect_apartments import inspect_apartments


def main(argv=None):
    parser = argparse.ArgumentParser(description='부산 학군 데이터 검증: Phase 1-6')
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
