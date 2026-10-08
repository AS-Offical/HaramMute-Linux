# HaramMute-Linux
<p align="center">
  <img src="assets/cover.png" alt="HaramMute Linux">
</p>

> **الإصدارات / Releases:** [صفحة الإصدارات والتنزيلات](https://github.com/AS-Offical/HaramMute-Linux/releases). نزّل الحزم المنشورة هناك فقط؛ مجلد `dist/` في نسخة المصدر قد يحتوي على ملفات بناء محلية قديمة.

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
       |           CPU / CUDA / OpenVINO / MIGraphX
       |
       +-- app/pipeline.py
            Processing orchestration
            Progress tracking and final chunk assembly
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
- Python 3.10 إلى 3.12؛ يجهز المثبت Python 3.12 محليًا عبر `uv` إذا كانت نسخة التوزيعة أحدث
- `ffmpeg`
- `ffprobe`
- Python bindings for Ayatana AppIndicator or compatible AppIndicator3 (Tray)
- اتصال بالإنترنت لتنزيل الوسائط عند الحاجة

### التنزيلات والإصدارات

تُنشر الإصدارات والحزم الجاهزة في [GitHub Releases](https://github.com/AS-Offical/HaramMute-Linux/releases). اختر الحزمة المناسبة لتوزيعتك (`.deb` أو `.rpm` أو `.pkg.tar.zst`) أو AppImage، وتأكد من أن الإصدار يذكر دعم `x86_64`. إذا لم تظهر حزمة تثبيت ضمن ملفات الإصدار، استخدم تعليمات البناء من المصدر أدناه؛ لا تستخدم ملفًا قديمًا من مجلد `dist/`.

### تسريع المعالجة

يعمل المشروع باستخدام CPU بشكل افتراضي.

يتعرف التطبيق تلقائيًا على مزودي ONNX Runtime المثبتين: NVIDIA CUDA، وIntel OpenVINO، وAMD MIGraphX، ثم يستخدم CPU تلقائيًا إذا لم يتوفر مزود مناسب. يجب اختيار حزمة التسريع المطابقة لكرت الشاشة وتعريفاته؛ تثبيت الحزمة وحده لا يضيف دعمًا لتعريف أو جهاز غير متوافق.

يدعم مثبت المشروع الاختيارات التالية:

```bash
./install.sh --acceleration cpu      # المسار الافتراضي والأوسع توافقًا
./install.sh --acceleration nvidia   # يتطلب تعريف NVIDIA وCUDA/cuDNN المتوافقين
./install.sh --acceleration intel    # CPU أو GPU أو NPU عبر OpenVINO
./install.sh --acceleration amd      # MIGraphX؛ يعتمد توفره على إصدار ROCm وglibc والجهاز
```

يبقى CPU مسار الرجوع الآمن إذا لم يتوفر مزود GPU أو فشل تحميله.

---

## التثبيت

### التثبيت من المصدر

إذا لم تتوفر حزمة لتوزيعتك في [صفحة الإصدارات](https://github.com/AS-Offical/HaramMute-Linux/releases)، ثبّت نسخة المصدر وشغّل المثبت:

```bash
git clone https://github.com/AS-Offical/HaramMute-Linux.git
cd HaramMute-Linux
./install.sh --acceleration cpu
```

يطلب المثبت صلاحية المدير فقط لإضافة متطلبات النظام، ثم ينشئ بيئة Python ويجهز مشغل التطبيق وبدء التشغيل التلقائي. تنزيل PyTorch واعتماديات فصل الصوت قد يحتاج عدة جيجابايت من المساحة والإنترنت.

يمكن تجاوز تثبيت حزم النظام إذا كانت مجهزة مسبقًا باستخدام `HARAMMUTE_SKIP_SYSTEM_DEPS=1 ./install.sh`. تحتاج بيئة Python إلى عدة جيجابايت بسبب PyTorch وONNX Runtime.

يتعرف المثبت على Debian وFedora وArch وopenSUSE وGentoo، ثم يتحقق من وجود FFmpeg وGTK3 وPyGObject وAyatana AppIndicator أو AppIndicator3 المتوافق قبل إكمال التثبيت. على التوزيعات الأخرى، جهز `ffmpeg` و`ffprobe` و`curl` وحزم GTK3 وPyGObject وواحدًا من مزودي AppIndicator ثم شغّله مع `HARAMMUTE_SKIP_SYSTEM_DEPS=1`. خدمة المستخدم تشغّل Tray والخادم المحلي معًا؛ إذا تعطل Tray تتوقف الخدمة والخادم. ظهور الأيقونة يحتاج لوحة سطح مكتب تدعم AppIndicator/SNI. تتطلب PyTorch وONNX Runtime توزيعة Linux تستخدم glibc؛ Alpine/musl غير مدعومة حاليًا بهذه الإصدارات المثبتة.

### تثبيت حزمة إصدار

للحزم الجاهزة، نزّل ملف التوزيعة من [صفحة الإصدارات](https://github.com/AS-Offical/HaramMute-Linux/releases) واتبع أمر التثبيت المقابل أدناه.

لبناء حزمة Debian وAppImage بمعمارية x86_64 بعد تجهيز Python المستقل والبيئة، استخدم:

```bash
./install.sh --managed-python --acceleration cpu
APPIMAGETOOL=/path/to/appimagetool.AppImage \
LINUXDEPLOY=/path/to/linuxdeploy.AppImage ./packaging/build-linux-packages.sh
```

يتطلب بناء AppImage أيضًا `linuxdeploy` و`appimagetool`، ويجب بناؤه على أقدم إصدار glibc مستهدف. يمكن بناء حزمة Debian وحدها دون أدوات AppImage؛ يتجاوزها السكربت عند غياب الأدوات. تتضمن الحزم Python 3.12 المستقل ومكتبات Python وDeno؛ وحزمة Debian تعتمد على FFmpeg ومكتبات Tray الخاصة بالتوزيعة. يضم AppImage FFmpeg وتبعياته، لكنه يحتاج GTK3 وPyGObject وAyatana AppIndicator أو AppIndicator3 من النظام المضيف. لا يبدأ AppImage الخادم إذا لم تتوفر متطلبات Tray.

لبناء الحزمة الأصلية على Arch أو Fedora/openSUSE، بعد تجهيز البيئة نفسها:

```bash
./packaging/build-native-packages.sh
```

ينتج `makepkg` حزمة Arch وينتج `rpmbuild` حزمة RPM بحسب أدوات البناء المثبتة. ابنِ الحزمة على عائلة التوزيعة المستهدفة. يعمل AppImage كمسار التوزيعات الأخرى المبنية على glibc، لكنه لا يغطي Alpine/musl أو كل معماريات المعالجات؛ الباني الحالي يستهدف x86_64. CPU هو الاختيار الافتراضي. يمكن اختيار تسريع GPU قبل البناء، مع بقاء تعريفات الجهاز ومكتبات CUDA/ROCm متطلبات على الجهاز.

لتثبيت حزمة Debian الناتجة:

```bash
sudo apt install ./dist/harammute-linux_*_amd64.deb
```

تثبيت الحزم الأصلية على التوزيعات الأخرى:

```bash
sudo pacman -U ./dist/harammute-linux-*.pkg.tar.zst  # Arch ومشتقاته
sudo dnf install ./dist/harammute-linux-*.rpm         # Fedora/RHEL
sudo zypper install ./dist/harammute-linux-*.rpm      # openSUSE
```

لتشغيل AppImage، اجعله قابلًا للتنفيذ ثم افتحه:

```bash
chmod +x ./dist/HaramMute-*-x86_64.AppImage
./dist/HaramMute-*-x86_64.AppImage
```

حزمة التوزيعة الأصلية تربط الخادم وTray في خدمة واحدة. فعّل الخدمة لتشغيلهما معًا:

```bash
systemctl --user enable --now harammute
```

---

## التشغيل

### تشغيل التطبيق وTray

```bash
./harammute
```

يشغّل الأمر Tray والخادم معًا، ويعمل الخادم افتراضيًا على:

```text
http://127.0.0.1:8765
```

يمكن تمرير منفذ آخر للاختبار؛ يجب أن يظل المنفذ `8765` لاستخدام الإضافة دون تغيير إعداداتها:

```bash
./harammute --port 8901
```

---

## تشغيل الخادم باستخدام systemd

ينشئ المثبت ملف خدمة يشغّل Tray والخادم كعملية واحدة. لتشغيلهما:

```bash
systemctl --user enable --now harammute
```

لمتابعة السجلات:

```bash
journalctl --user -u harammute -f
```

---

## Tray Launcher

ينشئ المثبت مشغل القائمة ويضيفه إلى بدء التشغيل التلقائي. لتشغيله يدويًا:

```bash
~/.local/bin/harammute-tray
```

يتطلب ذلك وجود الحزمة:

```text
gir1.2-ayatanaappindicator3-0.1
```

يعتمد الـ Tray Launcher على AppIndicator / SNI، وبالتالي يمكن استخدامه مع بيئات سطح المكتب التي تدعم هذه التقنية، مثل XFCE وGNOME.

يتأكد المشغل من استجابة `/health` قبل إعادة استخدام أي خادم على المنفذ، ويسجل أخطاء بدء الخادم في `~/.local/share/HaramMute/logs/server.log`.

عند معالجة المقاطع، تبقى ملفات MP3 لكل مقطع متاحة للتشغيل التدريجي، ثم يجمع الخادم الصوت إلى ملف `vocals.mp3` كامل عند انتهاء المهمة.

---

## Desktop Entry

يضيف المثبت HaramMute إلى قائمة التطبيقات وبدء التشغيل تلقائيًا. أعد تشغيل `./install.sh` لتحديث مداخل سطح المكتب بعد نقل مجلد المشروع.

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

يتم تجاوز مصادقة المهام في الوضع المحلي؛ لذلك يرفض المشغل ربط الخادم بعنوان شبكة عام ويستمع افتراضيًا على loopback فقط. يسمح CORS بمصادر إضافات Chrome وFirefox.

---

## الإعدادات

يمكن تخصيص سلوك الخادم باستخدام متغيرات البيئة التالية:

| المتغير | القيمة الافتراضية | الوصف |
|---|---|---|
| `MUSIC_REMOVER_DATA_DIR` أو `HARAMMUTE_DATA_DIR` | `~/.local/share/HaramMute` عند التشغيل عبر المشغل | المجلد الرئيسي لبيانات المشروع |
| `MUSIC_REMOVER_CHUNK_THRESHOLD` | `120` | الحد الزمني بالثواني قبل تقسيم الصوت إلى أجزاء مدتها 60 ثانية |
| `MUSIC_REMOVER_FORCE_CPU` | غير محدد | تعيينه إلى `true` لإجبار البرنامج على استخدام CPU |
| `MUSIC_REMOVER_COOKIES_FILE` | غير محدد | ملف cookies بصيغة Netscape لـ yt-dlp |
| `MUSIC_REMOVER_BROWSER_FOR_COOKIES` | اكتشاف تلقائي | اختيار متصفح لاستخراج cookies منه |
| `MUSIC_REMOVER_SKIP_BROWSER_COOKIES` | `false` | منع محاولة قراءة ملفات تعريف المتصفح |
| `MUSIC_REMOVER_DENO_BINARY` | `deno` | مسار Deno المستخدم لميزات JavaScript في yt-dlp |
| `MUSIC_REMOVER_YT_DLP_BINARY` | `yt-dlp` | مسار yt-dlp |
| `MUSIC_REMOVER_FFMPEG_BINARY` | `ffmpeg` | مسار FFmpeg |
| `MUSIC_REMOVER_DOWNLOAD_DELAY` | `5` ثوانٍ | أقل فاصل بين محاولات تنزيل الوسائط |
| الحد الأقصى لطول الوسيط | `90` دقيقة | يتم رفض الوسائط الأطول قبل تنزيلها عند توفر metadata، وإلا بعد فحص الملف |
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

وحدات المعالجة المحلية الخاصة بنسخة Linux:

```text
app/jobs.py
app/local_processing.py
app/pipeline.py
```

### Telemetry

يتم تعطيل Telemetry افتراضيًا.

يبقى مفتاح PostHog داخل الوحدة الاختيارية الخاصة بالـ Telemetry فقط، ولا يتم إرسال البيانات ما لم يتم تفعيل الميزة.

### نموذج ONNX

ملف النموذج الكبير غير محفوظ في Git، لذلك لا يكون مضمّنًا في أرشيف المصدر. عند أول عملية فصل، يقوم `audio-separator` بتنزيل نموذج `UVR-MDX-NET-Voc_FT.onnx` إذا لم يجده في cache؛ يلزم اتصال بالإنترنت ومساحة تخزين إضافية. ملفات بيانات النماذج الوصفية موجودة في المستودع، ويُنسخ أي نموذج متاح إلى مجلد بيانات HaramMute عند بدء المعالجة.

### الفحوص الآلية

يتحقق GitHub Actions من صياغة الشيفرة وسكربتات التثبيت، وملفات Desktop وsystemd وبيانات الحزم، كما يثبت متطلبات GTK وAppIndicator في حاويات Debian وFedora وArch وopenSUSE. هذه الفحوص لا تحاكي لوحة سطح مكتب لعرض الأيقونة ولا تغني عن فحص إصدار الحزمة النهائي.

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
             Progress tracking and final chunk assembly
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
- Python 3.10–3.12; the installer uses `uv` to provision Python 3.12 locally when the distribution ships a newer version
- `ffmpeg`
- `ffprobe`
- Internet access when media needs to be downloaded

### Hardware Acceleration

CPU processing is supported by default.

The installer detects NVIDIA CUDA, Intel OpenVINO, or AMD MIGraphX ONNX Runtime providers and falls back to CPU when acceleration is unavailable. Install the provider matching your hardware and driver stack:

```bash
./install.sh --acceleration cpu      # default, widest compatibility
./install.sh --acceleration nvidia   # requires compatible NVIDIA CUDA/cuDNN drivers
./install.sh --acceleration intel    # Intel CPU/GPU/NPU through OpenVINO
./install.sh --acceleration amd      # MIGraphX; depends on ROCm, glibc, and GPU support
```

---

## Installation

### Install from source

If a package for your distribution is not available on the [Releases page](https://github.com/AS-Offical/HaramMute-Linux/releases), clone the source and run the installer:

```bash
git clone https://github.com/AS-Offical/HaramMute-Linux.git
cd HaramMute-Linux
./install.sh --acceleration cpu
```

The installer requests administrator privileges only for system dependencies, then prepares Python, the application launcher, and login autostart. PyTorch and audio-separation dependencies require several GB of disk space and an internet connection.

Use `HARAMMUTE_SKIP_SYSTEM_DEPS=1` if system dependencies are already installed. Python dependencies require several GB of disk space.

The installer recognizes Debian, Fedora, Arch, openSUSE, and Gentoo, then checks FFmpeg, GTK3, PyGObject, and either Ayatana AppIndicator or compatible AppIndicator3 before continuing. For other distributions, install `ffmpeg`, `ffprobe`, `curl`, GTK3, PyGObject, and one of the AppIndicator providers, then run with `HARAMMUTE_SKIP_SYSTEM_DEPS=1`. The user service runs the tray and local server together; if the tray exits, the server exits with it. Showing the icon also requires a desktop panel that supports AppIndicator/SNI. The pinned PyTorch and ONNX Runtime stack requires a glibc-based Linux distribution; Alpine/musl is not supported by these pinned dependencies.

### Install a packaged release

Download the package for your distribution from the [Releases page](https://github.com/AS-Offical/HaramMute-Linux/releases), then use the matching installation command below.

To build the x86_64 Debian package and AppImage after preparing the managed Python environment, run:

```bash
./install.sh --managed-python --acceleration cpu
APPIMAGETOOL=/path/to/appimagetool.AppImage \
LINUXDEPLOY=/path/to/linuxdeploy.AppImage ./packaging/build-linux-packages.sh
```

AppImage builds require `linuxdeploy` and `appimagetool` and should use the oldest targeted glibc baseline. The Debian package can be built without AppImage tools; the builder skips AppImage if they are unavailable. Packages include standalone Python 3.12, Python dependencies, and Deno. The Debian package depends on distro FFmpeg and tray libraries. The AppImage bundles FFmpeg and its shared libraries, but requires host GTK3, PyGObject, and either Ayatana AppIndicator or compatible AppIndicator3; it exits with an error when those bindings are missing rather than running without a tray.

To build native Arch or Fedora/openSUSE packages on their respective build systems:

```bash
./packaging/build-native-packages.sh
```

`makepkg` creates an Arch package and `rpmbuild` creates an RPM when available. Build native packages on the target distro family. The AppImage is the fallback for other glibc distributions, but the current builder targets x86_64 and does not cover Alpine/musl or every CPU architecture. CPU is the default. GPU acceleration can be selected before building, subject to compatible host drivers and CUDA/ROCm libraries.

Install a generated Debian package with:

```bash
sudo apt install ./dist/harammute-linux_*_amd64.deb
```

Install native packages on other distributions:

```bash
sudo pacman -U ./dist/harammute-linux-*.pkg.tar.zst  # Arch and derivatives
sudo dnf install ./dist/harammute-linux-*.rpm         # Fedora/RHEL
sudo zypper install ./dist/harammute-linux-*.rpm      # openSUSE
```

To run the AppImage, mark it executable and launch it:

```bash
chmod +x ./dist/HaramMute-*-x86_64.AppImage
./dist/HaramMute-*-x86_64.AppImage
```

Native packages run the tray and server as one user service. Enable them together with:

```bash
systemctl --user enable --now harammute
```

---

## Running

### Start HaramMute and its Tray

```bash
./harammute
```

The command starts the tray and its supervised server. The server listens by default at:

```text
http://127.0.0.1:8765
```

For testing with a custom port:

```bash
./harammute --port 8901
```

---

## Running with systemd

After installation, the user service keeps the tray and server in one lifecycle:

```bash
systemctl --user enable --now harammute
```

Follow the service logs with:

```bash
journalctl --user -u harammute -f
```

---

## Tray Launcher

The installer adds the tray to the application menu and login autostart. Start it manually with:

```bash
~/.local/bin/harammute-tray
```

The system package below is required:

```text
gir1.2-ayatanaappindicator3-0.1
```

The tray launcher uses AppIndicator / SNI and can therefore appear in desktop environments whose panels support these technologies, including XFCE and GNOME. On Hyprland, configure a status-notifier tray module in the panel (for example Waybar); running the tray process alone cannot display an icon without a host panel.

The tray verifies the server's `/health` endpoint before reuse and writes startup errors to `~/.local/share/HaramMute/logs/server.log`. Long jobs expose ready chunks progressively and provide a full `vocals.mp3` when processing finishes.

---

## Desktop Entry

The installer adds HaramMute to the desktop application menu and configures the paired tray/server user service to start at login. Rerun `./install.sh` after moving the project folder.

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

Job authentication is intentionally bypassed in local mode. The launcher therefore binds only to loopback, and CORS accepts browser-extension origins only.

---

## Configuration

The following environment variables can be used to configure the server:

| Variable | Default | Description |
|---|---|---|
| `MUSIC_REMOVER_DATA_DIR` or `HARAMMUTE_DATA_DIR` | `~/.local/share/HaramMute` when using the launcher | Project data directory |
| `MUSIC_REMOVER_CHUNK_THRESHOLD` | `120` | Audio duration threshold in seconds before splitting into 60-second chunks |
| `MUSIC_REMOVER_FORCE_CPU` | unset | Set to `true` to force CPU processing |
| `MUSIC_REMOVER_COOKIES_FILE` | unset | Netscape-format yt-dlp cookies file |
| `MUSIC_REMOVER_BROWSER_FOR_COOKIES` | auto-detected | Browser used to read cookies |
| `MUSIC_REMOVER_SKIP_BROWSER_COOKIES` | `false` | Disable browser-cookie attempts |
| `MUSIC_REMOVER_DENO_BINARY` | `deno` | Deno path for yt-dlp JavaScript support |
| `MUSIC_REMOVER_YT_DLP_BINARY` | `yt-dlp` | yt-dlp executable path |
| `MUSIC_REMOVER_FFMPEG_BINARY` | `ffmpeg` | FFmpeg executable path |
| `MUSIC_REMOVER_DOWNLOAD_DELAY` | `5` seconds | Minimum interval between media download attempts |
| Maximum media duration | `90` minutes | Checked before download when metadata exists, otherwise after probing |
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

The Linux-specific local processing modules are:

```text
app/jobs.py
app/local_processing.py
app/pipeline.py
```

### Telemetry

Telemetry is disabled by default.

The PostHog key remains only inside the optional telemetry module. No telemetry is sent unless the feature is explicitly enabled.

### ONNX Model

The large model file is excluded from Git, so it is not included in the source archive. On the first separation job, `audio-separator` downloads `UVR-MDX-NET-Voc_FT.onnx` if it is not already cached. An internet connection and additional disk space are required. Model metadata is tracked in the repository, and any model file already available is copied into HaramMute's data cache before processing.

### Automated checks

GitHub Actions checks source and shell syntax, desktop and systemd metadata, package metadata, and GTK/AppIndicator prerequisites inside Debian, Fedora, Arch, and openSUSE containers. These checks do not emulate a desktop panel or replace a final packaged-app smoke check.

---

## Disclaimer

HaramMute-Linux is an unofficial and independent project.

It was developed by a user of the original extension to provide a local Linux-compatible implementation of the HaramMute service.

All rights and ownership related to the original extension, application, hosting, and their respective components belong to their original creators and owners.

This project does not claim ownership, official status, affiliation, or endorsement by the original HaramMute developers.

---

# HaramMute-Linux
