#!/usr/bin/env python3
"""Build customer-ready DOCX/PDF guides with screenshots embedded."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent
SCREENSHOTS = DOCS / "screenshots"
OUTPUT = DOCS / "output"

SCREENSHOT_SECTIONS = {
    "ATTENDANCE_AUTOMATION_USER_GUIDE.md": [
        ("## 1. Show Automation Rules", "02-debug-mode.png", "Developer mode and Automation Rules"),
        ("## 2. Create a template", "03-template-header.png", "Template name, company, and effective period"),
        ("## 3. Late & Early Exit", "04-late-early.png", "Late-entry and early-exit rules"),
        ("## 4. Breaks", "05-breaks.png", "Break allowance"),
        ("## 5. Overtime", "06-overtime.png", "Overtime window, minimum, and rounding"),
        ("## 6. Rates and salary slabs", "07-slabs.png", "Salary ranges and OT rates"),
        ("## 8. Assign and review", "08-assigned-employees.png", "Employees assigned to the template"),
        ("## 8. Assign and review", "10-dashboard-ot.png", "Employees detected with overtime"),
        ("## 8. Assign and review", "11-ot-dialog.png", "HR overtime review"),
        ("## 8. Assign and review", "12-dashboard-fine.png", "Employees detected with late/fine"),
        ("## 8. Assign and review", "13-fine-dialog.png", "HR late/fine review"),
        ("## 8. Assign and review", "15-payroll.png", "Saved result in payroll"),
    ],
    "ATTENDANCE_AUTOMATION_MANUAL_TESTING.md": [
        ("## How to record a result", "09-attendance-input.png", "Attendance punches used for testing"),
        ("## How to record a result", "10-dashboard-ot.png", "Overtime result on the dashboard"),
        ("## How to record a result", "11-ot-dialog.png", "Overtime review result"),
        ("## How to record a result", "12-dashboard-fine.png", "Late/fine result on the dashboard"),
        ("## How to record a result", "13-fine-dialog.png", "Late/fine review result"),
        ("## How to record a result", "14-saved-snapshot.png", "Saved HR calculation snapshot"),
        ("## How to record a result", "15-payroll.png", "Payroll result"),
    ],
}


def available_screenshot(name: str) -> Path | None:
    exact = SCREENSHOTS / name
    if exact.exists():
        return exact
    stem = Path(name).stem
    for suffix in (".jpg", ".jpeg", ".webp"):
        candidate = SCREENSHOTS / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def inject_screenshots(source: Path) -> tuple[str, list[str]]:
    text = source.read_text(encoding="utf-8")
    missing = []
    insertions: dict[str, list[str]] = {}
    for heading, filename, caption in SCREENSHOT_SECTIONS[source.name]:
        screenshot = available_screenshot(filename)
        if screenshot:
            relative = screenshot.resolve().as_posix()
            insertions.setdefault(heading, []).append(
                f"\n**{caption}**\n\n![{caption}]({relative})\n"
            )
        else:
            missing.append(filename)
    for heading, blocks in insertions.items():
        text = text.replace(heading, heading + "\n" + "".join(blocks), 1)
    return text, missing


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True)


def build(source_name: str, output_name: str, require_screenshots: bool) -> list[str]:
    source = DOCS / source_name
    content, missing = inject_screenshots(source)
    if require_screenshots and missing:
        raise SystemExit("Missing screenshots: " + ", ".join(sorted(set(missing))))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="attendance-docs-") as temp:
        prepared = Path(temp) / source.name
        prepared.write_text(content, encoding="utf-8")
        docx = OUTPUT / f"{output_name}.docx"
        run(["pandoc", str(prepared), "--standalone", "--resource-path", str(DOCS), "-o", str(docx)])
        run([
            "libreoffice", "--headless", "--convert-to", "pdf", "--outdir",
            str(OUTPUT), str(docx),
        ])
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check sources and screenshot names only")
    parser.add_argument("--require-screenshots", action="store_true", help="fail if any screenshot is missing")
    args = parser.parse_args()

    missing = sorted({
        filename
        for items in SCREENSHOT_SECTIONS.values()
        for _heading, filename, _caption in items
        if not available_screenshot(filename)
    })
    if args.check:
        print("Documentation sources: OK")
        if missing:
            print("Screenshots still required:")
            for filename in missing:
                print(f"- {filename}")
        else:
            print("Screenshots: complete")
        return 1 if args.require_screenshots and missing else 0

    unavailable = [name for name in ("pandoc", "libreoffice") if not shutil.which(name)]
    if unavailable:
        raise SystemExit("Install required commands first: " + ", ".join(unavailable))

    all_missing = []
    all_missing += build(
        "ATTENDANCE_AUTOMATION_USER_GUIDE.md",
        "Attendance_Automation_User_Guide",
        args.require_screenshots,
    )
    all_missing += build(
        "ATTENDANCE_AUTOMATION_MANUAL_TESTING.md",
        "Attendance_Automation_Manual_Testing",
        args.require_screenshots,
    )
    print(f"Generated documents in {OUTPUT}")
    if all_missing:
        print("Warning: generated without these screenshots: " + ", ".join(sorted(set(all_missing))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
