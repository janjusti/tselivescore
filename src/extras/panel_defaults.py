from extras.fixtures import MOCK_ENABLED
from extras.tse_client import (
    CARGO_DEP_DISTRITAL,
    CARGO_DEP_ESTADUAL,
    CARGO_DEP_FEDERAL,
    CARGO_GOVERNADOR,
    CARGO_PRESIDENTE,
    CARGO_SENADOR,
    resolve_panel,
)

MIN_PANEL_PRINTABLES = 5
MAX_DEFAULT_PRINTABLES = 15

# Cadeiras na Câmara dos Deputados por UF (eleição 2022, vigente em 2026).
VAGAS_DEP_FEDERAL = {
    "ac": 8,
    "al": 9,
    "am": 8,
    "ap": 8,
    "ba": 39,
    "ce": 22,
    "df": 8,
    "es": 10,
    "go": 17,
    "ma": 18,
    "mg": 53,
    "ms": 8,
    "mt": 8,
    "pa": 17,
    "pb": 12,
    "pe": 25,
    "pi": 10,
    "pr": 30,
    "rj": 46,
    "rn": 8,
    "ro": 8,
    "rr": 8,
    "rs": 31,
    "sc": 16,
    "se": 8,
    "sp": 70,
    "to": 8,
}

# Deputados estaduais/distritais por UF (tamanho das assembleias, eleição 2022).
VAGAS_DEP_ESTADUAL = {
    "ac": 24,
    "al": 27,
    "am": 24,
    "ap": 24,
    "ba": 63,
    "ce": 46,
    "df": 24,
    "es": 30,
    "go": 41,
    "ma": 42,
    "mg": 77,
    "ms": 24,
    "mt": 24,
    "pa": 41,
    "pb": 36,
    "pe": 49,
    "pi": 24,
    "pr": 54,
    "rj": 70,
    "rn": 24,
    "ro": 24,
    "rr": 24,
    "rs": 55,
    "sc": 40,
    "se": 24,
    "sp": 94,
    "to": 24,
}


def qtd_vagas_for_panel(panel_key: str) -> int:
    if MOCK_ENABLED:
        from extras.fixtures import _scenario

        return int(_scenario(panel_key)["qtd_vagas"])

    _, uf, cargo = resolve_panel(panel_key)
    if cargo in (CARGO_PRESIDENTE, CARGO_GOVERNADOR):
        return 1
    if cargo == CARGO_SENADOR:
        return 1
    if cargo == CARGO_DEP_FEDERAL:
        return VAGAS_DEP_FEDERAL.get(uf, MIN_PANEL_PRINTABLES)
    if cargo in (CARGO_DEP_ESTADUAL, CARGO_DEP_DISTRITAL):
        return VAGAS_DEP_ESTADUAL.get(uf, MIN_PANEL_PRINTABLES)
    return 1


def default_printables_for_panel(panel_key: str) -> int:
    vagas = qtd_vagas_for_panel(panel_key)
    return max(MIN_PANEL_PRINTABLES, min(MAX_DEFAULT_PRINTABLES, vagas))
