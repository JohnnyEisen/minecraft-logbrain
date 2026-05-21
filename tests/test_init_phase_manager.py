"""测试初始化阶段管理器 — InitializationPhaseManager 完整单元测试。"""

from __future__ import annotations

import pytest
from mca_core.init_phase_manager import (
    CircularDependencyError,
    InitializationPhase,
    InitializationPhaseManager,
    InitializationStep,
    MissingDependencyError,
    StepExecutionError,
)


class TestInitializationStep:
    def test_create_step_with_defaults(self):
        step = InitializationStep(
            name="test_step",
            phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None,
        )
        assert step.name == "test_step"
        assert step.phase == InitializationPhase.CORE_SERVICES
        assert step.dependencies == []
        assert step.description == ""

    def test_create_step_with_all_fields(self):
        step = InitializationStep(
            name="full_step",
            phase=InitializationPhase.EXTENSIONS,
            handler=lambda: None,
            dependencies=["dep1", "dep2"],
            description="完整配置的步骤",
        )
        assert step.dependencies == ["dep1", "dep2"]
        assert step.description == "完整配置的步骤"


class TestRegistration:
    def test_register_single_step(self):
        manager = InitializationPhaseManager()
        step = InitializationStep(
            name="s1",
            phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: None,
        )
        manager.register_step(step)
        assert manager.get_step("s1") is step

    def test_register_duplicate_name_raises(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="dup", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None,
        ))
        with pytest.raises(ValueError, match="已注册"):
            manager.register_step(InitializationStep(
                name="dup", phase=InitializationPhase.CORE_SERVICES, handler=lambda: None,
            ))

    def test_register_empty_name_raises(self):
        manager = InitializationPhaseManager()
        with pytest.raises(ValueError, match="不能为空"):
            manager.register_step(InitializationStep(
                name="", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None,
            ))

    def test_register_steps_batch(self):
        manager = InitializationPhaseManager()
        steps = [
            InitializationStep(name="a", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None),
            InitializationStep(name="b", phase=InitializationPhase.CORE_SERVICES, handler=lambda: None),
        ]
        manager.register_steps(steps)
        assert manager.get_step("a") is not None
        assert manager.get_step("b") is not None

    def test_get_step_nonexistent(self):
        manager = InitializationPhaseManager()
        assert manager.get_step("nonexistent") is None


class TestDependencyValidation:
    def test_valid_dependencies_no_errors(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="base", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None,
        ))
        manager.register_step(InitializationStep(
            name="derived", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["base"],
        ))
        errors = manager.validate_dependencies()
        assert len(errors) == 0

    def test_missing_dependency_error(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="orphan", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["nonexistent"],
        ))
        errors = manager.validate_dependencies()
        assert len(errors) >= 1
        assert any("nonexistent" in e for e in errors)

    def test_circular_dependency_simple(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="x", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["y"],
        ))
        manager.register_step(InitializationStep(
            name="y", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["x"],
        ))
        errors = manager.validate_dependencies()
        assert len(errors) >= 1
        assert any("循环依赖" in e for e in errors)

    def test_circular_dependency_three_nodes(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="p", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["q"],
        ))
        manager.register_step(InitializationStep(
            name="q", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["r"],
        ))
        manager.register_step(InitializationStep(
            name="r", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["p"],
        ))
        errors = manager.validate_dependencies()
        assert len(errors) >= 1

    def test_self_reference_detected_as_cycle(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="self_ref", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["self_ref"],
        ))
        errors = manager.validate_dependencies()
        assert len(errors) >= 1
        assert any("循环依赖" in e for e in errors)


class TestExecutionOrder:
    def test_execution_order_respects_phases(self):
        manager = InitializationPhaseManager()
        execution_log = []

        manager.register_step(InitializationStep(
            name="infra", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: execution_log.append("infra"),
        ))
        manager.register_step(InitializationStep(
            name="core", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: execution_log.append("core"),
        ))
        manager.register_step(InitializationStep(
            name="final", phase=InitializationPhase.FINALIZATION,
            handler=lambda: execution_log.append("final"),
        ))

        order = manager.get_execution_order()
        names = [s.name for s in order]
        infra_idx = names.index("infra")
        core_idx = names.index("core")
        final_idx = names.index("final")
        assert infra_idx < core_idx < final_idx

    def test_execution_order_within_same_phase_respects_deps(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="first", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None,
        ))
        manager.register_step(InitializationStep(
            name="second", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["first"],
        ))
        manager.register_step(InitializationStep(
            name="third", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["second"],
        ))

        order = manager.get_execution_order()
        names = [s.name for s in order]
        assert names.index("first") < names.index("second")
        assert names.index("second") < names.index("third")

    def test_execution_order_independent_steps_can_be_any_order(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="a", phase=InitializationPhase.CORE_SERVICES, handler=lambda: None,
        ))
        manager.register_step(InitializationStep(
            name="b", phase=InitializationPhase.CORE_SERVICES, handler=lambda: None,
        ))
        order = manager.get_execution_order()
        names = {s.name for s in order}
        assert names == {"a", "b"}

    def test_circular_dependency_in_same_phase_raises(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="m", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["n"],
        ))
        manager.register_step(InitializationStep(
            name="n", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["m"],
        ))
        with pytest.raises(CircularDependencyError):
            manager.get_execution_order()

    def test_cross_phase_dependency_not_in_same_phase_topology(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="infra_base", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: None,
        ))
        manager.register_step(InitializationStep(
            name="core_step", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["infra_base"],
        ))

        order = manager.get_execution_order()
        names = [s.name for s in order]
        assert names.index("infra_base") < names.index("core_step")


