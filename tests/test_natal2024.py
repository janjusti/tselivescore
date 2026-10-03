"""Golden test: vereadores Natal/RN 2024 (apuração final do TSE)."""
import unittest
from collections import Counter
from pathlib import Path

from extras.proporcional import (
    apply_proporcional,
    build_legendas,
    distribute_cadeiras_tse,
    is_candidato_eleito_tse,
)
from extras.tse_client import decode_jws, normalize_payload

JWS_PATH = Path(__file__).parent / "fixtures" / "natal2024_vereador.jws"
CARGO_VEREADOR = "13"
# https://resultados.tse.jus.br/oficial/ele2024/619/dados/rn/rn17612-c0013-e000619-u.jws


def load_natal2024() -> dict:
    raw = normalize_payload(decode_jws(JWS_PATH.read_text()), CARGO_VEREADOR)
    candidatos = []
    for cand in raw["cand"]:
        vap = cand.get("vap", 0)
        if isinstance(vap, str):
            vap = vap.replace(",", ".")
        candidatos.append(
            {
                "nome": cand.get("nmu") or cand.get("nm", ""),
                "qtd_votos": int(float(vap)),
                "agr_id": cand.get("_agr_id"),
                "par_sg": cand.get("_par_sg"),
                "sf_e": cand.get("e", "n"),
                "nascimento": cand.get("dna") or cand.get("dn") or "",
            }
        )
    return {
        "agr": raw["agr"],
        "candidatos": candidatos,
        "vagas": int(raw["v"]),
        "vv": int(raw["vv"]),
        "perc_apurado": float(str(raw["pst"]).replace(",", ".")),
    }


class TestNatal2024Vereador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not JWS_PATH.is_file():
            raise unittest.SkipTest(f"fixture ausente: {JWS_PATH}")
        cls.data = load_natal2024()

    def test_apuracao_final_100_porcento(self):
        self.assertGreaterEqual(self.data["perc_apurado"], 100.0)

    def test_projecao_bate_cadeiras_oficiais_por_legenda(self):
        legendas = build_legendas(self.data["agr"])
        por_legenda = {}
        for cand in self.data["candidatos"]:
            por_legenda.setdefault(cand["agr_id"], []).append(cand)

        oficial = Counter(
            cand["agr_id"]
            for cand in self.data["candidatos"]
            if is_candidato_eleito_tse(cand, True)
        )
        seats, calcs = distribute_cadeiras_tse(
            legendas, por_legenda, self.data["vagas"], self.data["vv"]
        )
        self.assertEqual(sum(oficial.values()), self.data["vagas"])
        self.assertEqual(sum(seats.values()), self.data["vagas"])
        for legenda in legendas:
            agr_id = legenda["id"]
            self.assertEqual(
                seats.get(agr_id, 0),
                oficial.get(agr_id, 0),
                msg=f"divergência em {agr_id}",
            )

        oficial_nomes = {
            c["nome"] for c in self.data["candidatos"] if is_candidato_eleito_tse(c, True)
        }
        proj_nomes = {c["nome"] for calc in calcs for c in calc.elected}
        self.assertEqual(oficial_nomes, proj_nomes)

    def test_fallback_oficial_100_porcento(self):
        candidatos = [dict(c) for c in self.data["candidatos"]]
        apply_proporcional(
            candidatos,
            self.data["agr"],
            self.data["vagas"],
            self.data["vv"],
            perc_apurado=100,
        )
        for cand in candidatos:
            if is_candidato_eleito_tse(cand, True):
                self.assertTrue(cand["dentro_proj"], msg=cand["nome"])
            else:
                self.assertFalse(cand["dentro_proj"], msg=cand["nome"])


if __name__ == "__main__":
    unittest.main()
