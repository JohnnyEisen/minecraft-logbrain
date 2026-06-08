"""
准备对比微调训练数据

使用 generate_mc_log.py 按场景批量生成崩溃日志，
按类别分目录存放，供 finetune_minilm.py 使用。

用法:
    python scripts/training/prepare_training_data.py --output_dir data/crashes --samples_per_category 30
"""

from __future__ import annotations

import argparse
import os
import sys

# 确保项目根目录在 path 中
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    src_path = os.path.join(project_root, "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

from scripts.dev.generate_mc_log import generate_batch, SCENARIOS


# 训练用的场景 → 类别目录名映射
CATEGORY_MAP = {
    "oom": "oom",
    "missing_dependency": "missing_dependency",
    "version_conflict": "version_conflict",
    "mixin_conflict": "mixin_conflict",
    "gl_error": "gpu_error",
    "compound": "compound",
    "normal": "normal",
}


def prepare_data(output_dir: str, samples_per_category: int = 30) -> None:
    """按类别生成训练数据。"""
    total = 0

    for scenario_key, category_dir in CATEGORY_MAP.items():
        if scenario_key not in SCENARIOS:
            print(f"  跳过未知场景: {scenario_key}")
            continue

        category_path = os.path.join(output_dir, category_dir)
        os.makedirs(category_path, exist_ok=True)

        print(f"生成 {category_dir}/ ({samples_per_category} 条)...")

        # 分批生成，避免内存溢出
        batch_size = 10
        generated = 0
        file_idx = 1

        while generated < samples_per_category:
            remaining = samples_per_category - generated
            current_batch = min(batch_size, remaining)

            summary = generate_batch(
                output_dir=category_path,
                target_bytes=256 * 1024,  # 256KB 足够
                seed=None,
                scenarios=[scenario_key],
                count=current_batch,
                report_path=None,
            )

            # 重命名为简洁文件名
            for item in summary:
                old_path = item.get("file", "")
                if not old_path or not os.path.exists(old_path):
                    continue
                new_name = f"crash_{file_idx:03d}.txt"
                new_path = os.path.join(category_path, new_name)
                try:
                    os.rename(old_path, new_path)
                    file_idx += 1
                    generated += 1
                except OSError:
                    pass

        count = len([f for f in os.listdir(category_path) if f.endswith(".txt")])
        total += count
        print(f"  OK {category_dir}: {count} 条")

    print(f"\n完成！共 {total} 条训练样本，存放在 {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="准备对比微调训练数据")
    parser.add_argument("--output_dir", default="data/crashes", help="输出目录")
    parser.add_argument("--samples_per_category", type=int, default=30, help="每类生成样本数")
    args = parser.parse_args()

    prepare_data(args.output_dir, args.samples_per_category)


if __name__ == "__main__":
    main()
