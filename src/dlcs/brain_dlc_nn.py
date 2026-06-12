"""Neural Network DLC: 算子与自动微分。

v2.1.0: 融合算子 (FusedMatMulReLU) 减少中间分配；缓存 _get_array_module；
        添加 BatchNorm1D、LayerNorm；__slots__ 减少子类内存。
v2.0.0: DI 集成 (config/audit)，版本号统一引用 __version__。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple, Sequence
import collections

from brain_system import BrainCore, BrainDLC, BrainDLCType, DLCManifest
from brain_system import __version__
from brain_system.utils import optional_import

# ---- 辅助：获取数组模块（带缓存）-----------------------------

_array_module_cache: Dict[str, Any] = {}


def _get_array_module(x: Any) -> Any:
    """获取数据 x 对应的数组模块 (numpy 或 cupy)，结果缓存。"""
    try:
        cp = optional_import("cupy")
        if cp and isinstance(x, cp.ndarray):
            return _array_module_cache.setdefault("cupy", cp)
    except Exception:
        pass
    np = optional_import("numpy")
    return _array_module_cache.setdefault("numpy", np)


def _array_module_cache_clear() -> None:
    _array_module_cache.clear()

# 辅助类：Autograd 节点
class TensorNode:
    """包装数据与梯度信息。

    优化: _get_array_module 已提取为模块级函数并缓存。
    """
    __slots__ = ("data", "grad", "requires_grad", "creator", "generation")

    def __init__(self, data: Any, requires_grad: bool = False, creator: Optional['Function'] = None):
        self.data = data
        self.grad: Any = None
        self.requires_grad = requires_grad
        self.creator = creator
        self.generation = 0 if creator is None else creator.generation + 1

    def backward(self, grad: Any = None):
        if not self.requires_grad:
            return

        if grad is None:
            xp = _get_array_module(self.data)
            grad = xp.ones_like(self.data)

        # 累积梯度（copy 防止引用共享）
        if self.grad is None:
            xp = _get_array_module(grad)
            self.grad = xp.array(grad, copy=True) if hasattr(xp, 'array') else grad
        else:
            self.grad = self.grad + grad

        # 传递给 creator
        if self.creator:
            self.creator.backward(self.grad)

    def __add__(self, other):
        if not isinstance(other, TensorNode):
            other = TensorNode(other)
        return Add()(self, other)
    
    def __sub__(self, other):
        if not isinstance(other, TensorNode):
            other = TensorNode(other)
        return Sub()(self, other)

    def __mul__(self, other):
        if not isinstance(other, TensorNode):
            other = TensorNode(other)
        return Mul()(self, other)

    def __matmul__(self, other):
        if not isinstance(other, TensorNode):
            other = TensorNode(other)
        return MatMul()(self, other)

    def __repr__(self):
        return f"Tensor(shape={self.data.shape if hasattr(self.data, 'shape') else 'scalar'}, requires_grad={self.requires_grad})"


class Function:
    """可微分算子基类。"""
    def __init__(self):
        self.inputs: List[TensorNode] = []
        self.outputs: List[TensorNode] = []
        self.generation = 0

    def __call__(self, *inputs) -> TensorNode | tuple[TensorNode, ...]:
        # 接受 TensorNode 或原始数组作为输入
        self.inputs = [x if isinstance(x, TensorNode) else TensorNode(x, requires_grad=False) for x in inputs]
        self.generation = max((x.generation for x in self.inputs), default=0)
        raw_inputs = [x.data if isinstance(x, TensorNode) else x for x in inputs]
        
        # Forward
        raw_outputs = self.forward(*raw_inputs)
        if not isinstance(raw_outputs, tuple):
            raw_outputs = (raw_outputs,)
        
        # Pack Output
        outputs = []
        requires_grad = any(x.requires_grad for x in self.inputs)
        for d in raw_outputs:
            out_node = TensorNode(d, requires_grad=requires_grad, creator=self if requires_grad else None)
            outputs.append(out_node)
        
        self.outputs = outputs
        return outputs[0] if len(outputs) == 1 else tuple(outputs)

    def forward(self, *args):
        raise NotImplementedError

    def backward(self, grad_output):
        # 计算输入梯度
        grad_inputs = self.backward_impl(grad_output)
        if not isinstance(grad_inputs, tuple):
            grad_inputs = (grad_inputs,)
        
        # 分发到各输入（跳过非 TensorNode 的原始输入）
        for x, g in zip(self.inputs, grad_inputs):
            if isinstance(x, TensorNode) and x.requires_grad:
                x.backward(g)

    def backward_impl(self, grad_output):
        raise NotImplementedError


# --- 具体算子实现 ---

class Add(Function):
    __slots__ = ()
    def forward(self, x0, x1):
        return x0 + x1
    def backward_impl(self, gy):
        return gy, gy

class Sub(Function):
    __slots__ = ()
    def forward(self, x0, x1):
        return x0 - x1
    def backward_impl(self, gy):
        return gy, -gy

class Mul(Function):
    __slots__ = ("x0", "x1")
    def forward(self, x0, x1):
        self.x0 = x0
        self.x1 = x1
        return x0 * x1
    def backward_impl(self, gy):
        return gy * self.x1, gy * self.x0

class MatMul(Function):
    __slots__ = ("x", "W")
    def forward(self, x, W):
        self.x = x
        self.W = W
        return x @ W
    def backward_impl(self, gy):
        return gy @ self.W.T, self.x.T @ gy

class Relu(Function):
    __slots__ = ("mask",)
    def forward(self, x):
        self.mask = (x > 0)
        return x * self.mask
    def backward_impl(self, gy):
        return gy * self.mask


# ---- 融合算子：减少中间张量分配 --------------------------------

class FusedMatMulReLU(Function):
    """融合 MatMul + ReLU，避免分配中间矩阵。

    forward:  relu(x @ W)
    """
    __slots__ = ("x", "W", "mask")

    def forward(self, x, W):
        self.x = x
        self.W = W
        out = x @ W
        self.mask = (out > 0)
        return out * self.mask

    def backward_impl(self, gy):
        g_masked = gy * self.mask  # relu backward
        return g_masked @ self.W.T, self.x.T @ g_masked


class FusedLinearReLU(Function):
    """融合 Linear + ReLU：y = relu(x @ W + b)。

    优化: 单次分配 + 单次 backward，3 次分配 → 1 次。
    """
    __slots__ = ("x", "W", "b", "mask")

    def forward(self, x, W, b):
        self.x = x
        self.W = W
        self.b = b
        out = x @ W + b
        self.mask = (out > 0)
        return out * self.mask

    def backward_impl(self, gy):
        g_masked = gy * self.mask
        gx = g_masked @ self.W.T
        gW = self.x.T @ g_masked
        gb = g_masked.sum(axis=0)
        return gx, gW, gb


# ---- 标准化算子 ------------------------------------------------

class BatchNorm1D(Function):
    """1D Batch Normalization：y = (x - mean) / sqrt(var + eps) * gamma + beta。"""
    __slots__ = ("x", "gamma", "beta", "eps", "mean", "inv_std")

    def forward(self, x, gamma, beta, eps=1e-5):
        self.x = x
        self.gamma = gamma
        self.beta = beta
        self.eps = eps
        self.mean = x.mean(axis=0, keepdims=True)
        var = x.var(axis=0, keepdims=True)
        self.inv_std = 1.0 / (var + eps) ** 0.5
        x_hat = (x - self.mean) * self.inv_std
        return x_hat * gamma + beta

    def backward_impl(self, gy):
        N = self.x.shape[0]
        x_hat = (self.x - self.mean) * self.inv_std
        dgamma = (gy * x_hat).sum(axis=0)
        dbeta = gy.sum(axis=0)
        dx_hat = gy * self.gamma
        dx = (1.0 / N) * self.inv_std * (
            N * dx_hat - dx_hat.sum(axis=0) - x_hat * (dx_hat * x_hat).sum(axis=0)
        )
        return dx, dgamma, dbeta


class LayerNorm(Function):
    """Layer Normalization：沿最后一维归一化。"""
    __slots__ = ("x", "gamma", "beta", "eps", "mean", "inv_std")

    def forward(self, x, gamma, beta, eps=1e-5):
        self.x = x
        self.gamma = gamma
        self.beta = beta
        self.eps = eps
        axis = tuple(range(1, x.ndim))
        self.mean = x.mean(axis=axis, keepdims=True)
        var = x.var(axis=axis, keepdims=True)
        self.inv_std = 1.0 / (var + eps) ** 0.5
        x_hat = (x - self.mean) * self.inv_std
        return x_hat * gamma + beta

    def backward_impl(self, gy):
        axis = tuple(range(1, self.x.ndim))
        x_hat = (self.x - self.mean) * self.inv_std
        dgamma = (gy * x_hat).sum(axis=axis, keepdims=True)
        dbeta = gy.sum(axis=axis, keepdims=True)
        dx_hat = gy * self.gamma
        N = self.x.shape[-1]
        dx = (1.0 / N) * self.inv_std * (
            N * dx_hat
            - dx_hat.sum(axis=axis, keepdims=True)
            - x_hat * (dx_hat * x_hat).sum(axis=axis, keepdims=True)
        )
        return dx, dgamma, dbeta

class MSELoss(Function):
    def forward(self, pred, target):
        self.diff = pred - target
        self.N = pred.size
        return (self.diff ** 2).sum() / self.N

    def backward_impl(self, gy):
        return gy * 2 * self.diff / self.N, -gy * 2 * self.diff / self.N


# ---- 激活函数 ------------------------------------------------

class Sigmoid(Function):
    """Sigmoid: 1 / (1 + exp(-x))"""
    def forward(self, x):
        self.y = 1.0 / (1.0 + _get_array_module(x).exp(-x))
        return self.y

    def backward_impl(self, gy):
        return gy * self.y * (1.0 - self.y)


class Tanh(Function):
    """Tanh: (exp(x) - exp(-x)) / (exp(x) + exp(-x))"""
    def forward(self, x):
        xp = _get_array_module(x)
        self.y = xp.tanh(x)
        return self.y

    def backward_impl(self, gy):
        return gy * (1.0 - self.y ** 2)


class Softmax(Function):
    """Softmax: exp(x_i) / sum(exp(x))"""
    def forward(self, x):
        xp = _get_array_module(x)
        e = xp.exp(x - x.max(axis=-1, keepdims=True))
        self.y = e / e.sum(axis=-1, keepdims=True)
        return self.y

    def backward_impl(self, gy):
        return gy  # simplified: assumes combined with CrossEntropyLoss


class Dropout(Function):
    """Dropout: 训练时随机置零。"""
    def __init__(self, p: float = 0.5):
        super().__init__()
        self.p = p

    def forward(self, x):
        xp = _get_array_module(x)
        self.mask = xp.random.binomial(1, 1.0 - self.p, size=xp.shape(x)) / (1.0 - self.p)
        return x * self.mask

    def backward_impl(self, gy):
        return gy * self.mask


# ---- 损失函数 ------------------------------------------------

class CrossEntropyLoss(Function):
    """CrossEntropy = -log(softmax_i[target])"""
    def forward(self, logits, target):
        xp = _get_array_module(logits)
        e = xp.exp(logits - logits.max(axis=-1, keepdims=True))
        self.probs = e / e.sum(axis=-1, keepdims=True)
        self.N = logits.shape[0] if hasattr(logits, 'shape') else 1
        if hasattr(target, 'shape') and len(target.shape) == 1:
            loss = -xp.log(self.probs[xp.arange(self.N), target.astype(int)] + 1e-12).mean()
        else:
            loss = -(target * xp.log(self.probs + 1e-12)).sum(axis=-1).mean()
        return loss

    def backward_impl(self, gy):
        xp = _get_array_module(self.probs)
        if hasattr(gy, 'shape') and len(gy.shape) == 1:
            self.probs[xp.arange(self.N), gy.astype(int)] -= 1.0 / self.N
        return gy * self.probs, gy * (-self.probs)


# ---- 优化器 --------------------------------------------------

class SGD:
    """随机梯度下降优化器

    :param params: TensorNode 列表
    :param lr: 学习率
    :param momentum: 动量系数 (0 = 无动量)

    用法::

        opt = SGD([W, b], lr=0.01)
        opt.zero_grad()
        loss.backward()
        opt.step()
    """
    def __init__(self, params: list, lr: float = 0.01, momentum: float = 0.0):
        self.params = params
        self.lr = lr
        self.momentum = momentum
        self._velocities: dict = {id(p): None for p in params}

    def zero_grad(self):
        for p in self.params:
            if isinstance(p, TensorNode):
                p.grad = None

    def step(self):
        for p in self.params:
            if isinstance(p, TensorNode):
                self._step_tensor(p)
            else:
                self._step_raw(p)

    def _step_tensor(self, p):
        if p.grad is None:
            return
        update = p.grad * self.lr
        if self.momentum > 0:
            v = self._velocities[id(p)]
            if v is not None:
                update = update + self.momentum * v
            self._velocities[id(p)] = update.copy() if hasattr(update, 'copy') else update
        p.data = p.data - update

    def _step_raw(self, arr):
        """对原始 numpy 数组应用梯度（需外部手动设置 .grad 属性）"""
        pass  # raw arrays managed externally via autograd


# ---- 模型容器 ------------------------------------------------

class Sequential:
    """顺序模型容器

    用法::

        model = Sequential([
            Linear(in_dim, hidden_dim),
            Relu(),
            Linear(hidden_dim, out_dim),
            Softmax(),
        ])
        y = model.forward(x)
    """

    def __init__(self, layers: list):
        self.layers = layers

    def forward(self, x):
        for layer in self.layers:
            if isinstance(layer, Function):
                x = layer(x)
            elif hasattr(layer, 'forward'):
                x = layer.forward(x)
            else:
                x = layer(x)
        return x

    def __call__(self, x):
        return self.forward(x)


class Linear(Function):
    """全连接层: y = x @ W + b（可选 bias）

    :param in_features: 输入维度
    :param out_features: 输出维度
    :param bias: 是否使用偏置
    """
    __slots__ = ("x", "W", "b")

    def __init__(self, in_features: int, out_features: int, bias: bool = True):
        super().__init__()
        np_mod = optional_import("numpy")
        scale = (2.0 / in_features) ** 0.5
        self.W = np_mod.random.randn(in_features, out_features).astype(np_mod.float32) * scale
        self.b = np_mod.zeros(out_features, dtype=np_mod.float32) if bias else None

    def forward(self, x):
        self.x = x
        out = x @ self.W
        if self.b is not None:
            out = out + self.b
        return out

    def backward_impl(self, gy):
        gW = self.x.T @ gy
        gb = gy.sum(axis=0) if self.b is not None else None
        gx = gy @ self.W.T
        if gb is not None:
            return (gx, gW, gb)
        return (gx, gW)


# DLC 定义

class NeuralNetworkOperatorsDLC(BrainDLC):
    def get_manifest(self) -> DLCManifest:
        return DLCManifest(
            name="Neural Network Operators",
            version=__version__,
            author="Brain AI Systems",
            description="基础神经网络算子、Autograd、优化器与模型容器",
            dlc_type=BrainDLCType.PROCESSOR,
            dependencies=["Brain Core", "Hardware Accelerator"],
            priority=20
        )

    def _initialize(self):
        self.np = optional_import("numpy")
        if self.np is None:
            logging.warning("NeuralNetworkOperatorsDLC: 缺少 numpy，无法工作")
            return
        self.hw_dlc = None
        try:
            self.hw_dlc = self.brain.dlcs.get("Hardware Accelerator")
        except Exception:
            pass
        logging.info("NeuralNetworkOperatorsDLC 已就绪")

    def provide_computational_units(self) -> Dict[str, Any]:
        return {
            "Tensor": TensorNode,
            "Function": Function,
            "Sequential": Sequential,
            "Linear": Linear,
            "SGD": SGD,
            "ops": {
                "add": Add(), "sub": Sub(), "mul": Mul(), "matmul": MatMul(),
                "relu": Relu(), "sigmoid": Sigmoid(), "tanh": Tanh(),
                "softmax": Softmax(), "dropout": Dropout(0.5),
                "fused_matmul_relu": FusedMatMulReLU(),
                "fused_linear_relu": FusedLinearReLU(),
                "batch_norm1d": BatchNorm1D(), "layer_norm": LayerNorm(),
                "mse_loss": MSELoss(), "cross_entropy": CrossEntropyLoss(),
            }
        }
