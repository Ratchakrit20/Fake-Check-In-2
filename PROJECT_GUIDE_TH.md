# คู่มือโครงการ Image Relation Inspector

## 1. โครงการนี้ทำอะไร

ระบบนี้ช่วยตรวจว่าภาพสองภาพหรือภาพจำนวนมากมีความสัมพันธ์กันหรือไม่ เช่น ไฟล์เดียวกัน ภาพเดิมที่บีบอัดใหม่ ภาพกลับด้าน ภาพหมุน 90/180/270 องศา ภาพครอปหรือเบลอ ภาพที่ถ่ายซ้ำผ่านหน้าจอ และการนำบุคคลหรือส่วนของภาพเดิมไปเปลี่ยนฉาก

ระบบไม่ใช้คะแนนจากโมเดลเดียวตัดสิน แต่รวมหลักฐานหลายชนิด แล้วเก็บเหตุผลและค่าที่ตรวจพบไว้ให้ตรวจสอบย้อนหลังได้ ผลลัพธ์หลักมี 3 ระดับคือ:

- `เข้าข่ายใช้ภาพเดิม` มีหลักฐานเพียงพอ
- `ควรตรวจสอบโดยเจ้าหน้าที่` พบสัญญาณ แต่ไม่ควรตัดสินอัตโนมัติ
- `ยังไม่เข้าข่ายใช้ภาพเดิม` หลักฐานไม่พอ

หน้าเว็บรองรับการเปรียบเทียบสองภาพ การอัปโหลดหลายภาพ การติดตามความคืบหน้า และการดูกลุ่มภาพที่เชื่อมโยงกัน

## 2. ลำดับการวิเคราะห์

```text
รับไฟล์และตรวจความปลอดภัย
        |
        v
SHA-256 ตรวจไฟล์ตรงกันทุกไบต์
        |
        v
pHash ตรวจภาพโดยรวม/ภาพกลับด้าน/ภาพหมุน 90, 180 และ 270 องศา
        |
        v
SSCD สร้างลายนิ้วมือสำหรับตรวจสำเนาเป็น batch (GPU เมื่อใช้ได้)
        |
        v
FAISS เลือกเฉพาะภาพใกล้เคียง Top-K
        |
        v
SIFT จับรายละเอียดเฉพาะจุด + RANSAC ยืนยันตำแหน่ง (CPU หลาย worker)
        |
        v
โมเดล mask แยกอวัยวะ (GPU เมื่อใช้ได้)
        |
        v
รวมคะแนน/จำแนกผล -> บันทึก SQLite -> สร้างกลุ่มแบบเชื่อมโยงทางอ้อม
```

การจัดกลุ่มความสัมพันธ์ใช้ connected components เช่น 1 เชื่อม 2, 1 เชื่อม 3 และ 3 เชื่อม 4 ระบบจะรวม 1, 2, 3, 4 เป็นกลุ่มย่อยเดียว แม้ 1 จะไม่เชื่อมกับ 4 โดยตรง

หน้า Groups มีอีกชั้นสำหรับจัดระเบียบการแสดงผล: หากชื่อไฟล์มี `home_<เลข 10 หลัก>` หรือ `splitter_<เลข 10 หลัก>` กลุ่มย่อยที่พบเลขเดียวกันจะถูกรวมไว้ใต้กลุ่มใหญ่เดียวกัน การรวมชั้นนี้ไม่สร้างความสัมพันธ์ใหม่ และรายการกลุ่มด้านซ้ายจะติดหน้าจอพร้อมเลื่อนภายในได้

## 3. การใช้ CPU และ GPU

ไฟล์ `backend/app/core/runtime.py` ตรวจจำนวน logical CPU, ตรวจ CUDA และอ่าน VRAM ตอนเริ่มงาน:

- SSCD ใช้ CUDA เมื่อ PyTorch มองเห็น GPU
- Ultralytics mask ใช้ CUDA อัตโนมัติเมื่อรองรับ
- ขนาด batch เลือกจาก VRAM: VRAM มากใช้ batch ใหญ่ขึ้น; CPU-only ใช้ batch เล็กลง
- SIFT/RANSAC ใช้ thread pool หลาย worker และแบ่งจำนวน OpenCV threads เพื่อไม่ให้แต่ละ workerแย่ง CPU กัน
- FAISS รุ่นในโครงการเป็น `faiss-cpu` จึงทำงานบน CPU
- SQLite เขียนผลเป็นชุด ลดเวลาล็อกฐานข้อมูล
- คู่ A-B และ B-A ถูก normalize และคำนวณเพียงครั้งเดียวต่อรอบ

ค่าศูนย์ใน `embedding.batch_size`, `performance.cpu_workers` และ `performance.opencv_threads` หมายถึงเลือกอัตโนมัติ หากเครื่องมีข้อจำกัดสามารถกำหนดค่าเองได้

