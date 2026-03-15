#!/usr/bin/env python3
"""Minimal Pipedrive helper.

Reads env:
  PIPEDRIVE_DOMAIN
  PIPEDRIVE_API_TOKEN

Commands:
  me
  pipelines
  stages
  deals-recent [--limit N]

Outputs JSON to stdout.
"""

import argparse
import json
import os
import sys
from urllib.parse import urlencode
import urllib.request


def api_get(path, params=None):
    domain=os.environ.get('PIPEDRIVE_DOMAIN')
    token=os.environ.get('PIPEDRIVE_API_TOKEN')
    if not domain or not token:
        raise SystemExit('Missing PIPEDRIVE_DOMAIN or PIPEDRIVE_API_TOKEN')
    base=f"https://{domain}/api/v1"
    params = dict(params or {})
    params['api_token']=token
    url=f"{base}{path}?{urlencode(params)}"
    req=urllib.request.Request(url, headers={'Accept':'application/json'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data=resp.read().decode('utf-8')
        return json.loads(data)


def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('me')
    sub.add_parser('pipelines')
    sub.add_parser('stages')
    p=sub.add_parser('deals-recent')
    p.add_argument('--limit', type=int, default=10)

    args=ap.parse_args()

    if args.cmd=='me':
        out=api_get('/users/me')
    elif args.cmd=='pipelines':
        out=api_get('/pipelines')
    elif args.cmd=='stages':
        out=api_get('/stages')
    elif args.cmd=='deals-recent':
        out=api_get('/deals', {'start':0,'limit':args.limit,'sort':'add_time DESC'})
    else:
        raise SystemExit('unknown')

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write('\n')


if __name__=='__main__':
    main()
