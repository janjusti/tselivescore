import base64
import json
import os
from zoneinfo import ZoneInfo

TSE_BASE_URL = "https://resultados.tse.jus.br/oficial/ele2026"
TSE_REFERER = "https://resultados.tse.jus.br/oficial/app/index.html"

# 1º turno (04/10/2026) e 2º turno (25/10/2026) — códigos do ele-c.json do TSE.
ELEICAO_FEDERAL_T1 = "6257"
ELEICAO_FEDERAL_T2 = "6258"
ELEICAO_ESTADUAL_T1 = "6259"
ELEICAO_ESTADUAL_T2 = "6260"
ELEICAO_FEDERAL = ELEICAO_FEDERAL_T1
ELEICAO_ESTADUAL = ELEICAO_ESTADUAL_T1

# UFs com 2º turno de governador em 2026 (eleição 6260).
UFS_SEGUNDO_TURNO = ["ac", "am", "df", "es", "rn", "to"]

CARGO_PRESIDENTE = "1"
CARGO_GOVERNADOR = "3"
CARGO_SENADOR = "5"
CARGO_DEP_FEDERAL = "6"
CARGO_DEP_ESTADUAL = "7"
CARGO_DEP_DISTRITAL = "8"

CARGO_LABELS = {
    CARGO_PRESIDENTE: "Presidente",
    CARGO_GOVERNADOR: "Governador",
    CARGO_SENADOR: "Senador",
    CARGO_DEP_FEDERAL: "Deputado Federal",
    CARGO_DEP_ESTADUAL: "Deputado Estadual",
    CARGO_DEP_DISTRITAL: "Deputado Distrital",
}

CARGOS_MAJORITARIOS = {CARGO_PRESIDENTE, CARGO_GOVERNADOR, CARGO_SENADOR}
# Presidente e governador: maioria absoluta; abaixo de 50% vai a 2º turno (Lei 9.504/97).
# Senador: maioria relativa; os mais votados são eleitos, sem 2º turno (CF art. 46).
CARGOS_SEGUNDO_TURNO = {CARGO_PRESIDENTE, CARGO_GOVERNADOR}
CARGOS_PROPORCIONAIS = {CARGO_DEP_FEDERAL, CARGO_DEP_ESTADUAL, CARGO_DEP_DISTRITAL}

UFS = [
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt",
    "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp",
    "to",
]

# Horário local em que o TSE grava dt/ht (não é sempre Brasília).
# MS é UTC-3 oficialmente, mas o TSE publica ht no fuso Amazon/Cuiabá.
UF_TSE_TIMEZONE = {
    "ac": "America/Rio_Branco",
    "am": "America/Manaus",
    "mt": "America/Cuiaba",
    "ms": "America/Cuiaba",
    "ro": "America/Manaus",
    "rr": "America/Manaus",
}
TZ_BRASILIA = "America/Sao_Paulo"

REGIOES_BR = {
    "norte": ["ac", "am", "ap", "pa", "ro", "rr", "to"],
    "nordeste": ["al", "ba", "ce", "ma", "pb", "pe", "pi", "rn", "se"],
    "centro-oeste": ["df", "go", "ms", "mt"],
    "sudeste": ["es", "mg", "rj", "sp"],
    "sul": ["pr", "rs", "sc"],
}

REGIAO_LABELS = {
    "norte": "Norte",
    "nordeste": "Nordeste",
    "centro-oeste": "Centro-Oeste",
    "sudeste": "Sudeste",
    "sul": "Sul",
    "exterior": "Exterior",
}

REGIAO_ORDER = [
    "norte",
    "nordeste",
    "centro-oeste",
    "sudeste",
    "sul",
    "exterior",
]

UF_TO_REGIAO = {
    uf: regiao for regiao, ufs in REGIOES_BR.items() for uf in ufs
}


def normalize_turno(turno) -> int:
    try:
        value = int(turno)
    except (TypeError, ValueError):
        value = 2
    return 2 if value == 2 else 1


def default_turno() -> int:
    return normalize_turno(os.environ.get("TSELIVESCORE_TURNO", "2"))


def eleicao_id(cargo_cd: str, turno: int = 2) -> str:
    turno = normalize_turno(turno)
    if cargo_cd == CARGO_PRESIDENTE:
        return ELEICAO_FEDERAL_T2 if turno == 2 else ELEICAO_FEDERAL_T1
    return ELEICAO_ESTADUAL_T2 if turno == 2 else ELEICAO_ESTADUAL_T1


def ufs_for_turno(turno: int = 2) -> list[str]:
    if normalize_turno(turno) == 2:
        return list(UFS_SEGUNDO_TURNO)
    return list(UFS)


