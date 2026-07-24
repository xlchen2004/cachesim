"""对象级缓存 trace 读取器（ContentTraceReader）。

读取空格分隔的 trace，每行一条请求记录，格式（来自项目设计.md）：
  - time: long long int，当前未使用（留待未来 TTL 特性）。
  - id: long long int，对象唯一标识。
  - size: uint32，对象大小（字节）。
  - extra: 可选，一个或多个 uint16 分类特征（如对象类型），预留。

惰性流式产出四元组 ``(time, id, size, extra)``，``extra`` 为 int 元组（无 extra 列时为 ``()``）。
读取时对每一行做内联完整性校验（列数、类型、范围），违例抛 ``ValueError`` 并附带行号。
仅支持流式惰性读取，避免 76GB 的 twitter29_all.csv 耗尽内存。
"""

from pathlib import Path
from typing import Iterator, List, Tuple, Union

# 一次访问记录：(time, id, size, extra)
Access = Tuple[int, int, int, Tuple[int, ...]]

# uint32 / uint16 范围
_UINT32_MAX = (1 << 32) - 1
_UINT16_MAX = (1 << 16) - 1


class ContentTraceReader:
    """读取对象级缓存 (time, id, size[, extra]) trace 的读取器。

    每行按空白分隔解析为 ``(time, id, size, extra)``：前三列必需，其后可跟任意多个
    uint16 extra 列。空行自动跳过。类型/范围不符时抛 ``ValueError``（含行号）。

    用法::

        reader = ContentTraceReader("traces/twitter29/twitter29_test10.csv")
        for time, obj_id, size, extra in reader:
            ...
    """

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)

    def __iter__(self) -> Iterator[Access]:
        """逐行迭代，惰性产出 (time, id, size, extra)。"""
        with open(self.path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 3:
                    raise ValueError(
                        f"第 {lineno} 行: 至少需要 3 列 (time, id, size)，"
                        f"得到 {len(parts)} 列: {line!r}")
                try:
                    time = int(parts[0])
                    obj_id = int(parts[1])
                    size = int(parts[2])
                except ValueError:
                    raise ValueError(
                        f"第 {lineno} 行: time/id/size 必须为整数: {line!r}")
                if size < 0 or size > _UINT32_MAX:
                    raise ValueError(
                        f"第 {lineno} 行: size 须为 uint32 (0..{_UINT32_MAX})，"
                        f"得到 {size}: {line!r}")
                extra: List[int] = []
                for j, col in enumerate(parts[3:], 4):
                    try:
                        v = int(col)
                    except ValueError:
                        raise ValueError(
                            f"第 {lineno} 行: 第 {j} 列 extra 须为整数: {col!r}")
                    if v < 0 or v > _UINT16_MAX:
                        raise ValueError(
                            f"第 {lineno} 行: 第 {j} 列 extra 须为 uint16 "
                            f"(0..{_UINT16_MAX})，得到 {v}: {line!r}")
                    extra.append(v)
                yield time, obj_id, size, tuple(extra)

    def read_all(self) -> List[Access]:
        """一次性读取全部记录。慎用于大文件。"""
        return list(self)


# 向后兼容别名（原 twitter29 读取器）
TwitterReader = ContentTraceReader


def check_trace(path: Union[str, Path], max_lines: int = 0) -> dict:
    """对 trace 做一遍完整性检查并返回统计。

    单遍流式扫描（常量内存），逐行复用 :class:`ContentTraceReader` 的校验，
    首个违例即抛 ``ValueError``（含行号）。用于模拟器启动时的完整性检查。

    Args:
        path: trace 文件路径。
        max_lines: 最多检查的行数；``0`` 表示全量检查。

    Returns:
        统计字典：num_requests / num_unique_objects / total_bytes /
        num_extra_cols / min_size / max_size。
    """
    seen = set()
    num = 0
    total_bytes = 0
    min_size = None
    max_size = 0
    n_extra = 0
    for i, (_t, obj_id, size, extra) in enumerate(ContentTraceReader(path), 1):
        num = i
        seen.add(obj_id)
        total_bytes += size
        min_size = size if min_size is None else min(min_size, size)
        max_size = max(max_size, size)
        n_extra = max(n_extra, len(extra))
        if max_lines and i >= max_lines:
            break
    return {
        "num_requests": num,
        "num_unique_objects": len(seen),
        "total_bytes": total_bytes,
        "num_extra_cols": n_extra,
        "min_size": min_size if min_size is not None else 0,
        "max_size": max_size,
    }