## 4. โครงสร้างโครงการ

```text
fake ckeck in/
├─ backend/app/
│  ├─ main.py                     เริ่ม FastAPI, เตรียมฐานข้อมูล, กู้คืนงานค้าง และเสิร์ฟหน้าเว็บ
│  ├─ api/
│  │  ├─ router.py                รวม API ทุกหมวดภายใต้ /api/v1
│  │  └─ routes/
│  │     ├─ compare.py            รับภาพ 2 ภาพและส่งผลเปรียบเทียบ
│  │     ├─ batches.py            รับหลายไฟล์และสร้างงานวิเคราะห์ใหม่/วิเคราะห์ซ้ำ
│  │     ├─ jobs.py               อ่านสถานะและความคืบหน้าของงาน
│  │     ├─ groups.py             สร้างผลกลุ่มภาพสัมพันธ์
│  │     ├─ images.py             บันทึก อ่าน metadata และส่งเนื้อไฟล์ภาพ
│  │     └─ dashboard.py          สรุปจำนวนภาพ งาน และความสัมพันธ์
│  ├─ core/
│  │  ├─ config.py                อ่านและตรวจสอบ config YAML/environment variables
│  │  ├─ runtime.py               ตรวจ CPU, CUDA, VRAM และเลือก worker/batch
│  │  ├─ exceptions.py            exception ของระบบ
│  │  └─ logging.py               ตั้งค่า log
│  ├─ db/
│  │  ├─ models.py                ตาราง images, embeddings, pairwise results และ jobs
│  │  └─ session.py               SQLAlchemy async, SQLite WAL และ connection settings
│  ├─ detectors/
│  │  ├─ sha256_detector.py       ตรวจไฟล์ที่เหมือนกันทุกไบต์
│  │  ├─ perceptual_hash_detector.py สร้าง pHash สำหรับภาพปกติ กลับด้าน และช่วยเลือกมุมหมุน
│  │  ├─ sift_matcher.py          จับ keypoints และจับคู่รายละเอียดภาพ
│  │  ├─ ransac_verifier.py       กรองคู่จุดผิดและยืนยันความสัมพันธ์เชิงเรขาคณิต
│  │  ├─ flip_detector.py         สนับสนุนการตรวจภาพกลับด้าน
│  │  ├─ image_quality_detector.py วัดความเบลอ
│  │  └─ body_part_detector.py    ใช้ organ.pt แยกและตรวจจุดบนอวัยวะ
│  ├─ embeddings/
│  │  └─ sscd.py                  โหลด SSCD, เลือกอุปกรณ์ และสร้าง embedding แบบ batch
│  ├─ vector_store/
│  │  └─ faiss_store.py           เก็บ/ค้นเวกเตอร์ใกล้เคียงและบันทึก index
│  ├─ services/
│  │  ├─ pair_analysis_service.py รวม detector เพื่อวิเคราะห์ภาพหนึ่งคู่
│  │  ├─ relationship_scorer.py   รวมหลักฐานและกำหนดคำตัดสิน
│  │  ├─ batch_analysis_service.py จัด embedding, candidate, parallel verification และบันทึกผล
│  │  ├─ relationship_graph_service.py รวมกลุ่มด้วย connected components
│  │  ├─ source_filename.py       อ่านเลข 10 หลักหลัง home_/splitter_
│  │  └─ image_validation_service.py ตรวจชนิด ขนาด และความถูกต้องของไฟล์
│  ├─ storage/local_storage.py    จัดเก็บภาพลง data/images
│  └─ domain/                     enum, schema และ interface กลาง
├─ frontend/src/
│  ├─ main.tsx                    จุดเริ่ม React และ CSS
│  ├─ App.tsx                     route ของหน้าเว็บ
│  ├─ api/client.ts               เรียก FastAPI ด้วย fetch/FormData
│  ├─ components/                 layout และตัวเลือกไฟล์
│  └─ pages/                      ภาพรวม, เปรียบเทียบ, หลายภาพ และกลุ่มภาพ
├─ config/default.yaml            ค่าระบบ เกณฑ์ และ performance
├─ data/images/                   ไฟล์ภาพที่ระบบจัดเก็บ
├─ data/app.db                    ฐานข้อมูล SQLite
├─ data/faiss/                    FAISS index และรายการ image id
├─ data/models/                   SSCD และโมเดลแยกอวัยวะ
├─ tests/                         unit tests
├─ environment.yml               Conda environment แบบพกพา
├─ THIRD_PARTY_LICENSES.md        สรุป license ของ dependency หลัก
└─ README.md                      วิธีเริ่มใช้งานแบบย่อ
```

## 5. ติดตั้งบนเครื่องใหม่ (Windows)

