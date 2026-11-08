"""Shared test fixtures: the candidate under test, a fixed branch model, Git, GitHub users and the fakes that several
test modules use. The file name does not start with `test`, so unittest discovery never loads it as a test module.

Candidate modules other than contracts are imported inside the helpers that need them: test_engine also runs
test_contracts.py with this file against a minimal tree that holds only contracts.py and branches.py."""
import copy
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import unquote

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))


def use(*relative):
    """First on sys.path, in this order, so the code under test always comes from ROOT."""
    sys.path[:0] = [str(ROOT / path) for path in relative]


use('tools/factory')

from contracts import REPOSITORY, REVIEWER, Blocked, binding, digest  # noqa: E402

HTTPS = f'https://github.com/{REPOSITORY}.git'
FIXTURE_REPO = 'fixture/repo'

GIT_ENV = {'PATH': os.environ['PATH'], 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
           'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}


def git(root, *args):
    """Without global or system configuration or hooks: the developer's own Git setup must never shape a fixture."""
    return subprocess.run(['git', '-C', str(root), '-c', 'core.hooksPath=/dev/null', *args], env=GIT_ENV,
                          capture_output=True, text=True, check=True).stdout.strip()


# --- GitHub users ----------------------------------------------------------------------------------------------------

MAINTAINER = {'type': 'User', 'id': 1, 'login': 'test-human'}  # the one maintainer of fixture_config()
STRANGER = {'type': 'User', 'id': 999, 'login': 'stranger'}
BOT = {'type': 'Bot', 'id': 900, 'login': 'factory-publisher[bot]'}
DISPATCHER = {'type': 'Bot', 'id': 41898282, 'login': 'github-actions[bot]'}


def user(entry):
    return {'type': 'User', 'id': entry['id'], 'login': entry['login']}


# --- configuration ---------------------------------------------------------------------------------------------------

# Config PRs change the candidate's branch list and run these tests against it: fixtures take every other value from
# the candidate's factory/config.json, but never its branch model.
BRANCH_MODEL = {'schema_version': 1,
                'validation': [{'name': 'testing', 'gate': 'full', 'kinds': ['factory', 'product', 'smoke']}],
                'production': [{'name': 'production', 'review': 'maintainer-manual'}]}


def candidate_config_text():
    """The candidate's factory/config.json text with the fixed branch model spliced in; its layout stays."""
    import branches
    return branches.edited((ROOT / 'factory/config.json').read_text(),
                           lambda config: {**config, 'config_branch': 'production', 'branches': copy.deepcopy(BRANCH_MODEL)})


def candidate_config(**changes):
    """The candidate's configuration with the fixed branch model, testing (gate full, every kind, default branch) and
    production (the config branch), and `changes`."""
    config = json.loads(candidate_config_text())
    config.update(default_branch='testing', config_branch='production', branches=copy.deepcopy(BRANCH_MODEL), **changes)
    return config


def fixture_config(maintainers=(MAINTAINER,), **changes):
    """candidate_config() on the repository fixture/repo with publisher App 7 and the given maintainers."""
    config = candidate_config()
    config.update(repository=FIXTURE_REPO, publisher_app_id=7,
                  maintainers=[{'login': m['login'], 'id': m['id']} for m in maintainers], **changes)
    return config


# --- transport fakes -------------------------------------------------------------------------------------------------

class Response(io.BytesIO):
    """What urllib.request.urlopen returns, as a context manager."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def job(workflow, name):
    """The text of one job of a workflow: from its key to the next key at the same or a lower indentation."""
    rest = workflow.split(f'\n  {name}:\n', 1)[1]
    return re.split(r'\n {0,2}(?=\S)', rest, maxsplit=1)[0]


def review_for(snapshot, outcome='changes_requested'):
    """A schema-valid senior review of `snapshot`; changes_requested carries one P1 defect in example.txt."""
    findings = [{'id': 'F-1', 'kind': 'defect', 'confidence': 'high', 'priority': 'P1', 'file': 'example.txt', 'line': 1,
                 'impact': 'i', 'evidence': 'e', 'requirement': 'r', 'minimal_fix': 'm', 'verification': 'v'}
                ] if outcome == 'changes_requested' else []
    return {**{k: snapshot[k] for k in ('repository', 'pr', 'head_sha', 'base_sha', 'policy_sha', 'run_id', 'run_attempt')},
            **REVIEWER, 'scope': ['example.txt'], 'evidence': [], 'limitations': [], 'complete': True,
            'outcome': outcome, 'summary': 's', 'findings': findings}


# --- work-order issues -----------------------------------------------------------------------------------------------

STAMP, LATER = '2026-11-06T10:00:00Z', '2026-11-06T11:00:00Z'
DRAFT = ('Intro\n\n```factory-task\n{"status":"draft","kind":"factory","allowed_paths":[]}\n```\n\n'
         '## Goal\n\nExport the energy costs as CSV.\n\n## Acceptance criteria\n\n'
         '1. AC-1: When asked, the export shall list one row per day.\n')


class IssueHub:
    """Issues and issue comments of config['repository'] as the REST API returns them, with maintainer commands and
    publisher-App records; tools/factory/issues.py and issue_review.py run unchanged against it."""
    def __init__(self, config):
        self.config, self.repo, self.app = config, config['repository'], config['publisher_app_id']
        self.maintainer = user(config['maintainers'][0])
        self.issues, self.comments, self.calls, self.posts = {}, [], [], []
        self.next_id = 50000  # far from other fixtures' comment IDs

    def issue(self, number=57, body=DRAFT, title='CSV export', author=None, state='open'):
        self.issues[number] = {'number': number, 'title': title, 'body': body, 'state': state,
                               'user': dict(author or self.maintainer),
                               'repository_url': f'https://api.github.com/repos/{self.repo}',
                               'html_url': f'https://github.com/{self.repo}/issues/{number}'}
        return self.issues[number]

    def comment(self, number, body, author=None, app=None, edited=False):
        self.next_id += 1
        item = {'id': self.next_id, 'body': body, 'user': dict(author or self.maintainer), 'created_at': STAMP,
                'updated_at': LATER if edited else STAMP,
                'issue_url': f'https://api.github.com/repos/{self.repo}/issues/{number}',
                'html_url': f'https://github.com/{self.repo}/issues/{number}#issuecomment-{self.next_id}'}
        if app is not None:
            item['performed_via_github_app'] = {'id': app}
        self.comments.append(item)
        return item

    def record(self, number, marker, data, app=None, author=BOT):
        import issues
        return self.comment(number, issues.record_body(marker, data, 'Text for humans.'), author,
                            self.app if app is None else app)

    def review(self, number=57, paths=('docs/',), kind='factory'):
        import issues
        return self.record(number, issues.REVIEW, {'issue': number, 'text_sha256': issues.text_sha256(self.issues[number]),
                                                   'kind': kind, 'allowed_paths': list(paths), 'command': 1, 'run_id': 1})

    def approve(self, number=57, paths=('docs/',), accepters=None, kind='factory'):
        """The state /review and /accept leave: review record, /accept comments, approved block, approval record."""
        import issues
        issue = self.issues[number]
        reviewed = issues.text_sha256(issue)
        review = self.review(number, paths, kind)
        accepted = [self.comment(number, '/accept', author) for author in (accepters or [self.maintainer])]
        issue['body'] = issues.with_block(issue['body'], {'status': 'approved', 'kind': kind, 'allowed_paths': list(paths)})
        return self.record(number, issues.APPROVAL, {
            'issue': number, 'text_sha256': issues.text_sha256(issue), 'reviewed_sha256': reviewed, 'review': review['id'],
            'kind': kind, 'allowed_paths': list(paths), 'run_id': 1,
            'accepted_by': [{'login': c['user']['login'], 'id': c['user']['id'], 'comment': c['id']} for c in accepted]})

    def owns(self, path):
        prefix = f'/repos/{self.repo}/issues/'
        if not path.startswith(prefix):
            return False
        rest = path[len(prefix):].split('?')[0]
        if rest.startswith('comments/'):
            return int(rest.split('/')[1]) in {c['id'] for c in self.comments}
        return int(rest.split('/')[0]) in self.issues

    def request(self, method, path, data=None):
        self.calls.append((method, path, copy.deepcopy(data)))
        prefix = f'/repos/{self.repo}/issues/'
        if not path.startswith(prefix):
            raise AssertionError((method, path))
        rest = path[len(prefix):]
        if rest.startswith('comments/'):
            found = [c for c in self.comments if c['id'] == int(rest.split('/')[1])]
            if method != 'GET' or not found:
                raise Blocked(f'GitHub {method} /issues/comments: HTTP 404')
            return copy.deepcopy(found[0])
        number = int(rest.split('/')[0])
        if rest.endswith('/comments') and method == 'POST':
            self.posts.append(data['body'])  # only what the code under test posts
            return copy.deepcopy(self.comment(number, data['body'], BOT, self.app))
        if number not in self.issues:
            raise Blocked(f'GitHub {method} /issues: HTTP 404')
        if method == 'PATCH':
            self.issues[number].update(copy.deepcopy(data))
        elif method != 'GET':
            raise AssertionError((method, path))
        return copy.deepcopy(self.issues[number])

    def pages(self, path, field=None):
        prefix = f'/repos/{self.repo}/issues/'
        if path.startswith(prefix) and path.endswith('/comments'):
            number = int(path[len(prefix):].split('/')[0])
            return [copy.deepcopy(c) for c in self.comments if c['issue_url'].endswith(f'/issues/{number}')]
        raise AssertionError(path)


# --- the pipeline's GitHub (fixture/repo, PR 1) ----------------------------------------------------------------------

HEAD, POLICY, BASE = 'a' * 40, 'b' * 40, 'e' * 40  # PR head, config branch tip (production), target tip (testing)
JOB_ENV = {'GITHUB_SHA': POLICY, 'GITHUB_REF': 'refs/heads/production', 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
           'FACTORY_RETRY': 'false'}
POSTED = '2026-11-01T10:00:00Z'  # when the human comments were posted; heads are committed a minute earlier


class Transport:
    """The App installation client of the pipeline stages: PR 1 of fixture/repo into testing with a file work order,
    its check runs, comments, labels and workflow runs."""
    def __init__(self, config):
        self.config = config
        self.checks = {}
        self.comments = []
        self.labels = set()
        self.calls = []
        self.runs = {}
        self.files = [{'filename': 'example.txt', 'status': 'modified'}]
        self.task = {'status': 'approved', 'kind': 'factory', 'allowed_paths': ['example.txt']}
        self.compare = {'status': 'ahead', 'behind_by': 0}
        self.tips = {'production': POLICY, 'testing': BASE}
        self.foreign = []
        self.texts = []
        self.committed = '2026-11-01T09:59:00Z'
        self.pr = {'number': 1, 'state': 'open', 'draft': False, 'changed_files': 1,
                   'head': {'sha': HEAD, 'ref': 'ftrutschnig/TEST', 'repo': {'full_name': FIXTURE_REPO}},
                   'base': {'ref': 'testing', 'sha': BASE},
                   'body': '```factory-handoff\n' + json.dumps({'runner': 'claude', 'task': 'docs/work/TEST.md',
                                                                'owner': MAINTAINER['login']}) + '\n```'}

    def comment(self, body, user=None, pr=1):
        """A human issue comment as the API returns it; other PRs' comments are not listed on PR 1."""
        ident = self.next_comment = getattr(self, 'next_comment', 1000) + 1
        (self.comments if pr == 1 else self.foreign).append({
            'id': ident, 'body': body, 'user': user or dict(MAINTAINER),
            'issue_url': f'https://api.github.com/repos/{FIXTURE_REPO}/issues/{pr}',
            'html_url': f'https://github.com/{FIXTURE_REPO}/pull/{pr}#issuecomment-{ident}',
            'created_at': POSTED, 'updated_at': POSTED})
        return ident

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method == 'GET':
            if path.endswith('/check-runs/' + path.rsplit('/', 1)[-1]) and '/check-runs/' in path:
                return copy.deepcopy(self.checks[int(path.rsplit('/', 1)[-1])])
            if path == f'/repos/{FIXTURE_REPO}':
                return {'full_name': FIXTURE_REPO, 'default_branch': 'testing'}
            if path.endswith('/pulls/1'):
                return copy.deepcopy(self.pr)
            if '/git/ref/heads/' in path:
                name = path.rsplit('/heads/', 1)[1]
                if name not in self.tips:
                    raise Blocked('GitHub GET ref: HTTP 404')
                return {'object': {'sha': self.tips[name], 'type': 'commit'}}
            if '/issues/comments/' in path:
                return copy.deepcopy(next(c for c in self.comments + self.foreign if c.get('id') == int(path.rsplit('/', 1)[-1])))
            if '/compare/' in path:
                return copy.deepcopy(self.compare)
            if '/commits/' in path and '/check-runs' not in path:
                return {'sha': path.rsplit('/', 1)[-1], 'commit': {'committer': {'date': self.committed}}}
        if method == 'PATCH' and '/check-runs/' in path:
            self.checks[int(path.rsplit('/', 1)[-1])].update(copy.deepcopy(data))
            return {}
        if method == 'GET' and '/actions/runs/' in path:
            return copy.deepcopy(self.runs[int(path.rsplit('/', 1)[-1])])
        if method == 'POST' and path.endswith('/issues/1/labels'):
            self.labels.update(data['labels'])
            return {}
        if method == 'DELETE' and '/issues/1/labels/' in path:
            self.labels.remove(path.rsplit('/', 1)[-1])
            return {}
        if path.endswith('/labels'):
            return {}
        if method == 'POST' and path.endswith('/check-runs'):
            item = {**data, 'id': len(self.checks) + 1, 'app': {'id': 7}}
            self.checks[item['id']] = copy.deepcopy(item)
            return item
        if method == 'POST' and path.endswith('/comments'):
            self.comments.append({**data, 'performed_via_github_app': {'id': 7}, 'user': {'type': 'Bot', 'id': 77}})
            return {'id': len(self.comments)}
        raise AssertionError((method, path))

    def pages(self, path, field=None):
        if path.endswith('/issues/1/comments'):
            return copy.deepcopy(self.comments)
        if path.endswith('/issues/1/labels'):
            return [{'name': name} for name in sorted(self.labels)]
        if path.endswith('/files'):
            return copy.deepcopy(self.files)
        if '/check-runs?' in path:
            sha = path.split('/commits/', 1)[1].split('/', 1)[0]
            return [copy.deepcopy(c) for c in self.checks.values() if c['head_sha'] == sha and c['name'] == 'factory/deterministic']
        return []

    def text(self, *args):
        self.texts.append(args)
        return '```factory-task\n' + json.dumps(self.task) + '\n```'


class QueueTransport(Transport):
    """Transport plus the verified workflow runs and jobs of the review queue: run 1 is the pipeline run."""
    def __init__(self, config):
        super().__init__(config)
        self.jobs = {}
        self.add_run(1, ['Snapshot', 'Deterministic tests', 'Publish gates'])
        self.fail_final_patch = False

    def add_run(self, number, names=None):
        self.runs[number] = {'id': number, 'run_attempt': 1, 'repository': {'full_name': FIXTURE_REPO},
                             'event': 'workflow_dispatch', 'head_sha': POLICY, 'head_branch': 'production',
                             'workflow_id': 10, 'triggering_actor': dict(MAINTAINER)}
        self.jobs[number] = [{'name': name, 'status': 'completed', 'conclusion': 'success'}
                             for name in (names or ['Review coordination'])]

    def request(self, method, path, data=None):
        if method == 'GET' and path == f'/repos/{FIXTURE_REPO}/actions/workflows/10':
            return {'path': self.config['workflow']}
        if self.fail_final_patch and method == 'PATCH' and data.get('status') == 'completed':
            raise Blocked('transport lost before publication')
        return super().request(method, path, data)

    def pages(self, path, field=None):
        if '/jobs?' in path:
            return copy.deepcopy(self.jobs[int(path.split('/runs/')[1].split('/')[0])])
        return super().pages(path, field)


def reviewer():
    """The reviewer metadata the local reviewer records with its result."""
    import local_review_queue
    return {**local_review_queue.REVIEWER_IDENTITY, 'thread_id': 'thread-1', 'turns': 1,
            'usage': {'input_tokens': 10, 'output_tokens': 3}}


# --- the maintainer's local session ----------------------------------------------------------------------------------

# testing (full) and quick (tests) are gated validation branches, sandbox is not gated; production is the config branch.
SESSION_BRANCHES = {'schema_version': 1, 'validation': [
    {'name': 'testing', 'gate': 'full', 'kinds': ['factory', 'product']},
    {'name': 'quick', 'gate': 'tests', 'kinds': ['smoke']},
    {'name': 'sandbox', 'gate': 'none', 'kinds': []}],
    'production': [{'name': 'production', 'review': 'maintainer-manual'}]}


class SessionGitHub:
    """The maintainer's gh for session.py: authenticated API data, including mutable head and check state across
    watcher polls. `case` is the SessionRepos test case."""
    def __init__(self, case):
        self.case = case
        self.user = {'login': 'Zerosteps1', 'id': 115100163, 'type': 'User'}
        self.permission = 'admin'
        self.default = 'testing'
        self.tips = {name: case.base for name in ('production', 'testing', 'quick', 'sandbox')}
        self.comments = []
        self.elsewhere = []  # comments GitHub returns by id that this PR does not list (another PR's)
        self.checks = []
        self.head_checks = []
        self.posts = []
        self.creates = []
        self.readiness = []
        self.files = [{'filename': 'tools/factory/example.py', 'status': 'modified'}]
        self.pr = {'number': 1, 'state': 'open', 'draft': False, 'changed_files': 1,
                   'head': {'sha': case.head, 'ref': 'feature/one', 'repo': {'full_name': REPOSITORY}},
                   'base': {'sha': case.base, 'ref': 'testing', 'repo': {'full_name': REPOSITORY}},
                   'body': '```factory-handoff\n' + json.dumps({'runner': 'claude',
                           'task': 'docs/work/TEST.md', 'owner': 'Zerosteps1'}) + '\n```'}

    def target(self, name, head_ref=None):
        """As on GitHub, a retargeted PR reports the target's current tip as its base."""
        self.pr['base'].update(ref=name, sha=self.tips[name])
        if head_ref:
            self.pr['head']['ref'] = head_ref

    def command(self, arguments, data=None):
        if arguments[:2] == ['pr', 'ready']:
            self.readiness.append(arguments)
            self.pr['draft'] = '--undo' in arguments
            return ''
        if arguments[:2] != ['pr', 'create']:
            raise AssertionError(arguments)
        body = Path(arguments[arguments.index('--body-file') + 1]).read_text()
        self.creates.append({'arguments': arguments, 'body': body})
        self.pr['body'] = body
        self.pr['draft'] = '--draft' in arguments
        self.target(arguments[arguments.index('--base') + 1])
        return 'https://github.com/' + REPOSITORY + '/pull/1'

    def request(self, method, path, data=None):
        prefix = '/repos/' + REPOSITORY
        if method == 'GET':
            if path == '/user':
                return copy.deepcopy(self.user)
            if path == prefix:
                return {'full_name': REPOSITORY, 'default_branch': self.default}
            if '/collaborators/' in path:
                return {'permission': self.permission, 'user': copy.deepcopy(self.user)}
            if path.startswith(prefix + '/git/ref/heads/'):
                name = unquote(path.rsplit('/', 1)[1])
                if name == self.pr['head']['ref'] and name not in self.tips:
                    return {'object': {'sha': self.pr['head']['sha']}}
                return {'object': {'sha': self.tips[name]}}
            if path == prefix + '/pulls/1':
                return copy.deepcopy(self.pr)
            if '/issues/comments/' in path:
                found = [c for c in self.comments + self.elsewhere if c['id'] == int(path.rsplit('/', 1)[1])]
                if not found:
                    raise Blocked('GitHub CLI failed; check your own gh login and repository access')  # deleted: HTTP 404
                return copy.deepcopy(found[0])
        if method == 'POST' and path == prefix + '/issues/1/comments':
            self.posts.append(copy.deepcopy(data))
            return {'html_url': 'https://github.com/' + REPOSITORY + '/pull/1#issuecomment-9'}
        raise AssertionError((method, path, data))

    def pages(self, path, field=None):
        if path.endswith('/files'):
            return copy.deepcopy(self.files)
        if path.endswith('/issues/1/comments'):
            return copy.deepcopy(self.comments)
        if '/check-runs?' in path:
            return copy.deepcopy(self.head_checks)
        return []

    def text(self, repo, path, sha):
        if repo != REPOSITORY:
            raise AssertionError(repo)
        return git(self.case.candidate, 'show', sha + ':' + path) + '\n'

    def pending(self, ident=1):
        """The pipeline's awaiting-review receipt for the PR as it is now (production: reserved by /review)."""
        base = self.pr['base']['ref']
        production = base == 'production'
        snapshot = {'repository': REPOSITORY, 'pr': 1, 'head_sha': self.pr['head']['sha'],
                    'base_sha': self.tips[base], 'policy_sha': self.tips['production'], 'base_ref': base,
                    'mode': 'production' if production else 'validation', 'gate': 'tests' if production else 'full',
                    'review_request': 9 if production else None, 'run_id': ident, 'run_attempt': 1, 'check_id': ident,
                    'handoff': None if production else {'runner': 'claude', 'task': 'docs/work/TEST.md', 'owner': 'Zerosteps1'},
                    'files': [f['filename'] for f in self.files], 'task': None if production else {
                        'status': 'approved', 'kind': 'factory', 'allowed_paths': ['tools/factory/']},
                    'feedback_digest': digest(self.comments), 'draft': False, 'control_changed': True}
        receipt = {'phase': 'awaiting_review', 'snapshot': snapshot, 'tests': {'ok': True}}
        return {'id': ident, 'name': 'factory/senior-review', 'status': 'in_progress',
                'head_sha': snapshot['head_sha'], 'app': {'id': 77}, 'external_id': binding(snapshot),
                'output': {'text': json.dumps(receipt)}}


class SessionRepos:
    """TestCase mixin: a control checkout of the config tip (production, publisher App 77, SESSION_BRANCHES) with two
    file work orders, docs/work/TEST.md (factory) and docs/work/QUICK.md (smoke), and a candidate on feature/one with
    one commit; SessionGitHub stands in for the maintainer's gh, and the trusted modules run from the control."""
    def setUp(self):
        import branches
        import engine
        import local_review
        import session
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.control = Path(self.temp.name) / 'control'
        self.control.mkdir()
        git(self.control, 'init', '-q', '-b', 'production')
        git(self.control, 'config', 'user.name', 'Fixture')
        git(self.control, 'config', 'user.email', 'fixture@example.invalid')
        git(self.control, 'remote', 'add', 'origin', HTTPS)
        self.config = json.loads((ROOT / 'factory/config.json').read_text())
        self.config['publisher_app_id'] = 77
        self.config['review_context_paths'] = []
        self.config.update(default_branch='testing', config_branch='production', branches=copy.deepcopy(SESSION_BRANCHES))
        files = {'factory/config.json': json.dumps(self.config), 'factory/policy.md': 'TRUSTED POLICY',
                 'factory/review.schema.json': (ROOT / 'factory/review.schema.json').read_text(),
                 'docs/work/TEST.md': 'Approved task.\n```factory-task\n' + json.dumps({
                     'status': 'approved', 'kind': 'factory', 'allowed_paths': ['tools/factory/', 'AGENTS.md', '.gitattributes']}) + '\n```\n',
                 'docs/work/QUICK.md': 'Approved smoke task.\n```factory-task\n' + json.dumps({
                     'status': 'approved', 'kind': 'smoke', 'allowed_paths': ['tools/factory/']}) + '\n```\n',
                 'tools/factory/example.py': 'VALUE = 1\n', 'AGENTS.md': 'CONTROL INSTRUCTIONS\n'}
        if self.config.get('northstar_path'):
            files[self.config['northstar_path']] = 'Fixture product draft; no product approval.\n'
        for name, content in files.items():
            path = self.control / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        git(self.control, 'add', '.')
        git(self.control, 'commit', '-qm', 'Control')
        self.base = git(self.control, 'rev-parse', 'HEAD')
        self.candidate = Path(self.temp.name) / 'candidate'
        git(self.control, 'clone', '-q', str(self.control), str(self.candidate))
        git(self.candidate, 'config', 'user.name', 'Fixture')
        git(self.candidate, 'config', 'user.email', 'fixture@example.invalid')
        git(self.candidate, 'remote', 'set-url', 'origin', 'git@github.com:' + REPOSITORY + '.git')
        git(self.candidate, 'switch', '-qc', 'feature/one')
        (self.candidate / 'tools/factory/example.py').write_text('VALUE = 2\n')
        git(self.candidate, 'commit', '-qam', 'Candidate')
        self.head = git(self.candidate, 'rev-parse', 'HEAD')
        self.gh = SessionGitHub(self)
        patches = [patch.object(module, 'ROOT', self.control) for module in (session, engine, local_review)]
        # The trusted configuration is the control checkout's, as for session.py run from that checkout.
        patches.append(patch.object(branches, 'load_config',
                                    side_effect=lambda: json.loads((self.control / 'factory/config.json').read_text())))
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        self.model_calls = []

    def model(self, instructions, material, schema_path, config):
        """The reviewer model: a complete, passing review bound to the material it was given."""
        self.model_calls.append((instructions, json.loads(material)))
        bound = json.loads(material)['binding']
        return {**bound, **REVIEWER, 'scope': ['tools/factory/example.py'], 'evidence': [], 'limitations': [],
                'complete': True, 'outcome': 'pass', 'summary': 'Source review complete.', 'findings': []}, {'turns': 1}
