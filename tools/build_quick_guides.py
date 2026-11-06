"""Build the requested Word guides from the checked-in screenshots and text.

Optional document tools: python-docx and Pillow. They are not app dependencies.
Run only when rebuilding the guides; this script does not access APIs or app data.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(
    r"__version__\s*=\s*['\"]([^'\"]+)",
    (ROOT / "src/github_stars/__init__.py").read_text(encoding="utf-8"),
).group(1)
DATE = "2026-11-06"
MAIN_NAME = f"快速上手与运行结果_{VERSION}.docx"
CONFIG_NAME = f"简明配置指南_{VERSION}.docx"
SCREENS = ROOT / "docs/images" / f"web-{VERSION}"


def font(run, size=10.5, *, bold=False, code=False):
    run.font.name = "Consolas" if code else "Calibri"
    run.font.size = Pt(size)
    run.font.bold = bold
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def base_document(*, landscape=False):
    doc = Document()
    section = doc.sections[0]
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Mm(297), Mm(210)
    else:
        section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = Mm(13)
    section.left_margin = section.right_margin = Mm(15)
    section.header_distance = section.footer_distance = Mm(6)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(
        qn("w:eastAsia"), "Microsoft YaHei"
    )
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(5)
    for style_name in ("Heading 1", "Heading 2"):
        style = doc.styles[style_name]
        style.font.name = "Calibri"
        style.font.color.rgb = RGBColor.from_string("205A47")
        style.element.get_or_add_rPr().get_or_add_rFonts().set(
            qn("w:eastAsia"), "Microsoft YaHei"
        )
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    font(footer.add_run(f"GitHub Stars++ {VERSION}  ·  {DATE}  ·  "), 8)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    doc.core_properties.title = f"GitHub Stars++ {VERSION} 使用说明"
    doc.core_properties.subject = "本机网页操作与配置"
    return doc


def main_guide():
    doc = base_document(landscape=True)
    pages = [
        ("1  打开程序，看项目库", "双击“GitHub Stars++ 网页版”，打开 http://127.0.0.1:8765/。"
         "查新项目在上方，已保存的项目在下方。", "01_启动后的项目库.png"),
        ("2  选一个项目，先读介绍", "在已保存的项目中搜索 every-embodied，点击项目卡片。"
         "右侧读介绍，展开“阅读项目原文”看原始资料。", "02_查看项目.png"),
        ("3  在 AI 问答中看已有回答", "打开“AI问答”，点击以前问过的问题，查看回答和来源。"
         "重看历史不会新增模型调用；发送新问题会使用额度。", "03_已有AI回答.png"),
        ("4  打开已经生成的学习教程", "在项目库搜索 Embodied-AI-Guide，选择 TianxingChen 的项目，"
         "点“下载已有教程”。下载后用浏览器打开即可阅读。", "04_已有学习教程.png"),
        ("5  查看每周推荐", "打开“每周推荐”，选择已有的一周，阅读推荐理由。"
         "需要保留时，导出 HTML 或 Markdown。", "05_每周推荐.png"),
    ]
    for index, (title, text, filename) in enumerate(pages):
        if index:
            doc.add_page_break()
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        font(p.add_run(title), 20, bold=True)
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(7)
        font(p.add_run(text), 11)
        source = SCREENS / filename
        with Image.open(source) as pic:
            width, height = pic.size
        scale = min(9.8 / width, 5.60 / height)
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_picture(
            str(source), width=Inches(width * scale), height=Inches(height * scale)
        )
    target = ROOT / "docs" / MAIN_NAME
    doc.save(target)
    return target


def add_markdown(doc, line):
    if not line:
        return
    if line.startswith("# "):
        p = doc.add_paragraph()
        font(p.add_run(line[2:]), 19, bold=True)
        return
    if line.startswith("## "):
        p = doc.add_paragraph()
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(4)
        font(p.add_run(line[3:]), 13, bold=True)
        return
    line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", line)
    p = doc.add_paragraph()
    for part in re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", line):
        if part.startswith("`") and part.endswith("`"):
            font(p.add_run(part[1:-1]), 9.5, code=True)
        elif part.startswith("**") and part.endswith("**"):
            font(p.add_run(part[2:-2]), bold=True)
        else:
            font(p.add_run(part))


def config_guide():
    doc = base_document()
    source = (ROOT / "docs/配置与部署指南.md").read_text(encoding="utf-8")
    in_code = False
    for line in source.splitlines():
        if line.startswith("## 4.") or line.startswith("## 7."):
            doc.add_page_break()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.0
            font(p.add_run(line), 8.3, code=True)
            continue
        add_markdown(doc, line)
    target = ROOT / "docs" / CONFIG_NAME
    doc.save(target)
    return target


def copy_to_local(main_path, config_path, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if main_path:
        old = destination / "GitHub_Stars++_具身智能实操图文指南_20261106.docx"
        backup = destination / "备份/原37图详细版_20261106.docx"
        if old.exists() and not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, backup)
        shutil.copy2(main_path, old)
    if config_path:
        shutil.copy2(config_path, destination / f"GitHub_Stars++_{CONFIG_NAME}")


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("main", "config", "both"), default="both")
    parser.add_argument("--local-directory", type=Path, help="Also copy to this local guide folder")
    args = parser.parse_args()
    main_path = main_guide() if args.only in {"main", "both"} else None
    config_path = config_guide() if args.only in {"config", "both"} else None
    if args.local_directory:
        copy_to_local(main_path, config_path, args.local_directory)
    for path in (main_path, config_path):
        if path:
            print(path)


if __name__ == "__main__":
    run()
