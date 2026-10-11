# المساهمة في HaramMute Linux

شكرًا لمساهمتك. هذا مشروع Linux مستقل يعمل مع إضافة HaramMute. حافظ على توافق الخادم المحلي مع الإضافة عند تعديل الواجهة أو طريقة الاتصال.

## الإبلاغ عن مشكلة

افتح [بلاغًا جديدًا](https://github.com/AS-Offical/HaramMute-Linux/issues) بعد البحث عن بلاغ مشابه. أرفق:

- التوزيعة وإصدارها وبيئة سطح المكتب.
- معمارية الجهاز ومعالج الرسوميات إن وجدت.
- خطوات إعادة المشكلة ورسالتها كاملة.
- إصدار HaramMute وطريقة تثبيته.
- السجل ذي الصلة. لخدمة systemd استخدم `journalctl --user -u harammute -n 200 --no-pager`.

لا ترفق ملفات cookies أو رموز دخول أو ملفات صوت خاصة.

## بيئة التطوير

الباكيدجات الجاهزة تستهدف x86_64، وتشمل Debian/Ubuntu وFedora 44 وopenSUSE Tumbleweed وArch، إضافة إلى AppImage وNixOS. فحوص CI تراجع ملفات المشروع ومتطلبات Tray على هذه التوزيعات، لكنها لا تختبر كل توزيعة أو كل بيئة سطح مكتب. للتطوير، تحتاج Python 3.10–3.12 وFFmpeg. ويمكن للمثبّت إعداد Python وباقي متطلبات التطبيق.

```bash
git clone https://github.com/AS-Offical/HaramMute-Linux.git
cd HaramMute-Linux
./install.sh --acceleration cpu
```

لتشغيل واجهة Tray والخادم محليًا:

```bash
./harammute
```

عنوان API الافتراضي هو `http://127.0.0.1:8765`. لا تغيّر المسار أو صيغة الاستجابات التي تعتمد عليها إضافة المتصفح دون تحديث متوافق معها.

## بناء الباكيدجات

يتطلب بناء `.deb` وAppImage تجهيز بيئة المشروع وأدوات AppImage المذكورة في سكربت البناء:

```bash
./install.sh --managed-python --acceleration cpu
```

```bash
APPIMAGETOOL=/path/to/appimagetool.AppImage LINUXDEPLOY=/path/to/linuxdeploy.AppImage ./packaging/build-linux-packages.sh
```

ابنِ باكيدج Arch أو RPM على التوزيعة المستهدفة:

```bash
./packaging/build-native-packages.sh
```

تستخدم الباكيدجات المنشورة حاليًا CPU وتستهدف x86_64. بناء GPU يحتاج اعتماديات النظام المناسبة، ولا يعني أن ملف الباكيدج الناتج سيعمل على أجهزة لا تملك التعريفات والمكتبات المطابقة. راجع ملفات `packaging/` قبل تغيير مساراتها؛ سكربتات البناء تعتمد على البنية الحالية.

## التحقق وطلبات السحب

تشغّل GitHub Actions فحوص صياغة shell وPython، والتحقق من ملفات سطح المكتب وخدمات systemd وبيانات الباكيدجات، وفحص اعتماديات GTK/AppIndicator في حاويات Debian وFedora وArch وopenSUSE. مسار بناء الإصدار يثبت الباكيدجات ويفحص استجابة `/health`، لكنه لا يجري فصلًا كاملًا لصوت ولا يتحقق بصريًا من Tray.

قبل فتح طلب السحب:

1. أنشئ فرعًا واضح الاسم.
2. اشرح المشكلة والتغيير وتأثيره على إضافة المتصفح والتوزيعات.
3. أرفق خطوات تحقق مناسبة، واذكر ما لم تتمكن من التحقق منه.
4. افتح [طلب سحب](https://github.com/AS-Offical/HaramMute-Linux/compare) واربط البلاغ المرتبط إن وجد.

## السلوك والتراخيص

كن محترمًا وواضحًا في النقاش. المساهمات المقدمة للمشروع تخضع لترخيص [MIT](LICENSE).
