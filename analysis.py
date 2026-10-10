"""按文件组织分析流程，不依赖窗口控件。计算公式仍在 core.py 中。"""
from pathlib import Path

from core import analyze_device, make_curves, normalize_curve

VOLTAGE_SCALES = {'V': 1, 'mV': 1e-3}
CURRENT_SCALES = {'A': 1, 'mA': 1e-3, 'uA': 1e-6, 'nA': 1e-9}


def prepare_curves(dataset):
    """应用当前文件的列映射、单位和极性设置。"""
    config = dataset['config']
    voltage_column = config['x']
    current_column = config['y']
    group_column = None if config['group'] == '不分组' else config['group']

    if voltage_column == current_column:
        raise ValueError('电压列与电流列不能相同。')
    if group_column in (voltage_column, current_column):
        raise ValueError('分组列不能与电压或电流列相同。')

    raw_curves = make_curves(
        dataset['rows'], voltage_column, current_column, group_column,
        VOLTAGE_SCALES[config['xu']], CURRENT_SCALES[config['yu']],
    )
    curves = []
    for raw_curve in raw_curves:
        raw_curve.source = dataset['source']
        curves.append(normalize_curve(raw_curve, config['polarity']))
    return curves


def analyze_datasets(datasets, transfer, logscale):
    """汇总各文件结果；任一文件失败时保留文件序号和名称供界面提示。"""
    curves = []
    results = []
    transconductances = []
    for file_number, dataset in enumerate(datasets, start=1):
        config = dataset['config']
        filename = Path(dataset['source'])
        try:
            for curve in prepare_curves(dataset):
                # 同名文件或同名分组仍需能在图例中区分。
                if len(datasets) > 1:
                    curve.name = f'{file_number}:{filename.stem} / {curve.name}'
                if logscale and any(current <= 0 for current in curve.y):
                    raise ValueError('对数坐标要求所有电流幅值严格大于零。')

                if transfer:
                    result, gm = analyze_device(
                        curve, float(config['target']), float(config['vds']),
                    )
                    transconductances.append(gm)
                else:
                    result = {
                        'name': curve.name,
                        'points': len(curve.x),
                        'Id_max_A': max(curve.y),
                        'polarity': curve.polarity,
                        'source': curve.source,
                    }
                curves.append(curve)
                results.append(result)
        except Exception as exc:
            raise ValueError(f'文件 {file_number}（{filename.name}）：{exc}') from exc
    return curves, results, transconductances
