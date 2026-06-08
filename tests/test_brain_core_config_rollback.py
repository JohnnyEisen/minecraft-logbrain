from __future__ import annotations

from unittest.mock import patch

from brain_system.core import BrainCore


def test_rollback_config_without_previous_snapshot_returns_false() -> None:
    brain = BrainCore(config_path=None)
    before = brain.get_config()

    rolled_back = brain.rollback_config()

    assert rolled_back is False
    assert brain.get_config() == before


def test_rollback_config_restores_previous_valid_config() -> None:
    brain = BrainCore(config_path=None)
    before = brain.get_config()

    brain._on_config_update(
        {
            "log_level": "DEBUG",
            "cache_max_entries": 321,
            "retry_max_attempts": 3,
            "retry_initial_delay_seconds": 0.05,
        }
    )
    assert brain.get_config()["log_level"] == "DEBUG"
    assert brain.get_config()["cache_max_entries"] == 321

    rolled_back = brain.rollback_config()

    assert rolled_back is True
    assert brain.get_config() == before


def test_rollback_config_restores_nested_config_without_aliasing() -> None:
    brain = BrainCore(config_path=None)
    base_prefixes = brain.get_config().get("cpu_task_prefixes", ["cpu_", "cpu_task", "thread_cpu_"])
    if not isinstance(base_prefixes, list):
        base_prefixes = ["cpu_", "cpu_task", "thread_cpu_"]

    update_prefixes = list(base_prefixes) + ["ml_"]
    brain._on_config_update({"cpu_task_prefixes": update_prefixes})
    assert "ml_" in brain.get_config()["cpu_task_prefixes"]

    rolled_back = brain.rollback_config()

    assert rolled_back is True
    assert brain.get_config()["cpu_task_prefixes"] == base_prefixes

    # 验证回滚后的配置与外部引用不共享可变对象
    update_prefixes.append("should_not_leak")
    assert "should_not_leak" not in brain.get_config()["cpu_task_prefixes"]


def test_failed_update_does_not_pollute_rollback_history() -> None:
    brain = BrainCore(config_path=None)
    before = brain.get_config()

    with patch("brain_system.core.RetryPolicy", side_effect=RuntimeError("policy boom")):
        brain._on_config_update({"cache_max_entries": 222})

    # 更新失败时，当前配置不应变化，且不应产生可回滚历史
    assert brain.get_config() == before
    assert brain.rollback_config() is False
