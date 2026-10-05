"""Read only named provider credentials; never execute a local env file."""
import os
from pathlib import Path
import re

NAMES = ('SEFIROT_ODDS_API_KEY', 'API_FOOTBALL_KEY', 'STAKE_API_TOKEN')


def credential(name, env_file=None):
    if name not in NAMES:
        raise ValueError('unsupported provider credential')
    value = os.environ.get(name)
    if value is None:
        configured = env_file or os.environ.get('SEFIROT_ENV_FILE')
        paths = ([Path(configured)] if configured else
                 [Path.cwd() / '.env', Path(__file__).resolve().parents[2] / '.env'])
        for path in dict.fromkeys(paths):
            if not path.is_file():
                continue
            found = {}
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, raw = line.split('=', 1)
                key, raw = key.strip(), raw.strip()
                if key not in NAMES:
                    continue
                if key in found:
                    raise ValueError('duplicate provider credential in env file')
                if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
                    raw = raw[1:-1]
                found[key] = raw
            if name in found:
                value = found[name]
                break
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', value):
        raise ValueError(name + ' is missing or invalid')
    return value


def credential_status():
    result = {}
    for name in NAMES:
        try:
            credential(name)
        except (ValueError, OSError):
            result[name] = 'MISSING_OR_INVALID'
        else:
            result[name] = 'CONFIGURED'
    return result
