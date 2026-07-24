"""报告生成器。

将多次模拟结果汇总为多算法对比报告，支持输出为 JSON 文件、CSV 文件，
以及打印到控制台的摘要表格。适配对象级缓存（OHR/BHR）。
"""

import csv
import io
import json
from pathlib import Path
from typing import List, Optional

from cache_sim.core.models import SimulationResult


def _cache_size(result: SimulationResult) -> str:
    """从 config 提取缓存容量用于展示。"""
    cfg = result.config or {}
    return str(cfg.get("capacity", ""))


class ReportGenerator:
    """报告生成器，汇总多次模拟结果。"""

    @staticmethod
    def to_json(results: List[SimulationResult], path: Optional[str] = None) -> str:
        data = [r.to_dict() for r in results]
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        if path:
            Path(path).write_text(text, encoding="utf-8")
        return text

    @staticmethod
    def to_csv(results: List[SimulationResult], path: Optional[str] = None) -> str:
        if not results:
            return ""
        rows = [r.to_csv_row() for r in results]
        fieldnames = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        text = buf.getvalue()
        if path:
            Path(path).write_text(text, encoding="utf-8", newline="")
        return text

    @staticmethod
    def print_summary(results: List[SimulationResult]) -> None:
        if not results:
            print("无结果")
            return
        print(f"{'algorithm':<20} {'dataset':<14} {'type':<16} {'k':>10} "
              f"{'hits':>8} {'misses':>8} {'hit_rate':>10} {'bhr':>8} {'cr':>8}")
        print("-" * 112)
        for r in results:
            cr = f"{r.competitive_ratio:.3f}" if r.competitive_ratio is not None else "-"
            bhr = f"{r.bhr:.4f}" if r.byte_total > 0 else "-"
            print(f"{r.algorithm:<20} {r.dataset:<14} {r.cache_type:<16} "
                  f"{_cache_size(r):>10} {r.hits:>8} {r.misses:>8} "
                  f"{r.hit_rate:>10.4f} {bhr:>8} {cr:>8}")
