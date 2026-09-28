from __future__ import annotations

import argparse
import asyncio
from typing import Optional

from .core import BrainCore


def _cmd_run(args: argparse.Namespace) -> int:
    async def runner():
        brain = BrainCore(config_path=args.config)
        if brain.config.get("auto_load_dlcs", True):
            brain.load_all_dlcs()
        try:
            brain.start_performance_monitor()
        except Exception:
            pass

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await brain.shutdown()

    asyncio.run(runner())
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    brain = BrainCore(config_path=args.config)
    if brain.config.get("auto_load_dlcs", True):
        brain.load_all_dlcs()

    from .server import create_app

    app = create_app(brain)

    try:
        import uvicorn  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("未安装 uvicorn，安装: pip install 'brain-system[server]'" ) from e

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    import json

    from .training import BrainTrainer, TrainingConfig

    async def runner():
        brain = BrainCore(config_path=args.config)
        if brain.config.get("auto_load_dlcs", True):
            brain.load_all_dlcs()

        trainer = BrainTrainer()
        report = await trainer.train(
            brain,
            cfg=TrainingConfig(duration_seconds=float(args.duration), concurrency=int(args.concurrency)),
            progress=lambda m: print(m, flush=True),
        )
        print(json.dumps(report.recommended_config, ensure_ascii=False, indent=2))
        await brain.shutdown()

    asyncio.run(runner())
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """运行 BrainCore 内置演示，避免依赖根目录兼容脚本。"""

    async def runner() -> None:
        brain = BrainCore(config_path=args.config)
        if brain.config.get("auto_load_dlcs", True):
            brain.load_all_dlcs()
        try:
            print(brain.health_check())
        finally:
            await brain.shutdown()

    asyncio.run(runner())
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="brain")
    parser.add_argument("--config", default="config/brain_config.json")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run BrainCore main loop")
    p_run.set_defaults(func=_cmd_run)

    p_serve = sub.add_parser("serve", help="Serve health/ready/metrics")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=_cmd_serve)

    p_train = sub.add_parser("train", help="Run performance training and print config recommendations")
    p_train.add_argument("--duration", default="20")
    p_train.add_argument("--concurrency", default="20")
    p_train.set_defaults(func=_cmd_train)

    p_demo = sub.add_parser("demo", help="Run built-in BrainCore demo")
    p_demo.set_defaults(func=_cmd_demo)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
