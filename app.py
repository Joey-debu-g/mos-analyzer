"""MOS 器件特性数据分析软件 V1.0 — desktop entry point."""
import csv
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from matplotlib import rcParams
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from core import read_table
from analysis import analyze_datasets
from project import DEFAULTS, read_project, write_project

ROOT = Path(__file__).resolve().parent
rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False


class ChineseToolbar(NavigationToolbar2Tk):
    """Use Matplotlib navigation history with visible Chinese text buttons."""
    toolitems = (
        ('Home', '恢复本次分析的初始视图', 'home', 'home'),
        ('Back', '返回上一次视图', 'back', 'back'),
        ('Forward', '前进到下一次视图', 'forward', 'forward'),
        (None, None, None, None),
        ('Pan', '开启后左键拖动平移；再次点击退出', 'move', 'pan'),
        ('Zoom', '左键框选放大；右键框选缩小；再次点击退出', 'zoom_to_rect', 'zoom'),
        ('放大', '以当前视图中心放大，两个坐标轴同时调整', 'zoom_to_rect', 'zoom_in'),
        ('缩小', '以当前视图中心缩小，两个坐标轴同时调整', 'zoom_to_rect', 'zoom_out'),
        (None, None, None, None),
        ('保存图片', '保存当前图表为 PNG、PDF 或 SVG', 'filesave', 'save_figure'),
    )

    def _Button(self, text, image_file, toggle, command):
        # Retain the backend's toggle states and history-button handling.
        if not hasattr(self, '_label_font'):
            self._label_font = ('Microsoft YaHei', 10)
        text = {'Home': '恢复全图', 'Back': '后退', 'Forward': '前进',
                'Pan': '平移', 'Zoom': '框选放大'}.get(text, text)
        return super()._Button(text, None, toggle, command)

    def set_message(self, message):
        translations = {'pan/zoom': '平移模式', 'zoom rect': '框选模式'}
        for original, chinese in translations.items():
            message = message.replace(original, chinese)
        super().set_message(message)

    def scale_view(self, factor):
        if not self.canvas.figure.axes:
            return
        if self._nav_stack() is None:
            self.push_current()
        for ax in self.canvas.figure.axes:
            for axis, getlim, setlim in ((ax.xaxis, ax.get_xlim, ax.set_xlim),
                                        (ax.yaxis, ax.get_ylim, ax.set_ylim)):
                # Work in scale coordinates so logarithmic axes remain valid.
                transform = axis.get_transform()
                lo, hi = transform.transform(getlim())
                center, half = (lo+hi)/2, (hi-lo)*factor/2
                bounds = transform.inverted().transform([center-half, center+half])
                setlim(bounds)
        self.push_current()
        self.canvas.draw_idle()

    def zoom_in(self):
        self.scale_view(0.8)

    def zoom_out(self):
        self.scale_view(1.25)

    def save_figure(self, *args):
        filename = filedialog.asksaveasfilename(title='保存当前图表', defaultextension='.png',
            initialfile='MOS曲线.png', filetypes=[('PNG 图片', '*.png'), ('PDF 文档', '*.pdf'), ('SVG 矢量图', '*.svg')])
        if filename:
            try:
                self.canvas.figure.savefig(filename, dpi=180)
            except Exception as exc:
                messagebox.showerror('图片保存失败', str(exc))


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('MOS 器件特性数据分析软件 V1.0')
        self.geometry('1280x840')
        self.minsize(1000, 700)
        self.rows, self.curves, self.results, self.gms = [], [], [], []
        self.source = None
        self.datasets = []
        self.active = 0
        self.switching = False
        self.file_choice = tk.StringVar()
        self.snapshot = None
        self.vars = {key: tk.StringVar(value=value) for key, value in {
            'x': '', 'y': '', 'group': '不分组', 'xu': 'V', 'yu': 'A',
            'mode': '转移特性 Id-Vgs', 'target': '1e-6', 'vds': '0.05',
            'polarity': 'NMOS',
        }.items()}
        self.logscale = tk.BooleanVar()
        self.status = tk.StringVar(value='请导入 CSV，或加载示例数据。')
        self.build_ui()
        for var in [*self.vars.values(), self.logscale]:
            var.trace_add('write', self.settings_changed)

    def settings_changed(self, *args):
        if self.switching:
            return
        if self.datasets:
            self.datasets[self.active]['config'] = {k: self.vars[k].get() for k in DEFAULTS}
        if self.snapshot is not None and self.snapshot != self.current_settings():
            self.result_status.set('设置已更改，下表及曲线为上次结果；请重新分析。')
        elif self.snapshot is not None:
            self.result_status.set('当前分析结果；单位见列标题。')

    def build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill='x')
        ttk.Label(top, text='MOS 器件特性分析', font=('Microsoft YaHei', 18, 'bold')).pack(side='left')
        for label, command in [('打开 CSV', self.open_file), ('转移示例', lambda: self.load(ROOT/'examples'/'transfer.csv')),
                               ('输出示例', lambda: self.load(ROOT/'examples'/'output.csv')),
                               ('导出结果', self.export), ('使用帮助', self.help)]:
            ttk.Button(top, text=label, command=command).pack(side='left', padx=6)
        files = ttk.Frame(self, padding=(12, 0, 12, 6))
        files.pack(fill='x')
        for label, command in [('添加 CSV 对比', self.add_files), ('移除当前文件', self.remove_file),
                               ('保存项目', self.save_project), ('打开项目', self.open_project),
                               ('PMOS 示例', lambda: self.load(ROOT/'examples'/'pmos_transfer.csv'))]:
            ttk.Button(files, text=label, command=command).pack(side='left', padx=(0, 6))
        ttk.Label(files, text='当前文件：').pack(side='left')
        self.file_combo = ttk.Combobox(files, textvariable=self.file_choice, state='readonly', width=27)
        self.file_combo.pack(side='left', fill='x', expand=True)
        self.file_combo.bind('<<ComboboxSelected>>', lambda event: self.select_dataset(self.file_combo.current()))
        settings = ttk.LabelFrame(self, text='数据映射与分析设置', padding=10)
        settings.pack(fill='x', padx=12)
        self.combos = {}
        fields = [('mode', '曲线类型', ['转移特性 Id-Vgs', '输出特性 Id-Vds']),
                  ('x', '电压列', []), ('y', '电流列', []), ('group', '分组列', ['不分组']),
                  ('xu', '电压单位', ['V', 'mV']), ('yu', '电流单位', ['A', 'mA', 'uA', 'nA'])]
        for column, (key, label, values) in enumerate(fields):
            ttk.Label(settings, text=label).grid(row=0, column=column, sticky='w', padx=5)
            widget = ttk.Combobox(settings, textvariable=self.vars[key], values=values, state='readonly', width=20 if key=='mode' else 14)
            widget.grid(row=1, column=column, padx=5, pady=4)
            self.combos[key] = widget
        line = ttk.Frame(self, padding=(17, 8))
        line.pack(fill='x')
        ttk.Label(line, text='当前器件').pack(side='left', padx=(0, 5))
        ttk.Combobox(line, textvariable=self.vars['polarity'], values=['NMOS', 'PMOS'], state='readonly', width=7).pack(side='left', padx=(0, 10))
        for key, label in [('target', '恒流判据 Id (A)'), ('vds', '转移扫描 Vds (V)')]:
            ttk.Label(line, text=label).pack(side='left', padx=(0, 5))
            ttk.Entry(line, textvariable=self.vars[key], width=12).pack(side='left', padx=(0, 16))
        ttk.Checkbutton(line, text='电流对数坐标', variable=self.logscale).pack(side='left')
        ttk.Button(line, text='绘图 / 重新分析', command=self.run).pack(side='left', padx=16)
        ttk.Label(self, text='列映射、单位、器件、判据和 Vds 按文件设置；曲线类型与对数坐标全局共用。PMOS 输入 Vgs/Vds/Id 负值，图中显示 Vsg/Vsd/-Id。', foreground='#526174').pack(anchor='w', padx=17)
        pane = ttk.Panedwindow(self, orient='vertical')
        pane.pack(fill='both', expand=True, padx=12, pady=8)
        chart = ttk.Frame(pane)
        pane.add(chart, weight=4)
        self.fig = Figure(figsize=(10, 4.5), dpi=100, layout='constrained')
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart)
        # Reserve controls before packing the expanding canvas: Tk packs in
        # order, so a large canvas packed first can consume all available height.
        self.toolbar = ChineseToolbar(self.canvas, chart, pack_toolbar=False)
        self.toolbar.pack(side='top', fill='x')
        ttk.Label(chart, text='标记说明：● 恒流交点  ◆ 最大跨导点  -- 外推切线  × 切线零电流截距  ▽ 修正后的外推阈值；对数坐标不显示切线。', foreground='#526174').pack(anchor='w')
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        bottom = ttk.Notebook(pane)
        self.tabs = bottom
        pane.add(bottom, weight=1)
        result_frame, preview_frame, report_frame = (ttk.Frame(bottom) for _ in range(3))
        bottom.add(result_frame, text='分析结果')
        bottom.add(preview_frame, text='原始数据预览')
        bottom.add(report_frame, text='详细报告')
        self.result_status = tk.StringVar(value='尚未分析。')
        ttk.Label(result_frame, textvariable=self.result_status).pack(anchor='w')
        self.result_table = self.make_table(result_frame)
        self.preview_status = tk.StringVar(value='尚未导入数据。')
        ttk.Label(preview_frame, textvariable=self.preview_status).pack(anchor='w')
        self.preview_table = self.make_table(preview_frame)
        self.preview_frame = preview_frame
        self.result_frame = result_frame
        self.report = tk.Text(report_frame, height=8, wrap='word', font=('Microsoft YaHei', 10))
        scroll = ttk.Scrollbar(report_frame, command=self.report.yview)
        self.report.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.report.pack(fill='both', expand=True)
        self.report.configure(state='disabled')
        ttk.Label(self, textvariable=self.status, padding=8, relief='sunken').pack(fill='x')

    @staticmethod
    def make_table(parent):
        holder = ttk.Frame(parent)
        holder.pack(fill='both', expand=True)
        table = ttk.Treeview(holder, show='headings', height=7)
        vertical = ttk.Scrollbar(holder, orient='vertical', command=table.yview)
        horizontal = ttk.Scrollbar(holder, orient='horizontal', command=table.xview)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        return table

    @staticmethod
    def fill_table(table, columns, rows):
        table.delete(*table.get_children())
        table['columns'] = [str(i) for i in range(len(columns))]
        for index, title in enumerate(columns):
            table.heading(str(index), text=title)
            table.column(str(index), width=150 if index else 120, minwidth=90, stretch=True)
        for row in rows:
            table.insert('', 'end', values=row)

    def open_file(self):
        filename = filedialog.askopenfilename(filetypes=[('CSV / TSV', '*.csv *.tsv *.txt'), ('所有文件', '*.*')])
        if filename:
            self.load(Path(filename))

    @staticmethod
    def dataset_from_path(path):
        headers, rows = read_table(path)
        config = dict(DEFAULTS)
        config['x'] = headers[0]
        config['y'] = headers[1] if len(headers) > 1 else headers[0]
        config['group'] = headers[2] if len(headers) > 2 else '不分组'
        return {'source': str(path), 'headers': headers, 'rows': rows, 'config': config}

    def refresh_files(self):
        self.file_combo['values'] = [f'{i+1}. {Path(ds["source"]).name}' for i, ds in enumerate(self.datasets)]
        if self.datasets:
            self.file_combo.current(self.active)
        else:
            self.file_choice.set('')

    def select_dataset(self, index):
        if not 0 <= index < len(self.datasets):
            return
        self.active = index
        ds = self.datasets[index]
        self.rows, self.source = ds['rows'], Path(ds['source'])
        headers = ds['headers']
        self.switching = True
        try:
            for key in ('x', 'y'):
                self.combos[key]['values'] = headers
            self.combos['group']['values'] = ['不分组'] + headers
            for key, value in ds['config'].items():
                self.vars[key].set(value)
            self.refresh_files()
        finally:
            self.switching = False
        preview_rows = []
        for line_number, row in enumerate(self.rows[:100], start=2):
            values = [row.get(header, '') for header in headers]
            preview_rows.append([line_number] + values)
        self.fill_table(self.preview_table, ['数据行'] + headers, preview_rows)
        self.preview_status.set(f'{self.source.name}：共 {len(self.rows)} 行，预览前 {min(100, len(self.rows))} 行；原始值未换算。')
        self.settings_changed()

    def clear_analysis(self):
        self.snapshot = None
        self.results, self.curves, self.gms = [], [], []
        self.fill_table(self.result_table, [], [])
        self.result_status.set('数据已更新，请重新分析所有文件。')
        self.fig.clear()
        self.toolbar.update()
        self.canvas.draw()
        self.set_report('请逐个确认文件的列映射和分析设置，再分析。')

    def load(self, path):
        try:
            ds = self.dataset_from_path(path)
        except Exception as exc:
            messagebox.showerror('导入失败', str(exc))
            return
        if path.parent == ROOT/'examples':
            ds['config']['polarity'] = 'PMOS' if path.stem.startswith('pmos') else 'NMOS'
            ds['config']['vds'] = '-0.05' if path.stem.startswith('pmos') else '0.05'
            self.vars['mode'].set('输出特性 Id-Vds' if path.stem.endswith('output') else '转移特性 Id-Vgs')
        self.datasets = [ds]
        self.clear_analysis()
        self.select_dataset(0)
        if path.parent == ROOT/'examples':
            self.run()
        else:
            self.tabs.select(self.preview_frame)
            self.status.set(f'已读取 {path.name}；请确认列、单位与器件，再分析。')

    def add_files(self):
        filenames = filedialog.askopenfilenames(title='选择要叠加对比的 CSV（可多选）', filetypes=[('CSV / TSV', '*.csv *.tsv *.txt')])
        if not filenames:
            return
        try:
            additions = [self.dataset_from_path(Path(name)) for name in filenames]
        except Exception as exc:
            messagebox.showerror('添加失败', str(exc))
            return
        self.datasets.extend(additions)
        self.clear_analysis()
        self.select_dataset(len(self.datasets)-1)
        self.tabs.select(self.preview_frame)
        self.status.set(f'共 {len(self.datasets)} 个文件；请在“当前文件”中逐个核对设置，再重新分析。')

    def remove_file(self):
        if not self.datasets:
            return
        del self.datasets[self.active]
        self.clear_analysis()
        if self.datasets:
            self.select_dataset(min(self.active, len(self.datasets)-1))
        else:
            self.rows, self.source = [], None
            self.refresh_files()
            self.fill_table(self.preview_table, [], [])
            self.preview_status.set('尚未导入数据。')
        self.status.set(f'当前保留 {len(self.datasets)} 个文件。')

    def save_project(self):
        if not self.datasets:
            messagebox.showinfo('提示', '请先导入数据。')
            return
        filename = filedialog.asksaveasfilename(title='保存项目（包含数据副本和设置）',
            defaultextension='.mosproj', initialfile='MOS分析.mosproj', filetypes=[('MOS 项目', '*.mosproj')])
        if not filename:
            return
        try:
            if any(Path(filename).resolve() == Path(ds['source']).resolve() for ds in self.datasets):
                raise ValueError('项目不能覆盖输入数据文件。')
            write_project(Path(filename), {'format': 'mos-analyzer-project', 'version': 1,
                'mode': self.vars['mode'].get(), 'logscale': self.logscale.get(),
                'active': self.active, 'datasets': self.datasets})
            self.status.set('项目已保存，包含全部原始数据副本及每个文件的设置。')
        except Exception as exc:
            messagebox.showerror('保存失败', str(exc))

    def open_project(self):
        filename = filedialog.askopenfilename(title='打开 MOS 项目', filetypes=[('MOS 项目', '*.mosproj')])
        if not filename:
            return
        try:
            payload = read_project(Path(filename))
        except Exception as exc:
            messagebox.showerror('项目打开失败', str(exc))
            return
        self.clear_analysis()
        self.switching = True
        try:
            self.datasets = payload['datasets']
            self.vars['mode'].set(payload['mode'])
            self.logscale.set(payload['logscale'])
        finally:
            self.switching = False
        self.select_dataset(payload.get('active', 0))
        self.tabs.select(self.preview_frame)
        self.status.set(f'已恢复 {len(self.datasets)} 个文件及设置，请点击重新分析。无需原始 CSV。')

    def current_settings(self):
        # Active-file selection itself does not invalidate comparison results.
        return {'mode': self.vars['mode'].get(), 'logscale': self.logscale.get(),
                'datasets': [{'source': ds['source'], 'config': dict(ds['config'])} for ds in self.datasets]}

    def run(self):
        self.snapshot = None
        self.result_status.set('分析尚未完成。')
        if not self.rows:
            messagebox.showinfo('提示', '请先导入 CSV。')
            return
        try:
            cfg = self.current_settings()
            transfer = cfg['mode'].startswith('转移')
            curves, results, gms = analyze_datasets(
                self.datasets, transfer=transfer, logscale=cfg['logscale'],
            )
            self.fig.clear()
            ax = self.fig.add_subplot(121 if transfer else 111)
            gm_ax = self.fig.add_subplot(122) if transfer else None
            for index, curve in enumerate(curves):
                line, = ax.plot(curve.x, curve.y, label=curve.name)
                if gm_ax:
                    gm_ax.plot(curve.x, gms[index], label=curve.name)
                    self.annotate_analysis(ax, gm_ax, curve, results[index], gms[index], line.get_color(), index, cfg['logscale'])
            ax.set(xlabel='NMOS: Vgs / PMOS: Vsg (V)' if transfer else 'NMOS: Vds / PMOS: Vsd (V)', ylabel='NMOS: Id / PMOS: -Id (A)', title='转移特性' if transfer else '输出特性')
            if cfg['logscale']:
                ax.set_yscale('log')
            for plot in [ax] + ([gm_ax] if gm_ax else []):
                plot.grid(True, alpha=0.25)
                plot.legend(fontsize=8)
            if gm_ax:
                gm_ax.set(xlabel='NMOS: Vgs / PMOS: Vsg (V)', ylabel='gm (S)', title='数值微分跨导')
            self.toolbar.update()
            self.canvas.draw()
            self.toolbar.push_current()
            self.curves, self.results, self.gms = curves, results, gms
            self.snapshot = cfg
            self.update_results(transfer)
            self.tabs.select(self.result_frame)
            self.set_report(self.report_text())
            self.status.set(f'{len(self.datasets)} 个文件 | {len(curves)} 组曲线 | 分析完成；内部与导出单位均为 V、A、S。')
        except Exception as exc:
            self.result_status.set('分析失败，下表及曲线已清空；请修正设置后重试。')
            self.results, self.curves, self.gms = [], [], []
            self.fill_table(self.result_table, [], [])
            self.fig.clear()
            self.toolbar.update()
            self.canvas.draw()
            self.set_report('分析失败：' + str(exc))
            messagebox.showerror('分析失败', str(exc))

    def annotate_analysis(self, ax, gm_ax, curve, result, gm, color, index, logscale):
        """Show the actual points used by the two extraction methods."""
        peak = max(range(1, len(gm)-1), key=lambda i: gm[i])
        xp, slope = curve.x[peak], gm[peak]
        short_name = curve.name.rsplit(' / ', 1)[-1]
        if len(self.datasets)>1:
            short_name = curve.name.split(':', 1)[0] + ':' + short_name
        gm_ax.plot(xp, slope, marker='D', color=color, linestyle='none', gid='gm_peak')
        gm_ax.annotate(f'{short_name}\ngm={slope:.3g} S', (xp, slope),
                       xytext=(0.03, 0.87-0.12*(index % 6)),
                       ha='left', textcoords='axes fraction', fontsize=8, color=color,
                       arrowprops={'arrowstyle': '-', 'color': color})
        if result['Vth_CC_V'] is not None:
            sign = 1 if curve.polarity == 'NMOS' else -1
            cc, target = sign*result['Vth_CC_V'], result['criterion_A']
            ax.plot(cc, target, marker='o', color=color, linestyle='none', gid='cc_point')
            ax.annotate(f"{short_name} 恒流阈值 {result['Vth_CC_V']:.4g} V", (cc, target),
                        xytext=(0.03, 0.53-0.09*(index % 6)), textcoords='axes fraction',
                        fontsize=8, color=color, arrowprops={'arrowstyle': '-', 'color': color})
        if result['Vth_ELR_V'] is not None:
            sign = 1 if curve.polarity == 'NMOS' else -1
            vth = sign*result['Vth_ELR_V']
            cross = vth + sign*result['Vds_V']/2
            ax.plot([vth], [0.02+0.035*(index % 3)], transform=ax.get_xaxis_transform(),
                    marker='v', color=color, linestyle='none', gid='elr_threshold')
            if not logscale:
                end = max(xp, cross + (curve.x[-1]-curve.x[0])*0.2)
                ax.plot([cross, end], [0, slope*(end-cross)], '--', color=color, alpha=0.7, gid='elr_tangent')
                ax.plot(cross, 0, marker='x', color=color, linestyle='none', gid='elr_intercept')
            gm_ax.text(0.98, 0.06+0.08*(index % 8), f"{short_name} 外推阈值={result['Vth_ELR_V']:.4g} V",
                       transform=gm_ax.transAxes, ha='right', fontsize=8, color=color)

    @staticmethod
    def format_parameter(value):
        if value is None:
            return '未提取'
        return f'{value:.6g}'

    def update_results(self, transfer):
        rows = []
        if transfer:
            columns = ['分组', '点数', '最大跨导 (S)', '峰值栅压 (V)', '恒流阈值 (V)',
                       '外推阈值 (V)', '恒流判据 (A)', '漏源电压 (V)', '分析提示']
            keys = ['gm_peak_S', 'gm_peak_Vgs_V', 'Vth_CC_V', 'Vth_ELR_V', 'criterion_A', 'Vds_V']
            for result in self.results:
                row = [result['name'], result['points']]
                row.extend(self.format_parameter(result[key]) for key in keys)
                row.append('；'.join(result['warnings']) or '无')
                rows.append(row)
        else:
            columns = ['分组', '点数', '最大电流幅值 (A)', '分析提示']
            for result in self.results:
                rows.append([
                    result['name'], result['points'],
                    self.format_parameter(result['Id_max_A']),
                    '输出特性不提取跨导与阈值',
                ])
        columns += ['器件', '源文件']
        for row, result in zip(rows, self.results):
            row.extend([result['polarity'], result['source']])
        self.fill_table(self.result_table, columns, rows)
        widths = [100, 50, 110, 100, 110, 110, 110, 110, 240] if transfer else [120, 60, 180, 360]
        widths += [70, 300]
        for i, width in enumerate(widths):
            self.result_table.column(str(i), width=width, minwidth=50)
        self.result_status.set('当前分析结果；单位见列标题。长提示可横向滚动，或查看“详细报告”。')

    def report_text(self):
        lines = ['MOS 器件特性数据分析软件 V1.0', '数据来源：' + '；'.join(ds['source'] for ds in self.datasets),
                 '设置：' + json.dumps(self.snapshot, ensure_ascii=False), '']
        for result in self.results:
            lines.append(f'【{result["name"]}】')
            for key, value in result.items():
                if key == 'warnings':
                    lines.extend('提示：'+w for w in value)
                elif key != 'name':
                    if isinstance(value, float):
                        display_value = f'{value:.8g}'
                    elif value is None:
                        display_value = '未提取'
                    else:
                        display_value = str(value)
                    lines.append(f'  {key}: {display_value}')
        lines.extend(['', 'gm 为 dId/dVgs 的数值估计，噪声会放大；峰值选择内部点，端点导数仅供显示。',
                      '恒流法：在指定电流处做线性插值，判据由用户选择，不自动按 W/L 归一化。',
                      '线性外推在 NMOS 正值 / PMOS Vsg、-Id 幅值域执行，PMOS 阈值与峰值栅压转换回负的 Vgs。需低漏压及固定 Vds。',
                      '结果用于教学与数据分析；请结合偏置、采样与器件模型评估有效性。'])
        return '\n'.join(lines)

    def set_report(self, text):
        self.report.configure(state='normal')
        self.report.delete('1.0', 'end')
        self.report.insert('end', text)
        self.report.configure(state='disabled')

    def export(self):
        if self.snapshot is None or self.snapshot != self.current_settings():
            messagebox.showinfo('请先分析', '设置已更改或没有有效结果，请重新分析后导出。')
            return
        filename = filedialog.asksaveasfilename(defaultextension='.json', initialfile='mos_analysis.json', filetypes=[('分析结果', '*.json')])
        if not filename:
            return
        path = Path(filename)
        files = [path, path.with_suffix('.csv'), path.with_suffix('.png'), path.with_suffix('.txt')]
        if any(p.exists() for p in files) and not messagebox.askyesno('覆盖确认', '将写入同名 JSON、CSV、PNG、TXT 文件，是否覆盖已有文件？'):
            return
        try:
            payload = {'software': 'MOS Analyzer V1.0', 'sources': [ds['source'] for ds in self.datasets], 'settings': self.snapshot, 'results': self.results}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            with path.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.writer(stream)
                writer.writerow(['group', 'voltage_magnitude_V', 'current_magnitude_A', 'gm_S', 'polarity', 'source', 'signed_voltage_V', 'signed_Id_A'])
                for i, curve in enumerate(self.curves):
                    for j, (x, y) in enumerate(zip(curve.x, curve.y)):
                        sign = 1 if curve.polarity == 'NMOS' else -1
                        gm = self.gms[i][j] if self.gms else ''
                        writer.writerow([
                            curve.name, x, y, gm, curve.polarity, curve.source,
                            sign * x, sign * y,
                        ])
            self.fig.savefig(path.with_suffix('.png'), dpi=180)
            path.with_suffix('.txt').write_text(self.report_text(), encoding='utf-8')
            self.status.set(f'已导出 JSON、CSV、PNG、TXT：{path.parent}')
        except Exception as exc:
            messagebox.showerror('导出失败', str(exc))

    def help(self):
        messagebox.showinfo('使用帮助', '1. 打开 CSV，或用“添加 CSV 对比”多选追加文件。\n2. 在“当前文件”中逐个核对列映射、单位、器件、判据和 Vds。\n3. PMOS 输入带负号的 Vgs/Vds/Id，恒流判据填正的幅值。图显示 Vsg/Vsd/-Id，表格阈值带原始符号。\n4. 所有文件使用同一种曲线类型，点击“绘图 / 重新分析”。\n5. 保存项目内含数据副本；打开项目后重新分析即可，无需原 CSV。\n6. 打开 CSV、示例或其他项目会替换当前数据集，需保留时先保存项目。\n\n对比示例：examples/NMOS_PMOS对比.mosproj\n详细说明：README.md、docs/代码说明.md。')


if __name__ == '__main__':
    Application().mainloop()
