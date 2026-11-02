"""Execute with this interpreter in an isolated kernel spec, without global registration."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager


parser = argparse.ArgumentParser()
parser.add_argument('--run-dir', help='Explicit run snapshot; otherwise use latest complete sample')
parser.add_argument('--output', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
if args.run_dir:
    os.environ['ROV_RUN_DIR'] = str(Path(args.run_dir).resolve())
else:
    os.environ.pop('ROV_RUN_DIR', None)
notebook = nbformat.read(root / 'notebooks/analysis.ipynb', as_version=4)
with tempfile.TemporaryDirectory(prefix='rov-notebook-') as temp:
    spec = Path(temp) / 'rov-project'
    spec.mkdir()
    (spec / 'kernel.json').write_text(json.dumps({
        'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
        'display_name': 'RoV project verification', 'language': 'python',
    }), encoding='utf-8')
    manager = KernelManager(kernel_name='rov-project', kernel_spec_manager=KernelSpecManager(kernel_dirs=[temp]))
    client = NotebookClient(notebook, km=manager, timeout=120, resources={'metadata': {'path': str(root)}})
    try:
        client.execute()
    finally:
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
nbformat.write(notebook, output)
print(f'Executed {sum(c.cell_type == "code" for c in notebook.cells)} code cells: {output}')
