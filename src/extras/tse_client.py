import base64
import json

TSE_BASE_URL = "https://resultados.tse.jus.br/oficial/ele2026"
TSE_REFERER = "https://resultados.tse.jus.br/oficial/app/index.html"

ELEICAO_FEDERAL = "6257"
ELEICAO_ESTADUAL = "6259"

CARGO_PRESIDENTE = "1"
CARGO_GOVERNADOR = "3"
CARGO_DEP_FEDERAL = "6"
CARGO_DEP_ESTADUAL = "7"
CARGO_DEP_DISTRITAL = "8"

CARGO_LABELS = {
    CARGO_PRESIDENTE: "Presidente",
    CARGO_GOVERNADOR: "Governador",
    CARGO_DEP_FEDERAL: "Deputado Federal",
    CARGO_DEP_ESTADUAL: "Deputado Estadual",
    CARGO_DEP_DISTRITAL: "Deputado Distrital",
}

UFS = [
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt",
    "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp",
    "to",
]


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
        for partido in agr.get("par", []):
            for cand in partido.get("cand", []):
                candidatos.append(
                    {
                        **cand,
                        "nm": cand.get("nmu") or cand.get("nm", ""),
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


def panel_title(uf: str, cargo_cd: str) -> str:
    cargo_nome = CARGO_LABELS[cargo_cd]
    if cargo_cd == CARGO_PRESIDENTE:
        return "Presidência"
    return f"{cargo_nome} {uf.upper()}"


def build_url(key: str) -> tuple[str, str, str]:
    key, uf, cargo_cd = resolve_panel(key)
    eleicao = ELEICAO_FEDERAL if cargo_cd == CARGO_PRESIDENTE else ELEICAO_ESTADUAL
    cargo_file = cargo_cd.zfill(4)
    url = (
        f"{TSE_BASE_URL}/{eleicao}/dados/{uf}/"
        f"{uf}-c{cargo_file}-e00{eleicao}-u.jws"
    )
    return panel_title(uf, cargo_cd), url, cargo_cd


def dashboard_categories() -> list[dict]:
    return [
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
