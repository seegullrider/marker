#!/usr/bin/env python3
"""
按固定页数分块调用 marker_single 转换大 PDF。

功能：
1) 自动读取 PDF 总页数
2) 自动生成分块任务（例如每 10 页）
3) 逐块转换为 markdown（每块独立输出目录）
4) 失败自动降批次重试，降低显存压力

示例：
python chunk_convert_pdf.py "E:\\book.pdf" --chunk-size 10 --output-root "D:\\Maker\\output_chunks"
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pypdfium2 as pdfium


@dataclass
class BatchConfig:
    layout_batch_size: int
    detection_batch_size: int
    ocr_error_batch_size: int
    recognition_batch_size: int
    table_rec_batch_size: int


DEFAULT_RETRY_CONFIGS: List[BatchConfig] = [
    BatchConfig(2, 1, 2, 16, 2),
    BatchConfig(1, 1, 1, 8, 1),
]


def sanitize_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", text.strip())
    text = re.sub(r"\s+", " ", text)
    return text[:120] if text else "document"


def get_pdf_page_count(pdf_path: Path) -> int:
    doc = pdfium.PdfDocument(str(pdf_path))
    return len(doc)


def page_ranges(start_page: int, end_page: int, chunk_size: int) -> Iterable[Tuple[int, int]]:
    cur = start_page
    while cur <= end_page:
        end = min(cur + chunk_size - 1, end_page)
        yield cur, end
        cur = end + 1


def resolve_marker_cmd(user_marker_cmd: Optional[str]) -> str:
    if user_marker_cmd:
        return user_marker_cmd

    if os.name == "nt":
        candidate = Path(sys.executable).resolve().parent / "marker_single.exe"
        if candidate.exists():
            return str(candidate)

    return "marker_single"


def has_markdown_output(chunk_dir: Path) -> bool:
    return any(chunk_dir.rglob("*.md"))


def run_one_chunk(
    marker_cmd: str,
    pdf_path: Path,
    out_dir: Path,
    start: int,
    end: int,
    batch: BatchConfig,
    torch_device: Optional[str],
) -> int:
    cmd = [
        marker_cmd,
        str(pdf_path),
        "--page_range",
        f"{start}-{end}",
        "--output_format",
        "markdown",
        "--output_dir",
        str(out_dir),
        "--layout_batch_size",
        str(batch.layout_batch_size),
        "--detection_batch_size",
        str(batch.detection_batch_size),
        "--ocr_error_batch_size",
        str(batch.ocr_error_batch_size),
        "--recognition_batch_size",
        str(batch.recognition_batch_size),
        "--table_rec_batch_size",
        str(batch.table_rec_batch_size),
    ]

    env = os.environ.copy()
    if torch_device:
        env["TORCH_DEVICE"] = torch_device

    print("\n[RUN]", " ".join(f'"{x}"' if " " in x else x for x in cmd))
    proc = subprocess.run(cmd, env=env)
    return proc.returncode


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="分块转换大 PDF（marker_single）")
    p.add_argument("pdf_path", type=str, help="PDF 文件路径")
    p.add_argument("--chunk-size", type=int, default=10, help="每块页数，默认 10")
    p.add_argument("--output-root", type=str, default="D:\\Maker\\output_chunks", help="输出根目录")
    p.add_argument("--job-name", type=str, default=None, help="任务目录名（默认用 PDF 文件名）")
    p.add_argument("--marker-cmd", type=str, default=None, help="marker_single 命令或绝对路径")
    p.add_argument("--start-page", type=int, default=0, help="起始页（含），默认 0")
    p.add_argument("--end-page", type=int, default=None, help="结束页（含），默认自动到最后一页")
    p.add_argument("--torch-device", type=str, default="cuda", help="TORCH_DEVICE，默认 cuda")
    p.add_argument("--skip-existing", action="store_true", help="若分块已有 md 则跳过")
    p.add_argument("--dry-run", action="store_true", help="仅打印计划，不实际运行")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"[ERROR] 文件不存在: {pdf_path}")
        return 2

    if args.chunk_size <= 0:
        print("[ERROR] --chunk-size 必须 > 0")
        return 2

    total_pages = get_pdf_page_count(pdf_path)
    if total_pages <= 0:
        print("[ERROR] 无法读取页数或 PDF 为空")
        return 2

    start_page = max(0, args.start_page)
    end_page = total_pages - 1 if args.end_page is None else min(args.end_page, total_pages - 1)
    if start_page > end_page:
        print(f"[ERROR] 起止页范围非法: start={start_page}, end={end_page}")
        return 2

    marker_cmd = resolve_marker_cmd(args.marker_cmd)
    job_name = sanitize_name(args.job_name) if args.job_name else sanitize_name(pdf_path.stem)
    base_out = Path(args.output_root) / job_name
    base_out.mkdir(parents=True, exist_ok=True)

    ranges = list(page_ranges(start_page, end_page, args.chunk_size))

    print("=" * 72)
    print(f"PDF: {pdf_path}")
    print(f"总页数: {total_pages}")
    print(f"处理页范围: {start_page}-{end_page}")
    print(f"分块大小: {args.chunk_size}")
    print(f"分块数量: {len(ranges)}")
    print(f"输出目录: {base_out}")
    print(f"marker 命令: {marker_cmd}")
    print("=" * 72)

    if args.dry_run:
        for s, e in ranges:
            print(f"[PLAN] p{s:04d}-{e:04d}")
        return 0

    ok = 0
    skipped = 0
    failed: List[str] = []

    for idx, (s, e) in enumerate(ranges, start=1):
        chunk_name = f"p{s:04d}-{e:04d}"
        chunk_dir = base_out / chunk_name
        chunk_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[{idx}/{len(ranges)}] {chunk_name}")

        if args.skip_existing and has_markdown_output(chunk_dir):
            print("[SKIP] 已存在 markdown，跳过")
            skipped += 1
            continue

        success = False
        for attempt, cfg in enumerate(DEFAULT_RETRY_CONFIGS, start=1):
            print(
                f"[TRY {attempt}] layout={cfg.layout_batch_size}, "
                f"detect={cfg.detection_batch_size}, ocr_err={cfg.ocr_error_batch_size}, "
                f"rec={cfg.recognition_batch_size}, table={cfg.table_rec_batch_size}"
            )
            code = run_one_chunk(
                marker_cmd=marker_cmd,
                pdf_path=pdf_path,
                out_dir=chunk_dir,
                start=s,
                end=e,
                batch=cfg,
                torch_device=args.torch_device,
            )
            if code == 0 and has_markdown_output(chunk_dir):
                print("[OK] 分块转换成功")
                success = True
                ok += 1
                break
            print(f"[WARN] 本次失败，返回码={code}")

        if not success:
            failed.append(f"{s}-{e}")
            print("[FAIL] 分块转换失败")

    print("\n" + "=" * 72)
    print(f"完成: 成功 {ok} | 跳过 {skipped} | 失败 {len(failed)}")
    if failed:
        print("失败分块:", ", ".join(failed))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