class TestExecute:
    def test_execute_all_steps_in_order(self):
        manager = InitializationPhaseManager()
        log = []

        manager.register_step(InitializationStep(
            name="s1", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: log.append("s1"),
            description="步骤1",
        ))
        manager.register_step(InitializationStep(
            name="s2", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: log.append("s2"),
            dependencies=["s1"],
            description="步骤2",
        ))
        manager.register_step(InitializationStep(
            name="s3", phase=InitializationPhase.FINALIZATION,
            handler=lambda: log.append("s3"),
            dependencies=["s2"],
            description="步骤3",
        ))

        manager.execute()
        assert log == ["s1", "s2", "s3"]
        assert manager.get_executed_steps() == ["s1", "s2", "s3"]

    def test_execute_tracks_executed_steps(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="only", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: None,
        ))
        manager.execute()
        assert manager.get_executed_steps() == ["only"]

    def test_execute_with_missing_dependency_raises(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="bad", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["missing"],
        ))
        with pytest.raises(MissingDependencyError):
            manager.execute()

    def test_execute_with_circular_dependency_raises(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="x", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["y"],
        ))
        manager.register_step(InitializationStep(
            name="y", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: None, dependencies=["x"],
        ))
        with pytest.raises(MissingDependencyError):
            manager.execute()

    def test_execute_step_failure_raises(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="failing", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: (_ for _ in ()).throw(ValueError("模拟失败")),
        ))
        with pytest.raises(StepExecutionError, match="failing"):
            manager.execute()

    def test_execute_steps_after_failure_not_executed(self):
        manager = InitializationPhaseManager()
        log = []

        manager.register_step(InitializationStep(
            name="fail", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: (_ for _ in ()).throw(RuntimeError("模拟失败")),
        ))
        manager.register_step(InitializationStep(
            name="never_run", phase=InitializationPhase.CORE_SERVICES,
            handler=lambda: log.append("never"),
        ))

        with pytest.raises(StepExecutionError):
            manager.execute()

        assert "never" not in log
        assert "never_run" not in manager.get_executed_steps()


class TestCallbacks:
    def test_before_step_callback(self):
        manager = InitializationPhaseManager()
        callback_log = []

        manager.register_step(InitializationStep(
            name="step1", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: None,
        ))
        manager.set_callbacks(
            before_step=lambda name: callback_log.append(f"before:{name}"),
        )
        manager.execute()
        assert "before:step1" in callback_log

    def test_after_step_callback(self):
        manager = InitializationPhaseManager()
        callback_log = []

        manager.register_step(InitializationStep(
            name="step1", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: None,
        ))
        manager.set_callbacks(
            after_step=lambda name: callback_log.append(f"after:{name}"),
        )
        manager.execute()
        assert "after:step1" in callback_log

    def test_error_callback_on_failure(self):
        manager = InitializationPhaseManager()
        error_log = []

        manager.register_step(InitializationStep(
            name="failing", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: (_ for _ in ()).throw(ValueError("测试错误")),
        ))
        manager.set_callbacks(
            on_error=lambda name, e: error_log.append((name, str(e))),
        )

        with pytest.raises(StepExecutionError):
            manager.execute()

        assert len(error_log) == 1
        assert error_log[0][0] == "failing"
        assert "测试错误" in error_log[0][1]

    def test_before_and_after_callbacks_together(self):
        manager = InitializationPhaseManager()
        log = []

        manager.register_step(InitializationStep(
            name="s", phase=InitializationPhase.INFRASTRUCTURE,
            handler=lambda: log.append("exec"),
        ))
        manager.set_callbacks(
            before_step=lambda n: log.append(f"b:{n}"),
            after_step=lambda n: log.append(f"a:{n}"),
        )
        manager.execute()
        assert log == ["b:s", "exec", "a:s"]


