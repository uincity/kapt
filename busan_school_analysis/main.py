import argparse
import json
import sys

from src.collect_schoolinfo import collect_schools
from src.inspect_apartments import inspect_apartments


def main(argv=None):
    parser = argparse.ArgumentParser(description='부산 학군 데이터 검증: Phase 1–5')
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
        elif args.command == 'import-advancement':
            from src.import_advancement import import_advancement
            result = import_advancement(args.csv)
        elif args.command == 'geocode-schools':
            from src.geocode_school import geocode_schools
            result = geocode_schools(retry_failed=args.retry_failed)
        elif args.command == 'collect-catchments':
            from src.collect_catchment import collect_catchments
            result = collect_catchments(args.office, args.year, force=args.force)
        elif args.command == 'collect-middle-assignment':
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
