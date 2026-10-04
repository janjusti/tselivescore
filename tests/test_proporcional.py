import unittest

from extras.fixtures import fetch_mock_panel, reset_mock_state
from extras.proporcional import (
    _candidato_garantido,
    _colegas_que_podem_passar,
    _legenda_sigla,
    apply_proporcional,
    calc_quociente_eleitoral,
    infer_mat_def_proporcional,
    calc_quociente_partidario,
    distribute_cadeiras_tse,
    min_cadeiras_por_legenda,
    min_votos_frac,
)


def _cand(nome: str, votos: int, agr_id: str = "A", par_sg: str | None = None) -> dict:
    return {
        "nome": nome,
        "qtd_votos": votos,
        "agr_id": agr_id,
        "par_sg": par_sg or agr_id,
        "sf_e": "n",
    }


class TestLegendaSigla(unittest.TestCase):
    def test_partido_isolado_usa_sigla(self):
        agr = {"nm": "PARTIDO LIBERAL", "par": [{"sg": "PL"}]}
        self.assertEqual(_legenda_sigla(agr), "PL")

    def test_federacao_com_sufixo_apos_hifen(self):
        agr = {
            "nm": "FEDERAÇÃO BRASIL DA ESPERANÇA - FE BRASIL",
            "par": [{"sg": "PT"}, {"sg": "PV"}, {"sg": "PCDOB"}],
        }
        self.assertEqual(_legenda_sigla(agr), "FE BRASIL")

    def test_federacao_sem_sufixo_usa_siglas_dos_partidos(self):
        agr = {
            "nm": "FEDERAÇÃO RENOVAÇÃO SOLIDÁRIA",
            "par": [{"sg": "SOLIDARIEDADE"}, {"sg": "PRD"}],
        }
        self.assertEqual(_legenda_sigla(agr), "SOLIDARIEDADE+PRD")

    def test_federacao_uniao_progressista(self):
        agr = {
            "nm": "FEDERAÇÃO UNIÃO PROGRESSISTA",
            "par": [{"sg": "UNIÃO"}, {"sg": "PP"}],
        }
        self.assertEqual(_legenda_sigla(agr), "UNIÃO+PP")


class TestQuocientes(unittest.TestCase):
    def test_qe_despreza_fracao_ate_meio(self):
        self.assertEqual(calc_quociente_eleitoral(10_000, 8), 1250)
        self.assertEqual(calc_quociente_eleitoral(10_004, 8), 1250)

    def test_qe_arredonda_fracao_acima_de_meio(self):
        self.assertEqual(calc_quociente_eleitoral(10_005, 8), 1251)

    def test_min80_sem_arredondar_para_baixo(self):
        qe = 1453
        self.assertEqual(min_votos_frac(qe, 4, 5), 1163)
        self.assertLess(1162, min_votos_frac(qe, 4, 5))

    def test_qp_despreza_fracao(self):
        self.assertEqual(calc_quociente_partidario(90_000, 10_000), 9)
        self.assertEqual(calc_quociente_partidario(99_999, 10_000), 9)


class TestDistribuicaoTse(unittest.TestCase):
    def test_total_de_cadeiras_igual_vagas(self):
        legendas = [
            {"id": "PL", "sigla": "PL", "votos": 450_000},
            {"id": "PT", "sigla": "PT", "votos": 350_000},
            {"id": "PSD", "sigla": "PSD", "votos": 200_000},
        ]
        por_legenda = {
            "PL": [_cand(f"PL{i}", 50_000 + i * 1000, "PL") for i in range(12)],
            "PT": [_cand(f"PT{i}", 40_000 + i * 1000, "PT") for i in range(10)],
            "PSD": [_cand(f"PSD{i}", 30_000 + i * 1000, "PSD") for i in range(8)],
        }
        vagas = 10
        vv = 1_000_000
        seats, _ = distribute_cadeiras_tse(legendas, por_legenda, vagas, vv)
        self.assertEqual(sum(seats.values()), vagas)

    def test_clausula_10_por_cento_no_qp(self):
        vv = 40_000
        vagas = 4
        qe = calc_quociente_eleitoral(vv, vagas)
        min10 = min_votos_frac(qe, 1, 10)
        legendas = [{"id": "A", "sigla": "A", "votos": 45_000}]
        por_legenda = {
            "A": [
                _cand("1", 15_000, "A"),
                _cand("2", 15_000, "A"),
                _cand("3", 14_900, "A"),
                _cand("4", min10 - 1, "A"),
            ],
        }
        seats, calcs = distribute_cadeiras_tse(legendas, por_legenda, vagas, vv)
        self.assertEqual(calc_quociente_partidario(45_000, qe), 4)
        self.assertEqual(seats["A"], 4)
        elected_votos = [c["qtd_votos"] for c in calcs[0].elected]
        self.assertEqual(elected_votos[:3], [15_000, 15_000, 14_900])
        self.assertEqual(elected_votos[3], min10 - 1)

    def test_federacao_soma_votos_do_agr(self):
        agr = [
            {
                "nm": "FED",
                "tp": "f",
                "par": [
                    {"sg": "PT", "tvan": "200000", "cand": []},
                    {"sg": "PCdoB", "tvan": "100000", "cand": []},
                ],
            }
        ]
        candidatos = [
            _cand("PT1", 120_000, "FED", "PT"),
            _cand("PT2", 80_000, "FED", "PT"),
            _cand("PC1", 100_000, "FED", "PCdoB"),
        ]
        resumo = apply_proporcional(
            candidatos,
            agr,
            vagas=3,
            vv=600_000,
            aprox_votos_restantes=0,
            perc_apurado=100,
        )
        self.assertEqual(sum(item["cadeiras"] for item in resumo), 3)
        self.assertTrue(any(c["dentro_proj"] for c in candidatos))

    def test_sem_legenda_atingindo_qe_usa_sobras(self):
        legendas = [
            {"id": "A", "sigla": "A", "votos": 500},
            {"id": "B", "sigla": "B", "votos": 400},
        ]
        por_legenda = {
            "A": [_cand("A1", 500, "A")],
            "B": [_cand("B1", 400, "B")],
        }
        seats, _ = distribute_cadeiras_tse(legendas, por_legenda, vagas=2, vv=1_000)
        self.assertEqual(sum(seats.values()), 2)


