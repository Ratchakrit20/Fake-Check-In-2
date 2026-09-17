# การนำระบบขึ้น Production

เอกสารนี้อธิบายรูปแบบ Production ที่แนะนำสำหรับ Image Relation Inspector โดยแยกหน้าเว็บ/API ออกจากงาน AI ที่ใช้ CPU และ GPU หนัก

## สถานะปัจจุบัน

หน้า React ทำหน้าที่รับไฟล์ แสดงสถานะ และแสดงผลเท่านั้น การวิเคราะห์ไม่ได้ทำใน browser

ปัจจุบัน `POST /api/v1/batches` เรียก `run_batch_job` ผ่าน FastAPI `BackgroundTasks` ดังนั้นงาน SSCD, FAISS, SIFT, RANSAC, YOLO26 และโมเดลอวัยวะยังทำงานในเครื่องและโปรเซสเดียวกับ API แม้โปรเจกต์จะมี Celery worker และ Redis แล้วก็ตาม Celery ปัจจุบันมีเพียง health-check และยังไม่ได้รับงานวิเคราะห์จริง

โครงสร้างปัจจุบันเหมาะกับการพัฒนาและใช้งานในเครื่องเดียว แต่ยังไม่ควรนำ API และ AI ไปแยก VM จนกว่าจะเชื่อม batch job เข้าคิวงานแบบถาวร

## สถาปัตยกรรมที่แนะนำ

```text
ผู้ใช้งาน
   │ HTTPS
   ▼
Reverse proxy / Load balancer
   │
   ├── React static files
   │
   ▼
FastAPI (Web/API VM)
   ├── ตรวจชนิดและขนาดไฟล์
   ├── บันทึกภาพลง Object Storage
   ├── สร้าง job ใน PostgreSQL
   └── ส่ง job_id เข้า Redis
                     │
                     ▼
              Celery AI Worker VM
              ├── SSCD + GPU
              ├── FAISS candidates
              ├── SIFT + RANSAC
              ├── body-part model
              └── บันทึกผลลง PostgreSQL

React ──poll job status──► FastAPI ──read──► PostgreSQL
```

บริการทั้งหมดอยู่ repository เดียวกันได้ แต่ต้องรันเป็นคนละ process หรือคนละ VM ตามหน้าที่

## หน้าที่ของแต่ละบริการ

### Web/API

- ให้บริการ React และ REST API
- ตรวจขนาด MIME และความสมบูรณ์ของภาพ
- สร้างสถานะงานและส่ง `job_id` เข้าคิว
- อ่านสถานะและผลจาก PostgreSQL
- ห้ามโหลดโมเดลหรือประมวลผลภาพหนักใน API process

### AI Worker

- โหลด SSCD, FAISS และโมเดลอวัยวะครั้งเดียวต่อ worker
- ดึงภาพจาก Object Storage ด้วย `image_id`
- ประมวลผลและบันทึกหลักฐานรายคู่
- อัปเดต progress และ error ลง PostgreSQL
- รับงานใหม่ผ่าน Redis/Celery เท่านั้น

### PostgreSQL

- เก็บรายการภาพ งานวิเคราะห์ embeddings ความสัมพันธ์ และสถานะ
- เปิดให้เข้าถึงเฉพาะ API/worker network
- สำรองข้อมูลและทดสอบ restore เป็นประจำ

### Redis

- ใช้เป็น message broker ไม่ใช่ฐานข้อมูลถาวร
- ห้ามเปิด port สู่ public internet
- เปิด authentication และ persistence ตามระดับความสำคัญของคิว

### Object Storage

- Production ควรใช้ S3-compatible storage หรือ MinIO แทน local disk
- API และ AI worker ต้องอ่านไฟล์เดียวกันได้โดยไม่แชร์ path ของระบบปฏิบัติการ
- เปิด encryption, lifecycle และสิทธิ์แบบ private

## สเปกเริ่มต้น

| บริการ | vCPU | RAM | GPU | หมายเหตุ |
|---|---:|---:|---|---|
| Web/API | 2 | 4 GB | ไม่ใช้ | เพียงพอสำหรับรับไฟล์และแสดงผล |
| PostgreSQL + Redis | 2 | 4–8 GB | ไม่ใช้ | แยกเครื่องเมื่อปริมาณงานเพิ่ม |
| AI Worker ขนาดเล็ก | 4 | 16 GB | VRAM 8 GB | เหมาะกับงาน 40–100 ภาพต่อชุด |
| AI Worker แนะนำ | 8 | 16–32 GB | VRAM 8–12 GB | เหมาะกับหลายร้อยถึงหลายพันภาพ |
| AI Worker แบบ CPU-only | 12–16 | 16–32 GB | ไม่ใช้ | ทำงานได้แต่ช้ากว่าอย่างมาก |

เริ่ม Production ด้วย Web/API 2 vCPU และ AI Worker 8 vCPU พร้อม GPU แล้ววัด queue latency, เวลาเฉลี่ยต่อภาพ, RAM และ VRAM ก่อนเพิ่ม worker

## งานที่ต้องแก้ก่อนแยก VM

