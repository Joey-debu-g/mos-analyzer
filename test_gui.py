"""Exercise real Tk widgets and export files without manual dialogs."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import Application, ROOT


class GuiTests(unittest.TestCase):
    def test_toolbar_visible_at_supported_window_sizes(self):
        app = Application()
        try:
            app.load(ROOT/'examples'/'output.csv')
            for size in ('1000x700', '1280x840', '1500x950'):
                app.geometry(size)
                app.update()
                toolbar = app.toolbar
                canvas = app.canvas.get_tk_widget()
                self.assertTrue(toolbar.winfo_ismapped(), size)
                self.assertGreater(toolbar.winfo_height(), 20, size)
                self.assertLessEqual(toolbar.winfo_y()+toolbar.winfo_height(), canvas.winfo_y(), size)
                self.assertGreater(canvas.winfo_height(), 100, size)
                for button in toolbar._buttons.values():
                    self.assertTrue(button.winfo_ismapped(), size)
                    self.assertLessEqual(button.winfo_x()+button.winfo_width(), toolbar.winfo_width(), size)
        finally:
            app.update_idletasks()
            app.destroy()

    def test_modes_export_and_stale_settings(self):
        app = Application()
        app.withdraw()
        try:
            with patch('app.messagebox.showerror') as errors:
                app.load(ROOT/'examples'/'transfer.csv')
                app.update()
                self.assertEqual(len(app.results), 2)
                self.assertAlmostEqual(app.results[0]['Vth_ELR_V'], 0.45, places=6)
                self.assertEqual(len(app.fig.axes), 2)
                self.assertEqual(len(app.preview_table.get_children()), 100)
                self.assertEqual(len(app.result_table.get_children()), 2)
                self.assertIn('恒流阈值', app.result_table.heading('4')['text'])
                markers = [line for ax in app.fig.axes for line in ax.lines if line.get_gid()]
                self.assertEqual(sum(line.get_gid() == 'cc_point' for line in markers), 2)
                self.assertEqual(sum(line.get_gid() == 'elr_tangent' for line in markers), 2)
                for line in markers:
                    if line.get_gid() == 'elr_intercept':
                        self.assertAlmostEqual(line.get_xdata()[0], 0.475, places=6)
                ax = app.fig.axes[0]
                initial = ax.get_xlim()
                app.toolbar.zoom_in()
                self.assertAlmostEqual((ax.get_xlim()[1]-ax.get_xlim()[0])/(initial[1]-initial[0]), 0.8)
                app.toolbar.back()
                self.assertEqual(ax.get_xlim(), initial)
                app.toolbar.forward()
                app.toolbar.zoom_out()
                self.assertAlmostEqual(ax.get_xlim()[0], initial[0])
                app.toolbar.home()
                self.assertEqual(ax.get_xlim(), initial)
                app.toolbar.pan()
                self.assertTrue(app.toolbar._buttons['Pan'].var.get())
                app.toolbar.zoom()
                self.assertFalse(app.toolbar._buttons['Pan'].var.get())
                self.assertTrue(app.toolbar._buttons['Zoom'].var.get())
                app.toolbar.zoom()
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder)/'analysis.json'
                    with patch('app.filedialog.asksaveasfilename', return_value=str(path)):
                        app.export()
                    for suffix in ('.json', '.csv', '.png', '.txt'):
                        self.assertGreater(path.with_suffix(suffix).stat().st_size, 100)
                    self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['results']), 2)
                app.vars['target'].set('2e-6')
                with patch('app.messagebox.showinfo') as info, patch('app.filedialog.asksaveasfilename') as dialog:
                    app.export()
                    info.assert_called_once()
                    dialog.assert_not_called()
                app.load(ROOT/'examples'/'output.csv')
                app.update()
                self.assertEqual(len(app.results), 5)
                self.assertEqual(len(app.fig.axes), 1)
                self.assertNotIn('gm_peak_S', app.results[0])
                self.assertEqual(len(app.result_table.get_children()), 5)
                self.assertEqual(len(app.result_table['columns']), 6)
                self.assertFalse(any(line.get_gid() for line in app.fig.axes[0].lines))
                errors.assert_not_called()
                # Save a real rendered figure for visual inspection.
                app.load(ROOT/'examples'/'transfer.csv')
                app.fig.savefig(ROOT/'examples'/'transfer_preview.png', dpi=120)
                app.logscale.set(True)
                app.run()
                self.assertEqual(app.fig.axes[0].get_yscale(), 'log')
                self.assertFalse(any(line.get_gid()=='elr_tangent' for line in app.fig.axes[0].lines))
                app.toolbar.zoom_out()
                self.assertGreater(app.fig.axes[0].get_ylim()[0], 0)
                # Imported files show original values and switch to preview.
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder)/'user.csv'
                    path.write_text('voltage,current\n0,0\n1,1\n2,2\n', encoding='utf-8')
                    app.load(path)
                    self.assertEqual(app.tabs.select(), str(app.preview_frame))
                    self.assertEqual(len(app.preview_table.get_children()), 3)
                    self.assertFalse(app.result_table.get_children())
        finally:
            app.update_idletasks()
            app.destroy()


if __name__ == '__main__':
    unittest.main()
