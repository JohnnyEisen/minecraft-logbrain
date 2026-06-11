# 补丁与更新指南

适用于 v2.0.0+。当前版本以 `CHANGELOG.md` 顶部为准。

---

## 1. 资源文件热修

以下目录的文件可直接修改或替换，重启即生效：

- `analysis_data/` — 规则库 (`diagnostic_rules.json` 等)
- `tools/` — 工具脚本
- `config/` — 配置文件

**发布**: 发送修改后的文件，用户覆盖安装目录对应位置。

---

## 2. DLC 扩展补丁

Brain System 支持动态加载 `dlcs/` 目录下的 Python DLC。高 `priority` 的 DLC 可在 `initialize()` 阶段修改系统行为：

```python
class HotfixDLC(BrainDLC):
    def get_manifest(self): return DLCManifest(name="Hotfix", priority=999)
    async def initialize(self):
        # Monkey Patch 运行时代码替换
        ...
```

**发布**: 发送 `.py` 文件，用户放入 `dlcs/` 目录。

---

## 3. 核心版本更新

### 3.1 源码热替换（推荐）

程序启动时优先检查 EXE 同级 `patches/` 目录，匹配同路径模块则优先加载：

```
minecraft-logbrain/
  ├── minecraft-logbrain.exe
  └── patches/
      └── mca_core/
          └── app.py          # 覆盖 EXE 内对应模块
```

### 3.2 全量重新打包

仅以下情况需要重新打包：

- 新增 pip 依赖
- 修改 `main.py` 或核心启动逻辑
- UI 框架重大变更

```bash
scripts/build/pack.bat
# 输出: dist/minecraft-logbrain/
```

---

## 4. 自动更新（未来计划）

启动时检查服务器 `version.json`，发现新版本自动下载替换。
