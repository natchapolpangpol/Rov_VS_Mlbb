# RoV vs MLBB — Data Engineering Pipeline

ระบบเตรียมข้อมูลความสนใจต่อเกมจาก Google Trends, YouTube และ Google Play Store
รันบนเครื่อง Windows ด้วย Python + SQLite โดยไม่ต้องมีบัญชี Firestore

**สถานะ:** ใช้ข้อมูลจริงครบสามแหล่งแล้ว: YouTube/รีวิวจาก snapshot ของทีม และ Trends ที่เก็บย้อนหลังใหม่ด้วยสเกลร่วม
ช่วงศึกษา 1 มกราคม 2025–10 มีนาคม 2026 ตาม notebook เดิม ผลรวม 30 เกม–เดือนยังติดสถานะ partial ตามข้อจำกัดข้อมูลจริง
ทดสอบ 45 กรณีผ่าน พร้อมหลักฐานรันซ้ำและตั้งเวลา Prefect ดู [รายงาน](docs/final_report.md) และ [ผลวิเคราะห์](docs/historical_findings.md)
ข้อมูลใน `data/sample/` เป็นข้อมูลจำลองสำหรับสาธิตเท่านั้น

## สิ่งที่ระบบทำ

- เก็บ raw input แบบเดิมพร้อม SHA-256, config และเวลาในแต่ละรอบ
- ตรวจ schema, key, วันที่, คะแนน และตัวเลข แยก rejected rows พร้อมเหตุผล
- เก็บข้อมูลใน SQLite โดยใช้ unique keys และ immutable content versions
- รัน batch เดิมซ้ำโดยไม่เพิ่ม observations ซ้ำ พร้อมเก็บประวัติการรันแยกกัน
- สรุปแต่ละแหล่งเป็นเกม–เดือน ก่อนเชื่อมเป็นตารางกลาง
- แสดง missing/partial/filtered coverage และไม่แทนการดึงข้อมูลล้มเหลวด้วยศูนย์
- ส่งออก CSV/Parquet, กราฟ และรายงานที่อ้างอิง run เดียวกัน
- ควบคุมลำดับการทำงานด้วย Prefect แบบ local และตั้งเวลารันได้

## เริ่มต้นบน PowerShell

Environment ที่ใช้ทดสอบ: **Python 3.13 บน Windows** ดูเวอร์ชัน dependencies จริงใน `requirements-lock.txt`

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m rov_mlbb.cli run --config config/sample.json
.\.venv\Scripts\python.exe -m pytest -q
```

การรัน sample ไม่เรียกบริการภายนอก ทุกครั้งจะได้ `run_id` ใหม่ แต่ observations ชุดเดิมในฐานข้อมูลไม่เพิ่มซ้ำ

```powershell
$run = Get-Content artifacts/sample/latest_complete.json -Raw | ConvertFrom-Json
.\.venv\Scripts\python.exe -m rov_mlbb.cli report --run-dir $run.artifact_dir
```

เปิด `report/report.md` และ `report/overview.png` ภายใน run directory หรือใช้ [analysis notebook](notebooks/analysis.ipynb)
เลือก kernel ของ `.venv` เมื่อเปิด notebook ใน VS Code/Jupyter

Notebook เลือกเกมและเดือนได้ผ่าน widgets หรือพารามิเตอร์ โดยค่าเริ่มต้นอ่าน sample เท่านั้น
รันตรวจทั้ง notebook โดยไม่ต้องเปิด UI:

```powershell
.\.venv\Scripts\python.exe scripts/execute_notebook.py --output artifacts/sample/analysis.executed.ipynb
# ใช้ snapshot จริงโดยระบุโฟลเดอร์ของ run เอง
.\.venv\Scripts\python.exe scripts/execute_notebook.py --run-dir artifacts/real/runs/<run_id> --output artifacts/real/analysis.executed.ipynb
```

ถ้าเปิดแบบ interactive ให้ตั้ง `ROV_RUN_DIR` ก่อนเปิด kernel หรือแก้ `RUN_DIR` ใน notebook แล้ว Restart + Run All
ตัว notebook ไม่เก็บข้อมูลใหม่เมื่อ Run All และไม่เลือก real run ให้อัตโนมัติ

สาธิต rerun → ข้อมูลผิด → recovery ในฐานข้อมูลจำลองแยกใหม่ทุกครั้ง:

```powershell
.\.venv\Scripts\python.exe scripts/demo.py
```

## โครงสร้างข้อมูลและ output

```text
config/                  ช่วงศึกษาและการตั้งค่า ไม่มี secret
data/sample/             ข้อมูลจำลองที่ commit ได้
data/imports/            ข้อมูลจริงที่เก็บหรือรับจากเพื่อน (ไม่ commit)
src/rov_mlbb/            collectors / quality / aggregate / storage / flows
tests/                   ทดสอบข้อมูลผิด รันซ้ำ การเชื่อม และ failure handling
artifacts/sample/        ฐานข้อมูลและผลสาธิต
artifacts/real/          ฐานข้อมูลและผลข้อมูลจริง แยกจาก sample
  pipeline.sqlite
  latest_attempt.json    สถานะรอบล่าสุด อาจเป็น failed
  latest_complete.json   เปลี่ยนเฉพาะรอบที่ครบตามกฎคุณภาพ/coverage
  runs/<run_id>/
    config.json
    raw/                 input ต้นฉบับก่อนตรวจคุณภาพ
    clean/               accepted records JSON/Parquet
    rejected/            row index และเหตุผล ย้อนกลับ raw ได้
    summary/             ตารางเกม–เดือน CSV/Parquet
    manifest.json        ที่มา counts, hashes และสถานะ
    report/              กราฟและรายงานที่สั่งสร้าง
