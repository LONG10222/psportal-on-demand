"""StarPass display branding. No runtime Pillow dependency or network activity."""
from pathlib import Path
import sys
import tkinter as tk

BRAND_NAME = "星渡 StarPass"


def asset_path(filename):
    """Resolve only a basename inside the source or PyInstaller asset directory."""
    if Path(filename).name != filename or filename in ("", ".", ".."):
        raise ValueError("Expected a branding asset basename")
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets" / "branding"
    else:
        root = Path(__file__).resolve().parents[2] / "native" / "assets" / "branding" / "desktop"
    return root / filename


def load_avatar(root, size=64):
    """Return a supported pre-sized PhotoImage, or None on unavailable Tk/assets.

    The caller must retain this image while a widget displays it.
    """
    if size not in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        raise ValueError("Unsupported pre-generated icon size")
    try:
        return tk.PhotoImage(master=root, file=str(asset_path(f"starpass-{size}.png")))
    except (tk.TclError, OSError):
        return None


def apply_window_icon(root):
    """Set a GUI icon without failing app startup on unsupported window managers."""
    if sys.platform == "win32":
        try:
            root.iconbitmap(default=str(asset_path("starpass.ico")))
            return True
        except (tk.TclError, OSError):
            pass
    images = [image for size in (32, 64, 128, 256)
              if (image := load_avatar(root, size)) is not None]
    if not images:
        return False
    try:
        root.iconphoto(True, *images)
        root._starpass_icon_images = images
        return True
    except (tk.TclError, OSError):
        # The macOS Dock icon comes from the app bundle's ICNS on native builds.
        return False