class TestApuracaoNaoIniciada(unittest.TestCase):
    def test_zero_porcento_nao_marca_eliminado(self):
        agr = [
            {
                "nm": "PL",
                "tp": "p",
                "par": [{"sg": "PL", "tvan": "0", "cand": []}],
            },
            {
                "nm": "PT",
                "tp": "p",
                "par": [{"sg": "PT", "tvan": "0", "cand": []}],
            },
        ]
        candidatos = [
            _cand("A", 0, "PL", "PL"),
            _cand("B", 0, "PT", "PT"),
        ]
        resumo = apply_proporcional(
            candidatos, agr, vagas=8, vv=0, aprox_votos_restantes=0, perc_apurado=0
        )
        self.assertEqual(resumo, [])
        for cand in candidatos:
            self.assertFalse(cand.get("eliminado_definitivo"))
            self.assertFalse(cand.get("eliminado_mat"))
            self.assertIsNone(cand.get("dentro_proj"))


class TestGarantiaMatematica(unittest.TestCase):
    def test_colegas_que_podem_passar_greedy(self):
        abaixo = [_cand("B", 4_000_000), _cand("C", 3_500_000)]
        self.assertEqual(_colegas_que_podem_passar(5_000_000, abaixo, 0), 0)
        self.assertEqual(_colegas_que_podem_passar(5_000_000, abaixo, 1_500_000), 1)
        self.assertEqual(_colegas_que_podem_passar(5_000_000, abaixo, 3_500_000), 2)

    def test_lider_nao_garantido_se_dois_colegas_alcancam(self):
        abaixo = [_cand("B", 4_950_000), _cand("C", 4_550_000), _cand("D", 1_460_000)]
        self.assertEqual(_colegas_que_podem_passar(6_500_000, abaixo, 4_040_000), 2)
        self.assertFalse(
            _candidato_garantido(1, 2, 6_500_000, abaixo, 4_040_000),
        )

    def test_margem_dentro_sem_colega_fora_usa_proximo_dentro(self):
        reset_mock_state()
        prev = None
        for tick in range(1, 14):
            prev = fetch_mock_panel("rn:6", prev, tick)
        psd1 = next(c for c in prev["candidatos"] if c["nome"] == "Dep. PSD 1")
        psd2 = next(c for c in prev["candidatos"] if c["nome"] == "Dep. PSD 2")
        self.assertTrue(psd1["margem_folga"])
        self.assertLess(psd1["margem_corte"], psd1["qtd_votos"])
        self.assertEqual(psd1["margem_corte"], psd1["qtd_votos"] - psd2["qtd_votos"])

    def test_mock_pl1_nao_garantido_em_81_porcento(self):
        reset_mock_state()
        prev = None
        for tick in range(1, 31):
            prev = fetch_mock_panel("rn:6", prev, tick)
        pl1 = next(c for c in prev["candidatos"] if c["nome"] == "Dep. PL 1")
        self.assertEqual(prev["perc_sec_totalizadas"], 81.2)
        self.assertEqual(pl1.get("cadeiras_proj"), 3)
        self.assertEqual(pl1.get("cadeiras_min"), 2)
        self.assertFalse(pl1.get("garantido"))

    def test_mock_pl1_garantido_em_100_porcento(self):
        reset_mock_state()
        prev = None
        for tick in range(1, 38):
            prev = fetch_mock_panel("rn:6", prev, tick)
        pl1 = next(c for c in prev["candidatos"] if c["nome"] == "Dep. PL 1")
        self.assertTrue(pl1.get("garantido"))

    def test_mock_deputados_mat_def_so_quando_todas_vagas_garantidas(self):
        reset_mock_state()
        prev = None
        for tick in range(1, 37):
            prev = fetch_mock_panel("rn:6", prev, tick)
        self.assertEqual(prev["perc_sec_totalizadas"], 98.0)
        self.assertEqual(prev.get("mat_def"), "")
        self.assertFalse(
            all(c.get("garantido") for c in prev["candidatos"] if c.get("dentro_proj"))
        )

        prev = fetch_mock_panel("rn:6", prev, 37)
        self.assertEqual(prev.get("mat_def"), "E")
        self.assertEqual(prev.get("mat_def_label"), "Eleitos")
        dentro = [c for c in prev["candidatos"] if c.get("dentro_proj")]
        self.assertEqual(len(dentro), prev["qtd_vagas"])
        self.assertTrue(all(c.get("garantido") for c in dentro))


if __name__ == "__main__":
    unittest.main()
