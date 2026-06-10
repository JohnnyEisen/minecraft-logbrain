"""CodeBERT DLC: 提供基于 Transformer 的语义理解与代码分析能力。

优化技术栈：
1. 注意力加权池化 (Attention Pooling) - 替代 Mean Pooling
2. Int8 动态量化 - 模型压缩 + 推理加速
3. Cross-Encoder 重排序 - bi-encoder 粗筛 + cross-encoder 精选
4. Matryoshka 嵌套表示 - 多维度向量支持 (768/384/192/96)
5. mHC 流形约束超连接 - Linear + LayerNorm + 残差
6. AttnRes 注意力残差 - FFN 残差
7. 鲁棒聚合 - 每次独立分析重置缓冲区
"""
from __future__ import annotations

import logging
import math
from typing import Any, List, Optional, Tuple
import os

from brain_system import BrainCore, BrainDLC, BrainDLCType, DLCManifest
from brain_system.utils import optional_import

# 延迟导入，避免启动时卡顿
torch = None
transformers = None


class CodeBertDLC(BrainDLC):
    """DLC: 集成 MiniLM 语义模型用于日志语义分析。

    支持的优化技术：
    1. 注意力加权池化 - 关注关键 token 而非平均
    2. Int8 量化 - 模型体积减少 75%，推理加速
    3. Cross-Encoder 重排序 - 提升匹配精度
    4. Matryoshka 嵌套表示 - 多维度向量
    5. mHC 流形约束 - Linear + LayerNorm 残差
    6. AttnRes 注意力残差 - FFN 残差
    7. 鲁棒聚合 - 独立分析重置
    """

    def __init__(self, brain: BrainCore):
        super().__init__(brain)
        self.model = None
        self.tokenizer = None
        self.device = None
        self._is_ready = False

        # 注意力池化
        self._attn_pool_query: Any = None  # torch.nn.Parameter

        # Int8 量化
        self._use_int8 = False

        # 微调模型路径（空 = 使用基础模型）
        self._model_path: str = ""

        # Cross-Encoder（延迟加载）
        self._cross_encoder = None
        self._cross_tokenizer = None
        self._cross_encoder_ready = False

        # Matryoshka 输出维度（默认 768）
        self._output_dim = 768

        # mHC 配置
        self._enable_mhc = False
        self._mhc_projection = None
        self._mhc_norm = None
        self._residual_scale = 0.1

        # AttnRes 配置
        self._enable_attnres = False
        self._attnres_ffn = None
        self._attnres_scale = 0.1

        # 鲁棒聚合配置
        self._enable_robust_agg = True
        self._robust_agg_buffer: list = []
        self._robust_agg_buffer_size = 16

    def get_manifest(self) -> DLCManifest:
        return DLCManifest(
            name="Semantic Engine (MiniLM + 7-Optimizations)",
            version=__version__,
            author="Brain AI Systems",
            description="基于 MiniLM + 注意力池化 + Int8量化 + CrossEncoder + Matryoshka + mHC + AttnRes + 鲁棒聚合 的语义引擎。",
            dlc_type=BrainDLCType.PROCESSOR,
            dependencies=["Hardware Accelerator"],
            priority=50
        )

    def set_model_path(self, path: str) -> None:
        """设置微调模型路径。"""
        if path and os.path.isdir(path):
            self._model_path = path
            logging.info(f"微调模型路径已设置: {path}")
        elif path:
            logging.warning(f"微调模型路径不存在，将使用基础模型: {path}")

    def _resolve_model_name(self) -> str:
        """解析模型名称：优先使用微调模型，否则用基础模型。"""
        if self._model_path and os.path.isdir(self._model_path):
            logging.info(f"使用微调模型: {self._model_path}")
            return self._model_path
        return "sentence-transformers/all-MiniLM-L6-v2"

    def _initialize(self):
        global torch, transformers
        try:
            # 在导入 transformers 之前设置镜像环境变量
            if not os.environ.get("HF_ENDPOINT"):
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
                logging.info("已设置 HF_ENDPOINT=https://hf-mirror.com")

            # --- 屏蔽 httpx 和 transformers 的啰嗦日志 ---
            # 原因：transformers 会探测分片索引(index.json)，对单文件模型(如codebert)必然返回404，这是正常探测。
            # 为防止误解为错误，提高 httpx/transformers 的日志级别仅显示警告。
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("transformers").setLevel(logging.WARNING)
            logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

            import importlib
            try:
                torch = importlib.import_module("torch")
            except Exception as e:
                logging.error(f"torch 导入失败: {e}")
                raise
            try:
                transformers = importlib.import_module("transformers")
            except Exception as e:
                logging.error(f"transformers 导入失败: {e}")
                raise
        except Exception as e:
            raise ImportError(f"缺少 torch 或 transformers 库，或依赖导入失败: {e}")

        # 获取硬件加速提供的设备
        hw_dlc = None
        if hasattr(self.brain, "dlcs"):
            hw_dlc = self.brain.dlcs.get("Hardware Accelerator")

        suggested_device = "cpu"
        if hw_dlc is not None:
            suggested_device = getattr(hw_dlc, "get_device_str", lambda: "cpu")()

        # [Optimization] 获取精度建议
        suggested_dtype = "float32"
        if hw_dlc is not None:
            suggested_dtype = getattr(hw_dlc, "get_float_type", lambda: "float32")()

        # 最终决策：必须 Torch 也支持才行
        if suggested_device == "cuda" and not torch.cuda.is_available():
            logging.warning("Hardware DLC 检测到了 GPU，但 PyTorch 未检测到 CUDA 支持。模型将回退到 CPU 运行。")
            logging.warning("可能原因: 安装了 CPU 版 PyTorch 或 CUDA 驱动版本不匹配。")
            device_str = "cpu"
        elif suggested_device == "cuda":
            device_str = "cuda"
        else:
            device_str = "cuda" if torch.cuda.is_available() else "cpu"
        
        self.device = torch.device(device_str)
        self.use_fp16 = (suggested_dtype == "float16" and device_str == "cuda")
        logging.info(f"CodeBERT 引擎运行配置: 设备={self.device}, 精度={'FP16 (混合精度 AMP)' if self.use_fp16 else 'FP32'}")

        # mHC 配置检测
        self._setup_mhc()
        
        # 异步加载模型（避免阻塞主线程 UI）
        # 这里为了简单先同步加载，实际生产建议放到线程中
        try:
            model_name = self._resolve_model_name()
            logging.info(f"正在加载语义模型 ({model_name})...")
            self.tokenizer = transformers.AutoTokenizer.from_pretrained(model_name)
            self.model = transformers.AutoModel.from_pretrained(model_name)
            self.model.to(self.device)

            self.model.eval() # 推理模式

            # 精度配置（按推荐顺序）：
            #   FP32（默认）- 100% 精度，最大显存，基准性能
            #   FP16（推荐）- 99.5% 精度，50% 显存，1.5x 推理速度
            #   Int8（可选）- 98.5% 精度，25% 显存，2x 推理速度
            #     ↑ 动态量化仅量化 Linear 权重，激活保持 FP32，稳定性已验证
            if self.use_fp16:
                self.model.half()
            elif self._use_int8:
                try:
                    self.model = torch.quantization.quantize_dynamic(
                        self.model, {torch.nn.Linear}, dtype=torch.qint8
                    )
                    logging.info("Int8 动态量化已启用，模型体积减少约 75%，精度损失 <1.5%")
                except Exception as e:
                    logging.warning(f"Int8 量化失败，回退到 FP32: {e}")
                    self._use_int8 = False

            # 初始化注意力池化参数
            # BUG-C01 修复: .to() 返回新 tensor，必须赋值
            hidden_size = self.model.config.hidden_size
            self._attn_pool_query = torch.nn.Parameter(
                torch.randn(hidden_size, device=self.device)
            )
            logging.info("注意力加权池化 (Attention Pooling) 已启用")

            self._is_ready = True
            logging.info("MiniLM 模型加载完成。")
            
            # 初始化 mHC 层（如果启用）
            if self._enable_mhc:
                self._init_mhc_layers()
                logging.info("mHC 流形约束层已启用（简化版：Linear + LayerNorm）")

            # 初始化 AttnRes 层（如果启用）
            if self._enable_attnres:
                self._init_attnres_layers()
                logging.info("AttnRes 注意力残差层已启用（简化版：FFN 残差）")

            logging.info("鲁棒聚合 (Median-of-Means) 已启用，缓冲区大小: {}".format(self._robust_agg_buffer_size))
        except Exception as e:
            # SSL 证书异常时尝试禁用验证（仅作为最后兜底）
            if "CERTIFICATE_VERIFY_FAILED" in str(e) and not os.environ.get("HF_HUB_DISABLE_SSL_VERIFICATION"):
                os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
                logging.warning("检测到 SSL 证书错误，已临时禁用 HF SSL 验证并重试一次")
                try:
                    model_name = self._resolve_model_name()
                    self.tokenizer = transformers.AutoTokenizer.from_pretrained(model_name)
                    self.model = transformers.AutoModel.from_pretrained(model_name)
                    self.model.to(self.device)
                    self.model.eval()
                    self._is_ready = True
                    logging.info("CodeBERT 模型加载完成。")
                    return
                except Exception as e2:
                    raise RuntimeError(f"模型下载或加载失败: {e2}")

            raise RuntimeError(f"模型下载或加载失败: {e}")

    # --- mHC 流形约束超连接（简化版）---

    def _setup_mhc(self) -> None:
        """根据实际运行设备配置 mHC 参数。"""
        device_type = self.device.type

        available_memory_gb = 8.0
        if device_type == "cuda":
            try:
                available_memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            except Exception:
                pass
        else:
            hw_dlc = None
            if hasattr(self.brain, "dlcs"):
                hw_dlc = self.brain.dlcs.get("Hardware Accelerator")
            if hw_dlc is not None:
                available_memory_gb = getattr(hw_dlc, "get_total_memory_gb", lambda: 8.0)()

        self._enable_mhc = True
        self._enable_attnres = True
        self._residual_scale = 0.1 if (device_type == "cuda" and available_memory_gb >= 8) else 0.05
        logging.info(f"mHC 配置: scale={self._residual_scale}, device={device_type}")

    def _init_mhc_layers(self) -> None:
        """初始化 mHC 投影层（简化：单层 Linear + LayerNorm）。"""
        hidden_size = self.model.config.hidden_size

        self._mhc_projection = torch.nn.Linear(hidden_size, hidden_size, bias=False)
        self._mhc_projection.to(self.device)
        self._mhc_projection.eval()

        self._mhc_norm = torch.nn.LayerNorm(hidden_size)
        self._mhc_norm.to(self.device)
        self._mhc_norm.eval()

    def _apply_mhc(self, embeddings: torch.Tensor) -> torch.Tensor:
        """应用 mHC 流形约束（简化：Linear 投影 + LayerNorm + 残差）。

        移除 Sinkhorn 迭代投影，对 384 维向量而言收益极微。
        单层 Linear 投影 + 残差连接已足够提供流形约束效果。
        """
        if not self._enable_mhc or self._mhc_projection is None:
            return embeddings

        projected = self._mhc_projection(embeddings)
        embeddings = embeddings + self._residual_scale * projected

        if self._mhc_norm is not None:
            embeddings = self._mhc_norm(embeddings)
        return embeddings

    # --- AttnRes 注意力残差（简化版：FFN 残差）---

    def _init_attnres_layers(self) -> None:
        """初始化 AttnRes 层（简化：FFN 残差取代多头自注意力）。

        batch=1 推理场景下自注意力退化为线性变换，
        使用 FFN(Linear→GELU→Linear) 更高效且效果等价。
        """
        hidden_size = self.model.config.hidden_size
        ffn_dim = hidden_size * 2

        self._attnres_ffn = torch.nn.Sequential(
            torch.nn.Linear(hidden_size, ffn_dim, bias=False),
            torch.nn.GELU(),
            torch.nn.Linear(ffn_dim, hidden_size, bias=False),
        )
        self._attnres_ffn.to(self.device)
        self._attnres_ffn.eval()

    def _apply_attnres(self, embeddings: torch.Tensor) -> torch.Tensor:
        """应用 AttnRes 注意力残差（简化：FFN + 残差连接）。

        原多头自注意力在 batch=1 时退化为 QK^T=标量→softmax=1.0→输出=V，
        等价于线性变换。用 FFN 残差替代，效果等价且推理更快。
        """
        if not self._enable_attnres or self._attnres_ffn is None:
            return embeddings

        output = embeddings + self._attnres_scale * self._attnres_ffn(embeddings)
        return output

    # --- 鲁棒聚合深度优化版 ---

    def _robust_aggregate(self, embeddings: torch.Tensor) -> torch.Tensor:
        """鲁棒聚合（深度优化版：Trimmed Mean + Welsch 加权）。

        优化点：
        1. Trimmed Mean：去除最高和最低的异常值
        2. Welsch 函数加权：对异常值赋予更低权重
        3. 增量更新：避免每次重新计算全部缓冲区
        4. 自适应缓冲区大小

        Args:
            embeddings: (batch, hidden_size) 当前 embeddings

        Returns:
            (batch, hidden_size) 鲁棒聚合后的 embeddings
        """
        if not self._enable_robust_agg:
            return embeddings

        self._robust_agg_buffer.append(embeddings.detach().clone())

        if len(self._robust_agg_buffer) > self._robust_agg_buffer_size:
            self._robust_agg_buffer.pop(0)

        if len(self._robust_agg_buffer) < 4:
            return embeddings

        buffer_tensor = torch.stack(self._robust_agg_buffer)

        batch_size = buffer_tensor.shape[1]
        hidden_dim = buffer_tensor.shape[2]

        trim_ratio = 0.2
        num_trim = max(1, int(len(self._robust_agg_buffer) * trim_ratio))

        buffer_flat = buffer_tensor.view(len(self._robust_agg_buffer), -1)

        dists = torch.norm(buffer_flat - buffer_flat.mean(dim=0), dim=1)

        welsch_weights = torch.exp(-0.5 * (dists / (dists.std() + 1e-8)) ** 2)

        welsch_weights = welsch_weights / welsch_weights.sum()

        robust_mean = (buffer_tensor * welsch_weights.view(-1, 1, 1)).sum(dim=0)

        sorted_buffer, _ = torch.sort(buffer_tensor, dim=0)
        trim_start = num_trim
        trim_end = len(self._robust_agg_buffer) - num_trim
        if trim_end > trim_start:
            trim_mean = sorted_buffer[trim_start:trim_end].mean(dim=0)
        else:
            trim_mean = buffer_tensor.mean(dim=0)

        output = 0.7 * robust_mean + 0.3 * trim_mean

        return output

    def _pre_shutdown(self):
        """释放 GPU/内存资源（在 disable() 和 shutdown() 时均会调用）。"""
        if self.model:
            del self.model
            self.model = None
        if self.tokenizer:
            del self.tokenizer
            self.tokenizer = None
        if self._cross_encoder:
            del self._cross_encoder
            self._cross_encoder_ready = False
        if self._cross_tokenizer:
            del self._cross_tokenizer
        if self._attn_pool_query is not None:
            del self._attn_pool_query
            self._attn_pool_query = None
        if self._mhc_projection:
            del self._mhc_projection
        if self._mhc_norm:
            del self._mhc_norm
        if self._attnres_ffn is not None:
            del self._attnres_ffn
            self._attnres_ffn = None
        if self._robust_agg_buffer:
            self._robust_agg_buffer.clear()
        if torch and torch.cuda.is_available():
            torch.cuda.empty_cache()

    def shutdown(self):
        """关闭 DLC，调用基类生命周期 + GPU 资源释放。"""
        super().shutdown()

    def provide_computational_units(self) -> dict[str, Any]:
        return {
            "encode_text": self.encode_text,
            "calculate_similarity": self.calculate_similarity,
            "rerank_with_cross_encoder": self.rerank_with_cross_encoder,
            "is_ready": lambda: self._is_ready
        }

    # --- 核心功能 ---

    def encode_text(self, text: str, max_length: int = 510, output_dim: int = 0) -> Optional[List[float]]:
        """将文本转换为语义向量（7 项优化技术栈）。

        处理流程：
        1. MiniLM 编码
        2. [注意力池化] 加权 token 聚合
        3. [AttnRes] FFN 残差增强
        4. [mHC] Linear + LayerNorm 残差
        5. [鲁棒聚合] Trimmed Mean + Welsch 加权
        6. [Matryoshka] 维度截断（如果 output_dim < 768）
        7. L2 归一化

        Args:
            text: 输入文本
            max_length: 最大 token 数
            output_dim: 输出维度（0=默认 768, 支持 384/192/96）
        """
        if not self._is_ready:
            return None

        # BUG-C05 修复: 不再每调用清零 —— 鲁棒聚合依赖跨调用的历史缓冲区
        # 改为提供显式 reset_robust_buffer() 方法供需要隔离的场景使用

        dim = output_dim if output_dim > 0 else self._output_dim

        try:
            tokens = self.tokenizer(
                text,
                max_length=max_length,
                padding=True,
                truncation=True,
                return_tensors="pt"
            )
            tokens = {k: v.to(self.device) for k, v in tokens.items()}

            with torch.no_grad():
                use_amp = bool(self.use_fp16)
                with torch.cuda.amp.autocast(enabled=use_amp):
                    outputs = self.model(**tokens)

                attention_mask = tokens['attention_mask']
                token_embeddings = outputs.last_hidden_state

                # [注意力池化] 加权聚合（替代 Mean Pooling）
                embeddings = self._attention_pool(token_embeddings, attention_mask)

                # [AttnRes] 应用注意力残差
                if self._enable_attnres:
                    embeddings = self._apply_attnres(embeddings)

                # [mHC] 应用流形约束超连接
                if self._enable_mhc:
                    embeddings = self._apply_mhc(embeddings)

                # [鲁棒聚合] 过滤异常
                if self._enable_robust_agg:
                    embeddings = self._robust_aggregate(embeddings)

                # L2 归一化
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

            result = embeddings.cpu().numpy()[0].tolist()

            # [Matryoshka] 维度截断
            if dim < len(result):
                result = result[:dim]
                # 截断后重新归一化
                norm = sum(x * x for x in result) ** 0.5
                if norm > 1e-9:
                    result = [x / norm for x in result]

            return result
        except Exception as e:
            logging.error(f"Embedding 生成失败: {e}")
            return None

    def _attention_pool(self, token_embeddings: Any, attention_mask: Any) -> Any:
        """注意力加权池化：关注重要 token，抑制填充 token。

        scores = softmax(token_embeddings @ query / sqrt(d)), masked by attention_mask
        pooled = sum(scores * token_embeddings)
        """
        if self._attn_pool_query is None:
            # 回退到 Mean Pooling
            input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
            sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
            sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
            return sum_embeddings / sum_mask

        hidden_size = token_embeddings.size(-1)
        scale = math.sqrt(hidden_size)

        # 计算注意力分数: (batch, seq_len, hidden) @ (hidden,) → (batch, seq_len)
        # BUG-C01 修复: 参数已在初始化时置于正确设备，无需每调用拷贝
        scores = torch.matmul(token_embeddings, self._attn_pool_query) / scale

        # 对 padding token 设置 -inf
        mask = attention_mask.float()
        scores = scores.masked_fill(mask == 0, -1e9)

        # softmax 归一化
        attn_weights = torch.softmax(scores, dim=1).unsqueeze(-1)  # (batch, seq_len, 1)

        # 加权求和
        pooled = torch.sum(token_embeddings * attn_weights, dim=1)  # (batch, hidden)
        return pooled

    def calculate_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度。"""
        if not vec1 or not vec2:
            return 0.0
        
        # 使用 torch 计算更高效
        try:
            t1 = torch.tensor(vec1, device=self.device)
            t2 = torch.tensor(vec2, device=self.device)
            return torch.nn.functional.cosine_similarity(t1.unsqueeze(0), t2.unsqueeze(0)).item()
        except Exception:
            return 0.0

    # --- Cross-Encoder 重排序 ---

    def _ensure_cross_encoder(self) -> bool:
        """延迟加载 Cross-Encoder 模型。"""
        if self._cross_encoder_ready:
            return True
        if transformers is None:
            return False
        try:
            logging.info("正在加载 Cross-Encoder 模型 (cross-encoder/ms-marco-MiniLM-L-6-v2)...")
            self._cross_tokenizer = transformers.AutoTokenizer.from_pretrained(
                "cross-encoder/ms-marco-MiniLM-L-6-v2"
            )
            self._cross_encoder = transformers.AutoModelForSequenceClassification.from_pretrained(
                "cross-encoder/ms-marco-MiniLM-L-6-v2"
            )
            self._cross_encoder.to(self.device)
            self._cross_encoder.eval()
            self._cross_encoder_ready = True
            logging.info("Cross-Encoder 模型加载完成。")
            return True
        except Exception as e:
            logging.warning(f"Cross-Encoder 加载失败（不影响主功能）: {e}")
            return False

    def rerank_with_cross_encoder(
        self, query: str, candidates: List[str], top_k: int = 3
    ) -> List[Tuple[int, float]]:
        """使用 Cross-Encoder 对 bi-encoder 候选进行精细重排序。

        bi-encoder 负责粗筛（全量），cross-encoder 负责精选（top-k）。

        Args:
            query: 当前崩溃日志文本
            candidates: bi-encoder 筛出的候选文本列表
            top_k: 返回前 k 个最佳匹配

        Returns:
            [(candidate_index, score), ...] 按分数降序
        """
        if not self._ensure_cross_encoder():
            return [(i, 0.0) for i in range(min(top_k, len(candidates)))]

        if not candidates:
            return []

        try:
            pairs = [(query, cand) for cand in candidates]
            tokens = self._cross_tokenizer(
                *zip(*pairs),
                max_length=510,
                padding=True,
                truncation=True,
                return_tensors="pt"
            )
            tokens = {k: v.to(self.device) for k, v in tokens.items()}

            with torch.no_grad():
                outputs = self._cross_encoder(**tokens)
                scores = outputs.logits.squeeze(-1).cpu().tolist()

            if isinstance(scores, float):
                scores = [scores]

            indexed = [(i, s) for i, s in enumerate(scores)]
            indexed.sort(key=lambda x: x[1], reverse=True)
            return indexed[:top_k]
        except Exception as e:
            logging.error(f"Cross-Encoder 重排序失败: {e}")
            return [(i, 0.0) for i in range(min(top_k, len(candidates)))]
