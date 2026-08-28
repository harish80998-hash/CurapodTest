import os, json
from collections import defaultdict

runs_dir = r'D:\CurapodTest\relief_matrix_runs'
stats = defaultdict(lambda: {'total': 0, 'pass': 0})

for root, _, files in os.walk(runs_dir):
    if 'report.json' in files:
        with open(os.path.join(root, 'report.json'), 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                for run in data:
                    site = run.get('site', 'Unknown')
                    side = run.get('side', '')
                    if side: site += f' [{side}]'
                    status = run.get('status', 'FAIL')
                    stats[site]['total'] += 1
                    if status == 'PASS':
                        stats[site]['pass'] += 1
            except Exception as e:
                pass

print('--- RESULTS ---')
for k, v in sorted(stats.items()):
    rate = (v['pass'] / v['total']) * 100 if v['total'] > 0 else 0
    print(f"{k}: {v['pass']}/{v['total']} ({rate:.1f}%)")
