import unittest

from extras.tse_client import (
    ELEICAO_ESTADUAL_T1,
    ELEICAO_ESTADUAL_T2,
    ELEICAO_FEDERAL_T1,
    ELEICAO_FEDERAL_T2,
    UFS_SEGUNDO_TURNO,
    apuracao_por_regiao,
    build_acompanhamento_br_url,
    build_url,
    dashboard_categories,
    default_panel_keys,
    eleicao_id,
    panel_supported,
    parse_tse_num,
)


def _uf_abr(uf: str, st: int, ts: int) -> dict:
    return {"tpabr": "uf", "cdabr": uf, "s": {"st": str(st), "ts": str(ts)}}


class TestApuracaoPorRegiao(unittest.TestCase):
    def test_agrega_por_secoes_ponderadas(self):
        payload = {
            "abr": [
                _uf_abr("sp", 80, 100),
                _uf_abr("rj", 50, 100),
                _uf_abr("ac", 90, 100),
            ]
        }
        rows = {row["id"]: row for row in apuracao_por_regiao(payload)}
        self.assertAlmostEqual(rows["sudeste"]["perc_apurado"], 65.0)
        self.assertAlmostEqual(rows["norte"]["perc_apurado"], 90.0)

    def test_inclui_exterior_quando_zz_presente(self):
        payload = {"abr": [_uf_abr("zz", 60, 100)]}
        rows = apuracao_por_regiao(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "exterior")
        self.assertEqual(rows[0]["perc_apurado"], 60.0)

    def test_vazio_sem_payload(self):
        self.assertEqual(apuracao_por_regiao(None), [])
        self.assertEqual(apuracao_por_regiao({}), [])

    def test_parse_tse_num_aceita_virgula(self):
        self.assertEqual(parse_tse_num("78,48"), 78.48)
        self.assertEqual(parse_tse_num("100"), 100.0)


class TestTurnoEleicao(unittest.TestCase):
    def test_ids_primeiro_e_segundo_turno(self):
        self.assertEqual(eleicao_id("1", 1), ELEICAO_FEDERAL_T1)
        self.assertEqual(eleicao_id("1", 2), ELEICAO_FEDERAL_T2)
        self.assertEqual(eleicao_id("3", 1), ELEICAO_ESTADUAL_T1)
        self.assertEqual(eleicao_id("3", 2), ELEICAO_ESTADUAL_T2)

    def test_url_presidente_segundo_turno(self):
        title, url, cargo = build_url("br:1", 2)
        self.assertEqual(cargo, "1")
        self.assertIn("/6258/", url)
        self.assertIn("e006258", url)
        self.assertEqual(title, "Presidência")

    def test_url_governador_primeiro_turno(self):
        title, url, cargo = build_url("rn:3", 1)
        self.assertEqual(cargo, "3")
        self.assertIn("/6259/", url)
        self.assertNotIn("2º turno", title)

    def test_acompanhamento_segue_turno(self):
        self.assertIn("6258", build_acompanhamento_br_url(2))
        self.assertIn("6257", build_acompanhamento_br_url(1))

    def test_categorias_segundo_turno_so_majoritarios_com_runoff(self):
        ids = [c["id"] for c in dashboard_categories(2)]
        self.assertEqual(ids, ["presidente", "governador"])
        ids_t1 = [c["id"] for c in dashboard_categories(1)]
        self.assertIn("senador", ids_t1)
        self.assertIn("dep_federal", ids_t1)

    def test_ufs_com_segundo_turno(self):
        self.assertTrue(panel_supported("br:1", 2))
        self.assertTrue(panel_supported("rn:3", 2))
        self.assertFalse(panel_supported("sp:3", 2))
        self.assertFalse(panel_supported("rn:6", 2))
        self.assertTrue(panel_supported("sp:3", 1))
        self.assertEqual(set(UFS_SEGUNDO_TURNO), {"ac", "am", "df", "es", "rn", "to"})

    def test_default_paineis_segundo_turno_inclui_todos_governadores(self):
        keys = default_panel_keys(2)
        self.assertEqual(keys[0], "br:1")
        self.assertEqual(keys[1], "rn:3")
        self.assertEqual(
            set(keys[2:]),
            {f"{uf}:3" for uf in UFS_SEGUNDO_TURNO if uf != "rn"},
        )
        self.assertEqual(len(keys), 1 + len(UFS_SEGUNDO_TURNO))


if __name__ == "__main__":
    unittest.main()
