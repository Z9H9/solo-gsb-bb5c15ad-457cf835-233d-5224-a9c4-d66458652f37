"""求解器单元测试（仅依赖标准库）。

运行：PYTHONPATH=. python3 -m unittest discover -s tests -v
  或：python3 tests/test_solver.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import solve_plan  # noqa: E402
from app.units import (  # noqa: E402
    canonical_concentration,
    convert_density,
    convert_volume,
)

NaCl = [
    {"id": 1, "name": "NaCl 储液", "solute": "NaCl", "concentration": 5,
     "concentration_unit": "M", "available_volume": 200, "volume_unit": "mL"},
    {"id": 2, "name": "NaCl 稀液", "solute": "NaCl", "concentration": 0.5,
     "concentration_unit": "M", "available_volume": 500, "volume_unit": "mL"},
]
GLU = [{"id": 3, "name": "葡萄糖储液", "solute": "葡萄糖", "concentration": 200,
        "concentration_unit": "g/L", "available_volume": 100, "volume_unit": "mL"}]

TARGET_MIX = [
    {"solute": "NaCl", "concentration": 150, "concentration_unit": "mM"},
    {"solute": "葡萄糖", "concentration": 10, "concentration_unit": "g/L"},
]


class TestUnits(unittest.TestCase):
    def test_volume(self):
        self.assertEqual(convert_volume(1, "L"), 1000)
        self.assertAlmostEqual(convert_volume(500, "uL"), 0.5)

    def test_density(self):
        self.assertAlmostEqual(convert_density(1000, "kg/m3"), 1.0)

    def test_concentration(self):
        self.assertAlmostEqual(canonical_concentration(1, "mM")[1], 0.001)
        self.assertAlmostEqual(canonical_concentration(1, "mg/mL")[1], 1.0)
        self.assertAlmostEqual(
            canonical_concentration(37, "%(w/w)", 1.19)[1], 0.37 * 1.19)
        with self.assertRaises(ValueError):
            canonical_concentration(37, "%(w/w)")


class TestSolver(unittest.TestCase):
    def test_basic_mix(self):
        r = solve_plan(NaCl + GLU, TARGET_MIX, 100, "mL")
        self.assertTrue(r["feasible"], r.get("reason"))
        nacl = next(u for u in r["used_stocks"] if u["solute"] == "NaCl")
        self.assertAlmostEqual(nacl["volume_ml"], 3.0, places=9)
        glu = next(u for u in r["used_stocks"] if u["solute"] == "葡萄糖")
        self.assertAlmostEqual(glu["volume_ml"], 5.0, places=9)
        self.assertAlmostEqual(r["diluent_volume_ml"], 92.0, places=9)
        self.assertEqual(
            len([u for u in r["used_stocks"] if u["solute"] == "NaCl"]), 1)
        for v in r["verification"]:
            self.assertLess(float(v["relative_error"]), 1e-9)

    def test_cascade_to_weaker_stock(self):
        stocks = [
            {"id": 1, "name": "浓", "solute": "X", "concentration": 1,
             "concentration_unit": "M", "available_volume": 2, "volume_unit": "mL"},
            {"id": 2, "name": "稀", "solute": "X", "concentration": 0.1,
             "concentration_unit": "M", "available_volume": 100, "volume_unit": "mL"},
        ]
        r = solve_plan(stocks, [{"solute": "X", "concentration": 50,
                                 "concentration_unit": "mM"}], 100, "mL")
        self.assertTrue(r["feasible"], r.get("reason"))
        used = {u["stock_name"]: u["volume_ml"] for u in r["used_stocks"]}
        self.assertAlmostEqual(used["浓"], 2.0, places=9)
        self.assertAlmostEqual(used["稀"], 30.0, places=9)
        self.assertAlmostEqual(r["diluent_volume_ml"], 68.0, places=9)

    def test_shortage(self):
        r = solve_plan(
            [{"id": 1, "name": "浓", "solute": "X", "concentration": 1,
              "concentration_unit": "M", "available_volume": 2, "volume_unit": "mL"}],
            [{"solute": "X", "concentration": 50, "concentration_unit": "mM"}],
            100, "mL")
        self.assertFalse(r["feasible"])
        self.assertIn("不足", r["reason"])
        self.assertTrue(r["details"])

    def test_missing_solute(self):
        r = solve_plan(GLU, [{"solute": "NaCl", "concentration": 1,
                              "concentration_unit": "M"}], 100, "mL")
        self.assertFalse(r["feasible"])
        self.assertIn("NaCl", r["reason"])

    def test_family_mismatch(self):
        r = solve_plan(
            [{"id": 1, "name": "NaCl", "solute": "NaCl", "concentration": 1,
              "concentration_unit": "M", "available_volume": 100, "volume_unit": "mL"}],
            [{"solute": "NaCl", "concentration": 5, "concentration_unit": "g/L"}],
            100, "mL")
        self.assertFalse(r["feasible"])
        self.assertIn("量纲", r["reason"])

    def test_ww_mixed_with_mass(self):
        r = solve_plan(
            [{"id": 1, "name": "浓盐酸", "solute": "HCl", "concentration": 37,
              "concentration_unit": "%(w/w)", "density": 1.19,
              "density_unit": "g/mL", "available_volume": 100, "volume_unit": "mL"}],
            [{"solute": "HCl", "concentration": 3.7, "concentration_unit": "g/L"}],
            1000, "mL")
        self.assertTrue(r["feasible"], r.get("reason"))
        self.assertAlmostEqual(
            r["used_stocks"][0]["volume_ml"], 3.7 / 0.4403, places=5)

    def test_volume_exceeded_multi_solute(self):
        r = solve_plan(
            [{"id": 1, "name": "X储液", "solute": "X", "concentration": 10,
              "concentration_unit": "g/L", "available_volume": 1000,
              "volume_unit": "mL"},
             {"id": 2, "name": "Y储液", "solute": "Y", "concentration": 10,
              "concentration_unit": "g/L", "available_volume": 1000,
              "volume_unit": "mL"}],
            [{"solute": "X", "concentration": 9, "concentration_unit": "g/L"},
             {"solute": "Y", "concentration": 9, "concentration_unit": "g/L"}],
            100, "mL")
        self.assertFalse(r["feasible"])
        self.assertIn("超过目标总体积", r["reason"])

    def test_unit_mix_l_and_ul(self):
        r = solve_plan(
            [{"id": 1, "name": "储液", "solute": "X", "concentration": 1,
              "concentration_unit": "M", "available_volume": 5000,
              "volume_unit": "uL"}],
            [{"solute": "X", "concentration": 10, "concentration_unit": "mM"}],
            0.5, "L")
        self.assertTrue(r["feasible"], r.get("reason"))
        self.assertAlmostEqual(r["used_stocks"][0]["volume_ml"], 5.0, places=9)
        self.assertAlmostEqual(r["diluent_volume_ml"], 495.0, places=9)

    def test_volfrac(self):
        r = solve_plan(
            [{"id": 1, "name": "乙醇", "solute": "乙醇", "concentration": 95,
              "concentration_unit": "%(v/v)", "available_volume": 1000,
              "volume_unit": "mL"}],
            [{"solute": "乙醇", "concentration": 70, "concentration_unit": "%(v/v)"}],
            500, "mL")
        self.assertTrue(r["feasible"], r.get("reason"))
        self.assertAlmostEqual(
            r["used_stocks"][0]["volume_ml"], 70 / 95 * 500, places=5)

    def test_exact_no_diluent(self):
        r = solve_plan(
            [{"id": 1, "name": "储液", "solute": "X", "concentration": 1,
              "concentration_unit": "M", "available_volume": 100, "volume_unit": "mL"}],
            [{"solute": "X", "concentration": 1, "concentration_unit": "M"}],
            100, "mL")
        self.assertTrue(r["feasible"])
        self.assertAlmostEqual(r["diluent_volume_ml"], 0.0, places=9)
        self.assertFalse(r["needs_diluent"])

    def test_invalid_inputs(self):
        self.assertFalse(solve_plan([], [], 0)["feasible"])
        self.assertFalse(solve_plan(NaCl, [], 100)["feasible"])
        r = solve_plan(NaCl, [
            {"solute": "NaCl", "concentration": 1, "concentration_unit": "mM"},
            {"solute": "nacl", "concentration": 2, "concentration_unit": "mM"}], 100)
        self.assertFalse(r["feasible"])
        self.assertIn("重复", r["reason"])

    def test_split_equal_concentration(self):
        r = solve_plan(
            [{"id": 1, "name": "A", "solute": "X", "concentration": 1,
              "concentration_unit": "M", "available_volume": 3, "volume_unit": "mL"},
             {"id": 2, "name": "B", "solute": "X", "concentration": 1,
              "concentration_unit": "M", "available_volume": 2, "volume_unit": "mL"}],
            [{"solute": "X", "concentration": 50, "concentration_unit": "mM"}],
            100, "mL")
        self.assertTrue(r["feasible"], r.get("reason"))
        used = {u["stock_name"]: u["volume_ml"] for u in r["used_stocks"]}
        self.assertAlmostEqual(used["A"], 3.0, places=9)
        self.assertAlmostEqual(used["B"], 2.0, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
