"""Build the portable, output-free presentation notebook from reviewable cells."""
from pathlib import Path
import textwrap

import nbformat as nbf


def markdown(text):
    return nbf.v4.new_markdown_cell(textwrap.dedent(text).strip())


def code(text):
    return nbf.v4.new_code_cell(textwrap.dedent(text).strip())


nb = nbf.v4.new_notebook(cells=[
    markdown("""
    # RoV vs MLBB — inspect one reproducible pipeline run

    Notebook นี้อ่าน **snapshot ของรอบที่ระบุ** ไม่ได้ดึงข้อมูลสดเมื่อกด Run All
    ค่าเริ่มต้นใช้ sample ที่ติดป้ายข้อมูลจำลอง รัน `rov-mlbb run --config config/sample.json` ก่อน
    ถ้าจะดูข้อมูลจริง ให้ตั้ง `ROV_RUN_DIR` เป็นโฟลเดอร์ run จริงก่อนเริ่ม kernel
    หรือแก้ `RUN_DIR` ใน cell ถัดไปแล้ว Restart + Run All

    คำถามสำหรับผู้วิเคราะห์คอนเทนต์เกม: การค้นหา การเผยแพร่วิดีโอ และรีวิวที่เก็บได้
    ต่างกันอย่างไรระหว่างเกมและเดือน ภายใต้ขอบเขตแหล่งข้อมูลที่กำหนด?
    ยังไม่ใช้ตัวชี้วัดเหล่านี้แทนจำนวนผู้เล่นหรือหลักฐานการย้ายเกม
    """),
    code("""
    import io
    import os
    import sys
    import json
    from pathlib import Path
    import pandas as pd
    import matplotlib.pyplot as plt
    from IPython.display import display, Markdown, Image
    from rov_mlbb.report import load_run, select_metrics, plot_metrics

    ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents)
                if (p / 'config/sample.json').exists())
    explicit_run = os.environ.get('ROV_RUN_DIR')
    if explicit_run:
        RUN_DIR = Path(explicit_run).resolve()
    else:
        pointer = json.loads((ROOT / 'artifacts/sample/latest_complete.json').read_text(encoding='utf-8'))
        RUN_DIR = ROOT / 'artifacts/sample/runs' / pointer['run_id']
    manifest, metrics = load_run(RUN_DIR)
    label = ('SYNTHETIC DEMO — NOT RESEARCH FINDINGS' if manifest['data_kind'] == 'sample'
             else 'REAL COLLECTED DATA — CHECK COVERAGE BEFORE INTERPRETATION')
    display(Markdown(f"## {label}\\nRun: `{manifest['run_id']}` | Status: **{manifest['status']}**"))
    print('Snapshot:', RUN_DIR)
    print('Python:', sys.executable)
    print('Processed:', manifest['finished_at'])
    """),
    markdown("""
    ## ขอบเขตและวันเก็บข้อมูล

    เวลาประมวลผลไม่ใช่เวลาเก็บข้อมูล ยอดวิวเป็นยอดสะสม ณ เวลาเก็บของวิดีโอที่เผยแพร่ในเดือนนั้น
    `complete` หมายถึงครบภายในกรอบตัวอย่างที่ประกาศเท่านั้น
    `partial` = ข้อมูลบางส่วน, `filtered` = มีแถวถูกคัดออก, `missing` = ไม่มีข้อมูล
    """),
    code("""
    provenance = []
    for source, quality in manifest['sources'].items():
        packet_path = RUN_DIR / 'raw' / f'{source}.json'
        packet = json.loads(packet_path.read_text(encoding='utf-8')) if packet_path.exists() else {}
        provenance.append({
            'source': source,
            'collected_at': quality.get('collected_at'),
            'collection_time_status': quality.get('collection_time_status', 'missing'),
            'collected_no_later_than': quality.get('provenance', {}).get('collected_no_later_than'),
            'exported_at': quality.get('provenance', {}).get('exported_at'),
            'selection': packet.get('context', {}).get('selection', quality.get('reason')),
            'coverage': json.dumps(quality.get('coverage', {}), ensure_ascii=False),
            'raw_sha256': quality.get('raw_sha256'),
        })
    display(pd.DataFrame(provenance))
    """),
    markdown("""
    ## ตัวกรองและกราฟ

    ใช้ controls เมื่อเปิดใน Jupyter/VS Code ที่รองรับ widgets หรือแก้พารามิเตอร์ด้านล่างแล้วรัน cell
    กราฟและตารางใช้ข้อมูลจาก run เดียวกัน ช่องว่างคงเป็นค่าที่ไม่ทราบ ไม่เติมศูนย์
    """),
    code("""
    GAME = 'all'  # all, rov, mlbb
    START_MONTH = metrics['month'].min()
    END_MONTH = metrics['month'].max()

    def show_selection(game=GAME, start=START_MONTH, end=END_MONTH):
        selected = select_metrics(metrics, game, start, end)
        display(Markdown(f'**{label}** | `{manifest["run_id"]}`'))
        fig = plot_metrics(manifest, selected)
        buffer = io.BytesIO()
        fig.savefig(buffer, format='png', dpi=110)
        plt.close(fig)
        display(Image(data=buffer.getvalue()))
        display(selected[['month', 'game', 'search_interest', 'published_video_count',
                          'median_views_at_collection', 'sampled_channel_count',
                          'review_count', 'mean_review_rating']])
        display(selected[['month', 'game', 'trends_coverage', 'youtube_coverage',
                          'playstore_coverage', 'trends_collected_at',
                          'youtube_collected_at', 'playstore_collected_at']])
        return selected

    selected = show_selection()
    """),
    code("""
    import ipywidgets as widgets
    months = sorted(metrics['month'].unique())
    game_control = widgets.Dropdown(options=['all', 'rov', 'mlbb'], value=GAME, description='Game')
    start_control = widgets.Dropdown(options=months, value=START_MONTH, description='From')
    end_control = widgets.Dropdown(options=months, value=END_MONTH, description='To')
    output = widgets.Output()
    button = widgets.Button(description='Apply filters')
    def refresh(_):
        with output:
            output.clear_output(wait=True)
            try:
                show_selection(game_control.value, start_control.value, end_control.value)
            except ValueError as error:
                print(str(error))
    button.on_click(refresh)
    display(widgets.VBox([widgets.HBox([game_control, start_control, end_control]), button, output]))
    """),
    markdown("""
    ## สุขภาพ pipeline และการตรวจย้อนกลับ

    ตารางนี้อธิบายสิ่งที่เกิดขึ้นระหว่างประมวลผล แยกจากตัวชี้วัดเกมด้านบน
    ตรวจจำนวน input = accepted + exact duplicates + rejected สำหรับแต่ละแหล่งที่มีข้อมูล
    """),
    code("""
    quality_rows = []
    for source, row in manifest['sources'].items():
        if 'input_rows' in row:
            assert row['input_rows'] == row['accepted_rows'] + row['duplicate_rows'] + row['rejected_rows']
        quality_rows.append({'source': source, **{key: row.get(key) for key in
            ['input_rows', 'accepted_rows', 'duplicate_rows', 'rejected_rows', 'reasons', 'status']}})
    assert not metrics.duplicated(['month', 'game']).any()
    assert metrics['run_id'].eq(manifest['run_id']).all()
    display(pd.DataFrame(quality_rows))
    print('Traceability and game-month uniqueness checks passed.')
    print('CSV:', RUN_DIR / 'summary/monthly_game_metrics.csv')
    print('Manifest:', RUN_DIR / 'manifest.json')
    """),
    markdown("""
    ## การอ่านผลและข้อจำกัด

    - Sample ใช้ทดสอบวิธีคำนวณและระบบเท่านั้น ห้ามใช้เป็นข้อค้นพบด้านเกม
    - Trends เป็นดัชนีภายใน joint query เดียว เปลี่ยนคำค้นหรือช่วงเวลาจะเปลี่ยนฐานเปรียบเทียบ
    - กรณีข้อมูลรายสัปดาห์ การเฉลี่ยรายเดือนถ่วงด้วยวันทับซ้อนเป็นค่าประมาณ
    - YouTube ครอบคลุมช่องและชื่อคลิปตามกฎที่เลือก ยอดวิวสะสมสัมพันธ์กับอายุวิดีโอ
    - คะแนนรีวิวต้องอ่านคู่กับจำนวนและ coverage; ภาษา request ไม่ยืนยันสัญชาติผู้เขียน
    - ข้อมูลเพียงหนึ่งเดือนไม่พออธิบายแนวโน้มหลายเดือน และข้อมูลที่ขาดไม่ยืนยันว่าไม่มีความสนใจ
    - ข้อค้นพบชุดข้อมูลย้อนหลังอยู่ใน `docs/historical_findings.md`; รอบทดลองเชื่อมต่ออยู่ใน `docs/pilot_findings.md`
    - วันเก็บยอดวิวเดิมที่ไม่ทราบคงเป็น null; เวลา export และเวลาที่ข้อมูลอยู่ใน Firestore ไม่ใช่วันเก็บต้นทาง

    ก่อนส่งอาจารย์ ให้ยืนยันช่วงศึกษาและเกณฑ์ส่งงาน เติมข้อมูลจริงที่ขาด
    และอัปเดตรายงานให้ชี้ไปยัง run ที่ใช้สรุปจริง
    """),
])
nb.metadata = {"kernelspec": {"display_name": "Python (project .venv)", "language": "python", "name": "python3"},
               "language_info": {"name": "python", "version": "3.13"}}
destination = Path(__file__).resolve().parents[1] / "notebooks/analysis.ipynb"
destination.parent.mkdir(exist_ok=True)
nbf.write(nb, destination)
print(destination)
