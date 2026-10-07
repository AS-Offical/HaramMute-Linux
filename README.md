# HaramMute-Linux

## العربية

### نبذة عن المشروع

**HaramMute-Linux** هو خادم محلي لمعالجة الصوت يعمل على Linux ومخصص للتكامل مع إضافة HaramMute للمتصفح.

المشروع عبارة عن إعادة بناء محلية لأجزاء المعالجة الموجودة في تطبيق Windows الأصلي، والتي كانت متوفرة فقط على شكل ملفات Windows مترجمة. تمت إعادة بناء هذه الأجزاء باستخدام Python مع الحفاظ على توافق واجهة الـ API مع خدمة FastAPI الأصلية.

هذا المشروع غير رسمي ومستقل، ولا يمثل أو يتبع مطوري HaramMute الأصليين.

### البنية

```text
Browser Extension
       |
       | HTTP
       v
uvicorn (127.0.0.1:8765)
       |
       +-- app/main.py
       |     API
       |
       +-- app/jobs.py
       |     JSON-persisted job store
       |
       +-- app/local_processing.py
       |     |
       |     +-- yt-dlp
       |     |     Media download
       |     |
       |     +-- ffmpeg
       |     |     WAV conversion
       |     |     Audio chunk splitting
       |     |     MP3 loudness normalization
       |     |
       |     +-- audio-separator
       |           UVR-MDX-NET-Voc_FT.onnx
       |           CPU / CUDA
       |
       +-- app/pipeline.py
             Processing orchestration
             Progress tracking
```

### تخزين البيانات

يتم تخزين بيانات المشروع محليًا في:

```text
~/.local/share/HaramMute/
```

ويحتوي المجلد على:

```text
jobs/       Job data
models/     Model files
```

أما سجلات الخدمة فتتم إدارتها من خلال `journald` عند تشغيلها باستخدام systemd.

---

## المتطلبات

- Linux
- Python 3.10 إلى 3.12
- `ffmpeg`
- `ffprobe`
- اتصال بالإنترنت لتنزيل الوسائط عند الحاجة

### تسريع المعالجة

يعمل المشروع باستخدام CPU بشكل افتراضي.

يمكن استخدام NVIDIA CUDA تلقائيًا عند تثبيت `onnxruntime-gpu`.

على الأجهزة التي تدعم AVX2، يمكن استخدام إصدارات أحدث من PyTorch وONNX Runtime للحصول على أداء أفضل.

---

## التثبيت

انتقل إلى مجلد المشروع:

```bash
cd ~/harammute-linux
```

أنشئ بيئة Python افتراضية:

```bash
python3 -m venv venv
```

ثبّت نسخة PyTorch المخصصة للـ CPU:

```bash
venv/bin/pip install torch==2.4.1 torchvision==0.19.1 \
    --index-url https://download.pytorch.org/whl/cpu
```

ثم ثبّت باقي المتطلبات:

```bash
venv/bin/pip install -r requirements.txt
```

تحتاج البيئة الافتراضية إلى حوالي 1.5 GB من مساحة التخزين.

---

## التشغيل

### تشغيل الخادم

```bash
./harammute
```

يعمل الخادم افتراضيًا على:

```text
http://127.0.0.1:8765
```

لتشغيله باستخدام منفذ مختلف:

```bash
./harammute --port 8901
```

---

## تشغيل الخادم باستخدام systemd

يمكن تشغيل الخادم كخدمة للمستخدم بحيث يستمر في العمل بعد تسجيل الخروج:

```bash
cp harammute.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now harammute
```

لمتابعة السجلات:

```bash
journalctl --user -u harammute -f
```

---

## Tray Launcher

يمكن تشغيل أيقونة النظام باستخدام:

```bash
python3 tray_launcher.py
```

يتطلب ذلك وجود الحزمة:

```text
gir1.2-ayatanaappindicator3-0.1
```

يعتمد الـ Tray Launcher على AppIndicator / SNI، وبالتالي يمكن استخدامه مع بيئات سطح المكتب التي تدعم هذه التقنية، مثل XFCE وGNOME.

إذا كان الخادم يعمل بالفعل، يعيد الـ Tray Launcher استخدام الخادم الموجود بدلًا من تشغيل نسخة أخرى.

### التشغيل تلقائيًا عند تسجيل الدخول

```bash
mkdir -p ~/.config/autostart
cp harammute-tray.desktop ~/.config/autostart/
```

---

## Desktop Entry

لإضافة HaramMute إلى قائمة التطبيقات:

```bash
mkdir -p ~/.local/share/applications
cp harammute.desktop ~/.local/share/applications/
```

---

## إعداد إضافة المتصفح

يجب أن تشير إضافة المتصفح إلى:

```text
http://127.0.0.1:8765
```

