# NixOS

## التثبيت السريع

على NixOS بمعمارية x86_64، افتح الطرفية وشغّل:

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash
```

المثبّت ينزّل أحدث باكيدج، يفحص سلامتها، ثم يثبتها لحسابك. تحتاج إلى `nix-store` و`nix-env` و`curl` و`sha256sum` و`tar` و`zstd`. لا تحتاج إلى تفعيل Flakes للتثبيت بهذه الطريقة.

حجم التنزيل نحو **1.1 GiB**، وبعد التثبيت تستخدم الملفات نحو **3.99 GiB** من Nix store. أول عملية فصل صوت تنزّل نموذج ONNX إضافيًا.

بعد التثبيت، افتح HaramMute من قائمة التطبيقات وثبّت إضافة المتصفح المناسبة:

- [Firefox](https://addons.mozilla.org/en-US/firefox/addon/harammute/)
- [Chrome وBrave](https://chromewebstore.google.com/detail/harammute-remove-backgrou/bbkbpldbnkoncockinoapcmbiijejgpn?hl=en)

## التثبيت من إعداد NixOS

لإضافة HaramMute إلى إعداد النظام باستخدام Flakes، راجع المثال الإنجليزي أدناه. هذا الخيار يحتاج Flakes.

---

# NixOS package

The NixOS package runs the published x86_64 AppImage with Nixpkgs' FHS AppImage runner. Nix provides Python, PyGObject, GTK 3, Ayatana AppIndicator, `curl`, and `xdg-utils` for the tray. The AppImage includes the audio-processing runtime, ONNX Runtime, FFmpeg, and Deno.

The flake uses the AppImage from the tested release. `flake.lock` records the exact Nixpkgs revision used for the build. To update it, change the release version and SHA256 in the root `flake.nix`, then rebuild and smoke-test it in GitHub Actions.

## Install the published package

On NixOS x86_64, install the latest package from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash
```

The installer checks the downloaded file, imports its Nix store files, and installs HaramMute in your user profile. It needs `nix-store`, `nix-env`, `curl`, `sha256sum`, `tar`, and `zstd`. You do not need to enable Flakes.

The download is about **1.1 GiB**. After installation, its files use about **3.99 GiB** in the Nix store. It includes the app and everything needed to run its tray and audio-processing server. The first audio separation also downloads an ONNX model.

## Build from this repository

The flake builds the package from the checked AppImage. It uses Nixpkgs 26.05 at the revision saved in `flake.lock`:

```bash
nix build .#harammute
```

To add HaramMute to your NixOS configuration, add this repository as a flake input and include its module:

```nix
{
  inputs.harammute.url = "github:AS-Offical/HaramMute-Linux";

  outputs = { nixpkgs, harammute, ... }: {
    nixosConfigurations.myHost = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        harammute.nixosModules.default
        ./configuration.nix
      ];
    };
  };
}
```

The module adds HaramMute to `environment.systemPackages`.

## Runtime behavior

Open HaramMute from your applications menu. It starts the tray and local server together. The tray needs a graphical session that supports GTK and AppIndicator/SNI. The server listens on `127.0.0.1:8765` so the required browser extension can connect. The app downloads its audio model the first time you use it.
