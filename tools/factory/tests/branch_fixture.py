"""A fixed branch model for tests.

Config PRs (`factory add … branch`, `remove branch`, `set config branch`) change only the branch list and the config
branch of the candidate's factory/config.json, and they run the trusted tests against that candidate. Tests therefore
take every other value from the candidate, but never its branch model.
"""
import copy
import json

BRANCHES = {'schema_version': 1,
            'validation': [{'name': 'testing', 'gate': 'full', 'kinds': ['factory', 'product', 'smoke']}],
            'production': [{'name': 'production', 'review': 'maintainer-manual'}]}


def fixed(config):
    """config with the fixed branch model: testing (gate full, every kind, default) and production (config branch)."""
    result = copy.deepcopy(config)
    result.update(default_branch='testing', config_branch='production', branches=copy.deepcopy(BRANCHES))
    return result


def text(root):
    """The candidate's factory/config.json text with the fixed branch model spliced in; its layout stays."""
    import branches  # tools/factory is on sys.path in every test module
    raw = (root / 'factory/config.json').read_text()
    return branches.edited(raw, lambda config: {**config, 'config_branch': 'production', 'branches': copy.deepcopy(BRANCHES)})


def load(root):
    return fixed(json.loads(text(root)))
