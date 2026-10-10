import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Application, ROOT
from core import Curve, normalize_curve, analyze_device
from project import read_project, write_project, validate


class PolarityTests(unittest.TestCase):
    def test_signed_pmos_threshold(self):
        # Low-drain linear relation: magnitude Id = gm*(Vsg-0.45-0.025).
        raw = Curve('p', [-0.6, -0.7, -0.8, -0.9], [-1.25e-5, -2.25e-5, -3.25e-5, -4.25e-5])
        curve = normalize_curve(raw, 'PMOS')
        result, gm = analyze_device(curve, 2.25e-5, -0.05)
        self.assertAlmostEqual(result['Vth_CC_V'], -0.7)
        self.assertAlmostEqual(result['Vth_ELR_V'], -0.45)
        self.assertAlmostEqual(result['gm_peak_S'], 1e-4)
        self.assertLess(result['gm_peak_Vgs_V'], 0)
        self.assertEqual(curve.x, [0.6, 0.7, 0.8, 0.9])

    def test_polarity_sign_errors(self):
        with self.assertRaises(ValueError):
            normalize_curve(Curve('bad', [-1, -2, -3], [1, 2, 3]), 'PMOS')
        with self.assertRaises(ValueError):
            normalize_curve(Curve('bad', [-1, 0, 1], [1, 2, 3]), 'NMOS')
        curve = normalize_curve(Curve('p', [-1, -2, -3], [-1, -2, -3]), 'PMOS')
        with self.assertRaises(ValueError):
            analyze_device(curve, 1, 0.05)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        self.app.withdraw()

    def tearDown(self):
        self.app.update_idletasks()
        self.app.destroy()

    def test_comparison_pmos_and_portable_project(self):
        app = self.app
        with patch('app.messagebox.showerror') as errors:
            app.load(ROOT/'examples'/'transfer.csv')
            with patch('app.filedialog.askopenfilenames', return_value=[str(ROOT/'examples'/'pmos_transfer.csv')]):
                app.add_files()
            app.vars['polarity'].set('PMOS')
            app.vars['vds'].set('-0.05')
            app.vars['target'].set('2e-6')
            app.run()
            self.assertEqual(len(app.results), 4)
            self.assertEqual(len({r['name'] for r in app.results}), 4)
            self.assertAlmostEqual(app.results[0]['Vth_ELR_V'], 0.45, places=6)
            self.assertAlmostEqual(app.results[2]['Vth_ELR_V'], -0.45, places=6)
            before = copy.deepcopy(app.results)
            app.select_dataset(0)
            self.assertEqual(app.vars['target'].get(), '1e-6')
            self.assertEqual(app.snapshot, app.current_settings())
            with tempfile.TemporaryDirectory() as folder:
                project = Path(folder)/'test.mosproj'
                with patch('app.filedialog.asksaveasfilename', return_value=str(project)):
                    app.save_project()
                payload = read_project(project)
                # Original files need not exist after loading a portable project.
                for ds in payload['datasets']:
                    ds['source'] = str(Path(folder)/Path(ds['source']).name)
                write_project(project, payload)
                app.load(ROOT/'examples'/'output.csv')
                with patch('app.filedialog.askopenfilename', return_value=str(project)):
                    app.open_project()
                self.assertIsNone(app.snapshot)
                app.run()
                self.assertEqual(len(app.results), 4)
                for a, b in zip(before, app.results):
                    self.assertEqual(a['Vth_ELR_V'], b['Vth_ELR_V'])
                    self.assertEqual(a['criterion_A'], b['criterion_A'])
                exported = Path(folder)/'compare.json'
                with patch('app.filedialog.asksaveasfilename', return_value=str(exported)):
                    app.export()
                self.assertEqual(len(json.loads(exported.read_text(encoding='utf-8'))['sources']), 2)
                import csv
                with exported.with_suffix('.csv').open(encoding='utf-8-sig') as stream:
                    rows = list(csv.DictReader(stream))
                pmos = next(r for r in rows if r['polarity']=='PMOS' and float(r['signed_voltage_V'])<0)
                self.assertLess(float(pmos['signed_Id_A']), 0)
                self.assertGreater(float(pmos['current_magnitude_A']), 0)
            errors.assert_not_called()

    def test_malformed_project_does_not_replace_data(self):
        app = self.app
        app.load(ROOT/'examples'/'transfer.csv')
        previous = copy.deepcopy(app.datasets)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.mosproj'
            path.write_text('{"format":"other"}', encoding='utf-8')
            with patch('app.filedialog.askopenfilename', return_value=str(path)), patch('app.messagebox.showerror') as error:
                app.open_project()
                error.assert_called_once()
            self.assertEqual(app.datasets, previous)
            self.assertIsNotNone(app.snapshot)

    def test_pmos_plot_and_removal(self):
        app = self.app
        with patch('app.messagebox.showerror') as errors:
            app.load(ROOT/'examples'/'pmos_transfer.csv')
            self.assertEqual(app.vars['polarity'].get(), 'PMOS')
            self.assertLess(app.results[0]['Vth_ELR_V'], 0)
            line = next(l for l in app.fig.axes[0].lines if l.get_gid()=='elr_intercept')
            self.assertAlmostEqual(line.get_xdata()[0], 0.475, places=6)
            app.logscale.set(True)
            app.run()
            self.assertEqual(app.fig.axes[0].get_yscale(), 'log')
            app.remove_file()
            self.assertEqual(app.datasets, [])
            self.assertFalse(app.result_table.get_children())
            self.assertFalse(app.preview_table.get_children())
            errors.assert_not_called()

    def test_different_columns_units_and_biases(self):
        app = self.app
        with tempfile.TemporaryDirectory() as folder, patch('app.messagebox.showerror') as errors:
            path = Path(folder)/'millivolts.csv'
            # Linear-region synthetic NMOS: Vth=0.45 V, Vds=0.1 V, gm=2e-4 S.
            path.write_text('gate_mV,drain_uA\n600,20\n700,40\n800,60\n900,80\n', encoding='utf-8')
            app.load(ROOT/'examples'/'transfer.csv')
            with patch('app.filedialog.askopenfilenames', return_value=[str(path)]):
                app.add_files()
            app.vars['xu'].set('mV')
            app.vars['yu'].set('uA')
            app.vars['vds'].set('0.1')
            app.vars['target'].set('4e-5')
            app.run()
            self.assertEqual(len(app.results), 3)
            self.assertAlmostEqual(app.results[-1]['Vth_ELR_V'], 0.45)
            self.assertAlmostEqual(app.results[-1]['Vth_CC_V'], 0.7)
            self.assertEqual(app.results[0]['Vds_V'], 0.05)
            self.assertEqual(app.results[-1]['Vds_V'], 0.1)
            app.select_dataset(0)
            self.assertEqual(app.vars['x'].get(), 'Vgs_V')
            app.select_dataset(1)
            self.assertEqual(app.vars['x'].get(), 'gate_mV')
            self.assertEqual(app.vars['xu'].get(), 'mV')
            self.assertEqual(app.snapshot, app.current_settings())
            app.remove_file()
            app.run()
            self.assertEqual(len(app.results), 2)
            errors.assert_not_called()

    def test_pmos_output_example(self):
        app = self.app
        with patch('app.messagebox.showerror') as errors:
            app.load(ROOT/'examples'/'pmos_output.csv')
            self.assertEqual(len(app.results), 5)
            self.assertEqual(len(app.fig.axes), 1)
            self.assertTrue(all(r['polarity']=='PMOS' for r in app.results))
            self.assertTrue(all(r['Id_max_A']>0 for r in app.results))
            errors.assert_not_called()


if __name__ == '__main__':
    unittest.main()
