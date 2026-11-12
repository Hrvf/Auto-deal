"""Registre des connecteurs disponibles."""
from __future__ import annotations

from .base import Connector
from .platforms import (
    AlcopaConnector,
    BCAConnector,
    DomaineConnector,
    LaCentraleConnector,
    LeboncoinConnector,
    ManualConnector,
    VPautoConnector,
)

_CONNECTORS: dict[str, Connector] = {
    c.key: c
    for c in (
        AlcopaConnector(),
        VPautoConnector(),
        DomaineConnector(),
        BCAConnector(),
        LeboncoinConnector(),
        LaCentraleConnector(),
        ManualConnector(),
    )
}


def get_connector(key: str) -> Connector:
    try:
        return _CONNECTORS[key]
    except KeyError as exc:
        raise KeyError(f"Connecteur inconnu : {key}") from exc


def all_connectors() -> list[Connector]:
    return list(_CONNECTORS.values())


def platform_name(key: str) -> str:
    c = _CONNECTORS.get(key)
    return c.name if c else key
