"""CSV 解析、极性转换和器件参数计算；内部单位为 V、A、S。"""
import csv
import io
import math
from dataclasses import dataclass


@dataclass
class Curve:
    name: str
    x: list[float]
    y: list[float]
    polarity: str = 'NMOS'
    source: str = ''


def normalize_curve(curve, polarity):
    """PMOS signed terminal data -> Vsg/Vsd and -Id; no absolute-value guessing."""
    if polarity not in ('NMOS', 'PMOS'):
        raise ValueError('器件类型必须为 NMOS 或 PMOS。')
    sign = 1 if polarity == 'NMOS' else -1
    pairs = sorted((sign*x, sign*y) for x, y in zip(curve.x, curve.y))
    if any(x < 0 or y < 0 for x, y in pairs):
        raise ValueError(f'{polarity} 符号不符合约定：NMOS 电压/Id 须非负，PMOS 电压/Id 须非正。')
    return Curve(curve.name, [x for x, _ in pairs], [y for _, y in pairs], polarity, curve.source)


def analyze_device(curve, target, vds):
    """Analyze normalized data, return signed gate thresholds and drain bias."""
    sign = 1 if curve.polarity == 'NMOS' else -1
    if not math.isfinite(vds) or sign*vds <= 0:
        raise ValueError(f'{curve.polarity} 的 Vds 必须为有限的' + ('正值。' if sign == 1 else '负值。'))
    result, gm = analyze(curve, target, sign*vds)
    for key in ('gm_peak_Vgs_V', 'Vth_CC_V', 'Vth_ELR_V'):
        if result[key] is not None:
            result[key] *= sign
    result.update(polarity=curve.polarity, source=curve.source, Vds_V=vds)
    return result, gm


def read_table(path):
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('文件编码无法识别，请另存为 UTF-8 CSV。')
    try:
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    headers = reader.fieldnames
    if not headers or any(not h or not h.strip() for h in headers):
        raise ValueError('第一行必须包含非空列名。')
    if len(set(headers)) != len(headers):
        raise ValueError('列名不能重复。')
    rows = list(reader)
    if not rows:
        raise ValueError('文件中没有数据行。')
    return headers, rows


def make_curves(rows, xcol, ycol, groupcol=None, xscale=1, yscale=1):
    groups = {}
    for line, row in enumerate(rows, 2):
        try:
            x, y = float(row[xcol]) * xscale, float(row[ycol]) * yscale
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise ValueError(f'第 {line} 行的所选列存在空值或无效数字。') from None
        key = row.get(groupcol) if groupcol else '曲线 1'
        if key is None or not str(key).strip():
            raise ValueError(f'第 {line} 行的分组值为空。')
        groups.setdefault(str(key), []).append((x, y))
    curves = []
    for key, pairs in groups.items():
        pairs.sort()
        if len(pairs) < 3:
            raise ValueError(f'分组 {key} 至少需要 3 个点。')
        if any(a[0] == b[0] for a, b in zip(pairs, pairs[1:])):
            raise ValueError(f'分组 {key} 存在重复电压；请用分组列区分不同扫描。')
        curves.append(Curve(key, [p[0] for p in pairs], [p[1] for p in pairs]))
    return curves


def derivative(x, y):
    """Three-point derivative for unequal spacing; endpoints use secants."""
    result = [(y[1] - y[0]) / (x[1] - x[0])]
    for i in range(1, len(x) - 1):
        a, b = x[i] - x[i-1], x[i+1] - x[i]
        result.append(-b / (a*(a+b))*y[i-1] + (b-a)/(a*b)*y[i] + a/(b*(a+b))*y[i+1])
    result.append((y[-1] - y[-2]) / (x[-1] - x[-2]))
    return result


def constant_current(x, y, target):
    if not math.isfinite(target) or target <= 0:
        raise ValueError('恒流判据必须是正的有限值，单位为 A。')
    if any(b < a for a, b in zip(y, y[1:])):
        return None, '电流非单调，恒流阈值未提取'
    for i, value in enumerate(y):
        if value == target:
            if y.count(target) > 1:
                return None, '判据落在电流平台，阈值不唯一'
            return x[i], ''
        if i and y[i-1] < target < value:
            return x[i-1] + (target-y[i-1])*(x[i]-x[i-1])/(value-y[i-1]), ''
    return None, '恒流判据不在扫描电流范围内'


def analyze(curve, target, vds):
    if not math.isfinite(vds) or vds <= 0:
        raise ValueError('线性外推的 Vds 必须是正的有限值。')
    if any(y < 0 for y in curve.y):
        raise ValueError('首版仅支持正向 NMOS 数据，Id 不能为负。')
    gm = derivative(curve.x, curve.y)
    peak = max(range(1, len(gm)-1), key=lambda i: gm[i])
    cc, warning = constant_current(curve.x, curve.y, target)
    warnings = [warning] if warning else []
    elr = None
    if any(b < a for a, b in zip(curve.y, curve.y[1:])):
        warnings.append('电流非单调，线性外推未执行；请检查噪声或扫描方向')
    elif gm[peak] <= 0:
        warnings.append('内部采样点没有正跨导，线性外推未执行')
    else:
        elr = curve.x[peak] - curve.y[peak]/gm[peak] - vds/2
        if peak in (1, len(gm)-2) or max(gm[0], gm[-1]) > gm[peak]:
            warnings.append('跨导峰值接近边界，建议扩大扫描范围')
        if not curve.x[0] <= elr <= curve.x[-1]:
            warnings.append('外推阈值超出扫描范围')
    if vds > 0.1:
        warnings.append('Vds > 0.1 V，请确认低漏压线性区条件；外推结果仅供参考')
    return {'name': curve.name, 'points': len(curve.x), 'gm_peak_S': gm[peak],
            'gm_peak_Vgs_V': curve.x[peak], 'Vth_CC_V': cc, 'Vth_ELR_V': elr,
            'criterion_A': target, 'Vds_V': vds, 'warnings': warnings}, gm
