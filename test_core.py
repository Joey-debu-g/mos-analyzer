import tempfile
import unittest
from pathlib import Path
from core import Curve, derivative, analyze, constant_current, make_curves, read_table


class AnalysisTests(unittest.TestCase):
    def test_unequal_spacing_quadratic(self):
        x = [0, 0.1, 0.4, 0.9, 1.6]
        actual = derivative(x, [v*v for v in x])
        for i in range(1, len(x)-1):
            self.assertAlmostEqual(actual[i], 2*x[i])

    def test_known_linear_region_threshold(self):
        x = [i/100 for i in range(181)]
        y = [1e-12 if vg<=0.45 else (0.001*(vg-0.45)**2 if vg<0.5 else 0.002*((vg-0.45)*0.05-0.05**2/2)+1e-12) for vg in x]
        result, gm = analyze(Curve('known', x, y), 1e-6, 0.05)
        self.assertAlmostEqual(result['Vth_ELR_V'], 0.45, places=6)
        self.assertAlmostEqual(result['gm_peak_S'], 1e-4, places=10)
        self.assertIsNotNone(result['Vth_CC_V'])

    def test_constant_current_interpolation(self):
        self.assertEqual(constant_current([0, 1, 2], [0, 2, 4], 3)[0], 1.5)
        self.assertIsNone(constant_current([0, 1, 2], [0, 2, 4], 5)[0])

    def test_nonmonotonic_and_plateau(self):
        self.assertIsNone(constant_current([0, 1, 2], [0, 2, 1], 1)[0])
        self.assertIsNone(constant_current([0, 1, 2], [1, 1, 2], 1)[0])
        result, _ = analyze(Curve('noise', [0, 1, 2], [0, 2, 1]), 1, 0.05)
        self.assertIsNone(result['Vth_ELR_V'])

    def test_group_sort_and_units(self):
        rows = [{'v': v, 'i': i, 'g': 'a'} for v, i in [('2000','3'), ('0','1'), ('1000','2')]]
        c = make_curves(rows, 'v', 'i', 'g', 0.001, 1e-6)[0]
        self.assertEqual(c.x, [0, 1, 2])
        self.assertAlmostEqual(c.y[2], 3e-6)

    def test_invalid_values(self):
        for value in ['nan', 'inf', '', 'bad']:
            with self.assertRaises(ValueError):
                make_curves([{'v': value, 'i': '1'}], 'v', 'i')
        with self.assertRaises(ValueError):
            make_curves([{'v': '1', 'i': '1'}]*3, 'v', 'i')
        with self.assertRaises(ValueError):
            analyze(Curve('a', [0, 1, 2], [0, 1, 2]), 1, float('nan'))

    def test_csv_delimiter_and_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'test.csv'
            path.write_text('电压;电流\n0;0\n1;1\n2;2\n', encoding='gb18030')
            headers, rows = read_table(path)
            self.assertEqual(headers, ['电压', '电流'])
            self.assertEqual(len(rows), 3)
            path.write_text('x,x\n1,2\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_table(path)


if __name__ == '__main__':
    unittest.main()
