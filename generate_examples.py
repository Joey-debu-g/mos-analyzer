"""Generate clearly labeled synthetic long-channel NMOS data, not measurements."""
import csv
from pathlib import Path
from core import read_table
from project import DEFAULTS, write_project


def generate():
    folder = Path(__file__).resolve().parent/'examples'
    folder.mkdir(exist_ok=True)
    beta, vth = 0.002, 0.45
    def current(vgs, vds):
        over = vgs-vth
        if over <= 0:
            return 1e-12
        if vds < over:
            return beta*(over*vds-vds*vds/2)+1e-12
        return beta*over*over/2+1e-12
    with (folder/'transfer.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Vgs_V', 'Id_A', 'device'])
        for scale, label in [(1.0, 'NMOS_A'), (0.8, 'NMOS_B')]:
            for i in range(181):
                vg = i*0.01
                writer.writerow([f'{vg:.2f}', current(vg, 0.05)*scale, label])
    with (folder/'output.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Vds_V', 'Id_A', 'Vgs_V'])
        for vg in [0.6, 0.8, 1.0, 1.2, 1.5]:
            for i in range(181):
                vd = i*0.01
                writer.writerow([f'{vd:.2f}', current(vg, vd), vg])
    # Mirror signed terminal voltages and currents for an ideal PMOS.
    for original in ('transfer', 'output'):
        with (folder/f'{original}.csv').open(encoding='utf-8-sig') as stream:
            records = list(csv.reader(stream))
        with (folder/f'pmos_{original}.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerow(records[0])
            for row in records[1:]:
                writer.writerow([-float(row[0]), -float(row[1]), row[2].replace('NMOS', 'PMOS') if original=='transfer' else -float(row[2])])
    datasets = []
    for name, polarity, bias in [('transfer.csv', 'NMOS', '0.05'), ('pmos_transfer.csv', 'PMOS', '-0.05')]:
        headers, rows = read_table(folder/name)
        datasets.append({'source': name, 'headers': headers, 'rows': rows,
            'config': {**DEFAULTS, 'x': headers[0], 'y': headers[1], 'group': headers[2], 'polarity': polarity, 'vds': bias}})
    write_project(folder/'NMOS_PMOS对比.mosproj', {'format': 'mos-analyzer-project', 'version': 1,
        'datasets': datasets, 'active': 0, 'mode': '转移特性 Id-Vgs', 'logscale': False})


if __name__ == '__main__':
    generate()
