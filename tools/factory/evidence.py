"""Product check results: parse tool output, bound the evidence, render the job summary, check summary and annotations.

Trusted host code, standard library only. Everything parsed here was written by PR-controlled processes: it is
size-bounded, never decides that a step passed (exit codes do; a failed test case can only turn a step red), and is
escaped before it reaches Markdown, so a test name cannot break a table, add a link, mention someone or close a block."""
import json
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path

STEPS = ('factory', 'backend-deps', 'backend-build', 'backend-test', 'frontend-deps', 'frontend-lint', 'frontend-test',
         'frontend-build')
MARK = {'passed': '✅', 'failed': '❌', 'timeout': '❌ timeout', 'skipped': '⏭️ skipped', 'not present': '➖ not present'}
OK = ('passed', 'not present')
DATABASE_NOTE = ('Tests with Category=Database were not run: Testcontainers needs the Docker socket, '
                 'which the sandbox does not provide.')
WORK = '/work/'
TRX = '{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}'
MAX_XML = 8 * 1024 * 1024
MAX_ITEMS = 50
MAX_MESSAGE = 300
MAX_NAME = 200
MAX_TAIL = 4000
MAX_RECORD = 30000
MAX_CHECK_SUMMARY = 6000
MAX_SUMMARY_BYTES = 20000  # the check summary as emit() measures it (JSON, ASCII-escaped)
MAX_JOB_SUMMARY = 1_000_000
CONTROL = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f\x7f]')
UNSAFE_PATH = re.compile(r'[\x00-\x1f\x7f\\]')
# Named entities only: a numeric one such as &#35;1 would itself read like an issue reference.
ESCAPE = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '|': '&vert;', '`': '&grave;', '[': '&lsqb;', ']': '&rsqb;',
          '@': '&commat;', '#': '&num;', '\\': '&bsol;'}
DIAGNOSTIC = re.compile(r'^\s*(?:\d+>)?(?P<file>[^\s(][^(\n]*?)\((?P<line>\d+)(?:,\d+)*\)\s*:\s*error\s+(?P<code>[A-Za-z]+\d+)'
                        r'\s*:\s*(?P<msg>.*?)(?:\s+\[[^\]\n]*\])?\s*$')
FILELESS = re.compile(r'^\s*(?:\d+>)?\S[^\n]*?\s:\s*error\s+(?P<code>[A-Za-z]+\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[[^\]\n]*\])?\s*$')
OXLINT = re.compile(r'^(?P<file>[^:\s][^:\n]*):(?P<line>\d+):\d+: (?P<msg>.+\[(?:Error|Warning)/[^\]\n]+\])\s*$')
STACK_FRAME = re.compile(r' in (?P<path>/\S+?):line (?P<line>\d+)')


class EvidenceError(ValueError):
    pass


def clean(text):
    """Untrusted text without terminal escapes, control characters or lone surrogates (which break UTF-8 writes)."""
    return CONTROL.sub('', str(text)).encode('utf-8', 'replace').decode('utf-8')


def emitted_size(value):
    """Bytes of `value` as engine.emit() writes it."""
    return len(json.dumps(value, separators=(',', ':'), ensure_ascii=True).encode())


def line_number(text):
    """A plausible 1-based line number from tool output, or None (absurd values drop the location)."""
    return int(text) if text and text.isdigit() and len(text) <= 7 and 0 < int(text) < 10_000_000 else None


