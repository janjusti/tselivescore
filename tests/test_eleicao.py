import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from extras.eleicao import (
    apply_garantido_segundo_turno,
    apply_mat_def,
    calc_maioria_1t,
    infer_mat_def,
    infer_mat_def_plurality,
    infer_mat_def_segundo_turno,
)
from extras.tse_client import (
    CARGO_GOVERNADOR,
    CARGO_PRESIDENTE,
    CARGO_SENADOR,
    TZ_BRASILIA,
    tse_timezone_for_panel,
)


def _cand(nome: str, votos: int, perc: float) -> dict:
    return {"nome": nome, "qtd_votos": votos, "perc_votos": perc, "sf_e": "n"}


class TestTseTimezone(unittest.TestCase):
    def test_ms_ht_do_tse_e_fuso_amazon_nao_brasilia(self):
        tz = tse_timezone_for_panel("ms:3")
        local = datetime(2026, 10, 4, 17, 38, 32, tzinfo=tz)
        brasilia = local.astimezone(ZoneInfo(TZ_BRASILIA))
        self.assertEqual(brasilia.hour, 18)
        self.assertEqual(brasilia.minute, 38)

    def test_sp_ht_do_tse_e_fuso_brasilia(self):
        tz = tse_timezone_for_panel("sp:3")
        self.assertEqual(str(tz), TZ_BRASILIA)


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

    def test_senador_aplica_eleito_mat_sem_alterar_sf_e(self):
        cands = [
            _cand("A", 42_000_000, 42.04),
            _cand("B", 25_640_000, 25.64),
            _cand("C", 23_350_000, 23.35),
        ]
        apply_mat_def(cands, "E", CARGO_SENADOR, 2)
        self.assertTrue(cands[0]["eleito_mat"])
        self.assertTrue(cands[1]["eleito_mat"])
        self.assertFalse(cands[2].get("eleito_mat"))
        self.assertEqual(cands[0]["sf_e"], "n")
        self.assertEqual(cands[1]["sf_e"], "n")

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
        mat_def, _ = infer_mat_def(cands, 0, CARGO_PRESIDENTE, 1, 100_000_000)
        self.assertEqual(mat_def, "E")

    def test_senador_indefinido_com_votos_restantes(self):
        cands = [
            _cand("A", 34_000_000, 34.0),
            _cand("B", 31_000_000, 31.0),
            _cand("C", 30_500_000, 30.5),
        ]
        mat_def, _ = infer_mat_def_plurality(cands, 1_000_000, 2)
        self.assertEqual(mat_def, "")

    def test_garantido_segundo_turno_antes_de_mat_def(self):
        cands = [
            _cand("A", 39_900_000, 46.0),
            _cand("B", 35_600_000, 41.0),
            _cand("C", 6_940_000, 8.0),
            _cand("D", 4_340_000, 5.0),
        ]
        apply_garantido_segundo_turno(cands, 13_200_000, "")
        self.assertTrue(cands[0]["garantido_turno"])
        self.assertTrue(cands[1]["garantido_turno"])
        self.assertFalse(cands[2].get("garantido_turno"))

    def test_garantido_segundo_turno_nao_aplica_se_ja_eleito(self):
        cands = [
            _cand("A", 55_000_000, 55.0),
            _cand("B", 30_000_000, 30.0),
            _cand("C", 15_000_000, 15.0),
        ]
        apply_garantido_segundo_turno(cands, 0, "E")
        self.assertFalse(cands[0].get("garantido_turno"))

    def test_segundo_turno_nao_altera_sf_e(self):
        cands = [
            _cand("A", 42_000_000, 42.04),
            _cand("B", 25_640_000, 25.64),
            _cand("C", 23_350_000, 23.35),
        ]
        cands[1]["viavel"] = False
        cands[1]["distancia_votos"] = 5_000_000
        apply_mat_def(cands, "S", CARGO_PRESIDENTE, 1)
        self.assertEqual(cands[0]["sf_e"], "n")
        self.assertEqual(cands[1]["sf_e"], "n")
        self.assertEqual(cands[2]["sf_e"], "n")
        self.assertIsNone(cands[0]["viavel"])
        self.assertIsNone(cands[1]["viavel"])
        self.assertIsNone(cands[1]["distancia_votos"])

    def test_governador_usa_segundo_turno(self):
        cands = [
            _cand("A", 42_000_000, 42.04),
            _cand("B", 25_640_000, 25.64),
            _cand("C", 23_350_000, 23.35),
        ]
        mat_def, _ = infer_mat_def(cands, 0, CARGO_GOVERNADOR, 1)
        self.assertEqual(mat_def, "S")

    def test_md_minusculo_do_tse_aplica_eleito_mat_sem_garantido_turno(self):
        cands = [
            _cand("RIEDEL", 768_000, 67.32),
            _cand("TRAD", 266_000, 23.12),
            _cand("CATAN", 86_000, 7.48),
        ]
        mat_def = "e".upper()
        apply_mat_def(cands, mat_def, CARGO_GOVERNADOR, 1)
        apply_garantido_segundo_turno(cands, 210_000, mat_def)
        self.assertTrue(cands[0]["eleito_mat"])
        self.assertEqual(cands[0]["sf_e"], "n")
        self.assertFalse(cands[0].get("garantido_turno"))

    def test_governador_nao_eleito_mat_abaixo_de_50_no_final(self):
        cands = [
            _cand("MORO", 2_733_278, 50.34),
            _cand("SANDRO", 1_363_032, 25.10),
            _cand("REQUIAO", 1_274_873, 23.48),
        ]
        mat_def, _ = infer_mat_def_segundo_turno(cands, 854_711, 5_428_698)
        self.assertEqual(mat_def, "")


