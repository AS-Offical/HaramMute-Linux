# NixOS package

The NixOS package wraps the published x86_64 AppImage with Nixpkgs' FHS AppImage runner. Its FHS runtime supplies the system Python with PyGObject, GTK 3, Ayatana AppIndicator, `curl`, and `xdg-utils`. The audio-processing Python environment, ONNX Runtime, FFmpeg, and Deno stay inside the AppImage.

The package tracks the AppImage from the latest tested release. `flake.lock` pins the exact Nixpkgs revision used to build it. Updating a release requires updating the version and SHA256 in the root `flake.nix`, then rebuilding and smoke-checking the package in GitHub Actions.

## Install the published binary package

On NixOS x86_64, install the package from the latest GitHub release:

```bash
curl -fsSL https://raw.githubusercontent.com/AS-Offical/HaramMute-Linux/main/install-release.sh | bash
```

This imports the verified Nix store closure and installs the app in the current user's Nix profile. It requires `nix-store`, `nix-env`, `curl`, `sha256sum`, `tar`, and `zstd`. The installer uses the release checksum; it does not require enabling Flakes.

The current archive is about **1.1 GiB compressed** and imports a **3.99 GiB Nix store closure**. It contains the extracted AppImage runtime and all of its Nix dependencies, including GTK and the tray bindings. The archive is large because it is self-contained; the first separation also downloads its ONNX model separately.

## Build from this repository

The flake builds the package from the checksummed AppImage using the exact NixOS 26.05 package set revision recorded in `flake.lock`:

```bash
nix build .#harammute
```

To add HaramMute declaratively, add this repository as an input and include its module in your NixOS configuration:

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

The module adds the package to `environment.systemPackages`.

## Runtime behavior

The desktop entry launches the tray and local service together. The tray requires an active graphical session with GTK/AppIndicator or StatusNotifierItem support. The service listens only on `127.0.0.1:8765` for browser-extension compatibility. Audio model data is downloaded into the user's data directory on first use.