```

`complete` หมายถึงครบภายในกลุ่มตัวอย่างและช่วงที่ประกาศ ไม่ใช่ข้อมูลผู้เล่นทั้งหมด
รอบ `partial` มีผลส่งออกให้ตรวจสอบได้ แต่ไม่ทับ `latest_complete.json`
รอบ `failed` เก็บหลักฐานข้อผิดพลาดและ raw ที่อ่านได้ โดยไม่ commit accepted records/summary ของรอบนั้น
ถ้า SQLite commit สำเร็จแล้วแต่เขียน pointer ไม่ได้ คำสั่งจะแจ้ง `Data committed; pointer publication failed`
สถานะข้อมูลที่ commit แล้วจะยังคงเดิมพร้อม diagnostic ในฐานข้อมูลและ manifest เมื่อเขียนได้
ตรวจด้วย run path ที่แจ้ง หรือรัน input เดิมซ้ำเพื่ออัปเดต pointer โดยไม่เพิ่มข้อมูลซ้ำ

## เก็บข้อมูลจริง

### ใช้ข้อมูลประวัติที่นำเข้าไว้แล้ว

ไม่ต้องใช้ YouTube API key หรือเปิด Firestore เพื่อรัน snapshot ในเครื่องซ้ำ:

```powershell
.\.venv\Scripts\python.exe -m rov_mlbb.cli run --config data/imports/historical-ec4ce616ddb2466a8b9b65ea03e29e9e/pipeline_config.json
```

คำสั่งคืน run_id และ artifact_dir ใหม่ ใช้ path นั้นกับคำสั่ง report
ผลศึกษาที่ตรึงไว้คือ `artifacts/real/runs/fd1a7d895cb3477ea72591e4199e5e38/` ดู [inventory](docs/data_inventory.md)
สำหรับเครื่องอื่นต้องมี snapshot ที่ได้รับสิทธิ์และสร้าง config ใหม่ตาม [คู่มือนำเข้า](docs/importing_data.md)
ไฟล์ data/imports ไม่รวมใน source package การรัน sample จึงเป็นเส้นทางเริ่มต้นสำหรับผู้ตรวจพอร์ตที่ไม่มี raw ของทีม

### เก็บรอบใหม่

คัดลอก `config/collect.example.json` แล้วตั้งวันที่และรายชื่อช่องให้ตรงกับโจทย์
ตัวอย่างเดิมมีเพียงสองช่อง จึงไม่ใช่กลุ่มตัวอย่างที่ครอบคลุมประเทศไทย
`config/pilot.json` ใช้ทดลองการเชื่อมต่อและ coverage เท่านั้น ไม่ใช่ช่วงศึกษาที่ตกลงแล้ว

YouTube ต้องใช้ environment variable `YOUTUBE_API_KEY` ในเครื่อง ห้ามเขียน key ใน config หรือ notebook
ไม่จำเป็นต้องใช้ API key สำหรับคำสั่ง `run`, `report` และ sample

```powershell
.\.venv\Scripts\python.exe -m rov_mlbb.cli collect --config config/collect.example.json
# หรือทดลองทีละแหล่ง
.\.venv\Scripts\python.exe -m rov_mlbb.cli collect --config config/pilot.json --sources trends playstore
```

คำสั่งคืน path ของ `pipeline_config.json` และ `collection_status.json` ให้ตรวจ coverage ก่อนใช้:

```powershell
.\.venv\Scripts\python.exe -m rov_mlbb.cli run --config data/imports/<batch_id>/pipeline_config.json
```

ตัวเก็บข้อมูลมีเพดาน pagination และ timeout/retry แบบจำกัด หากชนเพดานจะแสดง `partial`
ขยายเพดานเมื่อได้ตรวจจำนวนข้อมูลและข้อจำกัดของผู้ให้บริการแล้ว ไม่เปลี่ยน API key เพื่อหลบ quota

CLI ใช้ certificate store ของระบบผ่าน truststore และยังตรวจ TLS ตามปกติ
การเรียก collectors จาก Python โดยตรงควรตั้งค่าระบบ certificate ใน application entry point ตามเอกสาร truststore

### ข้อมูลเก่าจากเพื่อน / Google Trends CSV

รองรับ CSV หรือ JSON array พร้อม metadata ระบุวันเก็บ เงื่อนไข และ coverage จริง:

```powershell
.\.venv\Scripts\python.exe -m rov_mlbb.cli import --input data/imports/export.csv --metadata data/imports/export.metadata.json --output data/imports/packet.json
```

ดู [คู่มือนำเข้า](docs/importing_data.md) ห้ามใส่วันนำเข้าแทนวันเก็บยอดวิวเดิม
ข้อมูลเก่าที่ไม่ทราบวันเก็บใช้ historical adapter schema v2 พร้อมหลักฐานและข้อจำกัด โดยไม่ปลอมวันเก็บ
Trends ที่ไม่ทราบสเกลหรือเป็นการต่อ query แยกยังไม่นำมาใช้เปรียบเทียบข้ามเวลา

## Prefect แบบ local

รัน flow หนึ่งครั้ง (สร้าง temporary local server และปิดเมื่อจบ):

```powershell
$env:PREFECT_HOME = Join-Path (Get-Location) '.prefect'
$env:PREFECT_SERVER_ANALYTICS_ENABLED = 'false'
.\.venv\Scripts\python.exe -m rov_mlbb.flows --config config/sample.json
```

ตั้งเวลาแบบ local โดยเปิด PowerShell สองหน้าต่างด้วย environment เดียวกัน:

```powershell
# หน้าต่างที่ 1
$env:PREFECT_HOME = Join-Path (Get-Location) '.prefect'
$env:PREFECT_SERVER_ANALYTICS_ENABLED = 'false'
.\.venv\Scripts\prefect.exe server start --host 127.0.0.1