def cut(text, limit):
    text = clean(text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def cell(text, limit=MAX_MESSAGE):
    """One line of untrusted text for Markdown: whitespace folded, special characters as named entities, bare URLs
    broken so they are not linked."""
    text = ' '.join(cut(text, limit).split())
    text = ''.join(ESCAPE.get(char, char) for char in text).replace('://', ':&sol;&sol;')
    # GFM also links bare www. hosts and e-mail addresses; a zero-width space breaks both.
    return re.sub(r'(?i)(www)\.', '\\1\u200b.', text).replace('&commat;', '&commat;\u200b')


def pre(text):
    """Untrusted text for a <pre> block (no Markdown is rendered there): the same named entities, line breaks kept."""
    return ''.join(ESCAPE.get(char, char) for char in clean(text)).replace('://', ':&sol;&sol;')


def safe_relative(path):
    if not isinstance(path, str) or not 0 < len(path) <= 500 or UNSAFE_PATH.search(path):
        return False
    return all(part not in ('', '.', '..', '.git') for part in path.split('/'))


def repo_path(candidate, raw, base=''):
    """The repository path of a file a tool reported, or None. Absolute paths count only inside the sandbox's /work
    copy; every component is checked with lstat, so a symlink in the candidate never leads outside it."""
    raw = raw.strip()
    if raw.startswith(WORK):
        relative = raw[len(WORK):]
    elif raw.startswith('/'):
        return None
    else:
        relative = f'{base}/{raw}' if base else raw
    if not safe_relative(relative):
        return None
    path, mode = Path(candidate), 0
    for part in relative.split('/'):
        path = path / part
        try:
            mode = os.lstat(path).st_mode
        except OSError:
            return None
        if stat.S_ISLNK(mode):
            return None
    return relative if stat.S_ISREG(mode) else None


def xml_root(data):
    if len(data) > MAX_XML:
        raise EvidenceError('result file too large')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise EvidenceError('result file is not UTF-8') from None
    if re.search(r'<!(?:DOCTYPE|ENTITY)', text, re.I):
        raise EvidenceError('result file declares a DTD')
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        raise EvidenceError('unreadable result file') from None


def case(name, status, seconds=None, message='', details='', path=None, line=None):
    return {'name': cut(name, 1000), 'status': status, 'seconds': seconds, 'message': cut(message, 4000),
            'details': cut(details, 8000), 'path': path, 'line': line}


def counts(cases):
    result = {'total': len(cases), 'passed': 0, 'failed': 0, 'skipped': 0}
    for item in cases:
        result[item['status']] += 1
    return result


def text_of(element):
    return element.text or '' if element is not None else ''


def trx_seconds(value):
    try:
        hours, minutes, seconds = (value or '').split(':')
        return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)
    except ValueError:
        return None


def parse_trx(data, candidate):
    """dotnet test --logger trx: every UnitTestResult, the first stack frame inside the candidate as location."""
    cases = []
    for result in xml_root(data).iter(TRX + 'UnitTestResult'):
        outcome = result.get('outcome', '')
        status = 'passed' if outcome == 'Passed' else 'skipped' if outcome in ('NotExecuted', 'Inconclusive') else 'failed'
        info = result.find(f'{TRX}Output/{TRX}ErrorInfo')
        message, trace = text_of(info.find(TRX + 'Message') if info is not None else None), \
            text_of(info.find(TRX + 'StackTrace') if info is not None else None)
        path = line = None
        for frame in STACK_FRAME.finditer(trace):
            path, line = repo_path(candidate, frame['path']), line_number(frame['line'])
            if path and line:
                break
            path = line = None
        cases.append(case(result.get('testName', '?'), status, trx_seconds(result.get('duration')),
                          '' if status == 'passed' else message, trace, path, line))
    return {'cases': cases, 'counts': counts(cases)}


def parse_junit(data, candidate, base):
    """JUnit XML (vitest): failure/error children fail a case, skipped skips it; the location is the first
    `❯ <file>:<line>:<column>` frame of the case's own file."""
    cases = []
    for testcase in xml_root(data).iter('testcase'):
        file, name = testcase.get('classname', ''), testcase.get('name', '?')
        problem = next((child for child in testcase if child.tag in ('failure', 'error')), None)
        skipped = any(child.tag == 'skipped' for child in testcase)
        try:
            seconds = round(float(testcase.get('time') or 0), 3)
        except ValueError:
            seconds = None
        path = line = None
        if problem is None:
            status, message, details = ('skipped' if skipped else 'passed'), '', ''
        else:
            details = (problem.text or '').strip()
            status, message = 'failed', problem.get('message') or details.split('\n', 1)[0]
            frame = re.search(r'❯ ' + re.escape(file) + r':(\d+):\d+', details) if file else None
            path = repo_path(candidate, file, base) if file else None
            line = line_number(frame[1]) if frame and path else None
            path = path if line else None
        cases.append(case(f'{file} > {name}' if file else name, status, seconds, message, details, path, line))
    return {'cases': cases, 'counts': counts(cases)}


def parse_errors(text, candidate, base):
    """Compiler and linter errors from a step's own output (MSBuild, tsc, oxlint), deduplicated, in order."""
    errors, seen = [], set()
    for raw in clean(text).splitlines():
        if match := DIAGNOSTIC.match(raw):
            path, line, message = repo_path(candidate, match['file'], base), line_number(match['line']), f"{match['code']}: {match['msg']}"
        elif match := OXLINT.match(raw):
            path, line, message = repo_path(candidate, match['file'], base), line_number(match['line']), match['msg']
        elif match := FILELESS.match(raw):
            path, line, message = None, None, f"{match['code']}: {match['msg']}"
        else:
            continue
        path, line = (path, line) if path and line else (None, None)
        key = (path, line, message)
        if key not in seen:
            seen.add(key)
            errors.append({'path': path, 'line': line, 'message': cut(message, 4000)})
    return errors