class TestDistanciaSegundoTurno(unittest.TestCase):
    def test_terceiro_mede_distancia_ao_segundo(self):
        from extras.fixtures import _calc_distancia

        cands = [
            {
                **_cand("Gov. RN A", 43_500_000, 51.84),
                "garantido_turno": True,
                "distancia_votos": None,
                "viavel": None,
            },
            {
                **_cand("Gov. RN B", 31_600_000, 37.63),
                "garantido_turno": True,
                "distancia_votos": None,
                "viavel": None,
            },
            _cand("Gov. RN C", 8_850_000, 10.53),
        ]
        _calc_distancia(cands, 1, 16_000_000, True, segundo_turno=True, mat_def="")
        self.assertIsNone(cands[0]["distancia_votos"])
        self.assertEqual(cands[1]["distancia_votos"], 11_900_000)
        self.assertTrue(cands[1]["viavel"])
        self.assertEqual(cands[2]["distancia_votos"], 22_750_000)
        self.assertFalse(cands[2]["viavel"])

    def test_segundo_perde_distancia_so_com_mat_def_s(self):
        from extras.fixtures import _calc_distancia

        cands = [
            _cand("A", 35_600_000, 45.45),
            {**_cand("B", 31_400_000, 39.99), "garantido_turno": True},
            _cand("C", 7_140_000, 9.10),
        ]
        _calc_distancia(cands, 1, 21_600_000, True, segundo_turno=True, mat_def="")
        self.assertEqual(cands[1]["distancia_votos"], 4_200_000)

        _calc_distancia(cands, 1, 21_600_000, True, segundo_turno=True, mat_def="S")
        self.assertIsNone(cands[1]["distancia_votos"])


class TestMaioria1t(unittest.TestCase):
    def test_caso_celina_df(self):
        cands = [_cand("CELINA", 794_000, 49.86), _cand("LEANDRO", 550_000, 34.5)]
        m = calc_maioria_1t(
            cands,
            55_000,
            1_592_000,
            segundo_turno=True,
            mat_def="",
            apuracao_iniciada=True,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["votos_necessarios"], 29_501)
        self.assertEqual(m["votos_restantes"], 55_000)
        self.assertFalse(m["garantida"])
        self.assertFalse(m["impossivel"])
        self.assertAlmostEqual(m["percentual_minimo_final"], 48.21, places=1)

    def test_garantida_quando_lider_ja_passa_de_50_no_pior_caso(self):
        cands = [_cand("A", 55_000_000, 55.0), _cand("B", 30_000_000, 30.0)]
        m = calc_maioria_1t(
            cands,
            1_000_000,
            100_000_000,
            segundo_turno=True,
            mat_def="",
            apuracao_iniciada=True,
        )
        self.assertTrue(m["garantida"])
        self.assertEqual(m["votos_necessarios"], 0)

    def test_impossivel_quando_precisa_mais_que_restantes(self):
        cands = [_cand("A", 42_000_000, 42.04), _cand("B", 25_640_000, 25.64)]
        m = calc_maioria_1t(
            cands,
            5_000_000,
            100_000_000,
            segundo_turno=True,
            mat_def="",
            apuracao_iniciada=True,
        )
        self.assertTrue(m["impossivel"])
        self.assertGreater(m["votos_necessarios"], m["votos_restantes"])

    def test_nao_aplica_senador(self):
        cands = [_cand("A", 42_000_000, 42.04), _cand("B", 25_640_000, 25.64)]
        m = calc_maioria_1t(
            cands,
            0,
            100_000_000,
            segundo_turno=False,
            mat_def="E",
            apuracao_iniciada=True,
        )
        self.assertIsNone(m)

    def test_nao_aplica_quando_ja_eleito(self):
        cands = [_cand("A", 55_000_000, 55.0), _cand("B", 30_000_000, 30.0)]
        m = calc_maioria_1t(
            cands,
            0,
            100_000_000,
            segundo_turno=True,
            mat_def="E",
            apuracao_iniciada=True,
        )
        self.assertIsNone(m)


if __name__ == "__main__":
    unittest.main()