# หน้าต่างที่ 2
$env:PREFECT_HOME = Join-Path (Get-Location) '.prefect'
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:PREFECT_SERVER_ANALYTICS_ENABLED = 'false'
.\.venv\Scripts\python.exe -m rov_mlbb.flows --config config/sample.json --serve --interval 300
```

เครื่องต้องเปิดและ process ต้องทำงานอยู่ จึงจะรันตามเวลาได้ `Ctrl+C` ปิด serve และหยุด schedule ตามค่าที่กำหนด
เพิ่ม `--refresh` เพื่อเก็บข้อมูลจริงก่อนประมวลผล โดยใช้ collector config แทน pipeline config
ช่วงวันที่ใน config เป็นค่าตายตัว การอัปเดตช่วงศึกษาเป็นงานที่ต้องกำหนดโดยชัดแจ้ง และ Trends แต่ละ query window มีสเกลของตนเอง

ตรวจสองรอบที่เริ่มจาก timer จริงแบบแยกฐานข้อมูลและปิด process เมื่อจบ (ใช้เวลาประมาณ 2–5 นาที):

```powershell
.\.venv\Scripts\python.exe scripts/verify_schedule.py
```

สคริปต์นี้ใช้ sample และ localhost เท่านั้น ไม่เรียกแหล่งข้อมูลภายนอก ผลอยู่ใน `artifacts/verification/schedule-*/evidence.json`

## การตีความข้อมูล

- Google Trends ใช้คำค้นสองคำในคำขอเดียว ไม่ต่อกราฟจากช่วงที่ normalize แยกกัน
- ถ้าต้นทางเป็นรายสัปดาห์ ใช้วันทับซ้อนถ่วงน้ำหนักรายเดือน เป็นการประมาณจากช่วงเวลา ไม่ได้กู้ข้อมูลรายวันจริง
- ยอดวิวเป็นยอดสะสม ณ เวลาเก็บของวิดีโอที่เผยแพร่ในเดือนนั้น ไม่ใช่ยอดวิวที่เกิดในเดือนนั้น
- คะแนนรีวิวแสดงคู่กับจำนวนรีวิว และไม่อ้างว่า request ภาษาไทยยืนยันสัญชาติผู้เขียน
- ไม่สรุปจำนวนผู้เล่น การย้ายเกม หรือสาเหตุของความเปลี่ยนแปลงจากข้อมูลนี้โดยตรง

## เอกสารประกอบพอร์ต

- [ขอบเขตและสถานะข้อมูล](docs/project_scope.md)
- [รายงานฉบับส่งมอบ](docs/final_report.md)
- [ผลวิเคราะห์ช่วงศึกษาเดิม](docs/historical_findings.md)
- [บัญชีข้อมูลและ snapshot](docs/data_inventory.md)
- [เชื่อม Firestore กับ notebook เดิม](docs/firestore_notebook_mapping.md)
- [สถาปัตยกรรม](docs/architecture.md)
- [Data dictionary](docs/data_dictionary.md)
- [คู่มือนำเข้าข้อมูล](docs/importing_data.md)
- [แผนจนจบงาน](docs/project_completion_plan.md)
- [สถานะงานล่าสุด](docs/work_status.md)
- [ผลข้อมูลจริงรอบทดลองและข้อจำกัด](docs/pilot_findings.md)
- [หลักฐานทดสอบและตั้งเวลา](docs/verification.md)
- [บทสาธิต](docs/demo_script.md)
- [ตรวจ notebook ก่อนย้ายฐานข้อมูล](docs/legacy_notebook_review.md)

Notebook เดิมและเอกสารเรียนเป็นแหล่งอ้างอิงในเครื่อง ไม่รวมใน repository สำหรับพอร์ต เช่นเดียวกับ raw imports และ credentials ผล aggregate ที่เลือกไว้แนบให้ตรวจรายงานได้ ส่วนการรันข้อมูลจริงใหม่ต้องนำเข้า snapshot ที่ได้รับสิทธิ์ตามคู่มือ
ต้นทางเป็นงานกลุ่ม ส่วนระบบนี้เป็นการต่อยอดด้วยความช่วยเหลือของ coding assistant ระบุหน้าที่ของแต่ละคนตามที่ทำจริงเมื่อนำเสนอ ผู้ใช้อนุญาตให้นำชุดส่งมอบไปยัง natchapolpangpol/Rov_VS_Mlbb แล้ว