def default_panel_keys(turno: int = 2) -> list[str]:
    if normalize_turno(turno) == 2:
        outros = [uf for uf in UFS_SEGUNDO_TURNO if uf != "rn"]
        return [
            f"br:{CARGO_PRESIDENTE}",
            f"rn:{CARGO_GOVERNADOR}",
            *[f"{uf}:{CARGO_GOVERNADOR}" for uf in outros],
        ]
    return [
        f"br:{CARGO_PRESIDENTE}",
        f"rn:{CARGO_GOVERNADOR}",
        f"rn:{CARGO_SENADOR}",
        f"rn:{CARGO_DEP_FEDERAL}",
        f"rn:{CARGO_DEP_ESTADUAL}",
    ]


def supported_panel_keys(turno: int = 2) -> list[str] | None:
    if normalize_turno(turno) != 2:
        return None
    return [f"br:{CARGO_PRESIDENTE}"] + [
        f"{uf}:{CARGO_GOVERNADOR}" for uf in UFS_SEGUNDO_TURNO
    ]


def panel_supported(key: str, turno: int = 2) -> bool:
    _, uf, cargo_cd = resolve_panel(key)
    if normalize_turno(turno) != 2:
        return True
    if cargo_cd == CARGO_PRESIDENTE:
        return uf == "br"
    if cargo_cd == CARGO_GOVERNADOR:
        return uf in UFS_SEGUNDO_TURNO
    return False


def tse_timezone_for_panel(panel_key: str) -> ZoneInfo:
    _, uf, _ = resolve_panel(panel_key)
    return ZoneInfo(UF_TSE_TIMEZONE.get(uf, TZ_BRASILIA))