def step(name, status, seconds=None, exit_code=None, tail='', cases=(), errors=(), note=''):
    """One step's full result. The status comes from the exit code; a failed test case can only turn it red."""
    if name not in STEPS or status not in MARK:
        raise ValueError(f'unknown step or status: {name} {status}')
    cases = list(cases)
    if status == 'passed' and any(item.get('status') == 'failed' for item in cases):
        status = 'failed'
    return {'name': name, 'status': status, 'seconds': seconds, 'exit_code': exit_code, 'tail': clean(tail),
            'cases': cases, 'errors': list(errors), 'note': cut(note, 500)}


def bounded(item, keep_tail):
    failures = [{'name': cut(c['name'], MAX_NAME), 'message': cut(c.get('message') or 'failed', MAX_MESSAGE),
                 'path': c.get('path'), 'line': c.get('line')} for c in item['cases'] if c.get('status') == 'failed']
    errors = [{'path': e['path'], 'line': e['line'], 'message': cut(e['message'], MAX_MESSAGE)} for e in item['errors']]
    result = {'name': item['name'], 'status': item['status'], 'ok': item['status'] in OK, 'exit_code': item['exit_code'],
              'seconds': None if item['seconds'] is None else round(item['seconds'], 1), 'note': item['note'],
              'failures': failures[:MAX_ITEMS], 'errors': errors[:MAX_ITEMS],
              'tail': item['tail'][-keep_tail:] if item['status'] not in OK and keep_tail else ''}
    if item['cases']:
        result['counts'] = counts(item['cases'])
    if omitted := len(failures) + len(errors) - len(result['failures']) - len(result['errors']):
        result['omitted'] = omitted
    if item['name'] == 'factory':
        result['pass_lines'] = [cut(line, 300) for line in item['tail'].splitlines() if line.startswith('PASS: ')][:4]
    return result


def record(steps):
    """The evidence the test job emits: every step, under MAX_RECORD bytes as emit() measures them. Tails shrink
    first, then the number and length of entries, then the entries go (counted in `omitted`)."""
    ok = all(item['status'] in OK for item in steps)
    for keep_tail in (MAX_TAIL, 1000, 0):
        result = {'ok': ok, 'steps': [bounded(item, keep_tail) for item in steps]}
        if emitted_size(result) < MAX_RECORD:
            return result
    for keep, length in ((5, 100), (0, 0)):
        for item in result['steps']:
            dropped = max(0, len(item['failures']) - keep) + max(0, len(item['errors']) - keep)
            item['failures'], item['errors'] = item['failures'][:keep], item['errors'][:keep]
            for entry in item['failures'] + item['errors']:
                entry['message'] = cut(entry['message'], length)
                entry.update({'name': cut(entry['name'], length)} if 'name' in entry else {})
            item['note'] = cut(item['note'], 200)
            if dropped:
                item['omitted'] = item.get('omitted', 0) + dropped
        if emitted_size(result) < MAX_RECORD:
            break
    return result


def valid(tests):
    """Evidence shape for publishing. Old evidence without steps is valid and has nothing to annotate."""
    if 'steps' not in tests:
        return True
    steps = tests['steps']
    if not isinstance(steps, list) or len(steps) > len(STEPS):
        return False
    for item in steps:
        if not isinstance(item, dict) or item.get('name') not in STEPS or item.get('status') not in MARK:
            return False
        for key in ('failures', 'errors'):
            entries = item.get(key, [])
            if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
                return False
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get('message', ''), str):
                    return False
                path, line = entry.get('path'), entry.get('line')
                if path is not None and not safe_relative(path):
                    return False
                if line is not None and (type(line) is not int or not 0 < line < 10_000_000):
                    return False
    return True


def duration(item):
    return '' if item.get('seconds') is None else f"{int(item['seconds'])} s"


def details(item):
    numbers = item.get('counts') or (counts(item['cases']) if item.get('cases') else None)
    if numbers and numbers['failed']:
        return f"{numbers['failed']} of {numbers['total']} tests failed"
    if item.get('errors'):
        count = len(item['errors'])
        return f"{count} error" if count == 1 else f"{count} errors"
    return ''


def table(steps):
    lines = ['| Step | Result | Duration | Details |', '|---|---|---|---|']
    lines += [f"| {item['name']} | {MARK[item['status']]} | {duration(item)} | {details(item)} |" for item in steps]
    return lines


def location(entry):
    return f" ({cell(entry['path'])}:{entry['line']})" if entry.get('path') and entry.get('line') else ''