يستخدم الخادم نفس واجهة الـ API المتوقعة من نسخة Windows.

يتم تجاوز مصادقة المهام في الوضع المحلي بشكل مقصود، لأن الخادم يعمل محليًا على جهاز المستخدم.

---

## الإعدادات

يمكن تخصيص سلوك الخادم باستخدام متغيرات البيئة التالية:

| المتغير | القيمة الافتراضية | الوصف |
|---|---|---|
| `HARAMMUTE_DATA_DIR` | `~/.local/share/HaramMute` | المجلد الرئيسي لبيانات المشروع |
| `MUSIC_REMOVER_CHUNK_THRESHOLD` | `120` | الحد الزمني بالثواني قبل تقسيم الصوت إلى أجزاء مدتها 60 ثانية |
| `MUSIC_REMOVER_FORCE_CPU` | غير محدد | تعيينه إلى `true` لإجبار البرنامج على استخدام CPU |
| `MUSIC_REMOVER_MODEL_NAME` | `UVR-MDX-NET-Voc_FT.onnx` | نموذج فصل الصوت المستخدم |
| `MUSIC_REMOVER_ENCODING_QUALITY` | `4` | جودة MP3 بنظام VBR، حيث `0` أعلى جودة و`9` أسرع ترميز |
| `HARAMMUTE_TELEMETRY_ENABLED` | معطل | تفعيل PostHog Telemetry اختياريًا |

مثال:

```bash
MUSIC_REMOVER_FORCE_CPU=true ./harammute
```

---

## التحقق من التشغيل

تم اختبار المشروع بالكامل على جهاز يعمل بمعالج Ivy Bridge بثلاث أنوية وبدون بطاقة رسومية منفصلة.

نتيجة الاختبار:

```text
YouTube video
Duration: 19 seconds

Download:       ~9 seconds
Separation:     ~113 seconds
Total:          ~135 seconds
```

تم التحقق من الملف الناتج باستخدام `ffprobe`:

```text
Duration: 19.1 seconds
Format: MP3
Channels: Stereo
Encoding: VBR
```

---

## ملاحظات تقنية

الملفات التالية هي مصادر upstream الأصلية بدون تعديل:

```text
app/main.py
schemas.py
limits.py
config.py
```

تمت إعادة بناء الوحدات التالية لتوفير المعالجة المحلية على Linux:

```text
app/jobs.py
app/local_processing.py
app/pipeline.py
```

### Telemetry

يتم تعطيل Telemetry افتراضيًا.

يبقى مفتاح PostHog داخل الوحدة الاختيارية الخاصة بالـ Telemetry فقط، ولا يتم إرسال البيانات ما لم يتم تفعيل الميزة.

### نموذج ONNX

النموذج المضمن موجود داخل:

```text
assets/model_cache/audio-separator/
```

ويتم نسخه إلى مجلد بيانات HaramMute عند أول تشغيل.

لا يحتاج النموذج إلى تنزيل إضافي أثناء التشغيل.

---

## إخلاء المسؤولية

HaramMute-Linux مشروع غير رسمي ومستقل.

تم تطوير هذا المشروع بواسطة مستخدم للإضافة الأصلية بهدف تشغيل خدمة HaramMute محليًا على Linux.

جميع الحقوق والملكية المتعلقة بالإضافة الأصلية، والتطبيق الأصلي، والاستضافة الأصلية، وأي مكونات تابعة لها تعود إلى صانعيها ومالكيها الأصليين.

هذا المشروع لا يدعي الملكية أو الرسمية، ولا يمثل أو يتبع مطوري HaramMute الأصليين.

---

# HaramMute-Linux

## English

### About

**HaramMute-Linux** is a local audio-processing server for Linux designed to work with the HaramMute browser extension.

It is a local Python rebuild of the processing components used by the original Windows application. Those components were distributed only as compiled Windows modules.

The Linux implementation maintains API compatibility with the original FastAPI service while providing the processing pipeline natively on Linux.

This is an unofficial and independent project. It is not affiliated with or endorsed by the original HaramMute developers.

---

## Architecture

```text
Browser Extension
       |
       | HTTP
       v
uvicorn (127.0.0.1:8765)
       |
       +-- app/main.py
       |     API
       |
       +-- app/jobs.py
       |     JSON-persisted job store
       |
       +-- app/local_processing.py
       |     |
       |     +-- yt-dlp
       |     |     Media download
       |     |
       |     +-- ffmpeg
       |     |     WAV conversion
       |     |     Audio chunk splitting
       |     |     MP3 loudness normalization
       |     |
       |     +-- audio-separator
       |           UVR-MDX-NET-Voc_FT.onnx
       |           CPU / CUDA
       |
       +-- app/pipeline.py
             Processing orchestration
             Progress tracking
```

### Data Storage

Project data is stored locally in:

