import base64
import json

TSE_BASE_URL = "https://resultados.tse.jus.br/oficial/ele2026"
TSE_REFERER = "https://resultados.tse.jus.br/oficial/app/index.html"

CARGO_PRESIDENTE = "1"
CARGO_GOVERNADOR = "3"

ELEICAO_FEDERAL = "6257"
ELEICAO_ESTADUAL = "6259"


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


def build_url(cod: str) -> tuple[str, str]:
    if cod == "br":
        return (
            "Presidência",
            f"{TSE_BASE_URL}/{ELEICAO_FEDERAL}/dados/br/"
            f"br-c000{CARGO_PRESIDENTE}-e00{ELEICAO_FEDERAL}-u.jws",
        )

    uf = cod.lower()
    return (
        f"Governo {uf.upper()}",
        f"{TSE_BASE_URL}/{ELEICAO_ESTADUAL}/dados/{uf}/"
        f"{uf}-c000{CARGO_GOVERNADOR}-e00{ELEICAO_ESTADUAL}-u.jws",
    )
