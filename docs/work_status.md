# สถานะงานล่าสุด

อัปเดต 2 พฤศจิกายน 2026 — ระบบ รายงาน และชุดส่งมอบผ่านการตรวจแล้ว ปลายทาง GitHub: natchapolpangpol/Rov_VS_Mlbb

## เสร็จแล้ว

- รักษา notebook เดิม อ่านเอกสารเรียน และเทียบที่มาข้อมูลจากโค้ดกับ Firestore
- Export 7 collections ครบ 27,130 documents แบบอ่านอย่างเดียว จำนวนตรงกับ output เดิม
- ใช้ SQLite พร้อม raw/clean/rejected/summary, hashes, quality gate, deduplication และประวัติแต่ละ run
- ข้อมูลจริงที่ผ่านการตรวจ: YouTube 5,826 คลิป รีวิว 16,288 รายการ Trends ใหม่ 124 intervals
- ช่วงศึกษา 1 มกราคม 2025–10 มีนาคม 2026 ได้ 30 เกม–เดือน สถานะ partial ตามข้อจำกัดข้อมูล
- ตรวจสมมติฐาน UTC/เวลาไทย และผลจากองค์ประกอบช่อง YouTube ที่ต่างกันระหว่างช่วง
- รันข้อมูลจริงซ้ำ observations คง 22,580 รวม pilot แยก 342 รายการ
- Prefect timer สองรอบจริงสำเร็จ ปิด process ที่ใช้ตรวจแล้ว
- ทดสอบ 45 กรณีผ่านใน environment แยกจาก lock file; notebook จริงรันครบ 5 code cells
- มี README, dictionary, architecture, final report, findings, inventory และบทสาธิต
- ทดลอง demo จากโฟลเดอร์ส่งมอบที่ย้ายตำแหน่งแล้วสำเร็จ และตรวจรายการไฟล์/credential patterns ก่อน commit

## เปิดดูผลงาน

[รายงาน](final_report.md) · [ผลข้อมูลจริง](historical_findings.md) · [หลักฐานทดสอบ](verification.md) · [บทสาธิต](demo_script.md) · [บัญชีข้อมูล](data_inventory.md)

## การส่งมอบ

ทำงาน solo ไม่ใช้ sub-agent ผู้ใช้อนุญาตอัปโหลดไป https://github.com/natchapolpangpol/Rov_VS_Mlbb แล้ว
ปลายทางตรวจว่าเป็น repository ว่าง ส่ง source, sample, เอกสารและผล aggregate ที่ตรวจแล้ว โดยไม่ส่ง raw ของทีม credentials notebook ต้นฉบับ หรือเอกสารเรียน

ยังไม่มี rubric/แม่แบบมหาวิทยาลัยเพิ่มเติม จัดส่ง Markdown พร้อมกราฟ notebook และบทสาธิต
API key ใหม่จำเป็นเฉพาะเมื่อเก็บ YouTube รอบใหม่ ไม่ขวางการใช้ snapshot ที่นำเข้าแล้ว

## ข้อจำกัด

วันเก็บยอดวิวเดิมไม่ทราบ เขตเวลารีวิวเป็นสมมติฐาน วิธีเลือกรีวิวสองเกมต่างกัน และเดือนต้น/ท้ายมีข้อมูลไม่เต็มเดือน
เก็บข้อจำกัดไว้ใน metadata และรายงาน ไม่อ้างจำนวนผู้เล่น การย้ายเกม หรือ causal effect
