"""Entry point for source and PyInstaller builds."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from converter import VERSION, collect_jars, convert_jar


def main():
    parser = argparse.ArgumentParser(description="NeoConverter — Fabric → NeoFabric")
    parser.add_argument("--batch", nargs="+", metavar="JAR", help="不打开界面，批量转换（便于自动验收）")
    parser.add_argument("--report", type=Path, help="批量验收结果 JSON 路径")
    parser.add_argument("--gui-smoke-report", type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.batch:
        paths, notes = collect_jars(options.batch)
        results = [convert_jar(path) for path in paths]
        report = {
            "version": VERSION,
            "success": sum(item.success for item in results),
            "skipped": sum(not item.success for item in results),
            "notes": notes,
            "results": [
                {key: str(value) if isinstance(value, Path) else value for key, value in asdict(item).items()}
                for item in results
            ],
        }
        if options.report:
            options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if sys.stdout is not None:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if options.report:
        parser.error("--report 必须与 --batch 一起使用")
    import tkinter as tk
    from app import ConverterApp
    root = tk.Tk()
    app = ConverterApp(root)
    if options.gui_smoke_report:
        def smoke_report():
            root.update_idletasks()
            options.gui_smoke_report.write_text(json.dumps({
                "version": VERSION, "tk": str(root.tk.call("info", "patchlevel")),
                "nativeDrop": app.drop is not None,
                "window": [root.winfo_width(), root.winfo_height()],
                "startButtonVisible": bool(app.start_button.winfo_ismapped()),
                "footerVisible": bool(app.footer.winfo_ismapped()),
            }, indent=2), encoding="utf-8")
            app.close()
        root.after(500, smoke_report)
    root.mainloop()


if __name__ == "__main__":
    main()