class TestQueryAndClear:
    def test_get_steps_by_phase(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="infra1", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None,
        ))
        manager.register_step(InitializationStep(
            name="infra2", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None,
        ))
        manager.register_step(InitializationStep(
            name="core1", phase=InitializationPhase.CORE_SERVICES, handler=lambda: None,
        ))

        infra_steps = manager.get_steps_by_phase(InitializationPhase.INFRASTRUCTURE)
        core_steps = manager.get_steps_by_phase(InitializationPhase.CORE_SERVICES)
        assert len(infra_steps) == 2
        assert len(core_steps) == 1

    def test_clear_removes_all_steps(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="s", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None,
        ))
        manager.clear()
        assert manager.get_step("s") is None
        assert manager.get_executed_steps() == []

    def test_clear_after_execute(self):
        manager = InitializationPhaseManager()
        manager.register_step(InitializationStep(
            name="s", phase=InitializationPhase.INFRASTRUCTURE, handler=lambda: None,
        ))
        manager.execute()
        assert manager.get_executed_steps() == ["s"]
        manager.clear()
        assert manager.get_executed_steps() == []


class TestFullIntegration:
    """模拟真实场景的集成测试——复刻 MinecraftCrashAnalyzer 初始化流程。"""

    def test_full_init_flow_simulated(self):
        manager = InitializationPhaseManager()
        state = {}

        manager.register_steps([
            InitializationStep(
                name="init_root_window",
                phase=InitializationPhase.INFRASTRUCTURE,
                handler=lambda: state.update({"window": "ok"}),
                dependencies=[],
                description="初始化根窗口配置",
            ),
            InitializationStep(
                name="init_threading",
                phase=InitializationPhase.INFRASTRUCTURE,
                handler=lambda: state.update({"threading": "ok"}),
                dependencies=[],
                description="初始化线程相关组件",
            ),
            InitializationStep(
                name="init_services",
                phase=InitializationPhase.CORE_SERVICES,
                handler=lambda: state.update({"services": "ok"}),
                dependencies=["init_threading"],
                description="初始化服务层组件",
            ),
            InitializationStep(
                name="init_cache",
                phase=InitializationPhase.CORE_SERVICES,
                handler=lambda: state.update({"cache": "ok"}),
                dependencies=[],
                description="初始化缓存系统",
            ),
            InitializationStep(
                name="init_state",
                phase=InitializationPhase.CORE_SERVICES,
                handler=lambda: state.update({"state": "ok"}),
                dependencies=[],
                description="初始化应用状态",
            ),
            InitializationStep(
                name="init_di_container",
                phase=InitializationPhase.DEPENDENCY_INJECTION,
                handler=lambda: state.update({"di": "ok"}),
                dependencies=["init_services"],
                description="初始化依赖注入容器",
            ),
            InitializationStep(
                name="init_plugins",
                phase=InitializationPhase.EXTENSIONS,
                handler=lambda: state.update({"plugins": "ok"}),
                dependencies=["init_di_container"],
                description="初始化插件系统",
            ),
            InitializationStep(
                name="init_detectors",
                phase=InitializationPhase.EXTENSIONS,
                handler=lambda: state.update({"detectors": "ok"}),
                dependencies=["init_di_container"],
                description="初始化检测器注册表",
            ),
            InitializationStep(
                name="init_brain",
                phase=InitializationPhase.EXTENSIONS,
                handler=lambda: state.update({"brain": "ok"}),
                dependencies=[],
                description="初始化 Brain AI 系统",
            ),
            InitializationStep(
                name="setup_detectors",
                phase=InitializationPhase.FINALIZATION,
                handler=lambda: state.update({"setup": "ok"}),
                dependencies=["init_detectors", "init_brain", "init_di_container"],
                description="设置检测器和完成初始化",
            ),
        ])

        manager.execute()

        assert state["window"] == "ok"
        assert state["services"] == "ok"
        assert state["di"] == "ok"
        assert state["plugins"] == "ok"
        assert state["detectors"] == "ok"
        assert state["brain"] == "ok"
        assert state["setup"] == "ok"

        expected = [
            "init_root_window", "init_threading", "init_services",
            "init_cache", "init_state", "init_di_container",
            "init_plugins", "init_detectors", "init_brain",
            "setup_detectors",
        ]
        actual = manager.get_executed_steps()
        for step_name in expected:
            assert step_name in actual
        assert actual.index("init_services") < actual.index("init_di_container")
        assert actual.index("init_di_container") < actual.index("init_plugins")
        assert actual.index("init_di_container") < actual.index("setup_detectors")