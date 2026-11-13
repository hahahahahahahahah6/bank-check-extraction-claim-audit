"""Command-line interface."""
import argparse
import json
import sys

from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, '%s: error: %s\n' % (self.prog, message))


def main(argv=None):
    parser = Parser(prog='bank-check-extraction-claim-audit')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('audit', help='audit a repository')
    command.add_argument('repo', nargs='?', default='.')
    command.add_argument('--json', action='store_true')
    command.add_argument('--verbose', action='store_true')
    command.add_argument('--ignore', action='append', default=[], metavar='PREFIX')
    command.add_argument('--fail-on', choices=('high', 'medium'), default='high')
    args = parser.parse_args(argv)
    try:
        report = audit(args.repo, args.ignore)
    except (OSError, ValueError, UnicodeError) as error:
        print('error: %s' % error, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(report['verdict'])
        for finding in report['findings']:
            print('%s %s: %s' % (finding['severity'], finding['id'], finding['message']))
            if args.verbose:
                print('  docs: ' + ', '.join(finding['docs']))
        if args.verbose:
            print('Production evidence: ' + ', '.join(report['production_evidence']))
            print('Test evidence: ' + ', '.join(report['test_evidence']))
    return 2 if any(f['severity'] == 'HIGH' or args.fail_on == 'medium' for f in report['findings']) else 0


if __name__ == '__main__':
    sys.exit(main())
