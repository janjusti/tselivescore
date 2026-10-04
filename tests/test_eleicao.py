import unittest

from extras.eleicao import (
    apply_mat_def,
    infer_mat_def,
    infer_mat_def_plurality,
    infer_mat_def_segundo_turno,
)
from extras.tse_client import CARGO_GOVERNADOR, CARGO_PRESIDENTE, CARGO_SENADOR


def _cand(nome: str, votos: int, perc: float) -> dict:
    return {"nome": nome, "qtd_votos": votos, "perc_votos": perc, "sf_e": "n"}


class TestMatDefSenador(unittest.TestCase):
    def test_senador_nao_tem_segundo_turno(self):
        """Cenário RN 100%: líder ~42%, sem maioria absoluta — eleitos os 2 primeiros."""
        cands = [
            _cand("A", 42_000_000, 42.04),
            _cand("B", 25_640_000, 25.64),
            _cand("C", 23_350_000, 23.35),
            _cand("D", 9_000_000, 9.0),
        ]
        mat_def, label = infer_mat_def(cands, 0, CARGO_SENADOR, 2)
        self.assertEqual(mat_def, "E")
        self.assertEqual(label, "Eleitos")
        self.assertNotEqual(mat_def, "S")

    def test_senador_aplica_eleitos_nos_dois_primeiros(self):
        cands = [
            _cand("A", 42_000_000, 42.04),
            _cand("B", 25_640_000, 25.64),
            _cand("C", 23_350_000, 23.35),
        ]
        apply_mat_def(cands, "E", CARGO_SENADOR, 2)
        self.assertEqual(cands[0]["sf_e"], "e")
        self.assertEqual(cands[1]["sf_e"], "e")
        self.assertEqual(cands[2]["sf_e"], "n")

    def test_presidente_mesmos_votos_vai_segundo_turno(self):
        cands = [
            _cand("A", 42_000_000, 42.04),
            _cand("B", 25_640_000, 25.64),
            _cand("C", 23_350_000, 23.35),
        ]
        mat_def, label = infer_mat_def_segundo_turno(cands, 0)
        self.assertEqual(mat_def, "S")
        self.assertEqual(label, "Segundo turno")

    def test_presidente_eleito_com_maioria_absoluta(self):
        cands = [
            _cand("A", 55_000_000, 55.0),
            _cand("B", 30_000_000, 30.0),
            _cand("C", 15_000_000, 15.0),
        ]
        mat_def, _ = infer_mat_def(cands, 0, CARGO_PRESIDENTE, 1)
        self.assertEqual(mat_def, "E")

    def test_senador_indefinido_com_votos_restantes(self):
        cands = [
            _cand("A", 34_000_000, 34.0),
            _cand("B", 31_000_000, 31.0),
            _cand("C", 30_500_000, 30.5),
        ]
        mat_def, _ = infer_mat_def_plurality(cands, 1_000_000, 2)
        self.assertEqual(mat_def, "")

    def test_governador_usa_segundo_turno(self):
        cands = [
            _cand("A", 42_000_000, 42.04),
            _cand("B", 25_640_000, 25.64),
            _cand("C", 23_350_000, 23.35),
        ]
        mat_def, _ = infer_mat_def(cands, 0, CARGO_GOVERNADOR, 1)
        self.assertEqual(mat_def, "S")


if __name__ == "__main__":
    unittest.main()
