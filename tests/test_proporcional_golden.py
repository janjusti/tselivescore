import json
import unittest
from pathlib import Path

from extras.proporcional import (
    apply_proporcional,
    build_legendas,
    distribute_cadeiras_tse,
    is_candidato_eleito_tse,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as fh:
        return json.load(fh)


class TestGoldenCenario(unittest.TestCase):
    def test_cenario_cinco_vagas(self):
        data = _load("cenario_cinco_vagas.json")
        legendas = build_legendas(data["agr"])
        por_legenda = {}
        for cand in data["candidatos"]:
            por_legenda.setdefault(cand["agr_id"], []).append(cand)

        seats, calcs = distribute_cadeiras_tse(
            legendas, por_legenda, data["vagas"], data["vv"]
        )
        self.assertEqual(seats, data["expected_seats"])
        elected = sorted(c["nome"] for calc in calcs for c in calc.elected)
        self.assertEqual(elected, sorted(data["expected_elect"]))

    def test_apuracao_completa_usa_sf_e_oficial(self):
        data = _load("cenario_cinco_vagas.json")
        candidatos = [dict(c) for c in data["candidatos"]]
        for nome in data["expected_elect"]:
            cand = next(c for c in candidatos if c["nome"] == nome)
            cand["sf_e"] = "s"
        # Projeção isolada elegeria B2; oficial marca só os eleitos reais do TSE.
        candidatos[4]["sf_e"] = "n"

        apply_proporcional(
            candidatos,
            data["agr"],
            data["vagas"],
            data["vv"],
            perc_apurado=100,
        )
        eleitos = {c["nome"] for c in candidatos if c["dentro_proj"]}
        self.assertEqual(eleitos, set(data["expected_elect"]) - {"B2"})
        self.assertFalse(
            any(
                is_candidato_eleito_tse(c, True) and not c["dentro_proj"]
                for c in candidatos
            )
        )


class TestDesempateIdade(unittest.TestCase):
    def test_maior_idade_vence_empate_de_votos_no_qp(self):
        legendas = [{"id": "X", "sigla": "X", "votos": 25_000}]
        por_legenda = {
            "X": [
                {
                    "nome": "Velho",
                    "qtd_votos": 5000,
                    "agr_id": "X",
                    "par_sg": "X",
                    "sf_e": "n",
                    "nascimento": "01/01/1960",
                },
                {
                    "nome": "Novo",
                    "qtd_votos": 5000,
                    "agr_id": "X",
                    "par_sg": "X",
                    "sf_e": "n",
                    "nascimento": "01/01/1990",
                },
                {
                    "nome": "Lider",
                    "qtd_votos": 15_000,
                    "agr_id": "X",
                    "par_sg": "X",
                    "sf_e": "n",
                    "nascimento": "01/01/1970",
                },
            ],
        }
        seats, calcs = distribute_cadeiras_tse(legendas, por_legenda, vagas=2, vv=25_000)
        self.assertEqual(seats["X"], 2)
        elected = [c["nome"] for c in calcs[0].elected]
        self.assertEqual(elected, ["Lider", "Velho"])


if __name__ == "__main__":
    unittest.main()