### 5.1 สิ่งที่ต้องเตรียม

- Miniconda หรือ Anaconda
- Git หรือคัดลอกโฟลเดอร์โครงการมาทั้งชุด
- พื้นที่ว่างสำหรับภาพ ฐานข้อมูล และ model cache
- ถ้าจะใช้ NVIDIA GPU: ติดตั้ง NVIDIA Driver รุ่นที่รองรับก่อน

### 5.2 สร้าง Conda environment

เปิด PowerShell ที่โฟลเดอร์โครงการ:

```powershell
conda env create -f environment.yml
conda activate fake-check-in
```

หากสร้าง environment ไว้แล้ว:

```powershell
conda activate fake-check-in
python -m pip install -e ".[dev]"
```

### 5.3 เปิดใช้ NVIDIA GPU

คำสั่งติดตั้ง PyTorch CUDA เปลี่ยนตามรุ่น driver/PyTorch จึงควรเลือกคำสั่งล่าสุดจาก https://pytorch.org/get-started/locally/ โดยเลือก Windows, Pip, Python และ CUDA ที่เหมาะกับเครื่อง แล้วรันภายใน environment `fake-check-in`

ตรวจหลังติดตั้ง:

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

ต้องได้ `True` จึงจะใช้ GPU หากได้ `False` ระบบยังรันได้ แต่ใช้ CPU และช้ากว่า

### 5.4 โมเดล

- วางโมเดลอวัยวะที่ `data/models/human_mask/organ.pt`
- SSCD จะดาวน์โหลดครั้งแรกไปที่ `data/models/sscd_disc_mixup.torchscript.pt`
- หากเครื่องใหม่ไม่มีอินเทอร์เน็ต ให้คัดลอกทั้ง `data/models` จากเครื่องเดิม

### 5.5 สร้างหน้าเว็บ

ต้องทำครั้งแรก หรือเมื่อแก้ `frontend/src`:

```powershell
cd frontend
npm install
npm run build
cd ..
```

หลัง build แล้ว ผู้ใช้งานรันด้วย Python เพียงคำสั่งเดียว

### 5.6 เริ่มระบบ

```powershell
conda activate fake-check-in
python -m backend.app.main
```

เปิด http://127.0.0.1:8000 และ API docs ที่ http://127.0.0.1:8000/docs

## 6. การย้ายข้อมูลจากเครื่องเดิม

ปิด Backend ก่อนคัดลอกเพื่อไม่ให้ฐานข้อมูลกำลังเขียน แล้วคัดลอกรายการต่อไปนี้โดยรักษา path ภายในโครงการ:

- `data/app.db` ข้อมูลภาพ งาน และผลความสัมพันธ์
- `data/images` ไฟล์ภาพทั้งหมด
- `data/faiss` index สำหรับค้นหา candidate
- `data/models` model cache และ `organ.pt`
- `config/default.yaml` หากมีการปรับเกณฑ์

ระบบมีตัวค้นหาไฟล์สำรองจาก `image_id` ใต้ `data/images` จึงรองรับการย้ายโครงการไป path ใหม่ แม้ `storage_path` เดิมใน SQLite เป็น absolute path โดยต้องคัดลอก `data/app.db` และ `data/images` มาด้วยกัน ห้ามเปลี่ยนชื่อไฟล์ภายใน `data/images`

## 7. วิธีใช้งาน

### เปรียบเทียบ 2 ภาพ

เข้าเมนู “เปรียบเทียบภาพ” เลือกภาพ A/B แล้วกดเริ่มวิเคราะห์ หน้าผลจะแสดงคำตัดสิน เหตุผล เทคโนโลยีที่ผ่านเกณฑ์ และปุ่มเปิดภาพเทียบ

### วิเคราะห์หลายภาพ

เข้าเมนู “วิเคราะห์หลายภาพ” เลือกหลายไฟล์หรือโฟลเดอร์ แล้วเริ่มวิเคราะห์ สามารถเปลี่ยนหน้า/รีเฟรชได้ งานไม่เริ่มใหม่และหน้าเว็บจะเชื่อมกลับไปยังงานเดิม

### วิเคราะห์ข้อมูลเดิมใหม่

ใช้หลังเปลี่ยนเกณฑ์ ระบบจะคำนวณคู่ที่เป็น candidate ใหม่และอัปเดตผลเดิม โดยไม่ลบไฟล์ภาพต้นฉบับ

### ดูกลุ่ม

เข้าเมนู “กลุ่มภาพสัมพันธ์” รายการด้านซ้ายเป็นกลุ่มใหญ่ตามเลขงานเมื่อชื่อไฟล์มีรูปแบบที่รองรับ ส่วนด้านขวาแสดงกลุ่มย่อยจากเส้นเชื่อมที่ผ่านคำตัดสิน ไม่จำเป็นต้องให้ทุกภาพสัมพันธ์กันโดยตรง กดแถวความสัมพันธ์เพื่อเปิดภาพคู่นั้นในหน้าเปรียบเทียบได้

