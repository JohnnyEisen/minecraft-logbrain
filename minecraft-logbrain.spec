# -*- mode: python ; coding: utf-8 -*-
# MCA Brain System - Optimized EXE Packaging Config
# 优化策略: 核心分析器 (~50-100 MB) + 可选AI模块 (DLC)

block_cipher = None

# 排除所有重型AI/ML库，它们作为可选的DLC/插件提供
heavy_excludes = [
    # PyTorch 生态 (~4.5 GB with CUDA)
    'torch', 'torchvision', 'torchaudio', 'torchgen',
    'torch._C', 'torch._dynamo', 'torch._inductor', 'torch._functorch',
    'torch._export', 'torch._library', 'torch._logging',
    'torch._strobelight', 'torch._subclasses',
    'torch.autograd', 'torch.backends', 'torch.compiler',
    'torch.cpu', 'torch.cuda', 'torch.distributed', 'torch.distributions',
    'torch.fft', 'torch.func', 'torch.futures', 'torch.fx',
    'torch.jit', 'torch.library', 'torch.linalg', 'torch.masked',
    'torch.monitor', 'torch.multiprocessing', 'torch.nested',
    'torch.nn', 'torch.optim', 'torch.package', 'torch.profiler',
    'torch.quasirandom', 'torch.random', 'torch.serialization',
    'torch.signal', 'torch.sparse', 'torch.special',
    'torch.testing', 'torch.utils',
    'torch_xla', 'functorch', 'triton',

    # CUDA/NVIDIA 运行时
    'cuda', 'cuda_occupancy',
    'nvidia', 'nvidia.cublas', 'nvidia.cuda_cupti', 'nvidia.cuda_nvrtc',
    'nvidia.cuda_runtime', 'nvidia.cudnn', 'nvidia.cufft',
    'nvidia.curand', 'nvidia.cusolver', 'nvidia.cusparse',
    'nvidia.nccl', 'nvidia.nvjitlink', 'nvidia.nvtx',

    # Transformers / HuggingFace (~83 MB)
    'transformers',
    'sentencepiece', 'tokenizers',
    'huggingface_hub', 'safetensors',
    'accelerate', 'peft',

    # 其他AI/ML库
    'sympy', 'mpmath',  # ~68 MB
    'tensorboard', 'tensorboardX',
    'keras', 'keras_preprocessing',
    'optree', 'opt_einsum',

    # 数据分析 (已从EXE排除，由外部lib提供)
    'matplotlib', 'mpl_toolkits', 'PIL', 'Pillow',
    'networkx', 'scipy', 'pandas',
    'psutil', 'packaging',

    # 未被核心使用的服务
    'fastapi', 'uvicorn', 'starlette',
    'redis', 'prometheus_client',
    'opentelemetry',
]

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('data/diagnostic_rules.json', 'data'),
        ('plugins', 'plugins'),
    ],
    # DLCs 不作为 hidden import 捆绑，它们是可选的外部插件
    hiddenimports=[
        'mca_core.detectors',
        'mca_core.detectors.gl_errors',
        'mca_core.detectors.missing_dependencies',
        'mca_core.detectors.version_conflicts',
        'mca_core.detectors.duplicate_mods',
        'mca_core.detectors.out_of_memory',
        'mca_core.detectors.mixin_conflicts',
        'mca_core.services',
        'mca_core.controllers',
        'mca_core.main_window_mixins',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'test', 'tests', 'unittest', 'pytest',
        'debug', 'setuptools', 'pip',
        'pdb', 'doctest',
        # DLCs
        'dlcs',
        # Brain系统 (可选插件)
        'brain_system',
    ] + heavy_excludes,
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='minecraft-logbrain',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'python3*.dll', 'Qt6*.dll'],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app_icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'python3*.dll', 'Qt6*.dll'],
    name='minecraft-logbrain',
)