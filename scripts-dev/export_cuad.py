"""读取 CUADv1.json，导出每份真实合同为 txt，并打印结构统计。

用法（容器内）：
    python export_cuad.py /tmp/CUADv1.json /corpus/cuad
"""

import json
import re
import sys
from pathlib import Path


def safe_name(title: str, idx: int) -> str:
    name = re.sub(r"[^\w\-.]+", "_", title.strip(), flags=re.UNICODE)
    name = name.strip("_") or f"contract_{idx:03d}"
    return f"{idx:03d}_{name[:80]}.txt"


def main() -> None:
    src = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.load(open(src, encoding="utf-8"))
    contracts = data["data"]
    print("contracts:", len(contracts))
    print("top keys:", list(data.keys()))

    para_counts: list[int] = []
    lengths: list[int] = []
    for idx, contract in enumerate(contracts):
        paragraphs = contract["paragraphs"]
        para_counts.append(len(paragraphs))
        # CUAD 中每份合同的完整文本在 paragraphs[0].context；
        # 若被拆成多段则按顺序拼接（去重）
        seen: set[str] = set()
        parts: list[str] = []
        for p in paragraphs:
            ctx = p["context"].strip()
            if ctx and ctx not in seen:
                seen.add(ctx)
                parts.append(ctx)
        text = "\n\n".join(parts)
        lengths.append(len(text))
        (out_dir / safe_name(contract.get("title", ""), idx)).write_text(
            text, encoding="utf-8"
        )

    print("paragraph count distribution:",
          {n: para_counts.count(n) for n in sorted(set(para_counts))})
    print(f"char length min/median/max: "
          f"{min(lengths)}/{sorted(lengths)[len(lengths)//2]}/{max(lengths)}")
    print("exported to", out_dir)


if __name__ == "__main__":
    main()
