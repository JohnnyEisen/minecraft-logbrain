"""
MiniLM 领域对比微调脚本（轻量版）

不依赖 sentence-transformers/scipy/scikit-learn，
直接使用 transformers + torch 实现 MultipleNegativesRankingLoss。

训练数据格式:
    data/crashes/
    ├── oom/
    │   ├── crash_001.txt
    │   └── ...
    ├── missing_dependency/
    │   └── ...
    └── ...

用法:
    python scripts/training/finetune_minilm.py --data_dir data/crashes --output_dir models/minilm-minecraft
    python scripts/training/finetune_minilm.py --data_dir data/crashes --output_dir models/minilm-minecraft --matryoshka_dims 768,384,192,96
    python scripts/training/finetune_minilm.py --data_dir data/crashes --eval_only --model_path models/minilm-minecraft
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
from pathlib import Path
from typing import List, Tuple

import torch
import transformers

try:
    from huggingface_hub import scan_cache_dir
    HAS_HF_HUB = True
except ImportError:
    HAS_HF_HUB = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _find_local_model(model_name: str) -> str | None:
    """从 HuggingFace 缓存中查找模型本地路径。"""
    if not HAS_HF_HUB:
        return None
    try:
        cache = scan_cache_dir()
        for repo in cache.repos:
            if repo.repo_id == model_name:
                # 尝试所有修订版，找到有 config.json 的
                for rev in repo.revisions:
                    config_path = rev.snapshot_path / "config.json"
                    if config_path.exists():
                        return str(rev.snapshot_path)
                # fallback: 返回第一个修订版
                revs = list(repo.revisions)
                if revs:
                    return str(revs[0].snapshot_path)
    except Exception:
        pass
    return None


def collect_samples(data_dir: str) -> List[Tuple[str, str]]:
    """收集训练样本，返回 (类别标签, 文件路径) 列表。"""
    samples: List[Tuple[str, str]] = []
    data_path = Path(data_dir)

    if not data_path.exists():
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")

    for category_dir in sorted(data_path.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        for file_path in category_dir.glob("*"):
            if file_path.suffix.lower() in (".txt", ".log", ".md"):
                samples.append((category, str(file_path)))

    logger.info(f"收集到 {len(samples)} 个样本，{len(set(c for c, _ in samples))} 个类别")
    return samples


def read_text(file_path: str, max_chars: int = 2000) -> str:
    """读取文件内容（截断到 max_chars）。"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars)
        return text
    except Exception as e:
        logger.warning(f"读取文件失败 {file_path}: {e}")
        return ""


# 关键行关键词（区分不同崩溃类型的核心信号）
_ERROR_KEYWORDS = [
    "Error", "Exception", "FATAL", "CRASH", "crash",
    "OutOfMemory", "GC overhead", "heap space", "Metaspace",
    "GLFW", "OpenGL", "GL_", "shader", "Pixel format",
    "Mixin", "InjectionError", "Injection", "mixin",
    "missing", "not found", "dependency", "Failed to",
    "version", "conflict", "incompatible",
    "Caused by", "at net.minecraft", "at java.lang",
]


def extract_key_sections(text: str, max_chars: int = 1500) -> str:
    """从崩溃日志中提取关键段（ERROR/FATAL/Exception 行 + 上下文）。

    10K 行日志中只有几行是区分性特征，其余全是噪声。
    此函数只保留包含错误关键词的行及其上下文，
    显著提升信噪比。
    """
    if not text:
        return text

    lines = text.split("\n")
    if len(lines) < 50:
        return text[:max_chars]

    # 标记关键行
    key_indices = set()
    for i, line in enumerate(lines):
        if any(kw.lower() in line.lower() for kw in _ERROR_KEYWORDS):
            # 关键行 ±2 行上下文
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                key_indices.add(j)

    if not key_indices:
        # 没有关键行，取最后 30 行（崩溃信息通常在末尾）
        key_indices = set(range(max(0, len(lines) - 30), len(lines)))

    # 按顺序拼接关键行
    result_lines = [lines[i] for i in sorted(key_indices)]
    result = "\n".join(result_lines)

    return result[:max_chars]


