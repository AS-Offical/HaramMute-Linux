{
  description = "HaramMute local audio-processing server for NixOS";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      version = "1.0.18-3";
      trayPython = pkgs.python312.withPackages (pythonPkgs: [ pythonPkgs.pygobject3 ]);
      trayUtilLinux = pkgs.util-linux.override { systemdSupport = false; };
      trayGlib = pkgs.glib.override { withIntrospection = true; };
      trayPango = pkgs.pango.override { withIntrospection = true; };
      trayLibraries = pkgs.lib.makeLibraryPath [
        trayUtilLinux.lib
        trayGlib
        pkgs.gobject-introspection-unwrapped
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
          mkdir -p "$out/nix-girepository-1.0"
          for runtime_package in ${trayGlib} ${trayGlib.dev} ${trayGlib.devdoc}; do
            echo "GLib GObject introspection files in $runtime_package:"
            find -L "$runtime_package" \( -name '*.gir' -o -name '*.typelib' \) -print
          done
          for runtime_package in ${trayPango} ${trayPango.dev} ${trayPango.devdoc}; do
            echo "GObject typelibs in $runtime_package:"
            find -L "$runtime_package" -name '*.typelib' -print
            echo "GObject introspection sources in $runtime_package:"
            find -L "$runtime_package" -name '*.gir' -print
          done
          for runtime_package in \
            ${pkgs.gobject-introspection-unwrapped} ${pkgs.gobject-introspection-unwrapped.dev} \
            ${trayGlib} ${trayGlib.dev} ${trayGlib.devdoc} ${pkgs.cairo} ${pkgs.cairo.dev} ${pkgs.harfbuzz} ${pkgs.harfbuzz.dev} \
            ${trayPango} ${trayPango.dev} ${trayPango.devdoc} ${pkgs.gdk-pixbuf} ${pkgs.atk} ${pkgs.gtk3} \
            ${pkgs.libayatana-appindicator}; do
            find -L "$runtime_package" -path '*/girepository-1.0/*.typelib' \
              -exec ln -sf {} "$out/nix-girepository-1.0/" \;
          done
          gir_directories=()
          for runtime_package in \
            ${pkgs.gobject-introspection-unwrapped} ${pkgs.gobject-introspection-unwrapped.dev} \
            ${trayGlib} ${trayGlib.dev} ${trayGlib.devdoc} ${pkgs.cairo} ${pkgs.cairo.dev} ${pkgs.harfbuzz} ${pkgs.harfbuzz.dev} \
            ${trayPango} ${trayPango.dev} ${trayPango.devdoc} ${pkgs.gdk-pixbuf} ${pkgs.atk} ${pkgs.gtk3} \
            ${pkgs.libayatana-appindicator}; do
            while IFS= read -r gir_directory; do
              gir_directories+=(--includedir="$gir_directory")
            done < <(find -L "$runtime_package" -type d -path '*/share/gir-1.0')
          done
          echo "Collected Nix typelibs:"
          ls -l "$out/nix-girepository-1.0"
          while IFS= read -r gir_file; do
            typelib_file="$out/nix-girepository-1.0/$(basename "''${gir_file%.gir}.typelib")"
            ${pkgs.gobject-introspection-unwrapped.dev}/bin/g-ir-compiler \
              "''${gir_directories[@]}" "$gir_file" --output "$typelib_file"
          done < <(find -L ${trayGlib} ${trayGlib.dev} ${trayGlib.devdoc} ${trayPango} ${trayPango.dev} ${trayPango.devdoc} -name '*.gir')
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
export GI_TYPELIB_PATH="$HERE/nix-girepository-1.0"
export PYTHONPYCACHEPREFIX="$DATA_DIR/python-cache"
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
          trayUtilLinux.lib
          trayPango
          appimagePkgs.gobject-introspection-unwrapped
          trayGlib
          appimagePkgs.cairo
          appimagePkgs.gdk-pixbuf
          appimagePkgs.atk
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
