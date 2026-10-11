# HaramMute Linux

<p align="center">
  <a href="https://github.com/AS-Offical/HaramMute-Linux/actions/workflows/linux-package-checks.yml"><img src="https://img.shields.io/github/actions/workflow/status/AS-Offical/HaramMute-Linux/linux-package-checks.yml?branch=main&amp;label=CI&amp;logo=github&amp;logoColor=white" alt="CI status" /></a>
  <a href="https://github.com/AS-Offical/HaramMute-Linux/releases/latest"><img src="https://img.shields.io/github/v/release/AS-Offical/HaramMute-Linux?logo=github&amp;logoColor=white" alt="Latest release" /></a>
  <a href="https://codecov.io/gh/AS-Offical/HaramMute-Linux"><img src="https://codecov.io/gh/AS-Offical/HaramMute-Linux/branch/main/graph/badge.svg" alt="Core runtime coverage" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?logo=opensourceinitiative&amp;logoColor=white" alt="License: MIT" /></a>
 
</p>

<p align="center">
  <img src="assets/cover.png" alt="HaramMute Linux">
</p>

[العربية](#العربية) · [English](#english)

## العربية

> **آخر إصدار مستقر:** [v1.0.18-3 والتنزيلات](https://github.com/AS-Offical/HaramMute-Linux/releases/tag/v1.0.18-3) · نزّل الملفات من صفحة الإصدار، وليس من `dist/` المحلي.

نسخة Linux مستقلة من خادم HaramMute المحلي، تعمل مع إضافة المتصفح عبر `http://127.0.0.1:8765`. المشروع غير رسمي ولا يتبع مطوري نسخة Windows.

**إضافة HaramMute للمتصفح مطلوبة أيضًا؛ تثبيت تطبيق Linux وحده لا يكفي.**

- [Firefox](https://addons.mozilla.org/en-US/firefox/addon/harammute/)
- [Chrome وBrave](https://chromewebstore.google.com/detail/harammute-remove-backgrou/bbkbpldbnkoncockinoapcmbiijejgpn?hl=en)

## التثبيت السريع

الباكيدجات الجاهزة تعمل على أجهزة **x86_64** وتستخدم المعالج (CPU). المثبّت يختار أحدث إصدار والباكيدج المناسبة لتوزيعتك، ويتأكد من سلامة الملف قبل التثبيت:

للتثبيت تلقائيًا، استخدم:

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash
```

يفحص المثبّت الملف قبل تثبيته. يثبت باكيدج التوزيعة على Debian وUbuntu وFedora 44 وopenSUSE Tumbleweed وArch، ويستورد باكيدج NixOS إلى حسابك، ويستخدم AppImage على توزيعات Linux المبنية على glibc. يستخدم `sudo` فقط عند تثبيت باكيدج تحتاج صلاحيات مدير النظام. لا يدعم ARM أو Alpine حاليًا.

### NixOS

في NixOS، ينزّل المثبّت باكيدج بُنيت على GitHub، ويتأكد من سلامتها، ثم يضيفها إلى Nix ويثبتها لحسابك. تحتاج إلى `nix-store` و`nix-env` و`zstd` و`curl` و`sha256sum`. حجم التنزيل يقارب 1.1 GiB، وبعد التثبيت تحتاج الملفات إلى نحو 3.99 GiB.

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash
```

بعد التثبيت، افتح HaramMute من قائمة التطبيقات. ثبّت إضافة المتصفح بشكل منفصل. أول مرة تفصل فيها الصوت، ينزّل التطبيق نموذج ONNX. للتثبيت من إعداد NixOS، راجع [دليل NixOS](packaging/nixos/README.md).

لمعرفة الإصدار والباكيدج التي سيختارها المثبّت من دون تنزيل أو تثبيت:

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash -s -- --dry-run
```

للتثبيت يدويًا، نزّل الباكيدج المناسبة وملف `SHA256SUMS` من [صفحة الإصدارات](https://github.com/AS-Offical/HaramMute-Linux/releases/latest) إلى المجلد نفسه. بعد ذلك، افحص الملف بالأمر التالي:

```bash
sha256sum --ignore-missing -c SHA256SUMS
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

يتطلب AppImage نظامًا مبنيًا على glibc، ومكتبات GTK3 وPyGObject وAppIndicator/SNI من النظام. إذا لم يكن FUSE متوفرًا، شغّله بهذا الأمر: `APPIMAGE_EXTRACT_AND_RUN=1 ./HaramMute-1.0.18-x86_64.AppImage`. لا يدعم هذا الإصدار ARM أو Alpine/musl.

```bash
chmod +x ./HaramMute-1.0.18-x86_64.AppImage
./HaramMute-1.0.18-x86_64.AppImage
```

## أول تشغيل

بعد تثبيت باكيدج التوزيعة، افتح **HaramMute** من قائمة التطبيقات أو شغّل:

```bash
harammute-open
```

يشغّل ذلك Tray والخادم المحلي معًا ويفتح صفحة الاتصال. اترك التطبيق يعمل عند استخدام إضافة المتصفح. قد لا تظهر أيقونة Tray إلا في بيئة سطح مكتب أو لوحة تدعم AppIndicator/SNI. لتشغيل الخدمة تلقائيًا عند تسجيل الدخول:

```bash
systemctl --user enable --now harammute
```

أول عملية فصل تنزّل نموذج ONNX؛ يلزم اتصال بالإنترنت ومساحة إضافية. قد تحتاج معالجة الصوت إلى وقت وموارد CPU بحسب طول الملف ومواصفات الجهاز.

## التوافق وما تم التحقق منه

| الباكيدج | أين تم بناؤها وفحصها |
|---|---|
| `.deb` | Ubuntu 22.04 للبناء، وفحص تثبيت وتشغيل الخدمة |
| Fedora `.rpm` | Fedora 44، وفحص تثبيت وتشغيل الخدمة |
| openSUSE `.rpm` | Tumbleweed، وفحص تثبيت وتشغيل الخدمة |
| Arch `.pkg.tar.zst` | Arch Linux، وفحص تثبيت وتشغيل الخدمة |
| AppImage | شُغّل الخادم للتأكد من استجابته لفحص `/health` |
| NixOS | بنى GitHub Actions إغلاق Nix واختبر تشغيل Tray والخادم وفحص `/health` داخل Xvfb |

تأكدنا من أن الباكيدجات تُبنى وتُثبت وأن الخادم يستجيب. لم نختبر فصل أغنية كاملة أو ظهور أيقونة Tray على كل أجهزة Linux. قد تعمل توزيعات أخرى، لكننا لم نختبرها كلها. الإصدار الحالي لا يدعم ARM أو Alpine، وكل الباكيدجات الجاهزة تستخدم CPU فقط.

## التثبيت من المصدر

استخدم هذا الخيار إذا لم تجد باكيدج تناسب توزيعتك. المثبّت يجهز Python والملفات التي يحتاجها التطبيق. قد تحتاج إلى تنزيل عدة جيجابايت وتوفير مساحة كافية.

```bash
git clone https://github.com/AS-Offical/HaramMute-Linux.git
cd HaramMute-Linux
./install.sh --acceleration cpu
```

المثبّت يجهز المتطلبات تلقائيًا على Debian وUbuntu وFedora وArch ومشتقاته وopenSUSE وGentoo. على التوزيعات الأخرى، ثبّت `ffmpeg` و`ffprobe` و`curl` وGTK3 وPyGObject وAppIndicator/SNI أولًا، ثم شغّل المثبّت مع `HARAMMUTE_SKIP_SYSTEM_DEPS=1`. يلزم Linux مبني على glibc؛ Alpine غير مدعوم حاليًا.

### اختيار مسار المعالجة عند التثبيت من المصدر

استخدام CPU هو الخيار الافتراضي. خيارات GPU تحتاج جهازًا وتعريفات ومكتبات مناسبة، ولا تتوفر في باكيدجات الإصدار الجاهزة:

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
- إذا لم تتصل الإضافة، تأكد أن HaramMute يعمل، ثم راجع السجل بالأمر أعلاه.
- ملفات RPM في هذا الإصدار غير موقعة. `SHA256SUMS` يكشف تلف التنزيل، لكنه ليس توقيعًا يثبت هوية الناشر.

## للمساهمين والبناء

راجع [CONTRIBUTING.md](CONTRIBUTING.md) لإعداد بيئة التطوير وإرشادات المساهمة. ملفات بناء الباكيدجات موجودة في `packaging/`. لا تغيّر أسماءها أو مساراتها من دون تحديث سكربتات البناء. مجلد `dist/` محلي ولا يحتوي على ملفات التنزيل الرسمية.

### تنظيم الملفات

- `app/`: واجهة API ومعالجة المهام والصوت.
- `packaging/`: ملفات بناء باكيدجات Debian وRPM وArch وAppImage وNixOS.
- `assets/`: الصور وبيانات النموذج؛ ملف النموذج الكبير يُنزّل عند الحاجة ولا يُرفع إلى Git.
- `install.sh` و`install-release.sh` و`harammute*` و`tray_launcher.py`: أدوات التثبيت والتشغيل.
- `.github/workflows/`: فحوص المشروع وبناء باكيدجات الإصدارات.

## الترخيص

المشروع مرخص بموجب [MIT](LICENSE).


---

## English

> **Latest stable release:** [v1.0.18-3 downloads](https://github.com/AS-Offical/HaramMute-Linux/releases/tag/v1.0.18-3). Download published assets from Releases; do not use a local `dist/` folder.

HaramMute Linux is an independent local server for the HaramMute browser extension. It connects to the extension at `http://127.0.0.1:8765`. This is an unofficial project and is not affiliated with the original Windows developers.

**You must install the browser extension too; the Linux app alone is not enough.**

- [Firefox add-on](https://addons.mozilla.org/en-US/firefox/addon/harammute/)
- [Chrome and Brave extension](https://chromewebstore.google.com/detail/harammute-remove-backgrou/bbkbpldbnkoncockinoapcmbiijejgpn?hl=en)

### Quick install

The current release packages target **x86_64** and use CPU inference. The installer selects the latest release and the package for your distribution, then verifies its SHA256 before installation. To install automatically, run:

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash
```

The installer uses native packages on Debian/Ubuntu, Fedora 44, openSUSE Tumbleweed, and Arch. On NixOS it imports a Nix store closure built on GitHub Actions into the current user's profile. Other glibc-based distributions use the AppImage. It verifies SHA256 before installation and requests `sudo` only for native system packages. The NixOS download is currently about 1.1 GiB because it includes the complete Nix store closure. ARM and Alpine/musl are not supported.

To preview the release and package it selects without downloading or installing it:

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash -s -- --dry-run
```

To install manually, download your package and `SHA256SUMS` from the [release page](https://github.com/AS-Offical/HaramMute-Linux/releases/latest) into the same folder, then verify the downloaded package:

```bash
sha256sum --ignore-missing -c SHA256SUMS
```

#### Debian and Ubuntu

```bash
sudo apt install ./harammute-linux_1.0.18-3_amd64.deb
```

#### Fedora 44

```bash
sudo dnf install ./harammute-linux-1.0.18-3.fc44.x86_64.rpm
```

#### NixOS

Use the automatic installer above. It downloads the NixOS-specific package built and smoke-checked on GitHub Actions, then installs it into the current user's Nix profile. It requires `nix-store`, `nix-env`, `zstd`, `curl`, and `sha256sum`. The package uses a Nix FHS AppImage wrapper to provide GTK, PyGObject, and AppIndicator for the tray; the processing runtime and FFmpeg are bundled. The current archive is about 1.1 GiB compressed and imports a 3.99 GiB Nix store closure.

For declarative NixOS configurations, the repository also provides a flake package and `nixosModules.default`; see [NixOS packaging](packaging/nixos/README.md).

#### openSUSE Tumbleweed

The RPM is unsigned. Verify its SHA256, then install it with:

```bash
sudo zypper --no-gpg-checks install ./harammute-linux-1.0.18-3.x86_64.rpm
```

#### Arch Linux

```bash
sudo pacman -U ./harammute-linux-1.0.18-3-x86_64.pkg.tar.zst
```

#### AppImage

The AppImage requires a glibc-based system and host GTK3, PyGObject, and AppIndicator/SNI support. If FUSE is unavailable, run it with `APPIMAGE_EXTRACT_AND_RUN=1 ./HaramMute-1.0.18-x86_64.AppImage`. ARM and Alpine/musl are not supported by this release.

```bash
chmod +x ./HaramMute-1.0.18-x86_64.AppImage
./HaramMute-1.0.18-x86_64.AppImage
```

### First launch

After installing a native package, launch **HaramMute** from your applications menu or run:

```bash
harammute-open
```

This starts the tray and local server together, then opens the connection page. Keep HaramMute running while using the browser extension. The tray icon appears only in desktop panels that support AppIndicator/SNI. To start the service automatically when you log in:

```bash
systemctl --user enable --now harammute
```

The first separation downloads the ONNX model and requires internet access and additional disk space. Processing time and CPU use depend on the audio length and your hardware.

### Compatibility and validation

| Package | Release build/check environment |
|---|---|
| `.deb` | Built on Ubuntu 22.04; installation and service startup checked |
| Fedora `.rpm` | Fedora 44; installation and service startup checked |
| openSUSE `.rpm` | Tumbleweed; installation and service startup checked |
| Arch `.pkg.tar.zst` | Arch Linux; installation and service startup checked |
| AppImage | Extracted and its server `/health` endpoint checked |
| NixOS | Nix closure built on GitHub Actions; tray startup and `/health` checked under Xvfb |

These checks confirm package installation and server health. They do not test a complete audio-separation job or tray visibility in every graphical session. Other glibc-based distributions may work, but have not all been verified. This release does not support ARM or Alpine/musl. All published packages use CPU; GPU options available when building from source are not included in the release packages.

### Install from source

Use this option if there is no suitable package for your distribution. The installer prepares Python and project dependencies, which may require several gigabytes of downloads and disk space.

```bash
git clone https://github.com/AS-Offical/HaramMute-Linux.git
cd HaramMute-Linux
./install.sh --acceleration cpu
```

The installer has automatic dependency recipes for Debian/Ubuntu, Fedora, Arch and its derivatives, openSUSE, and Gentoo. On other distributions, install `ffmpeg`, `ffprobe`, `curl`, GTK3, PyGObject, and AppIndicator/SNI, then run with `HARAMMUTE_SKIP_SYSTEM_DEPS=1`. A glibc-based system is required; Alpine is currently unsupported because of the PyTorch and ONNX Runtime dependencies.

#### Select a processing provider when installing from source

CPU is the default and most compatible option. GPU options depend on compatible hardware, drivers, and system libraries, and are not included in the prebuilt release packages:

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

### Useful information

- Local server: `http://127.0.0.1:8765`, the address expected by the browser extension.
- App data and model: `~/.local/share/HaramMute/`.
- systemd user service logs: `journalctl --user -u harammute -f`.
- If the extension cannot connect, make sure HaramMute and its tray are running, then check the service log.
- RPM packages in this release are unsigned. `SHA256SUMS` detects download corruption but does not verify publisher identity.

### Contributing and repository layout

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and contribution guidelines. Package files live in `packaging/`; keep their paths intact because the build scripts depend on them. The local `dist/` directory is ignored by Git and is not the source of public release downloads.

- `app/`: API, jobs, and audio processing.
- `packaging/`: Debian, RPM, Arch, AppImage, and NixOS package files.
- `assets/`: images and model metadata; the large model is downloaded when needed and is not stored in Git.
- `install.sh`, `install-release.sh`, `harammute*`, and `tray_launcher.py`: source and release installers, launchers, and service integration.
- `.github/workflows/`: CI checks and release package builds.

### License

This project is licensed under the [MIT License](LICENSE).
