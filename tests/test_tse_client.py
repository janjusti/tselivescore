import unittest

from extras.tse_client import apuracao_por_regiao, parse_tse_num


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


if __name__ == "__main__":
    unittest.main()
