import gi

gi.require_version("GIRepository", "3.0")
from gi.repository import GIRepository, GObject

repository = GIRepository.Repository.dup_default()
print("GI search path:", repository.get_search_path(), flush=True)
repository.require("Gio", "2.0", 0)
info = repository.find_by_name("Gio", "ActionMap")
gtype = info.get_g_type()
is_interface = GObject.type_is_a(gtype, GObject.TYPE_INTERFACE)
print("Gio.ActionMap GType:", gtype.name, "is interface:", is_interface, flush=True)
print("Loaded GLib/Gio libraries:", flush=True)
with open("/proc/self/maps", encoding="utf-8") as maps:
    for line in maps:
        if any(name in line for name in ("libgio-2.0", "libglib-2.0", "libgirepository")):
            print(line.rstrip(), flush=True)

