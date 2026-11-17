#!/usr/bin/env python3
"""Command line helpers: unpack / pack vpk, tex <-> png, nfo -> obj, scene info."""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vtoy import vpk
from vtoy.nfo import Nfo
from vtoy.scn import Scene
from vtoy.tex import Texture


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("unpack", help="demo.vpk -> folder"); p.add_argument("vpk"); p.add_argument("out")
    p = sub.add_parser("pack", help="folder -> vpk"); p.add_argument("folder"); p.add_argument("vpk")
    p = sub.add_parser("tex2png"); p.add_argument("tex"); p.add_argument("png")
    p = sub.add_parser("png2tex"); p.add_argument("png"); p.add_argument("tex")
    p.add_argument("--fmt", choices=["dxt1", "dxt5"]); p.add_argument("--mips", action="store_true")
    p = sub.add_parser("nfo2obj"); p.add_argument("nfo"); p.add_argument("obj")
    p = sub.add_parser("un7z", help="extract a .7z (pure Python, supports LZMA/LZMA2/BCJ/BCJ2)"); p.add_argument("archive"); p.add_argument("out")
    p = sub.add_parser("import-model", help="import models of 'Torrente, el juego' into a game folder"); p.add_argument("library"); p.add_argument("game"); p.add_argument("names", nargs="+")
    p = sub.add_parser("import-map", help="import a level (.opt + .hm) of 'Torrente, el juego'"); p.add_argument("library"); p.add_argument("game"); p.add_argument("name")
    p = sub.add_parser("convert-scene", help="convert a scene of 'Torrente, el juego' into an Online scene")
    p.add_argument("library"); p.add_argument("game"); p.add_argument("scene"); p.add_argument("new_name")
    p.add_argument("--mode", default="DM", choices=["DM", "DMT", "DO", "B"], help="game mode of the new scene")
    p.add_argument("--template", help="Online scene whose settings (fog, main module) are copied; default: first mp_dm_*.scn")
    p = sub.add_parser("info", help="print the modules of a .scn"); p.add_argument("scn")
    p = sub.add_parser("install-map", help="install an exported map zip into an unpacked game folder (never replaces files)")
    p.add_argument("game"); p.add_argument("zip")
    p = sub.add_parser("uninstall-map", help="remove a map installed with install-map"); p.add_argument("game"); p.add_argument("name")
    p = sub.add_parser("check-map", help="list what would crash the game or break play in a scene")
    p.add_argument("game"); p.add_argument("scene")
    p = sub.add_parser("balance", help="team balance of a scene: distances / times to the flags and health packs")
    p.add_argument("game"); p.add_argument("scene"); p.add_argument("--cell", type=float, default=45.0)
    p.add_argument("--speed", type=float, default=450.0)
    p = sub.add_parser("auto-hm", help="rebuild the floor / wall collision (.hm) of a scene from its meshes and save it")
    p.add_argument("game"); p.add_argument("scene")
    p = sub.add_parser("import-obj", help="add an OBJ model to the map of a scene (with collision) and save it")
    p.add_argument("game"); p.add_argument("scene"); p.add_argument("obj")
    p.add_argument("x", type=float); p.add_argument("y", type=float); p.add_argument("z", type=float)
    p.add_argument("--scale", type=float, default=100.0); p.add_argument("--yaw", type=float, default=0.0)
    p.add_argument("--up", choices=("y", "z"), default="y")
    a = ap.parse_args()
    if a.cmd in ("balance", "auto-hm", "import-obj"):
        from vtoy.app.state import EditorState
        st = EditorState(a.game, log=print)
        st.load(a.scene)
        if a.cmd == "balance":
            for line in st.balance_lines(st.balance_report(a.cell, a.speed)):
                print(line)
            return
        if a.cmd == "auto-hm":
            print(st.auto_collision("map"))
        else:
            print(st.import_obj(a.obj, (a.x, a.y, a.z), a.scale, a.yaw, a.up))
        print(st.save_map())
        st.save_scene()
        return
    if a.cmd in ("install-map", "uninstall-map", "check-map"):
        from vtoy.app.state import EditorState
        st = EditorState(a.game)
        if a.cmd == "install-map":
            print(st.install_map_zip(a.zip))
        elif a.cmd == "uninstall-map":
            print(st.uninstall_map(a.name))
        else:
            st.load(a.scene)
            for r in st.validate_map():
                print(f"[{r['level']}] {r['msg']}")
        return
    if a.cmd == "unpack":
        print(vpk.unpack(a.vpk, a.out), "files")
    elif a.cmd == "pack":
        print(vpk.repack(a.folder, a.vpk), "entries")
    elif a.cmd == "tex2png":
        Texture.load(a.tex).to_png(a.png)
    elif a.cmd == "png2tex":
        fmt = {"dxt1": 0, "dxt5": 1, None: None}[a.fmt]
        Texture.from_png(a.png, fmt=fmt, mipmaps=a.mips).save(a.tex)
    elif a.cmd == "nfo2obj":
        Nfo.load(a.nfo).export_obj(a.obj)
    elif a.cmd == "un7z":
        from sevenzip_min import extract
        print(extract(a.archive, a.out), "files")
    elif a.cmd in ("import-model", "import-map"):
        from vtoy.importer import Importer, Library
        lib = Library(a.library); imp = Importer(lib, a.game)
        pool = lib.models() if a.cmd == "import-model" else lib.maps()
        for n in (a.names if a.cmd == "import-model" else [a.name]):
            hit = next((m for m in pool if m.lower() in (n.lower(), n.lower() + (".nfo" if a.cmd == "import-model" else ".opt"))), None)
            if hit is None:
                sys.exit(f"not in library: {n}")
            print(n, "->", (imp.model if a.cmd == "import-model" else imp.map)(hit))
        print(imp.report.summary())
        for m in sorted(set(imp.report.missing)):
            print("  missing:", m)
    elif a.cmd == "convert-scene":
        from vtoy.convert import Converter
        from vtoy.importer import Library
        from vtoy.gamefs import GameFS
        fs = GameFS(a.game)
        tname = a.template or next((os.path.basename(p) for p in fs.list("scns", ".scn") if os.path.basename(p).startswith("mp_dm")), None)
        if tname is None:
            sys.exit("no Online template scene found in <game>/scns (use --template)")
        lib = Library(a.library)
        hit = next((s for s in lib.scenes() if s.lower() in (a.scene.lower(), a.scene.lower() + ".scn")), None)
        if hit is None:
            sys.exit(f"scene not in library: {a.scene}")
        cv = Converter(lib, a.game, fs.scene(tname))
        print("written", cv.convert(hit, a.new_name, a.mode))
        print(cv.summary())
    elif a.cmd == "info":
        s = Scene.load(a.scn)
        print(f"map={s.map_name} heightmap={s.heightmap_name} fog={s.fog_color} {s.fog_near}-{s.fog_far}")
        for r in s.modules:
            print(f"  {r.object_name:32s} {r.clean_name}")


if __name__ == "__main__":
    main()
