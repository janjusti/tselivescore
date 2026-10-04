import unittest

from extras.panel_defaults import (
    MAX_DEFAULT_PRINTABLES,
    MIN_PANEL_PRINTABLES,
    default_printables_for_panel,
    qtd_vagas_for_panel,
)


class TestPanelDefaults(unittest.TestCase):
    def test_majoritario_usa_minimo_5(self):
        self.assertEqual(default_printables_for_panel("br:1"), 5)
        self.assertEqual(default_printables_for_panel("rn:3"), 5)

    def test_proporcional_rn_usa_vagas_ate_teto(self):
        self.assertEqual(qtd_vagas_for_panel("rn:6"), 8)
        self.assertEqual(default_printables_for_panel("rn:6"), 8)
        self.assertEqual(qtd_vagas_for_panel("rn:7"), 24)
        self.assertEqual(default_printables_for_panel("rn:7"), MAX_DEFAULT_PRINTABLES)

    def test_sp_federal_respeita_teto_default(self):
        self.assertEqual(qtd_vagas_for_panel("sp:6"), 70)
        self.assertEqual(default_printables_for_panel("sp:6"), MAX_DEFAULT_PRINTABLES)

    def test_limites_default(self):
        self.assertEqual(MIN_PANEL_PRINTABLES, 5)
        self.assertEqual(MAX_DEFAULT_PRINTABLES, 15)


if __name__ == "__main__":
    unittest.main()
