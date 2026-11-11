"""Deterministic factory checks. In CI this file is always from the trusted base."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

import branches  # Trusted: imported from this file's directory, never from the candidate.
import contracts
import issues


def run(command, **kwargs):
    result=subprocess.run(command, text=True, capture_output=True, timeout=180, **kwargs)
    if result.returncode:
        raise ValueError('check failed: '+command[0]+'\n'+(result.stdout+result.stderr)[-14000:])
    return result.stdout


# TypeScript reads its tsconfig files as JSONC (comments, trailing commas); every other .json file stays strict JSON.
TSCONFIG=re.compile(r'tsconfig(\.[A-Za-z0-9_-]+)*\.json')


def jsonc(text):
    """Strict JSON from JSONC: drop // and /* */ comments and trailing commas outside strings."""
    out,i,n=[],0,len(text)
    while i<n:
        c=text[i]
        if c=='"':
            j=i+1
            while j<n and text[j]!='"':j+=2 if text[j]=='\\' else 1
            out.append(text[i:j+1]);i=j+1
        elif text.startswith('//',i):
            i=text.find('\n',i);i=n if i<0 else i
        elif text.startswith('/*',i):
            end=text.find('*/',i+2)
            if end<0:raise ValueError('unterminated comment in JSONC')
            i=end+2
        elif c==',':
            j=i+1
            while j<n and (text[j].isspace() or text.startswith('//',j) or text.startswith('/*',j)):
                if text.startswith('//',j):j=text.find('\n',j);j=n if j<0 else j
                elif text.startswith('/*',j):
                    end=text.find('*/',j+2)
                    if end<0:raise ValueError('unterminated comment in JSONC')
                    j=end+2
                else:j+=1
            if j<n and text[j] in '}]':i+=1
            else:out.append(c);i+=1
        else:out.append(c);i+=1
    return ''.join(out)


def structural(root, trusted):
    for path in root.rglob('*'):
        if '.git' in path.parts or '__pycache__' in path.parts or '.factory-runtime' in path.parts:continue
        if path.is_symlink():raise ValueError('symlink in candidate: '+str(path))
        if not path.is_file():continue
        if path.suffix=='.json':json.loads(jsonc(path.read_text()) if TSCONFIG.fullmatch(path.name) else path.read_text())
        elif path.suffix=='.toml':tomllib.loads(path.read_text())
        elif path.suffix=='.py':ast.parse(path.read_text(),filename=str(path))
        elif path.suffix=='.md':
            for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
                target=target.split('#')[0].strip('<>')
                if not target or re.match(r'[A-Za-z][A-Za-z0-9+.-]*:',target):continue
                if not (path.parent/target).resolve().is_relative_to(root.resolve()):raise ValueError('documentation escapes repository')
                if not (path.parent/target).exists():raise ValueError(f'broken link: {path.relative_to(root)} -> {target}')
    config=json.loads((root/'factory/config.json').read_text())
    found=branches.problems(config)
    if found:raise ValueError('invalid branch configuration: '+'; '.join(found))
    found=issues.config_problems(config)
    if found:raise ValueError('invalid issue work-order configuration: '+'; '.join(found))
    reviewer=json.loads((root/'factory/review.schema.json').read_text())['properties']
    if {key:reviewer[key].get('const') for key in contracts.REVIEWER}!=contracts.REVIEWER:raise ValueError('review schema names another reviewer than contracts.REVIEWER')
    anchors(root, config)
    if config['limits']['max_rounds']>3 or config['limits']['max_rounds']<1:raise ValueError('invalid correction limit')
    if (root/'CLAUDE.md').read_text().splitlines().count('@AGENTS.md')!=1:raise ValueError('Claude must import AGENTS.md')
    run([sys.executable,str(trusted/'tools/factory/clients.py'),'check','--root',str(root)])
    fixture=json.loads((root/'factory-smoke.json').read_text())
    if fixture['quantity']*fixture['unit_price']!=fixture['total']:raise ValueError('controlled smoke fixture has incorrect total')


def anchors(root, config):
    """Places that cannot import contracts.REPOSITORY carry the repository as a literal; each must equal it."""
    found={'factory/config.json':[config.get('repository')],
           'factory/github-settings.json':[json.loads((root/'factory/github-settings.json').read_text()).get('repository')],
           'tools/factory/cli/install-factory-cli.sh':re.findall(r'^repository="([^"]+)"',(root/'tools/factory/cli/install-factory-cli.sh').read_text(),re.M)}
    for workflow in sorted((root/'.github/workflows').glob('*.yml')):
        found[str(workflow.relative_to(root))]=re.findall(r"github\.repository == '([^']+)'",workflow.read_text())
    for name,values in found.items():
        if any(value!=contracts.REPOSITORY for value in values) or (not values and not name.startswith('.github/')):
            raise ValueError(f'{name} names another repository than contracts.REPOSITORY')


def workflow_checks(root, actionlint):
    for path in sorted((root/'.github/workflows').glob('*.yml')):
        text=path.read_text()
        if text.count('\ncache-mode: none\n')!=1:raise ValueError('cache isolation missing: '+path.name)
        for reference in re.findall(r'uses:\s*([^\s#]+)',text):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}',reference):raise ValueError('unfixed action reference '+reference)
        if 'permissions: {}' not in text:raise ValueError('workflow needs explicit empty default permissions')
        # actionlint 1.7.12 predates GitHub cache-mode. Validate its exact mandatory
        # value ourselves, remove only that line, and lint every remaining field.
        normalized=text.replace('\ncache-mode: none\n','\n')
        run([actionlint,'-shellcheck=','-pyflakes=','-'],input=normalized,cwd=root)


def unit_tests(root, trusted):
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','FACTORY_CANDIDATE':str(root)}
    # -I excludes user/site startup hooks and cwd from Python's import path.
    # Tests explicitly import the candidate modules after loading unittest.
    for tests in ([trusted/'tools/factory/tests'] if trusted == root else
                  [trusted/'tools/factory/tests',root/'tools/factory/tests']):
        require_tests=list(tests.glob('test_*.py'))
        if not require_tests:raise ValueError('test suite absent: '+str(tests))
        output=run([sys.executable,'-I','-B','-m','unittest','discover','-s',str(tests),'-v'],env=env,cwd=trusted)
    return output


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--trusted-root',type=Path)
    p.add_argument('--ci',action='store_true');p.add_argument('--actionlint',default='actionlint');p.add_argument('--structure-only',action='store_true')
    args=p.parse_args();root=args.root.resolve();trusted=(args.trusted_root or root).resolve()
    try:
        structural(root,trusted)
        print('PASS: JSON/TOML/Python syntax, branch model, model/limit contract, native adapter drift, internal links and smoke fixture')
        if args.structure_only:return 0
        for tool in (args.actionlint,'gitleaks'):
            if not shutil.which(tool):raise ValueError('required verifier unavailable: '+tool)
        workflow_checks(root,args.actionlint);print('PASS: complete workflow syntax + exact cache isolation + full Action SHAs')
        with tempfile.TemporaryDirectory() as tmp:
            ignore=Path(tmp)/'empty-ignore';ignore.write_text('')
            run(['gitleaks','dir','--no-banner','--redact','--ignore-gitleaks-allow','--gitleaks-ignore-path',str(ignore),'--config',str(trusted/'factory/gitleaks.toml'),str(root)])
        print('PASS: Gitleaks with trusted rules and no candidate ignore escapes')
        unit_tests(root,trusted)
        print('PASS: fixed trusted regression suite and current candidate tests')
        return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print('FAIL: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
