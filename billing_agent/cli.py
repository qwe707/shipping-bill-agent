import argparse
import json
from pathlib import Path
from .pipeline import run_pipeline

def main():
    parser=argparse.ArgumentParser(description='Evidence-first billing reconciliation; demo is simulation only.')
    parser.add_argument('command',choices=['run','demo'])
    parser.add_argument('paths',nargs='*')
    parser.add_argument('--entity',required=True)
    parser.add_argument('--provider',choices=['api','codex'],default='api')
    parser.add_argument('--existing')
    parser.add_argument('--ocr-map')
    parser.add_argument('--output',default='runs')
    args=parser.parse_args()
    def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig')) if path else None
    paths=args.paths or ([str(Path(__file__).resolve().parent.parent/'examples'/'invoice.json')] if args.command=='demo' else [])
    try:result=run_pipeline(paths,args.entity,read(args.existing),mode='demo' if args.command=='demo' else args.provider,ocr_map=read(args.ocr_map),output_dir=args.output)
    except (ValueError,OSError) as exc:parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result['incomplete'] else 0
