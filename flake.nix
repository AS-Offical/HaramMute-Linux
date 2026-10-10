{
  description = "HaramMute local audio-processing server for NixOS";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      version = "1.0.18-3";
      trayPython = pkgs.python312.withPackages (pythonPkgs: [ pythonPkgs.pygobject3 ]);
      trayTypeLibs = pkgs.lib.makeSearchPath "lib/girepository-1.0" [
        pkgs.gtk3
        pkgs.libayatana-appindicator
      ];
      appimage = pkgs.fetchurl {
        url = "https://github.com/AS-Offical/HaramMute-Linux/releases/download/v${version}/HaramMute-1.0.18-x86_64.AppImage";
        hash = "sha256-PUmTV7G8voj/3p7zFMRUVk7donZhiLYnM5An/EEBpTU=";
      };
      harammute = pkgs.appimageTools.wrapType2 {
        pname = "harammute";
        inherit version;
        src = appimage;

        # The upstream AppImage uses the host Python only for its GTK tray.
        # The audio-processing Python runtime and FFmpeg are bundled in it.
        extraPkgs = appimagePkgs: [
          trayPython
          appimagePkgs.gtk3
          appimagePkgs.libayatana-appindicator
          appimagePkgs.gobject-introspection
          appimagePkgs.curl
          appimagePkgs.xdg-utils
        ];

        profile = ''
          export PATH="${trayPython}/bin:$PATH"
          export GI_TYPELIB_PATH="${trayTypeLibs}''${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
        '';

        extraInstallCommands = ''
          install -Dm444 ${./icon.png} \
            "$out/share/icons/hicolor/256x256/apps/harammute.png"
          install -Dm444 ${./packaging/nixos/harammute.desktop} \
            "$out/share/applications/harammute.desktop"
          substituteInPlace "$out/share/applications/harammute.desktop" \
            --replace-fail '@HARAMMUTE_BIN@' "$out/bin/harammute" \
            --replace-fail '@HARAMMUTE_ICON@' "$out/share/icons/hicolor/256x256/apps/harammute.png"
        '';

        meta = {
          description = "Local audio separation server and tray for the HaramMute browser extension";
          homepage = "https://github.com/AS-Offical/HaramMute-Linux";
          license = pkgs.lib.licenses.mit;
          mainProgram = "harammute";
          platforms = [ system ];
        };
      };
    in {
      packages.${system} = {
        default = harammute;
        inherit harammute;
      };

      apps.${system}.default = {
        type = "app";
        program = "${harammute}/bin/harammute";
      };

      nixosModules.default = { pkgs, ... }: {
        environment.systemPackages = [ self.packages.${pkgs.system}.harammute ];
      };
    };
}
