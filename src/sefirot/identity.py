"""Separate fit compatibility from exact build provenance and money approval."""
from pathlib import Path
from .contracts import digest

MODEL_IDENTITY_SCHEMA='probability-code-v1'
# Fail closed if a dependency disappears. Add any new sporting/model dependency
# here before using it for a fit. CLI, transport and presentation are excluded.
MODEL_MODULES=('_payoffs.py','contracts.py','evidence.py','goal_model.py',
               'identity.py','markets.py','probability.py')


def code_hash(root=None):
    root=Path(root) if root is not None else Path(__file__).parent
    return digest({p.name:p.read_text(encoding='utf-8') for p in sorted(root.glob('*.py'))})


def model_code_hash(root=None):
    root=Path(root) if root is not None else Path(__file__).parent
    return digest({'schema':MODEL_IDENTITY_SCHEMA,
                   'modules':{name:(root/name).read_text(encoding='utf-8') for name in MODEL_MODULES}})
