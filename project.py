"""Portable JSON project storage; embeds data, never executes file content."""
import json
import os
import tempfile
from pathlib import Path

DEFAULTS = {'x': '', 'y': '', 'group': '不分组', 'xu': 'V', 'yu': 'A',
            'target': '1e-6', 'vds': '0.05', 'polarity': 'NMOS'}
MODES = ['转移特性 Id-Vgs', '输出特性 Id-Vds']


def validate(payload):
    if not isinstance(payload, dict) or payload.get('format') != 'mos-analyzer-project' or payload.get('version') != 1:
        raise ValueError('不是支持的 MOS 项目文件（格式版本须为 1）。')
    if payload.get('mode') not in MODES or type(payload.get('logscale')) is not bool:
        raise ValueError('项目的曲线类型或坐标设置无效。')
    datasets = payload.get('datasets')
    if not isinstance(datasets, list) or not datasets:
        raise ValueError('项目必须包含至少一个数据文件。')
    for ds in datasets:
        if not isinstance(ds, dict) or not isinstance(ds.get('source'), str):
            raise ValueError('项目数据来源无效。')
        headers, rows, cfg = ds.get('headers'), ds.get('rows'), ds.get('config')
        if not isinstance(headers, list) or not headers or any(not isinstance(h, str) or not h.strip() for h in headers) or len(set(headers)) != len(headers):
            raise ValueError('项目列名无效。')
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or any(h not in r or not isinstance(r[h], (str, type(None))) for h in headers) for r in rows):
            raise ValueError('项目表格数据无效。')
        if not isinstance(cfg, dict) or set(cfg) != set(DEFAULTS) or any(not isinstance(v, str) for v in cfg.values()):
            raise ValueError('项目分析设置无效。')
        if cfg['x'] not in headers or cfg['y'] not in headers or cfg['group'] not in ['不分组']+headers:
            raise ValueError('项目列映射无效。')
        if cfg['xu'] not in ['V', 'mV'] or cfg['yu'] not in ['A', 'mA', 'uA', 'nA'] or cfg['polarity'] not in ['NMOS', 'PMOS']:
            raise ValueError('项目单位或器件类型无效。')
    active = payload.get('active', 0)
    if type(active) is not int or not 0 <= active < len(datasets):
        raise ValueError('项目当前文件索引无效。')
    return payload


def read_project(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def write_project(path, payload):
    validate(payload)
    path = Path(path)
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
