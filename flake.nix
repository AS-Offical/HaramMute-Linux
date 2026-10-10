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
        pkgs.gobject-introspection
        pkgs.glib
        pkgs.cairo
        pkgs.pango
        pkgs.gdk-pixbuf
        pkgs.atk
        pkgs.gtk3
        pkgs.libayatana-appindicator
      ];
      trayLibraries = pkgs.lib.makeLibraryPath [
        pkgs.glib
        pkgs.gobject-introspection
        pkgs.gtk3
        pkgs.libayatana-appindicator
      ];
      appimage = pkgs.fetchurl {
        url = "https://github.com/AS-Offical/HaramMute-Linux/releases/download/v${version}/HaramMute-1.0.18-x86_64.AppImage";
        hash = "sha256-PUmTV7G8voj/3p7zFMRUVk7donZhiLYnM5An/EEBpTU=";
      };
      extractedAppimage = pkgs.appimageTools.extractType2 {
        pname = "harammute";
        inherit version;
        src = appimage;
        postExtract = ''
          substituteInPlace "$out/AppRun" \
            --replace-fail 'command -v python3' 'command -v ${trayPython}/bin/python3' \
            --replace-fail 'python3 -c' '${trayPython}/bin/python3 -c' \
            --replace-fail 'PYTHONPATH python3 ' 'PYTHONPATH ${trayPython}/bin/python3 ' \
            --replace-fail "' >/dev/null 2>&1; then" "' >&2; then" \
            --replace-fail 'fi
if [ ! -x "$PYTHON_BIN" ]' 'fi
export HARAMMUTE_SERVER_LD_LIBRARY_PATH="$LD_LIBRARY_PATH"
export LD_LIBRARY_PATH="${trayLibraries}:$LD_LIBRARY_PATH"
if [ ! -x "$PYTHON_BIN" ]' \
            --replace-fail 'export HARAMMUTE_DATA_DIR="$DATA_DIR"' 'export HARAMMUTE_DATA_DIR="$DATA_DIR"
export GI_TYPELIB_PATH="${trayTypeLibs}"
'
          substituteInPlace "$out/usr/lib/harammute-linux/tray_launcher.py" \
            --replace-fail 'server_env = os.environ.copy()' 'server_env = os.environ.copy()
        if server_env.get("HARAMMUTE_SERVER_LD_LIBRARY_PATH"):
            server_env["LD_LIBRARY_PATH"] = server_env["HARAMMUTE_SERVER_LD_LIBRARY_PATH"]'
        '';
      };
      harammute = pkgs.appimageTools.wrapAppImage {
        pname = "harammute";
        inherit version;
        src = extractedAppimage;

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