def decode_jws(token: str) -> dict:
    payload_b64 = token.strip().split(".")[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    return decode_jws(text)


def extract_candidatos(cargo: dict) -> list:
    candidatos = []
    for agr in cargo.get("agr", []):
        agr_id = agr.get("nm") or agr.get("n") or ""
        for partido in agr.get("par", []):
            par_sg = partido.get("sg", "")
            for cand in partido.get("cand", []):
                candidatos.append(
                    {
                        **cand,
                        "nm": cand.get("nmu") or cand.get("nm", ""),
                        "_agr_id": agr_id,
                        "_par_sg": par_sg,
                    }
                )
    return candidatos


def normalize_payload(payload: dict, cargo_cd: str) -> dict:
    cargo = next(c for c in payload["carg"] if c["cd"] == cargo_cd)
    mat_def = payload.get("md", "")
    if not mat_def:
        esae = payload.get("esae", "")
        if esae and esae not in ("n", "N"):
            mat_def = esae

    return {
        "cand": extract_candidatos(cargo),
        "agr": cargo.get("agr", []),
        "st": payload["s"]["st"],
        "pst": payload["s"]["pst"],
        "psnt": payload["s"]["psnt"],
        "e": payload["e"]["te"],
        "pc": payload["e"]["pc"],
        "vv": payload["v"]["vv"],
        "pvv": payload["v"]["pvv"],
        "v": cargo["nv"],
        "dt": payload.get("dt") or payload.get("dg", ""),
        "ht": payload.get("ht") or payload.get("hg", ""),
        "md": mat_def,
    }


def normalize_panel_key(key: str) -> str:
    key = key.lower()
    if ":" not in key:
        legacy = {"br": f"br:{CARGO_PRESIDENTE}"}
        if key in legacy:
            return legacy[key]
        return f"{key}:{CARGO_GOVERNADOR}"
    return key


def resolve_panel(key: str) -> tuple[str, str, str]:
    key = normalize_panel_key(key)
    uf, cargo_cd = key.split(":", 1)
    if uf == "df" and cargo_cd == CARGO_DEP_ESTADUAL:
        cargo_cd = CARGO_DEP_DISTRITAL
    return key, uf, cargo_cd


def panel_title(uf: str, cargo_cd: str, turno: int = 2) -> str:
    cargo_nome = CARGO_LABELS[cargo_cd]
    if cargo_cd == CARGO_PRESIDENTE:
        return "Presidência"
    return f"{cargo_nome} {uf.upper()}"


def build_url(key: str, turno: int = 2) -> tuple[str, str, str]:
    key, uf, cargo_cd = resolve_panel(key)
    turno = normalize_turno(turno)
    eleicao = eleicao_id(cargo_cd, turno)
    cargo_file = cargo_cd.zfill(4)
    url = (
        f"{TSE_BASE_URL}/{eleicao}/dados/{uf}/"
        f"{uf}-c{cargo_file}-e00{eleicao}-u.jws"
    )
    return panel_title(uf, cargo_cd, turno), url, cargo_cd


def build_acompanhamento_br_url(turno: int = 2) -> str:
    eleicao = eleicao_id(CARGO_PRESIDENTE, turno)
    return f"{TSE_BASE_URL}/{eleicao}/dados/br/br-e00{eleicao}-ab.json"


def parse_tse_num(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _sec_counts(ab_entry: dict) -> tuple[int, int]:
    sec = ab_entry.get("s") or {}
    total = int(parse_tse_num(sec.get("ts")) or 0)
    done = int(parse_tse_num(sec.get("st")) or 0)
    return done, total


def _elector_counts(ab_entry: dict) -> tuple[int, int, int]:
    e = ab_entry.get("e") or {}
    te = int(parse_tse_num(e.get("te")) or 0)
    est = int(parse_tse_num(e.get("est")) or 0)
    esnt = int(parse_tse_num(e.get("esnt")) or 0)
    if te > 0 and esnt <= 0:
        esnt = max(0, te - est)
    return te, est, esnt


def apuracao_por_regiao(ab_payload: dict | None) -> list[dict]:
    """Agrega apuração por macro-região (seções EA14 e eleitores do acompanhamento)."""
    if not ab_payload:
        return []

    by_uf: dict[str, dict] = {}
    for abr in ab_payload.get("abr") or []:
        if (abr.get("tpabr") or "").lower() != "uf":
            continue
        uf = (abr.get("cdabr") or "").lower()
        if not uf:
            continue
        sec_done, sec_total = _sec_counts(abr)
        te, est, esnt = _elector_counts(abr)
        by_uf[uf] = {
            "sec_done": sec_done,
            "sec_total": sec_total,
            "te": te,
            "est": est,
            "esnt": esnt,
        }

    sec_totals = {reg: [0, 0] for reg in REGIOES_BR}
    sec_exterior = [0, 0]
    ele_totals = {reg: [0, 0, 0] for reg in REGIOES_BR}
    ele_exterior = [0, 0, 0]

    for uf, counts in by_uf.items():
        if uf == "zz":
            sec_exterior[0] += counts["sec_done"]
            sec_exterior[1] += counts["sec_total"]
            ele_exterior[0] += counts["te"]
            ele_exterior[1] += counts["est"]
            ele_exterior[2] += counts["esnt"]
            continue
        regiao = UF_TO_REGIAO.get(uf)
        if not regiao:
            continue
        sec_totals[regiao][0] += counts["sec_done"]
        sec_totals[regiao][1] += counts["sec_total"]
        ele_totals[regiao][0] += counts["te"]
        ele_totals[regiao][1] += counts["est"]
        ele_totals[regiao][2] += counts["esnt"]

    nacional_esnt = sum(v[2] for v in ele_totals.values()) + ele_exterior[2]

    rows = []
    for reg_id in REGIAO_ORDER:
        if reg_id == "exterior":
            sec_done, sec_total = sec_exterior
            te, est, esnt = ele_exterior
        else:
            sec_done, sec_total = sec_totals[reg_id]
            te, est, esnt = ele_totals[reg_id]
        if sec_total <= 0 and te <= 0:
            continue
        row = {
            "id": reg_id,
            "label": REGIAO_LABELS[reg_id],
        }
        if sec_total > 0:
            row["perc_apurado"] = round(sec_done * 100 / sec_total, 2)
        if te > 0:
            row["perc_eleitores"] = round(est * 100 / te, 2)
            row["esnt"] = esnt
            if nacional_esnt > 0 and esnt > 0:
                row["peso_pendente_nacional"] = round(esnt * 100 / nacional_esnt, 1)
        rows.append(row)
    return rows


def dashboard_categories(turno: int = 2) -> list[dict]:
    categories = [
        {
            "id": "presidente",
            "label": "Presidência",
            "requires_uf": False,
            "options": [
                {"key": f"br:{CARGO_PRESIDENTE}", "label": "Presidência"},
            ],
        },
        {
            "id": "governador",
            "label": "Governadores",
            "singular": "Governador",
            "requires_uf": True,
            "cargo": CARGO_GOVERNADOR,
        },
    ]
    if normalize_turno(turno) == 2:
        return categories
    categories.extend(
        [
            {
                "id": "senador",
                "label": "Senadores",
                "singular": "Senador",
                "requires_uf": True,
                "cargo": CARGO_SENADOR,
            },
            {
                "id": "dep_federal",
                "label": "Deputados Federais",
                "singular": "Deputado Federal",
                "requires_uf": True,
                "cargo": CARGO_DEP_FEDERAL,
            },
            {
                "id": "dep_estadual",
                "label": "Deputados Estaduais",
                "singular": "Deputado Estadual",
                "requires_uf": True,
                "cargo": CARGO_DEP_ESTADUAL,
                "uf_labels": {"df": "Deputado Distrital"},
            },
        ]
    )
    return categories
