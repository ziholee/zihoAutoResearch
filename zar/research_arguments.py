"""Research CLI grammar without importing execution or provider dependencies."""

def add_arguments(parser, parser_class):
    actions=parser.add_subparsers(dest='action',required=True,parser_class=parser_class)
    setup=actions.add_parser('setup',help='interactively configure a project and prepare its first proposal')
    setup.add_argument('--evaluation-path',action='append',help='fixed evaluation file; enables local file contract')
    setup.add_argument('--provenance-path',action='append',help='additional fixed input hashed locally; requires --evaluation-path')
    first=actions.add_parser('start',help='save explicit transmission scope; no model call or execution')
    first.add_argument('--profile',help='JSON connection profile; never include a key value')
    first.add_argument('--base-url');first.add_argument('--model');first.add_argument('--api-key-env')
    first.add_argument('--provider',choices=('api','codex'),help='default: api; codex uses a trusted installed CLI')
    first.add_argument('--codex-command',help='single trusted Codex executable name or path; default: codex')
    first.add_argument('--goal',required=True);first.add_argument('--read',action='append',required=True)
    first.add_argument('--command',dest='run_command',required=True,help='configured project command name')
    first.add_argument('--metric-file',required=True,help='new project-relative JSON output path')
    first.add_argument('--metric-key',required=True)
    first.add_argument('--max-calls',type=int,default=9);first.add_argument('--session-seconds',type=int,default=1800)
    first.add_argument('--scope',choices=('proxy','full'),default='full');first.add_argument('--seed',type=int)
    first.add_argument('--budget-ref',required=True)
    first.add_argument('--mode',choices=('baseline','candidate'),help='default: baseline without selection, candidate with a valid selected result')
    pair=actions.add_parser('variant-prepare',help='freeze the next role input and a user-supplied instruction variant; no calls')
    pair.add_argument('id');pair.add_argument('--file',required=True,help='project-relative UTF-8 role instructions')
    for name in ('variant-status','variant-approve','variant-advance','variant-recover','variant-cancel'):
        sub=actions.add_parser(name);sub.add_argument('id')
        if name=='variant-approve':sub.add_argument('--token',required=True)
        if name=='variant-advance':sub.add_argument('--send',action='store_true')
        if name=='variant-recover':sub.add_argument('--confirm-stopped',action='store_true')
    for name in ('next','revise','status','metrics','advance','approve','reject','run','decide','reconcile','recover'):
        sub=actions.add_parser(name);sub.add_argument('id')
        if name=='recover':sub.add_argument('--confirm-stopped',action='store_true')
        if name=='advance':sub.add_argument('--send',action='store_true',help='consent to transmit displayed scope to configured model provider')
        if name in ('approve','decide'):sub.add_argument('--token',required=True)
        if name=='decide':sub.add_argument('--select',action='store_true',help='also select a kept result; never checks out code')