1. สร้าง Celery task เช่น `analysis.process_batch(job_id, force=False)` ซึ่งเรียก `process_batch_job`
2. เปลี่ยน batch routes จาก `BackgroundTasks` เป็น `celery_app.send_task` หรือ `delay`
3. เลิก recovery งานค้างด้วย local thread ใน API และให้ Celery retry/ack เป็นผู้รับผิดชอบ
4. เปลี่ยน `LocalImageStorage` เป็น S3/MinIO adapter
5. ย้าย FAISS ออกจากไฟล์ local ที่เขียนร่วมกัน หรือกำหนดให้มี index-owner เพียง worker เดียว
6. เพิ่ม distributed lock/idempotency เพื่อป้องกัน job เดียวถูกรันซ้ำ
7. แยก image ของ API ออกจาก AI worker เพื่อไม่ติดตั้ง PyTorch/CUDA ใน Web VM
8. เพิ่ม health/readiness checks แยก API, database, Redis, storage, GPU และ model

ห้ามเพียงนำ API กับ worker ไปไว้คนละ VM โดยไม่แก้ storage และ queue เพราะ worker จะมองไม่เห็นไฟล์ local ของ API และงานปัจจุบันยังคงรันใน API อยู่

## การควบคุมจำนวน worker

บน AI VM ให้เริ่ม Celery concurrency ต่ำเพื่อไม่ให้โมเดล GPU ถูกโหลดซ้ำจน VRAM เต็ม โดยทั่วไปใช้หนึ่ง Celery process ต่อ GPU และให้ระบบภายในจัด parallel SIFT ตามจำนวน vCPU

ตัวอย่างแนวทาง:

```text
1 GPU VM  → 1 Celery process → 1 job หนักพร้อมกัน
2 GPU VM  → แยก queue/worker ตาม GPU
```

กำหนด `PERFORMANCE__CPU_WORKERS` เองใน container เพราะ `os.cpu_count()` อาจเห็นจำนวน CPU ของ host มากกว่า CPU quota ของ container

## ความปลอดภัยขั้นต่ำ

- เปิดระบบผ่าน HTTPS เท่านั้น
- เพิ่ม authentication และ role-based access ก่อนเปิดให้เครื่องอื่นเข้าถึง
- จำกัด request และ file size ทั้ง reverse proxy และ FastAPI
- เก็บ PostgreSQL, Redis และ Object Storage ใน private network
- ห้ามใช้รหัสผ่านตัวอย่าง และเก็บ secrets ใน secret manager
- ตรวจ SHA-256 ของไฟล์โมเดลก่อนโหลด
- ไม่บันทึกภาพหรือข้อมูลส่วนบุคคลลง application log
- กำหนด retention และสิทธิ์การเข้าถึงภาพพนักงาน
- สแกน dependencies และ container images ใน CI
- สำรอง PostgreSQL/Object Storage และทดสอบกู้คืน

ระบบปัจจุบัน bind ที่ `127.0.0.1` เหมาะกับการใช้งานในเครื่อง หากเปิด public network โดยไม่มี authentication ถือว่ายังไม่พร้อม Production

## ตัวแปร Environment สำคัญ

```dotenv
APP__RELOAD=false
DATABASE__URL=postgresql+asyncpg://USER:PASSWORD@postgres:5432/image_relation
JOBS__BROKER_URL=redis://:PASSWORD@redis:6379/0
JOBS__RESULT_BACKEND=redis://:PASSWORD@redis:6379/1
EMBEDDING__DEVICE=cuda
PERFORMANCE__CPU_WORKERS=4
VECTOR_SEARCH__TOP_K=30
```

ไม่ควรเก็บค่าจริงไว้ใน Git

## ลำดับการ Deploy

1. สร้าง PostgreSQL, Redis และ Object Storage ใน private network
2. รัน database migration
3. Deploy AI worker และตรวจว่าโหลด CUDA/โมเดลได้
4. Deploy API โดยปิด reload และไม่โหลดโมเดล AI
5. Deploy React ผ่าน reverse proxy/CDN
6. ส่งภาพทดสอบและตรวจเส้นทาง upload → queue → worker → result
7. ทดสอบ exact duplicate, ภาพแก้ไข, ภาพเบลอ, ภาพกลับด้าน, ภาพหมุน 90/180/270 องศา และสถานที่เดิม
8. ทดสอบ worker crash, retry, duplicate delivery และ database restore
9. เปิด monitoring/alert ก่อนรับงานจริง

## Metrics ที่ควรติดตาม

- จำนวน job ที่ queued/running/failed
- เวลารอคิวและเวลาประมวลผลต่อภาพ
- จำนวน candidate และคู่ที่ตรวจต่อ job
- CPU, RAM, GPU utilization และ VRAM
- อัตรา upload/error/retry
- PostgreSQL connection/latency และ Redis queue depth
- จำนวนผล reused/review/not-reused และผลที่เจ้าหน้าที่แก้คำตัดสิน

## สรุป

ไม่จำเป็นต้องแยก repository แต่ต้องแยก runtime responsibility ให้ชัดเจน: Web/API รับและแสดงผล ส่วน AI Worker ประมวลผลผ่าน durable queue และใช้ storage/database ร่วมกัน ก่อนทำส่วนนี้เสร็จให้ถือว่าระบบเป็น single-machine deployment

การจัดกลุ่มใหญ่จากเลข 10 หลักในชื่อไฟล์เป็น presentation logic ของ API/UI ไม่ใช่หลักฐานเชิงภาพ ขณะที่การข้ามคู่เลขเดียวกันก่อน SIFT เป็น optimization ตามกติกาธุรกิจ จึงต้องคงรูปแบบชื่อไฟล์และ regression test นี้ไว้เมื่อแยก worker ไป Production
