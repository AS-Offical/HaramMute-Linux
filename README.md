# HaramMute Linux

<p align="center">
  <img src="assets/cover.png" alt="HaramMute Linux">
</p>

> **آخر إصدار مستقر:** [v1.0.18-3 والتنزيلات](https://github.com/AS-Offical/HaramMute-Linux/releases/tag/v1.0.18-3) · نزّل الملفات من صفحة الإصدار، وليس من `dist/` المحلي.

نسخة Linux مستقلة من خادم HaramMute المحلي، تعمل مع إضافة المتصفح عبر `http://127.0.0.1:8765`. المشروع غير رسمي ولا يتبع مطوري نسخة Windows.

**إضافة HaramMute للمتصفح مطلوبة أيضًا؛ تثبيت تطبيق Linux وحده لا يكفي.**

- [Firefox](https://addons.mozilla.org/en-US/firefox/addon/harammute/)
- [Chrome وBrave](https://chromewebstore.google.com/detail/harammute-remove-backgrou/bbkbpldbnkoncockinoapcmbiijejgpn?hl=en)

## التثبيت السريع

حزم الإصدار الحالية تستهدف Linux بمعمارية **x86_64** وتستخدم CPU للمعالجة. نزّل ملف الحزمة و`SHA256SUMS` من [الإصدار](https://github.com/AS-Offical/HaramMute-Linux/releases/tag/v1.0.18-3) إلى مجلد واحد، ثم تحقق من سلامة الملفات:

```bash
sha256sum -c SHA256SUMS
```

### Debian وUbuntu

```bash
sudo apt install ./harammute-linux_1.0.18-3_amd64.deb
```

### Fedora 44

```bash
sudo dnf install ./harammute-linux-1.0.18-3.fc44.x86_64.rpm
```

### openSUSE Tumbleweed

ملف RPM غير موقع. بعد التحقق من SHA256، استخدم:

```bash
sudo zypper --no-gpg-checks install ./harammute-linux-1.0.18-3.x86_64.rpm
```

### Arch Linux

```bash
sudo pacman -U ./harammute-linux-1.0.18-3-x86_64.pkg.tar.zst
```

### AppImage

يتطلب AppImage نظامًا مبنيًا على glibc، ومكتبات GTK3 وPyGObject وAppIndicator/SNI من النظام. لا يدعم هذا الإصدار ARM أو Alpine/musl.

```bash
chmod +x ./HaramMute-1.0.18-x86_64.AppImage
./HaramMute-1.0.18-x86_64.AppImage
```

## أول تشغيل

بعد تثبيت حزمة التوزيعة، افتح **HaramMute** من قائمة التطبيقات أو شغّل:

```bash
harammute-open
```

يشغّل ذلك Tray والخادم المحلي معًا ويفتح صفحة الاتصال. اترك التطبيق يعمل عند استخدام إضافة المتصفح. قد لا تظهر أيقونة Tray إلا في بيئة سطح مكتب أو لوحة تدعم AppIndicator/SNI. لتشغيل الخدمة تلقائيًا عند تسجيل الدخول:

```bash
systemctl --user enable --now harammute
```

أول عملية فصل تنزّل نموذج ONNX؛ يلزم اتصال بالإنترنت ومساحة إضافية. قد تحتاج معالجة الصوت إلى وقت وموارد CPU بحسب طول الملف ومواصفات الجهاز.

## التوافق وما تم التحقق منه

| الحزمة | بيئة البناء/الفحص في الإصدار |
|---|---|
| `.deb` | Ubuntu 22.04 للبناء، وفحص تثبيت وتشغيل الخدمة |
| Fedora `.rpm` | Fedora 44، وفحص تثبيت وتشغيل الخدمة |
| openSUSE `.rpm` | Tumbleweed، وفحص تثبيت وتشغيل الخدمة |
| Arch `.pkg.tar.zst` | Arch Linux، وفحص تثبيت وتشغيل الخدمة |
| AppImage | فُكّت الحزمة وشُغّل خادمها لفحص `/health` |

هذه الفحوصات تؤكد بناء الحزم وتثبيتها واستجابة الخادم لفحص الصحة. لا تعني أنها اختبرت فصل ملف صوت كاملًا أو ظهور Tray في كل جلسة رسومية. التوزيعات الأخرى المبنية على glibc قد تعمل، لكن لم نتحقق من كل إصدار أو مشتقة. لا يدعم الإصدار الحالي ARM أو Alpine/musl. كل ملفات الإصدار الحالية تستخدم CPU؛ خيارات التسريع المتاحة عند البناء من المصدر ليست حزم GPU جاهزة.

## التثبيت من المصدر

استخدم هذا الخيار إذا لم تتوفر حزمة مناسبة لتوزيعتك. المثبت يجهز بيئة Python واعتماديات المشروع، وقد يحتاج تنزيلها إلى عدة جيجابايت من الإنترنت والمساحة.

```bash
git clone https://github.com/AS-Offical/HaramMute-Linux.git
cd HaramMute-Linux
./install.sh --acceleration cpu
```

يدعم المثبت وصفات اعتماديات تلقائية لـ Debian/Ubuntu وFedora وArch ومشتقاته وopenSUSE وGentoo. في التوزيعات الأخرى، جهز `ffmpeg` و`ffprobe` و`curl` وGTK3 وPyGObject وAppIndicator/SNI، ثم شغّله مع `HARAMMUTE_SKIP_SYSTEM_DEPS=1`. يلزم نظام glibc؛ Alpine غير مدعومة حاليًا بسبب اعتماديات PyTorch وONNX Runtime.

### اختيار مسار المعالجة عند التثبيت من المصدر

CPU هو الخيار الافتراضي والأوسع توافقًا. خيارات GPU تعتمد على توافق الجهاز والتعريفات ومكتبات النظام، ولا تدخل ضمن حزم الإصدار الجاهزة:

```bash
./install.sh --acceleration cpu
```

```bash
./install.sh --acceleration nvidia
```

```bash
./install.sh --acceleration intel
```

```bash
./install.sh --acceleration amd
```

## معلومات مفيدة

- عنوان الخادم المحلي: `http://127.0.0.1:8765`، وهو العنوان المتوقع من إضافة المتصفح.
- بيانات التطبيق والنموذج: `~/.local/share/HaramMute/`.
- سجلات خدمة systemd: `journalctl --user -u harammute -f`.
- إذا تعذر الاتصال، تأكد أن التطبيق/Tray يعمل، ثم افحص السجل بالأمر أعلاه.
- ملفات RPM في هذا الإصدار غير موقعة. `SHA256SUMS` يكشف تلف التنزيل، لكنه ليس توقيعًا يثبت هوية الناشر.

## للمساهمين والبناء

راجع [CONTRIBUTING.md](CONTRIBUTING.md) لإعداد بيئة التطوير وإرشادات المساهمة. ملفات الحزم موجودة تحت `packaging/`؛ أبقِ مساراتها كما هي لأن سكربتات البناء تعتمد عليها. مجلد `dist/` محلي ومستثنى من Git، وليس مصدرًا لحزم التنزيل العامة.

### تنظيم الملفات

- `app/`: واجهة API ومعالجة المهام والصوت.
- `packaging/`: ملفات بناء حزم Debian وRPM وArch وAppImage.
- `assets/`: الصور وبيانات النموذج؛ ملف النموذج الكبير يُنزّل عند الحاجة ولا يُرفع إلى Git.
- `install.sh` و`harammute*` و`tray_launcher.py`: التثبيت ومشغلات التطبيق والخدمة.
- `.github/workflows/`: فحوص CI وبناء حزم الإصدارات.

## الترخيص

المشروع مرخص بموجب [MIT](LICENSE).
