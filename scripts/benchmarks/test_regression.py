"""
MCA Brain System 回归测试套件

锁定当前基准，防止未来退化：
- 检测器准确性: F1 >= 95%
- 微调模型评估: CV 平均准确率 >= 85%
- 微调模型加载: 无错误
- 语义引擎集成: 无错误
- 评分模块: 基本功能正常

用法:
    python scripts/benchmarks/test_regression.py
    python scripts/benchmarks/test_regression.py --quick  # 快速模式（跳过 CV）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 确保路径正确
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
# 也需要项目根目录来导入 scripts
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# 基准阈值
BENCHMARKS = {
    "detector_f1": 0.95,       # 检测器 F1 分数 >= 95%
    "cv_mean_accuracy": 0.85,   # 交叉验证平均准确率 >= 85%
    "cv_std_max": 0.05,         # 交叉验证标准差 <= 5%
    "model_load_time_ms": 5000, # 模型加载时间 <= 5s
    "embedding_time_ms": 200,   # 单次编码时间 <= 200ms（含首次 CUDA warmup）
    "embedding_dim": 384,       # 向量维度 = 384
    "scorer_causes_min": 3,     # 评分器至少能识别 3 种崩溃原因
}


def test_detector_accuracy() -> dict:
    """测试检测器准确性是否达到基准。"""
    print("\n[1/5] 检测器准确性回归测试")

    import importlib
    mod = importlib.import_module("scripts.benchmarks.test_ai_accuracy_full")
    result = mod.run_comprehensive_test()

    f1 = result["f1_score"]
    passed = f1 >= BENCHMARKS["detector_f1"]

    status = "PASS" if passed else "FAIL"
    print(f"  结果: {status} (F1={f1:.3f}, 基准={BENCHMARKS['detector_f1']})")

    return {"name": "detector_accuracy", "passed": passed, "f1": f1,
            "benchmark": BENCHMARKS["detector_f1"]}


def test_model_loading() -> dict:
    """测试微调模型加载速度和正确性。"""
    print("\n[2/5] 微调模型加载回归测试")

    import torch
    import transformers

    model_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "models", "minilm-minecraft"
    )
    model_path = os.path.normpath(model_path)

    if not os.path.isdir(model_path):
        print(f"  跳过: 微调模型不存在 ({model_path})")
        return {"name": "model_loading", "passed": None, "reason": "model_not_found"}

    # 测试加载速度
    t0 = time.perf_counter()
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(model_path, use_fast=False)
        model = transformers.AutoModel.from_pretrained(model_path)
    except Exception as e:
        print(f"  FAIL: 模型加载失败: {e}")
        return {"name": "model_loading", "passed": False, "error": str(e)}

    load_time_ms = (time.perf_counter() - t0) * 1000
    load_passed = load_time_ms <= BENCHMARKS["model_load_time_ms"]

    # 测试 embedding 维度
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    test_text = "java.lang.OutOfMemoryError: Java heap space"
    tokens = tokenizer(test_text, max_length=128, padding=True, truncation=True, return_tensors="pt")
    tokens = {k: v.to(device) for k, v in tokens.items()}

    t0 = time.perf_counter()
    with torch.no_grad():
        output = model(**tokens)
        # Mean pooling
        mask = tokens["attention_mask"].unsqueeze(-1).expand(output.last_hidden_state.size()).float()
        emb = (output.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
    embed_time_ms = (time.perf_counter() - t0) * 1000

    emb_dim = emb.shape[1]
    dim_passed = emb_dim == BENCHMARKS["embedding_dim"]
    time_passed = embed_time_ms <= BENCHMARKS["embedding_time_ms"]

    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    all_passed = load_passed and dim_passed and time_passed
    status = "PASS" if all_passed else "FAIL"

    print(f"  加载时间: {load_time_ms:.1f}ms (基准={BENCHMARKS['model_load_time_ms']}ms) {'OK' if load_passed else 'FAIL'}")
    print(f"  向量维度: {emb_dim} (基准={BENCHMARKS['embedding_dim']}) {'OK' if dim_passed else 'FAIL'}")
    print(f"  编码时间: {embed_time_ms:.1f}ms (基准={BENCHMARKS['embedding_time_ms']}ms) {'OK' if time_passed else 'FAIL'}")
    print(f"  结果: {status}")

    return {
        "name": "model_loading",
        "passed": all_passed,
        "load_time_ms": load_time_ms,
        "embedding_dim": emb_dim,
        "embedding_time_ms": embed_time_ms,
    }


def test_cross_validation_baseline() -> dict:
    """测试交叉验证基准是否达标。"""
    print("\n[3/5] 交叉验证基准回归测试")

    cv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "models", "minilm-minecraft",
        "cross_validation.json"
    )
    cv_path = os.path.normpath(cv_path)

    if not os.path.exists(cv_path):
        print(f"  跳过: 交叉验证结果不存在 ({cv_path})")
        return {"name": "cv_baseline", "passed": None, "reason": "cv_not_run"}

    with open(cv_path, "r", encoding="utf-8") as f:
        cv_result = json.load(f)

    mean_acc = cv_result.get("mean_accuracy", 0)
    std_acc = cv_result.get("std_accuracy", 0)

    mean_passed = mean_acc >= BENCHMARKS["cv_mean_accuracy"]
    std_passed = std_acc <= BENCHMARKS["cv_std_max"]
    all_passed = mean_passed and std_passed

    status = "PASS" if all_passed else "FAIL"
    print(f"  平均准确率: {mean_acc:.4f} (基准={BENCHMARKS['cv_mean_accuracy']}) {'OK' if mean_passed else 'FAIL'}")
    print(f"  标准差: {std_acc:.4f} (基准<={BENCHMARKS['cv_std_max']}) {'OK' if std_passed else 'FAIL'}")
    print(f"  结果: {status}")

    return {
        "name": "cv_baseline",
        "passed": all_passed,
        "mean_accuracy": mean_acc,
        "std_accuracy": std_acc,
    }


def test_semantic_integration() -> dict:
    """测试语义引擎集成（CodeBertDLC + 微调模型）。"""
    print("\n[4/5] 语义引擎集成回归测试")

    try:
        from dlcs.brain_dlc_codebert import CodeBertDLC
        from brain_system.core import BrainCore
    except ImportError as e:
        print(f"  跳过: 导入失败 ({e})")
        return {"name": "semantic_integration", "passed": None, "reason": str(e)}

    model_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "models", "minilm-minecraft"
    )
    model_path = os.path.normpath(model_path)

    try:
        brain = BrainCore(config_path=None)
        dlc = CodeBertDLC(brain)

        if os.path.isdir(model_path):
            dlc.set_model_path(model_path)

        dlc._initialize()

        if not dlc._is_ready:
            print("  FAIL: DLC 初始化后未就绪")
            return {"name": "semantic_integration", "passed": False, "error": "dlc_not_ready"}

        # 测试编码
        test_text = "java.lang.OutOfMemoryError: Java heap space\nat java.util.Arrays.copyOf()"
        vec = dlc.encode_text(test_text)

        if vec is None:
            print("  FAIL: 编码返回 None")
            return {"name": "semantic_integration", "passed": False, "error": "encode_returned_none"}

        if len(vec) != BENCHMARKS["embedding_dim"]:
            print(f"  FAIL: 向量维度错误 ({len(vec)} != {BENCHMARKS['embedding_dim']})")
            return {"name": "semantic_integration", "passed": False,
                    "error": f"dim_mismatch: {len(vec)}"}

        # 测试相似度
        vec2 = dlc.encode_text("java.lang.OutOfMemoryError: GC overhead limit exceeded")
        if vec2:
            sim = dlc.calculate_similarity(vec, vec2)
            if sim < 0.5:
                print(f"  WARN: 同类 OOM 相似度偏低 ({sim:.3f})")
            else:
                print(f"  同类 OOM 相似度: {sim:.3f} OK")

        # 测试不同类别
        vec3 = dlc.encode_text("Missing mod 'geckolib' needed by 'dragonmounts'")
        if vec3:
            cross_sim = dlc.calculate_similarity(vec, vec3)
            print(f"  跨类别相似度: {cross_sim:.3f}")

        dlc.shutdown()
        print("  PASS: 语义引擎集成正常")

        return {"name": "semantic_integration", "passed": True}

    except Exception as e:
        print(f"  FAIL: {e}")
        return {"name": "semantic_integration", "passed": False, "error": str(e)}


def test_scorer_basics() -> dict:
    """测试评分器基本功能。"""
    print("\n[5/5] 评分器回归测试")

    from mca_core.scoring import CrashCauseScorer

    scorer = CrashCauseScorer()

    # 测试 OOM 检测
    oom_log = "java.lang.OutOfMemoryError: Java heap space"
    oom_scores = scorer.score(oom_log)
    oom_passed = len(oom_scores) > 0
    print(f"  OOM 检测: {'OK' if oom_passed else 'FAIL'} ({list(oom_scores.keys())})")

    # 测试缺失依赖检测
    dep_log = "Missing mod 'geckolib' needed by 'dragonmounts'"
    dep_scores = scorer.score(dep_log)
    dep_passed = len(dep_scores) > 0
    print(f"  缺失依赖检测: {'OK' if dep_passed else 'FAIL'} ({list(dep_scores.keys())})")

    # 测试正常日志
    normal_log = "All mods loaded successfully. Game running."
    normal_scores = scorer.score(normal_log)
    normal_passed = len(normal_scores) == 0
    print(f"  正常日志(无误报): {'OK' if normal_passed else 'FAIL'} ({list(normal_scores.keys())})")

    # 测试 has_cause
    has_cause = scorer.has_cause(oom_log, "内存溢出")
    print(f"  has_cause 查询: {'OK' if has_cause else 'FAIL'}")

    # 测试 get_error_keywords
    keywords = scorer.get_error_keywords()
    kw_passed = len(keywords) >= BENCHMARKS["scorer_causes_min"]
    print(f"  错误关键词数: {len(keywords)} (基准>={BENCHMARKS['scorer_causes_min']}) {'OK' if kw_passed else 'FAIL'}")

    all_passed = oom_passed and dep_passed and normal_passed and has_cause and kw_passed
    status = "PASS" if all_passed else "FAIL"
    print(f"  结果: {status}")

    return {
        "name": "scorer_basics",
        "passed": all_passed,
        "oom_detected": oom_passed,
        "dep_detected": dep_passed,
        "normal_no_fp": normal_passed,
    }


def main():
    parser = argparse.ArgumentParser(description="MCA Brain System 回归测试")
    parser.add_argument("--quick", action="store_true", help="快速模式（跳过 CV 结果检查）")
    args = parser.parse_args()

    print("=" * 60)
    print("MCA Brain System 回归测试套件")
    print("=" * 60)

    results = []

    # 1. 检测器准确性
    results.append(test_detector_accuracy())

    # 2. 模型加载
    results.append(test_model_loading())

    # 3. 交叉验证基准
    if not args.quick:
        results.append(test_cross_validation_baseline())
    else:
        print("\n[3/5] 交叉验证基准回归测试 (跳过 --quick)")
        results.append({"name": "cv_baseline", "passed": None, "reason": "skipped_quick"})

    # 4. 语义引擎集成
    results.append(test_semantic_integration())

    # 5. 评分器
    results.append(test_scorer_basics())

    # 汇总
    print("\n" + "=" * 60)
    print("回归测试汇总")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for r in results:
        name = r["name"]
        p = r.get("passed")
        if p is True:
            print(f"  [PASS] {name}")
            passed += 1
        elif p is False:
            print(f"  [FAIL] {name}: {r.get('error', r.get('reason', 'unknown'))}")
            failed += 1
        else:
            print(f"  [SKIP] {name}: {r.get('reason', 'unknown')}")
            skipped += 1

    total = passed + failed
    print(f"\n  通过: {passed}/{total}, 失败: {failed}/{total}, 跳过: {skipped}")

    if failed > 0:
        print("\n  回归测试失败! 请检查上述 FAIL 项。")
        sys.exit(1)
    else:
        print("\n  所有回归测试通过!")
        sys.exit(0)


if __name__ == "__main__":
    main()