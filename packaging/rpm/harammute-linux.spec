Name:           harammute-linux
Version:        1.0.18
Release:        3%{?dist}
Summary:        Local vocal separation server for the HaramMute browser extension
License:        MIT
BuildArch:      x86_64
Requires:       ffmpeg
Requires:       curl
Requires:       xdg-utils
Requires:       python3-gobject
%if 0%{?suse_version}
Requires:       ffmpeg
Requires:       typelib-1_0-Gtk-3_0
Requires:       typelib-1_0-AppIndicator3-0_1
Requires:       libgomp1
%else
Requires:       gtk3
Requires:       libayatana-appindicator-gtk3
Requires:       ffmpeg-free
Requires:       libgomp
%endif
Source0:        harammute-linux.tar.gz
Source1:        harammute
Source2:        harammute-tray
Source3:        harammute.desktop
Source4:        harammute.service
Source5:        harammute-open

%description
Independent Linux implementation of the local HaramMute service.
The browser extension API remains available at 127.0.0.1:8765.

%prep
%setup -q -c -T
tar -xzf %{SOURCE0}

%install
install -d %{buildroot}/opt/harammute-linux
cp -a harammute-linux/. %{buildroot}/opt/harammute-linux/
install -D -m 0755 %{SOURCE1} %{buildroot}/usr/bin/harammute
install -D -m 0755 %{SOURCE5} %{buildroot}/usr/bin/harammute-open
install -D -m 0755 %{SOURCE2} %{buildroot}/usr/bin/harammute-tray
install -D -m 0644 %{SOURCE3} %{buildroot}/usr/share/applications/harammute.desktop
install -D -m 0644 %{SOURCE4} %{buildroot}/usr/lib/systemd/user/harammute.service
install -D -m 0644 %{buildroot}/opt/harammute-linux/icon.png \
    %{buildroot}/usr/share/icons/hicolor/256x256/apps/harammute.png
%post
systemctl daemon-reload >/dev/null 2>&1 || :

%postun
systemctl daemon-reload >/dev/null 2>&1 || :

%files
/opt/harammute-linux
/usr/bin/harammute
/usr/bin/harammute-open
/usr/bin/harammute-tray
/usr/share/applications/harammute.desktop
/usr/share/icons/hicolor/256x256/apps/harammute.png
/usr/lib/systemd/user/harammute.service

%changelog
* Thu Oct 08 2026 HaramMute Linux contributors - 1.0.18-3
- Fix RPM package file manifests and bundled Python runtime metadata.