ชื่อไฟล์ที่ไม่มี `home_<เลข 10 หลัก>` หรือ `splitter_<เลข 10 หลัก>` ยังวิเคราะห์และจัดกลุ่มตามความสัมพันธ์ตามปกติ หากเพิ่มภาพในภายหลัง ระบบยังค้น candidate จากภาพเดิมในคลังได้

## 8. การปรับประสิทธิภาพ

ค่าหลักอยู่ใน `config/default.yaml`:

- `embedding.batch_size: 0` เลือก batch ตาม VRAM; กำหนดเลขเองเมื่อพบ GPU out-of-memory
- `performance.cpu_workers: 0` เลือกตาม CPU; เครื่อง RAM น้อยให้ตั้ง 2–4
- `performance.opencv_threads: 0` แบ่ง thread อัตโนมัติ
- `performance.pair_chunk_size` จำนวนคู่ที่ส่งเข้า thread pool พร้อมกัน
- `performance.candidate_min_similarity` ตัด candidate ที่ SSCD ต่ำมากก่อนใช้ SIFT
- `vector_search.top_k` จำนวนเพื่อนบ้านต่อภาพ ค่าสูงลดโอกาสตกหล่นแต่ใช้เวลามากขึ้น
- คู่ที่มีเลข 10 หลักหลัง `home_`/`splitter_` ตรงกันจะไม่ส่งเข้า SIFT เพราะชื่อระบุแหล่งเดียวกันอยู่แล้ว ส่วนภาพหมุนมี pHash fallback เพื่อไม่ให้หลุดเพราะ SSCD/FAISS จัดอันดับต่ำ
- `relationship.background_replaced_min_embedding_similarity` กันลายซ้ำหรือจุดหลอกที่ทำให้คนละภาพถูกตีความว่าเปลี่ยนฉาก
- `relationship.blur_variance_threshold` ค่ายิ่งสูงยิ่งยอมรับภาพที่ดูเบลอมากขึ้น; ใช้ร่วมกับเรขาคณิตและ SSCD ไม่ได้ตัดสินเดี่ยว ๆ
- `relationship.blurred_crop_max_phash_distance` ระยะ pHash สูงสุดสำหรับภาพเบลอ/ครอป ซึ่งอนุโลมมากกว่าภาพปกติ
- `sift.max_dimension` ลดค่านี้ทำให้เร็วขึ้นแต่จุดละเอียดอาจลดลง
- `body_parts.image_size` ลดค่านี้เมื่อ VRAM น้อย

สำหรับหลายพันภาพไม่ควรเปรียบเทียบทุกคู่ ระบบจึงใช้ FAISS Top-K และตัวกรอง SSCD ก่อนส่งเข้า detector ที่หนักกว่า

## 9. ตรวจสอบและแก้ปัญหา

```powershell
python -m pytest -q
python -m ruff check backend tests
```

- พอร์ต 8000 ถูกใช้: มี Backend อีกตัวทำงานอยู่ ให้เปิดเว็บเดิมหรือปิดโปรเซสนั้นก่อน
- `torch.cuda.is_available()` เป็น False: ติดตั้ง PyTorch CUDA ไม่ตรงกับ driver หรือเป็น CPU wheel
- SSCD ครั้งแรกช้า: กำลังดาวน์โหลด/โหลดโมเดล TorchScript; ครั้งต่อไปใช้ไฟล์ที่ cache ไว้
- `xFormers is not available`: เป็นคำเตือนเรื่อง optimization ไม่ทำให้ผลผิด แต่ inference อาจช้ากว่า
- งานดูค้างที่ภาพหนึ่ง: ภาพหนึ่งอาจมี candidate หลายคู่ ความคืบหน้าปัจจุบันนับภาพที่ตรวจเสร็จ
- CUDA out-of-memory: ลด `embedding.batch_size`, `body_parts.image_size` หรือ `performance.pair_chunk_size`

## 10. ข้อมูลและความปลอดภัย

ระบบทำงานในเครื่อง ไม่เรียก paid API ไฟล์ภาพอยู่ใต้ `data/images` และผลอยู่ใน `data/app.db` ควรจำกัดสิทธิ์เข้าถึงและสำรองข้อมูลก่อนปรับระบบใหญ่ รายการ license อยู่ใน `THIRD_PARTY_LICENSES.md`; Ultralytics เป็น AGPL-3.0 และควรให้ฝ่ายกฎหมายตรวจรูปแบบ deployment เชิงพาณิชย์ หรือเปลี่ยน inference เป็น ONNX Runtime หากข้อกำหนดองค์กรไม่เหมาะสม