def render(tests, image_line, run_url):
    """factory/deterministic summary: the step table first, then notes, the factory PASS lines and the first
    failures per red step, at most MAX_CHECK_SUMMARY characters. The test cases are in the run's job summary."""
    steps = tests['steps']
    head = [cell(image_line), ''] + table(steps) + ['']
    head += [f"- {item['name']}: {cell(item['note'])}" for item in steps if item.get('note')]
    head += ['', f'Test cases and full output: job summary of {run_url}', '']
    head += [cell(line) for item in steps for line in item.get('pass_lines', [])]
    body = []
    for item in steps:
        entries = [(cell(f['name'], MAX_NAME) + ': ' + cell(f['message']) + location(f)) for f in item.get('failures', [])]
        entries += [(cell(e['message']) + location(e)) for e in item.get('errors', [])]
        if entries:
            body += ['', f"**{item['name']}**"] + [f'- {entry}' for entry in entries[:10]]
            if more := max(0, len(entries) - 10) + item.get('omitted', 0):
                body.append(f'- … {more} more in the job summary')
    text = '\n'.join(head + body)
    limit = MAX_CHECK_SUMMARY
    while len(text) > limit or emitted_size(text) > MAX_SUMMARY_BYTES:
        text = '\n'.join(head + body)[:limit - 60].rsplit('\n', 1)[0] + '\n\n… cut; see the job summary.'
        limit = int(limit * 0.8)
    return text


def job_summary(steps, image_line):
    """The run's job summary: per step its result, all test cases, failure details, errors and failing output."""
    marker = '\n\n… cut: GitHub limits a job summary to 1 MiB.\n'
    limit = MAX_JOB_SUMMARY - len(marker.encode()) - 1000
    parts, size = [], 0

    def add(text):
        nonlocal size
        data = len(text.encode()) + 1
        if size + data > limit:
            return False
        parts.append(text)
        size += data
        return True

    add('## Deterministic tests\n\n' + cell(image_line) + '\n\n' + '\n'.join(table(steps)))
    for item in steps:
        if not add(f"\n### {item['name']} {MARK[item['status']]}" + (f"\n\n{cell(item['note'])}" if item['note'] else '')):
            return '\n'.join(parts) + marker
        failed = [c for c in item['cases'] if c['status'] == 'failed']
        for entry in failed:
            where = f"\n{entry['path']}:{entry['line']}" if entry.get('path') and entry.get('line') else ''
            if not add(f"\n<details><summary>❌ {cell(entry['name'], 1000)}</summary>\n\n<pre>{pre(entry.get('message', ''))}\n\n"
                       f"{pre(entry.get('details', ''))}{pre(where)}</pre>\n</details>"):
                return '\n'.join(parts) + marker
        if item['cases']:
            numbers = counts(item['cases'])
            add(f"\n{numbers['total']} test{'' if numbers['total'] == 1 else 's'}: {numbers['passed']} passed, {numbers['failed']} failed, "
                f"{numbers['skipped']} skipped\n\n| Result | Test | Duration |\n|---|---|---|")
            order = {'failed': 0, 'skipped': 1, 'passed': 2}
            ranked = sorted(item['cases'], key=lambda c: order[c['status']])
            for index, entry in enumerate(ranked):
                seconds = '' if entry.get('seconds') is None else f"{entry['seconds']:.2f} s"
                if not add(f"| {MARK[entry['status']]} | {cell(entry['name'], 1000)} | {seconds} |"):
                    return '\n'.join(parts) + f'\n\n… {len(ranked) - index} more test cases cut: GitHub limits a job summary to 1 MiB.\n'
        if item['errors']:
            add('')
            for entry in item['errors']:
                if not add(f"- {cell(entry['message'], 1000)}{location(entry)}"):
                    return '\n'.join(parts) + marker
        if item['status'] not in OK and item['tail']:
            if not add(f"\n<details><summary>Output of {item['name']}</summary>\n\n<pre>{pre(item['tail'][-60000:])}</pre>\n</details>"):
                return '\n'.join(parts) + marker
    return '\n'.join(parts) + '\n'


def annotations(tests):
    """Checks-API annotations for failing tests and errors with a location, at most 50, deduplicated."""
    if 'steps' not in tests or not valid(tests):
        return []
    notes, seen = [], set()
    for item in tests['steps']:
        entries = [(f"{item['name']}: {f['name']}", f) for f in item.get('failures', [])]
        entries += [(item['name'], e) for e in item.get('errors', [])]
        for title, entry in entries:
            key = (entry.get('path'), entry.get('line'), entry.get('message'))
            if entry.get('path') and entry.get('line') and key not in seen:
                seen.add(key)
                notes.append({'path': entry['path'], 'start_line': entry['line'], 'end_line': entry['line'],
                              'annotation_level': 'failure', 'title': cut(title, 255),
                              'message': cut(entry.get('message') or 'failed', 4000)})
    return notes[:50]
