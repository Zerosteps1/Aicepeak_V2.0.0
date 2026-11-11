"""The trusted test image: content-derived tag, build-if-missing and the Dockerfile's boundaries."""
import contextlib
import io
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory_testlib import ROOT
import images

ID = 'sha256:' + 'c' * 64
OTHER_ID = 'sha256:' + 'd' * 64


def tree(dockerfile=None):
    """A copy of the trusted image inputs, plus an unrelated file in the build context."""
    root = Path(tempfile.mkdtemp())
    (root / 'factory').mkdir()
    for name in ('test.Dockerfile', 'install_tools.py', 'tools.lock.json'):
        shutil.copy2(ROOT / 'factory' / name, root / 'factory' / name)
    if dockerfile is not None:
        (root / 'factory/test.Dockerfile').write_text(dockerfile)
    (root / 'factory/policy.md').write_text('unrelated\n')
    return root


class FakeDocker:
    """Records docker argv; `images` maps tag -> (id, label) for present images, a build adds the built one."""
    def __init__(self, present=None, build_code=0, built_id=ID):
        self.present, self.build_code, self.built_id, self.calls = dict(present or {}), build_code, built_id, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1:3] == ['image', 'inspect']:
            found = self.present.get(argv[-1])
            return subprocess.CompletedProcess(argv, 0 if found else 1, f'{found[0]} {found[1]}\n' if found else '', '')
        if argv[1] == 'build':
            if self.build_code:
                return subprocess.CompletedProcess(argv, self.build_code, '', 'boom')
            label = argv[argv.index('--label') + 1].split('=', 1)[1]
            self.present[argv[argv.index('-t') + 1]] = (self.built_id, label)
            return subprocess.CompletedProcess(argv, 0, self.built_id + '\n', '')
        raise AssertionError(argv)

    def builds(self):
        return [argv for argv in self.calls if argv[1] == 'build']


