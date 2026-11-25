import argparse
import shutil
import subprocess
import sys

from common import ROOT_DIR, resolve_game_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install or restore the Russian localization for Dirt Town Demo."
    )
    parser.add_argument(
        "--game-dir",
        help="Path to Dirt Town Demo folder (containing dirttown.exe and data.pack)",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore original English dirttown.exe and data.pack from backup_en/",
    )
    args = parser.parse_args()

    game_dir = resolve_game_dir(args.game_dir)
    if args.restore:
        backup_dir = game_dir / "backup_en"
        for name in ("dirttown.exe", "data.pack"):
            src = backup_dir / name
            dst = game_dir / name
            if not src.exists():
                raise FileNotFoundError(f"Backup missing: {src}")
            shutil.copy2(src, dst)
            print(f"Restored {dst} from {src}")
        return 0

    steps = [
        ("Backing up originals & unpacking fonts/TOMLs", "prep_backup_and_fonts.py"),
        ("Building code xref catalog", "build_loc_catalog.py"),
        ("Translating TOML resources", "translate_tomls.py"),
        ("Repacking data.pack", "repack_pack.py"),
        ("Patching dirttown.exe", "patch_exe.py"),
        ("Verifying patched files", "verify_patch.py"),
    ]
    for title, script in steps:
        print(f"\n=== {title} ({script}) ===")
        cmd = [sys.executable, str(ROOT_DIR / script)]
        if script != "translate_tomls.py" and args.game_dir:
            cmd.extend(["--game-dir", str(game_dir)])
        subprocess.run(cmd, check=True)

    print("\nRussian localization installed and verified successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