```text
~/.local/share/HaramMute/
```

The directory contains:

```text
jobs/       Job data
models/     Model files
```

Service logs are managed through `journald` when the server is running as a systemd user service.

---

## Requirements

- Linux
- Python 3.10–3.12
- `ffmpeg`
- `ffprobe`
- Internet access when media needs to be downloaded

### Hardware Acceleration

CPU processing is supported by default.

NVIDIA CUDA can be used automatically when `onnxruntime-gpu` is installed.

On AVX2-capable systems, newer PyTorch and ONNX Runtime builds may provide better performance.

---

## Installation

Enter the project directory:

```bash
cd ~/harammute-linux
```

Create a Python virtual environment:

```bash
python3 -m venv venv
```

Install the CPU build of PyTorch:

```bash
venv/bin/pip install torch==2.4.1 torchvision==0.19.1 \
    --index-url https://download.pytorch.org/whl/cpu
```

Install the remaining dependencies:

```bash
venv/bin/pip install -r requirements.txt
```

The virtual environment requires approximately 1.5 GB of disk space.

---

## Running

### Start the Server

```bash
./harammute
```

The server runs by default at:

```text
http://127.0.0.1:8765
```

To use a custom port:

```bash
./harammute --port 8901
```

---

## Running with systemd

To run HaramMute as a persistent user service:

```bash
cp harammute.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now harammute
```

Follow the service logs with:

```bash
journalctl --user -u harammute -f
```

---

## Tray Launcher

Start the tray icon with:

```bash
python3 tray_launcher.py
```

The system package below is required:

```text
gir1.2-ayatanaappindicator3-0.1
```

The tray launcher uses AppIndicator / SNI and can therefore appear in desktop environments that support these technologies, including XFCE and GNOME.

If a server is already running, the tray launcher reuses the existing server instead of spawning a duplicate instance.

### Start Automatically at Login

```bash
mkdir -p ~/.config/autostart
cp harammute-tray.desktop ~/.config/autostart/
```

---

## Desktop Entry

To add HaramMute to the desktop application menu:

```bash
mkdir -p ~/.local/share/applications
cp harammute.desktop ~/.local/share/applications/
```

---

## Browser Extension Configuration

The browser extension should point to:

```text
http://127.0.0.1:8765
```

The server exposes the same API expected by the Windows version.

Job authentication is intentionally bypassed in local mode because the server runs locally on the user's machine.

---

## Configuration

The following environment variables can be used to configure the server:

| Variable | Default | Description |
|---|---|---|
| `HARAMMUTE_DATA_DIR` | `~/.local/share/HaramMute` | Project data directory |
| `MUSIC_REMOVER_CHUNK_THRESHOLD` | `120` | Audio duration threshold in seconds before splitting into 60-second chunks |
| `MUSIC_REMOVER_FORCE_CPU` | unset | Set to `true` to force CPU processing |
| `MUSIC_REMOVER_MODEL_NAME` | `UVR-MDX-NET-Voc_FT.onnx` | Vocal-separation model |
| `MUSIC_REMOVER_ENCODING_QUALITY` | `4` | MP3 VBR quality, where `0` is highest quality and `9` is fastest encoding |
| `HARAMMUTE_TELEMETRY_ENABLED` | disabled | Optional PostHog telemetry |

Example:

```bash
MUSIC_REMOVER_FORCE_CPU=true ./harammute
```

---

## Verification

The complete pipeline was tested on an Ivy Bridge system with three CPU cores and no dedicated GPU.

Test results:

```text
YouTube video
Duration: 19 seconds

Download:       ~9 seconds
Separation:     ~113 seconds
Total:          ~135 seconds
```

The generated output was validated using `ffprobe`:

```text
Duration: 19.1 seconds
Format: MP3
Channels: Stereo
Encoding: VBR
```

---

## Technical Notes

The following files are unmodified upstream sources:

```text
app/main.py
schemas.py
limits.py
config.py
```

The following modules were rebuilt to provide the local Linux processing pipeline:

```text
app/jobs.py
app/local_processing.py
app/pipeline.py
```

### Telemetry

Telemetry is disabled by default.

The PostHog key remains only inside the optional telemetry module. No telemetry is sent unless the feature is explicitly enabled.

### ONNX Model

The bundled model is located at:

```text
assets/model_cache/audio-separator/
```

It is seeded into the HaramMute data directory on first run.

No additional model download is required during normal operation.

---

## Disclaimer

HaramMute-Linux is an unofficial and independent project.

It was developed by a user of the original extension to provide a local Linux-compatible implementation of the HaramMute service.

All rights and ownership related to the original extension, application, hosting, and their respective components belong to their original creators and owners.

This project does not claim ownership, official status, affiliation, or endorsement by the original HaramMute developers.

---

# HaramMute-Linux
