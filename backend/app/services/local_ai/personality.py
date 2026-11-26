from dataclasses import dataclass, field

from ...settings import get_settings


def _persona(key):
    return lambda: get_settings()['persona'][key]


@dataclass(frozen=True)
class Personality:
    avatar_name: str = field(default_factory=_persona('name'))
    speaking_style: str = field(default_factory=_persona('speaking_style'))
    response_length: str = 'short'