def mean_pool(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Mean Pooling：考虑 attention mask。"""
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
    return sum_embeddings / sum_mask


def mnr_loss(embeddings: torch.Tensor) -> torch.Tensor:
    """MultipleNegativesRankingLoss (in-batch negatives)。

    对于 batch 中的第 i 个样本，anchor=embeddings[i], positive=embeddings[i]，
    negatives=batch 中其他所有样本。损失函数为交叉熵。
    """
    # 相似度矩阵: (batch, batch)
    scores = torch.matmul(embeddings, embeddings.t()) / math.sqrt(embeddings.size(-1))
    # 对角线是 anchor-positive 对
    labels = torch.arange(scores.size(0), device=scores.device)
    return torch.nn.functional.cross_entropy(scores, labels)


def matryoshka_loss(
    embeddings: torch.Tensor,
    dims: List[int],
) -> torch.Tensor:
    """Matryoshka 损失：在多个维度截断上分别计算 MNR 损失。"""
    total_loss = torch.tensor(0.0, device=embeddings.device)
    for dim in dims:
        truncated = torch.nn.functional.normalize(embeddings[:, :dim], p=2, dim=1)
        total_loss = total_loss + mnr_loss(truncated)
    return total_loss / len(dims)


def finetune(
    data_dir: str,
    output_dir: str,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 8,
    num_epochs: int = 3,
    learning_rate: float = 2e-5,
    matryoshka_dims: List[int] | None = None,
    warmup_steps: int = 100,
    max_length: int = 510,
) -> None:
    """执行对比微调训练。"""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"训练设备: {device}")

    # 收集数据
    samples = collect_samples(data_dir)
    if len(samples) < 10:
        logger.error("训练样本不足（至少需要 10 个）")
        return

    # 按类别分组
    by_category: dict[str, List[str]] = {}
    for cat, path in samples:
        by_category.setdefault(cat, []).append(path)
    categories = list(by_category.keys())

    if len(categories) < 2:
        logger.error(f"至少需要 2 个类别，当前只有 {len(categories)} 个")
        return

    # 加载模型
    logger.info(f"加载模型: {model_name}")

    # 尝试从 HuggingFace 缓存中查找本地路径
    local_model_path = _find_local_model(model_name)
    load_path = local_model_path or model_name

    # MiniLM 基于 BERT，直接使用 BertTokenizer 避免 fast tokenizer 依赖问题
    try:
        tokenizer = transformers.BertTokenizer.from_pretrained(load_path)
    except Exception:
        tokenizer = transformers.AutoTokenizer.from_pretrained(load_path, use_fast=False)
    model = transformers.AutoModel.from_pretrained(load_path)
    model.to(device)
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)

    # 训练循环
    total_steps = num_epochs * len(samples) // batch_size
    global_step = 0
    total_loss = 0.0

    logger.info(f"开始训练: epochs={num_epochs}, batch_size={batch_size}, "
                f"lr={learning_rate}, total_steps={total_steps}")

    for epoch in range(num_epochs):
        random.shuffle(categories)
        epoch_loss = 0.0
        epoch_steps = 0

        # 构建训练对：每个类别选 2 个样本作为 anchor-positive
        # 同时加入 hard negative（来自相似类别）
        pairs: List[Tuple[str, str, str | None]] = []  # (anchor, positive, hard_negative)
        for cat in categories:
            paths = by_category[cat]
            if len(paths) >= 2:
                for i in range(min(len(paths) - 1, batch_size)):
                    # Hard negative: 从其他类别中选一个
                    neg_cat = random.choice([c for c in categories if c != cat])
                    neg_path = random.choice(by_category[neg_cat])
                    pairs.append((paths[i], paths[i + 1], neg_path))
            elif len(paths) == 1:
                neg_cat = random.choice([c for c in categories if c != cat])
                neg_path = random.choice(by_category[neg_cat])
                pairs.append((paths[0], paths[0], neg_path))

        random.shuffle(pairs)

        for batch_start in range(0, len(pairs), batch_size):
            batch_pairs = pairs[batch_start:batch_start + batch_size]
            if len(batch_pairs) < 2:
                continue

            # 编码所有 anchor（提取关键段，提升信噪比）
            anchor_texts = [extract_key_sections(read_text(a)) for a, _, _ in batch_pairs]
            anchor_texts = [t for t in anchor_texts if t]
            if len(anchor_texts) < 2:
                continue

            anchor_tokens = tokenizer(
                anchor_texts,
                max_length=max_length,
                padding=True,
                truncation=True,
                return_tensors="pt"
            )
            anchor_tokens = {k: v.to(device) for k, v in anchor_tokens.items()}

            # 编码所有 positive（提取关键段）
            positive_texts = [extract_key_sections(read_text(p)) for _, p, _ in batch_pairs]
            positive_texts = [t for t in positive_texts if t]
            if len(positive_texts) < 2:
                continue

            positive_tokens = tokenizer(
                positive_texts,
                max_length=max_length,
                padding=True,
                truncation=True,
                return_tensors="pt"
            )
            positive_tokens = {k: v.to(device) for k, v in positive_tokens.items()}

            # 编码 hard negatives
            neg_texts = [extract_key_sections(read_text(n)) for _, _, n in batch_pairs]
            neg_texts = [t for t in neg_texts if t]

            neg_emb = None
            if len(neg_texts) >= 2:
                neg_tokens = tokenizer(
                    neg_texts,
                    max_length=max_length,
                    padding=True,
                    truncation=True,
                    return_tensors="pt"
                )
                neg_tokens = {k: v.to(device) for k, v in neg_tokens.items()}
                with torch.cuda.amp.autocast(enabled=device.type == "cuda"):
                    neg_out = model(**neg_tokens)
                    neg_emb = mean_pool(neg_out.last_hidden_state, neg_tokens["attention_mask"])
                    neg_emb = torch.nn.functional.normalize(neg_emb, p=2, dim=1)

            # 前向传播
            with torch.cuda.amp.autocast(enabled=device.type == "cuda"):
                anchor_out = model(**anchor_tokens)
                positive_out = model(**positive_tokens)

                anchor_emb = mean_pool(anchor_out.last_hidden_state, anchor_tokens["attention_mask"])
                positive_emb = mean_pool(positive_out.last_hidden_state, positive_tokens["attention_mask"])

                anchor_emb = torch.nn.functional.normalize(anchor_emb, p=2, dim=1)
                positive_emb = torch.nn.functional.normalize(positive_emb, p=2, dim=1)

                # MNR loss: anchor[i] 与 positive[i] 配对
                # scores[i][j] = anchor[i] · positive[j]
                # temperature 缩放：让模型更关注细微差异
                temperature = 0.05
                scores = torch.matmul(anchor_emb, positive_emb.t()) / temperature

                # 加入 hard negative 得分
                if neg_emb is not None and neg_emb.size(0) == anchor_emb.size(0):
                    neg_scores = torch.matmul(anchor_emb, neg_emb.t()) / temperature
                    # 拼接: [positive_scores | negative_scores]
                    scores = torch.cat([scores, neg_scores], dim=1)

                # 标签: anchor[i] 匹配 positive[i]（对角线位置）
                labels = torch.arange(scores.size(0), device=scores.device)
                loss = torch.nn.functional.cross_entropy(scores, labels)

            # 反向传播
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            epoch_loss += loss.item()
            epoch_steps += 1
            global_step += 1

            if global_step % 10 == 0:
                avg_loss = epoch_loss / epoch_steps
                logger.info(f"Epoch {epoch+1}/{num_epochs} Step {global_step} - Loss: {avg_loss:.4f}")

        avg_epoch_loss = epoch_loss / max(epoch_steps, 1)
        total_loss += epoch_loss
        logger.info(f"Epoch {epoch+1}/{num_epochs} 完成 - 平均 Loss: {avg_epoch_loss:.4f}")

    # 保存模型
    os.makedirs(output_dir, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    # 保存训练配置
    config = {
        "base_model": model_name,
        "data_dir": data_dir,
        "batch_size": batch_size,
        "num_epochs": num_epochs,
        "learning_rate": learning_rate,
        "matryoshka_dims": matryoshka_dims,
        "num_samples": len(samples),
        "num_categories": len(categories),
        "final_loss": total_loss / max(global_step, 1),
    }
    with open(os.path.join(output_dir, "training_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info(f"训练完成，模型保存至: {output_dir}")


def evaluate(model_path: str, data_dir: str) -> None:
    """评估微调后的模型（余弦相似度分类准确率）。"""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    local_model_path = _find_local_model(model_path)
    load_path = local_model_path or model_path

    try:
        tokenizer = transformers.BertTokenizer.from_pretrained(load_path)
    except Exception:
        tokenizer = transformers.AutoTokenizer.from_pretrained(load_path, use_fast=False)
    model = transformers.AutoModel.from_pretrained(load_path)
    model.to(device)
    model.eval()

    samples = collect_samples(data_dir)
    by_category: dict[str, List[str]] = {}
    for cat, path in samples:
        by_category.setdefault(cat, []).append(path)
    categories = list(by_category.keys())

    # 每个类别取前 5 个样本计算类别中心
    max_length = 510
    centers: dict[str, torch.Tensor] = {}

    for cat in categories:
        texts = [extract_key_sections(read_text(p)) for p in by_category[cat][:5]]
        texts = [t for t in texts if t]
        if not texts:
            continue

        tokens = tokenizer(texts, max_length=max_length, padding=True, truncation=True, return_tensors="pt")
        tokens = {k: v.to(device) for k, v in tokens.items()}

        with torch.no_grad():
            outputs = model(**tokens)
            emb = mean_pool(outputs.last_hidden_state, tokens["attention_mask"])
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            centers[cat] = emb.mean(dim=0)

    # 对每个样本计算与各类别中心的相似度
    correct = 0
    total = 0

    for cat in categories:
        for path in by_category[cat][5:10]:  # 用不同的样本评估
            text = extract_key_sections(read_text(path))
            if not text:
                continue

            tokens = tokenizer([text], max_length=max_length, padding=True, truncation=True, return_tensors="pt")
            tokens = {k: v.to(device) for k, v in tokens.items()}

            with torch.no_grad():
                outputs = model(**tokens)
                emb = mean_pool(outputs.last_hidden_state, tokens["attention_mask"])
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)

            best_cat = None
            best_sim = -1.0
            for center_cat, center_emb in centers.items():
                sim = torch.nn.functional.cosine_similarity(emb, center_emb.unsqueeze(0)).item()
                if sim > best_sim:
                    best_sim = sim
                    best_cat = center_cat

            if best_cat == cat:
                correct += 1
            total += 1

    accuracy = correct / max(total, 1)
    logger.info(f"评估结果 - 分类准确率: {accuracy:.4f} ({correct}/{total})")
    return accuracy


def cross_validate(
    data_dir: str,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 8,
    num_epochs: int = 10,
    learning_rate: float = 2e-5,
    num_folds: int = 5,
    max_length: int = 510,
    model_path: str | None = None,
) -> dict:
    """5-fold 交叉验证，评估模型鲁棒性。

    将数据按类别分层划分为 num_folds 份，
    每次用 1 份作为验证集，其余 4 份作为训练集。

    如果提供 model_path，从微调模型开始（迁移学习评估）；
    否则从基础模型开始（训练方法论评估）。
    """
    import tempfile

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"交叉验证设备: {device}, folds={num_folds}")

    samples = collect_samples(data_dir)
    if len(samples) < 20:
        logger.error(f"样本不足（至少20个），当前: {len(samples)}")
        return {}

    # 按类别分组
    by_category: dict[str, List[str]] = {}
    for cat, path in samples:
        by_category.setdefault(cat, []).append(path)

    # 确定基础模型路径
    if model_path and os.path.isdir(model_path):
        base_load_path = model_path
        logger.info(f"交叉验证从微调模型开始: {model_path}")
    else:
        local_path = _find_local_model(model_name)
        base_load_path = local_path or model_name
        logger.info(f"交叉验证从基础模型开始: {base_load_path}")

    # 每个类别内 shuffle 后划分 fold
    fold_results = []
    for fold in range(num_folds):
        logger.info(f"--- Fold {fold + 1}/{num_folds} ---")

        val_pairs = []
        train_dir = tempfile.mkdtemp(prefix="cv_train_")

        for cat, paths in by_category.items():
            random.shuffle(paths)
            fold_size = max(1, len(paths) // num_folds)
            val_start = fold * fold_size
            val_end = (fold + 1) * fold_size if fold < num_folds - 1 else len(paths)

            val_paths = paths[val_start:val_end]
            train_paths = paths[:val_start] + paths[val_end:]

            # 写入训练目录
            cat_train_dir = os.path.join(train_dir, cat)
            os.makedirs(cat_train_dir, exist_ok=True)
            for tp in train_paths:
                fname = os.path.basename(tp)
                dest = os.path.join(cat_train_dir, fname)
                try:
                    with open(tp, "r", encoding="utf-8", errors="replace") as f_src:
                        with open(dest, "w", encoding="utf-8") as f_dst:
                            f_dst.write(f_src.read())
                except Exception:
                    pass

            # 记录验证集
            for vp in val_paths:
                val_pairs.append((cat, read_text(vp)))

        # 训练：从基础/微调模型开始，在 fold 训练集上继续微调
        fold_output = tempfile.mkdtemp(prefix="cv_model_")
        fold_model = transformers.AutoModel.from_pretrained(base_load_path)
        fold_model.to(device)
        fold_model.train()

        try:
            tokenizer = transformers.BertTokenizer.from_pretrained(base_load_path)
        except Exception:
            tokenizer = transformers.AutoTokenizer.from_pretrained(base_load_path, use_fast=False)
        train_samples = collect_samples(train_dir)
        train_by_cat: dict[str, List[str]] = {}
        for cat, path in train_samples:
            train_by_cat.setdefault(cat, []).append(path)
        categories = list(train_by_cat.keys())

        optimizer = torch.optim.AdamW(fold_model.parameters(), lr=learning_rate)

        for epoch in range(num_epochs):
            # 构建训练对：每个类别生成更多 pair
            pairs: List[Tuple[str, str, str | None]] = []
            for cat in categories:
                paths = train_by_cat[cat]
                if len(paths) >= 2:
                    # 使用更多 pair（上限为类别样本数的一半）
                    num_pairs = min(len(paths) // 2, batch_size * 2)
                    for i in range(num_pairs):
                        a_idx = i % len(paths)
                        p_idx = (i + 1) % len(paths)
                        neg_cat = random.choice([c for c in categories if c != cat])
                        neg_path = random.choice(train_by_cat[neg_cat])
                        pairs.append((paths[a_idx], paths[p_idx], neg_path))
                elif len(paths) == 1:
                    neg_cat = random.choice([c for c in categories if c != cat])
                    neg_path = random.choice(train_by_cat[neg_cat])
                    pairs.append((paths[0], paths[0], neg_path))

            random.shuffle(pairs)
            for batch_start in range(0, len(pairs), batch_size):
                batch_pairs = pairs[batch_start:batch_start + batch_size]
                if len(batch_pairs) < 2:
                    continue

                anchor_texts = [extract_key_sections(read_text(a)) for a, _, _ in batch_pairs]
                anchor_texts = [t for t in anchor_texts if t]
                positive_texts = [extract_key_sections(read_text(p)) for _, p, _ in batch_pairs]
                positive_texts = [t for t in positive_texts if t]
                if len(anchor_texts) < 2 or len(positive_texts) < 2:
                    continue

                anchor_tokens = tokenizer(anchor_texts, max_length=max_length, padding=True, truncation=True, return_tensors="pt")
                anchor_tokens = {k: v.to(device) for k, v in anchor_tokens.items()}
                positive_tokens = tokenizer(positive_texts, max_length=max_length, padding=True, truncation=True, return_tensors="pt")
                positive_tokens = {k: v.to(device) for k, v in positive_tokens.items()}

                # Hard negative
                neg_texts = [extract_key_sections(read_text(n)) for _, _, n in batch_pairs]
                neg_texts = [t for t in neg_texts if t]
                neg_emb = None
                if len(neg_texts) >= 2:
                    neg_tokens = tokenizer(neg_texts, max_length=max_length, padding=True, truncation=True, return_tensors="pt")
                    neg_tokens = {k: v.to(device) for k, v in neg_tokens.items()}
                    with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                        neg_out = fold_model(**neg_tokens)
                        neg_emb = mean_pool(neg_out.last_hidden_state, neg_tokens["attention_mask"])
                        neg_emb = torch.nn.functional.normalize(neg_emb, p=2, dim=1)

                with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                    anchor_out = fold_model(**anchor_tokens)
                    positive_out = fold_model(**positive_tokens)
                    anchor_emb = mean_pool(anchor_out.last_hidden_state, anchor_tokens["attention_mask"])
                    positive_emb = mean_pool(positive_out.last_hidden_state, positive_tokens["attention_mask"])
                    anchor_emb = torch.nn.functional.normalize(anchor_emb, p=2, dim=1)
                    positive_emb = torch.nn.functional.normalize(positive_emb, p=2, dim=1)

                    temperature = 0.05
                    scores = torch.matmul(anchor_emb, positive_emb.t()) / temperature
                    if neg_emb is not None and neg_emb.size(0) == anchor_emb.size(0):
                        neg_scores = torch.matmul(anchor_emb, neg_emb.t()) / temperature
                        scores = torch.cat([scores, neg_scores], dim=1)

                    labels = torch.arange(scores.size(0), device=scores.device)
                    loss = torch.nn.functional.cross_entropy(scores, labels)

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(fold_model.parameters(), 1.0)
                optimizer.step()

        # 评估 fold：使用所有训练样本计算类别中心
        fold_model.eval()
        # 预计算所有训练样本的类别中心
        centers: dict[str, torch.Tensor] = {}
        for tc in categories:
            tc_texts = [extract_key_sections(read_text(p)) for p in train_by_cat[tc]]
            tc_texts = [t for t in tc_texts if t]
            if not tc_texts:
                continue
            # 分批编码，避免 OOM
            all_embs = []
            for tc_batch_start in range(0, len(tc_texts), batch_size):
                tc_batch = tc_texts[tc_batch_start:tc_batch_start + batch_size]
                tc_tokens = tokenizer(tc_batch, max_length=max_length, padding=True, truncation=True, return_tensors="pt")
                tc_tokens = {k: v.to(device) for k, v in tc_tokens.items()}
                with torch.no_grad():
                    tc_out = fold_model(**tc_tokens)
                    tc_emb = mean_pool(tc_out.last_hidden_state, tc_tokens["attention_mask"])
                    tc_emb = torch.nn.functional.normalize(tc_emb, p=2, dim=1)
                    all_embs.append(tc_emb)
            if all_embs:
                centers[tc] = torch.cat(all_embs, dim=0).mean(dim=0)

        correct = 0
        total = 0
        for cat, text in val_pairs:
            text = extract_key_sections(text)
            if not text:
                continue

            tokens = tokenizer([text], max_length=max_length, padding=True, truncation=True, return_tensors="pt")
            tokens = {k: v.to(device) for k, v in tokens.items()}
            with torch.no_grad():
                out = fold_model(**tokens)
                emb = mean_pool(out.last_hidden_state, tokens["attention_mask"])
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)

            # 与所有训练样本的类别中心比较
            best_cat = None
            best_sim = -1.0
            for tc, center_emb in centers.items():
                sim = torch.nn.functional.cosine_similarity(emb, center_emb.unsqueeze(0)).item()
                if sim > best_sim:
                    best_sim = sim
                    best_cat = tc

            if best_cat == cat:
                correct += 1
            total += 1

        fold_acc = correct / max(total, 1)
        fold_results.append(fold_acc)
        logger.info(f"Fold {fold + 1} 准确率: {fold_acc:.4f} ({correct}/{total})")

        # 清理临时文件
        del fold_model
        import shutil
        shutil.rmtree(train_dir, ignore_errors=True)
        shutil.rmtree(fold_output, ignore_errors=True)

    # 汇总
    mean_acc = sum(fold_results) / len(fold_results)
    std_acc = (sum((x - mean_acc) ** 2 for x in fold_results) / len(fold_results)) ** 0.5
    logger.info(f"交叉验证完成 - 平均准确率: {mean_acc:.4f} +- {std_acc:.4f}")
    logger.info(f"各 Fold 准确率: {[f'{x:.4f}' for x in fold_results]}")

    return {
        "mean_accuracy": mean_acc,
        "std_accuracy": std_acc,
        "fold_results": fold_results,
        "num_folds": num_folds,
        "num_samples": len(samples),
    }


def main():
    parser = argparse.ArgumentParser(description="MiniLM 领域对比微调（轻量版）")
    parser.add_argument("--data_dir", required=True, help="训练数据目录")
    parser.add_argument("--output_dir", default="models/minilm-minecraft", help="模型输出目录")
    parser.add_argument("--model_name", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--num_epochs", type=int, default=3)
    parser.add_argument("--learning_rate", type=float, default=2e-5)
    parser.add_argument("--matryoshka_dims", type=str, default=None,
                        help="Matryoshka 维度，逗号分隔，如 768,384,192,96")
    parser.add_argument("--eval_only", action="store_true", help="仅评估模式")
    parser.add_argument("--cross_validate", action="store_true", help="5-fold 交叉验证")
    parser.add_argument("--model_path", default=None, help="评估用的模型路径")
    args = parser.parse_args()

    matryoshka_dims = None
    if args.matryoshka_dims:
        matryoshka_dims = [int(d) for d in args.matryoshka_dims.split(",")]

    if args.cross_validate:
        result = cross_validate(
            data_dir=args.data_dir,
            model_name=args.model_name,
            batch_size=args.batch_size,
            num_epochs=args.num_epochs,
            learning_rate=args.learning_rate,
            model_path=args.model_path,
        )
        import json
        cv_path = os.path.join(args.output_dir, "cross_validation.json")
        os.makedirs(args.output_dir, exist_ok=True)
        with open(cv_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"交叉验证结果已保存至: {cv_path}")
    elif args.eval_only:
        model_path = args.model_path or args.output_dir
        evaluate(model_path, args.data_dir)
    else:
        finetune(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            model_name=args.model_name,
            batch_size=args.batch_size,
            num_epochs=args.num_epochs,
            learning_rate=args.learning_rate,
            matryoshka_dims=matryoshka_dims,
        )


if __name__ == "__main__":
    main()
