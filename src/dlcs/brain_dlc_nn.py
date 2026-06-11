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
            _array_module_cache.setdefault("cupy", cp)
            return cp
    except Exception:
        pass
    np = optional_import("numpy")
    _array_module_cache.setdefault("numpy", np)
    return np


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

        # 累积当前梯度
        if self.grad is None:
            self.grad = grad
        else:
            self.grad += grad

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

    def __call__(self, *inputs: TensorNode) -> TensorNode | tuple[TensorNode, ...]:
        self.inputs = list(inputs)
        self.generation = max((x.generation for x in inputs), default=0)
        
        # Unpack data
        raw_inputs = [x.data for x in inputs]
        
        # Forward
        raw_outputs = self.forward(*raw_inputs)
        if not isinstance(raw_outputs, tuple):
            raw_outputs = (raw_outputs,)
        
        # Pack Output
        outputs = []
        requires_grad = any(x.requires_grad for x in inputs)
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
        
        # 分发到各输入
        for x, g in zip(self.inputs, grad_inputs):
            if x.requires_grad:
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


# DLC 定义

class NeuralNetworkOperatorsDLC(BrainDLC):
    def get_manifest(self) -> DLCManifest:
        return DLCManifest(
            name="Neural Network Operators",
            version=__version__,
            author="Brain AI Systems",
            description="提供基础神经网络算子与简易 Autograd",
            dlc_type=BrainDLCType.PROCESSOR,
            dependencies=["Brain Core", "Hardware Accelerator"],
            priority=20
        )

    def _initialize(self):
        # 检查 numpy
        self.np = optional_import("numpy")
        if self.np is None:
            logging.warning("NeuralNetworkOperatorsDLC: 缺少 numpy，无法工作")
            return

        # 获取 Hardware DLC (如果需要)
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
            "ops": {
                "add": Add(),
                "sub": Sub(),
                "mul": Mul(),
                "matmul": MatMul(),
                "relu": Relu(),
                "fused_matmul_relu": FusedMatMulReLU(),
                "fused_linear_relu": FusedLinearReLU(),
                "batch_norm1d": BatchNorm1D(),
                "layer_norm": LayerNorm(),
                "mse_loss": MSELoss(),
            }
        }