class TestImageTag(unittest.TestCase):
    def setUp(self):
        self.root = tree()
        self.addCleanup(shutil.rmtree, self.root)

    def test_inputs_are_the_dockerfile_and_every_file_it_copies_from_the_context(self):
        self.assertEqual(images.test_image_inputs(ROOT),
                         ['factory/test.Dockerfile', 'factory/install_tools.py', 'factory/tools.lock.json'])

    def test_tag_is_a_stable_prefix_of_the_input_digest(self):
        tag = images.test_image_tag(self.root)
        self.assertRegex(tag, r'^aicepeak-factory-test:[0-9a-f]{16}$')
        self.assertEqual(tag, images.test_image_tag(self.root))
        self.assertEqual(tag.split(':')[1], images.test_image_digest(self.root)[:16])
        self.assertEqual(images.test_image_tag(ROOT), images.test_image_tag(tree()))

    def test_changing_the_dockerfile_or_a_copied_file_changes_the_tag_and_nothing_else_does(self):
        before = images.test_image_tag(self.root)
        (self.root / 'factory/policy.md').write_text('changed\n')
        (self.root / 'factory/Dockerfile').write_text('FROM scratch\n')
        self.assertEqual(images.test_image_tag(self.root), before)
        for name in ('test.Dockerfile', 'install_tools.py', 'tools.lock.json'):
            with self.subTest(name=name):
                path = self.root / 'factory' / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                self.assertNotEqual(images.test_image_tag(self.root), before)
                path.write_bytes(original)
        self.assertEqual(images.test_image_tag(self.root), before)

    def test_a_new_copied_file_becomes_an_input(self):
        dockerfile = (self.root / 'factory/test.Dockerfile').read_text()
        (self.root / 'factory/extra.txt').write_text('x\n')
        before = images.test_image_tag(self.root)
        (self.root / 'factory/test.Dockerfile').write_text(dockerfile + 'COPY \\\n  extra.txt /opt/extra.txt\n')
        self.assertIn('factory/extra.txt', images.test_image_inputs(self.root))
        changed = images.test_image_tag(self.root)
        (self.root / 'factory/extra.txt').write_text('y\n')
        self.assertNotIn(images.test_image_tag(self.root), (before, changed))

    def test_copy_from_another_stage_is_not_a_context_input(self):
        root = tree('FROM a AS b\nFROM c\nCOPY --from=b /usr/local/bin/node /usr/local/bin/node\n')
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual(images.test_image_inputs(root), ['factory/test.Dockerfile'])

    def test_sources_outside_the_context_globs_and_missing_files_are_refused(self):
        for line, problem in (('COPY ../README.md /x', 'must be a file'), ('COPY *.py /x/', 'must be a file'),
                              ('COPY missing.txt /x', 'bounded regular file'), ('COPY onlyone', 'unexpected COPY')):
            with self.subTest(line=line):
                root = tree('FROM c\n' + line + '\n')
                self.addCleanup(shutil.rmtree, root)
                with self.assertRaisesRegex(images.ImageError, problem):
                    images.test_image_tag(root)

    def test_the_cli_prints_the_tag(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(images.main(['test-tag']), 0)
        self.assertEqual(output.getvalue(), images.test_image_tag(ROOT) + '\n')


class EnsureTestImage(unittest.TestCase):
    def setUp(self):
        self.root = tree()
        self.addCleanup(shutil.rmtree, self.root)
        self.digest = images.test_image_digest(self.root)
        self.tag = images.test_image_tag(self.root)

    def test_a_present_image_with_the_current_inputs_is_reused_without_a_build(self):
        docker = FakeDocker({self.tag: (ID, self.digest)})
        self.assertEqual(images.ensure_test_image(self.root, run=docker), (ID, self.tag, False, 0.0))
        self.assertEqual(docker.builds(), [])

    def test_a_missing_image_is_built_from_the_trusted_context_then_reused(self):
        docker = FakeDocker()
        image_id, tag, built, _ = images.ensure_test_image(self.root, run=docker)
        self.assertEqual((image_id, tag, built), (ID, self.tag, True))
        self.assertEqual(docker.builds(), [['docker', 'build', '--quiet', '-t', self.tag, '--label', f'{images.LABEL}={self.digest}',
                                            '-f', str(self.root / 'factory/test.Dockerfile'), str(self.root / 'factory')]])
        self.assertEqual(images.ensure_test_image(self.root, run=docker)[2], False)
        self.assertEqual(len(docker.builds()), 1)

    def test_a_present_tag_with_other_inputs_is_rebuilt(self):
        docker = FakeDocker({self.tag: (OTHER_ID, '0' * 64)})
        self.assertEqual(images.ensure_test_image(self.root, run=docker)[:3], (ID, self.tag, True))

    def test_a_failed_build_or_an_unexpected_identity_blocks(self):
        with self.assertRaisesRegex(images.ImageError, 'test image build failed: boom'):
            images.ensure_test_image(self.root, run=FakeDocker(build_code=1))
        with self.assertRaisesRegex(images.ImageError, 'invalid test image identity'):
            images.ensure_test_image(self.root, run=FakeDocker(built_id='latest'))

    def test_docker_gets_no_personal_environment(self):
        seen = []
        docker = FakeDocker({self.tag: (ID, self.digest)})
        images.ensure_test_image(self.root, run=lambda argv, **kwargs: seen.append(kwargs['env']) or docker(argv, **kwargs))
        self.assertTrue(seen and all(set(env) <= {'PATH', 'DOCKER_HOST', 'DOCKER_CONFIG'} for env in seen))


class TestDockerfile(unittest.TestCase):
    text = (ROOT / 'factory/test.Dockerfile').read_text()

    def test_every_base_image_is_pinned_by_tag_and_digest(self):
        bases = re.findall(r'^FROM\s+(\S+)', self.text, re.M)
        self.assertGreaterEqual(len(bases), 2)
        for base in bases:
            self.assertRegex(base, r'^[a-z0-9./-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$')

    def test_it_runs_unprivileged_on_a_read_only_root_without_provider_clients(self):
        self.assertRegex(self.text, r'(?m)^USER 1000:1000$')
        for setting in ('HOME=/tmp', 'NUGET_PACKAGES=/tmp/', 'npm_config_cache=/tmp/', 'DOTNET_CLI_TELEMETRY_OPTOUT=1',
                        'DOTNET_NOLOGO=1', 'PYTHONDONTWRITEBYTECODE=1'):
            self.assertIn(setting, self.text)
        for absent in ('package.json', '@openai/codex', '@anthropic-ai/claude-code', 'ARG ', 'SECRET', 'TOKEN'):
            self.assertNotIn(absent, self.text)

    def test_it_checks_the_exact_toolchain_and_the_pinned_check_tools(self):
        self.assertRegex(self.text, r'test "\$\(dotnet --version\)" = "10\.0\.\d+"')
        self.assertRegex(self.text, r'test "\$\(node --version\)" = "v\d+\.\d+\.\d+"')
        self.assertIn('install_tools.py --lock /opt/factory-tools/tools.lock.json', self.text)
        for tool in ('actionlint -version', 'gitleaks version', 'git --version', "python3 -c 'import tomllib'"):
            self.assertIn(tool, self.text)

    def test_the_sandbox_script_and_the_pipeline_use_the_test_image(self):
        script = (ROOT / 'tools/factory/sandbox-verify.sh').read_text()
        self.assertIn('"$root/tools/factory/images.py" test-tag', script)
        self.assertIn('"$root/tools/factory/images.py" ensure-test', script)
        self.assertNotIn('clients.py', script)
        engine = (ROOT / 'tools/factory/engine.py').read_text()
        test_stage = engine[engine.index('def test_stage'):engine.index('def run_url')]
        self.assertIn('images.ensure_test_image(ROOT)', test_stage)
        self.assertNotIn('factory/Dockerfile', test_stage)


if __name__ == '__main__':
    unittest.main()
