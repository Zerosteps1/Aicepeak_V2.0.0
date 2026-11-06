"""Work-order issues on a faked GitHub REST transport: maintainer commands and publisher-App records (FACTORY-009).

Only the transport is faked; tools/factory/issues.py and issue_review.py run unchanged against it."""
import copy

import issues
from contracts import Blocked

STAMP, LATER = '2026-11-06T10:00:00Z', '2026-11-06T11:00:00Z'
DRAFT = ('Intro\n\n```factory-task\n{"status":"draft","kind":"factory","allowed_paths":[]}\n```\n\n'
         '## Goal\n\nExport the energy costs as CSV.\n\n## Acceptance criteria\n\n'
         '1. AC-1: When asked, the export shall list one row per day.\n')
STRANGER = {'type': 'User', 'id': 5, 'login': 'stranger'}
BOT = {'type': 'Bot', 'id': 900, 'login': 'factory-publisher[bot]'}


def user(entry):
    return {'type': 'User', 'id': entry['id'], 'login': entry['login']}


class IssueHub:
    """Issues and issue comments of config['repository'] as the REST API returns them."""
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
        return self.comment(number, issues.record_body(marker, data, 'Text for humans.'), author,
                            self.app if app is None else app)

    def review(self, number=57, paths=('docs/',), kind='factory'):
        return self.record(number, issues.REVIEW, {'issue': number, 'text_sha256': issues.text_sha256(self.issues[number]),
                                                   'kind': kind, 'allowed_paths': list(paths), 'command': 1, 'run_id': 1})

    def approve(self, number=57, paths=('docs/',), accepters=None):
        """The state /review and /accept leave: review record, /accept comments, approved block, approval record."""
        issue = self.issues[number]
        reviewed = issues.text_sha256(issue)
        review = self.review(number, paths)
        accepted = [self.comment(number, '/accept', author) for author in (accepters or [self.maintainer])]
        issue['body'] = issues.with_block(issue['body'], {'status': 'approved', 'kind': 'factory', 'allowed_paths': list(paths)})
        return self.record(number, issues.APPROVAL, {
            'issue': number, 'text_sha256': issues.text_sha256(issue), 'reviewed_sha256': reviewed, 'review': review['id'],
            'kind': 'factory', 'allowed_paths': list(paths), 'run_id': 1,
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

