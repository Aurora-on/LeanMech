# MacBook 迁移风险审计

本文档用于梳理当前仓库中所有与本地路径、本地环境、操作系统差异及开发工具绑定相关的内容，目标是在将项目迁移到另一台设备（MacBook）之前，先明确哪些内容会直接导致运行失败，哪些内容需要手工适配，哪些内容仅影响开发体验而不影响主流程执行。

## 1. 结论摘要

当前项目**不能直接无修改迁移到 MacBook 运行**。最主要的阻塞项有四类：

1. `Python` 配置默认值中存在大量硬编码的 Windows 本地路径。
2. `Lean/Lake` 工程依赖使用本地相对路径绑定 `MechLib` 与 `PhysLean`，新设备若目录结构不一致会直接失效。
3. 多个 `YAML` 配置模板直接写死了 `F:/...` 路径、代理地址和 API key 环境变量名。
4. 文档与开发工具配置以 `PowerShell + VS Code + Windows 路径` 为默认前提，迁移后需要整体替换为 macOS 对应写法。

## 2. 会直接导致迁移失败的内容

### 2.1 Python 默认配置中的硬编码本地路径

以下默认值位于 [config.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)，如果不改，MacBook 上运行主流程时大概率会直接报路径不存在：

- `DEFAULT_LOCAL_ARCHIVE_ROOT = "F:/AI4Mechanics/datasets/archive"`
- `Lean4PhysConfig.bench_path = "F:/AI4Mechanics/coding/Lean4PHYS/LeanPhysBench/LeanPhysBench_v0.json"`
- `LeanConfig.physlean_dir = "F:/AI4Mechanics/PhysLean-master"`
- `LeanConfig.mechlib_dir = "F:/AI4Mechanics/coding/MechLib"`
- `KnowledgeConfig.mechlib_dir = "F:/AI4Mechanics/coding/MechLib"`
- `KnowledgeConfig.summary_corpus_path = "F:/AI4Mechanics/coding/MechLib/theorem_corpus.jsonl"`

影响：

- 数据集无法加载。
- `Lean` 预检无法定位 `PhysLean`。
- `MechLib` 检索与 theorem corpus 无法加载。
- 主流程与 baseline 均会失败。

### 2.2 Lean/Lake 本地路径依赖

当前 Lean 工程没有通过远程依赖自动拉取关键库，而是通过**本地路径依赖**绑定：

- [lakefile.toml](f:/AI4Mechanics/coding/pipeline1/lakefile.toml)
  - `path = "../MechLib"`
  - `path = "../../PhysLean-master/.lake/packages/mathlib"`

- [lake-manifest.json](f:/AI4Mechanics/coding/pipeline1/lake-manifest.json)
  - `dir = "../MechLib"`
  - `dir = "../MechLib/../../PhysLean-master/.lake/packages/mathlib"`
  - 以及 `plausible`、`LeanSearchClient`、`importGraph`、`proofwidgets`、`aesop`、`Qq`、`batteries`、`Cli` 等一系列从 `PhysLean-master/.lake/packages` 继承过来的本地路径

影响：

- 如果 MacBook 上没有与当前机器**相同的目录层级关系**，`lake` 无法解析依赖。
- 即使 `MechLib` 本身存在，只要 `PhysLean-master/.lake/packages/*` 的本地布局不一致，也会导致 Lean 构建失败。

这部分是迁移中的**一级阻塞项**。

### 2.3 配置模板中写死的 Windows 路径

当前 `configs/` 下大量模板直接写死了 `F:/...` 路径。典型文件包括：

- [mechanics101_proxy_gpt54_20260409.yaml](f:/AI4Mechanics/coding/pipeline1/configs/mechanics101_proxy_gpt54_20260409.yaml)
- [theoretical_mechanics_14_proxy_gpt54_20260407.yaml](f:/AI4Mechanics/coding/pipeline1/configs/theoretical_mechanics_14_proxy_gpt54_20260407.yaml)
- [direct_baseline_mechanics101_gpt54_20260410.yaml](f:/AI4Mechanics/coding/pipeline1/configs/direct_baseline_mechanics101_gpt54_20260410.yaml)
- [default_mechanics73_openai.yaml](f:/AI4Mechanics/coding/pipeline1/configs/default_mechanics73_openai.yaml)
- [full_run_openai_proxy_lean.yaml](f:/AI4Mechanics/coding/pipeline1/configs/full_run_openai_proxy_lean.yaml)
- [mvp_lean4phys_mechanics.yaml](f:/AI4Mechanics/coding/pipeline1/configs/mvp_lean4phys_mechanics.yaml)
- 以及其它多份 `mechanics*`、`competition*`、`mvp_*`、`api_*` 配置

这些配置中常见的本地路径字段有：

- `dataset.local_archive.root`
- `dataset.lean4phys.bench_path`
- `lean.physlean_dir`
- `lean.mechlib_dir`
- `knowledge.mechlib_dir`
- `knowledge.summary_corpus_path`

影响：

- 只要直接复用这些 YAML，MacBook 上就会因路径不存在而失败。

### 2.4 数据文件布局假设

当前项目默认依赖以下本地数据/仓库：

- `Lean4PHYS` benchmark JSON
- `PhysLean-master`
- `MechLib`
- `MechLib/theorem_corpus.jsonl`
- 可选的本地归档目录 `datasets/archive`

这些内容都不随当前仓库自动提供。迁移到 MacBook 后，如果仅复制 `pipeline1` 仓库本身，而不同时准备这些本地依赖，则主流程无法完整运行。

## 3. 本地环境假设

### 3.1 Lean 工具链版本

- [lean-toolchain](f:/AI4Mechanics/coding/pipeline1/lean-toolchain) 当前内容为：
  - `leanprover/lean4:v4.26.0`

这意味着新设备必须安装并切换到该版本，或者至少保证 `elan`/`lake` 能解析并下载该版本。

### 3.2 Python 运行环境

项目需要：

- Python 可执行环境
- `pyproject.toml` 中声明的依赖
- 以 `src` 为 `PYTHONPATH`

相关定义在：

- [pyproject.toml](f:/AI4Mechanics/coding/pipeline1/pyproject.toml)

如果在 MacBook 上只是直接运行脚本，而没有：

- 正确安装依赖
- 设置 `PYTHONPATH=src`

则 `python -m mech_pipeline.cli` 可能无法正常导入。

### 3.3 API 环境变量

当前不同配置模板会依赖不同的环境变量名，例如：

- `OPENAI_PROXY_KEY`
- `OPENAI_API_KEY`

相关位置：

- [config.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)
- 多个 `configs/*.yaml`

此外，很多配置还依赖：

- `model.base_url`

例如：

- `https://api.openai-proxy.org/v1`
- `https://api.deepseek.com/v1`
- `https://dashscope.aliyuncs.com/compatible-mode/v1`

影响：

- 如果 MacBook 上没有设置对应环境变量，模型初始化会失败。
- 如果网络环境无法访问当前代理地址，真实 API 实验无法运行。

## 4. Windows 专属或明显偏向 Windows 的内容

### 4.1 README 中的示例命令与路径

当前 [README.md](f:/AI4Mechanics/coding/pipeline1/README.md) 中存在大量 Windows 风格内容：

- `F:/...` 绝对路径示例
- PowerShell 语法：
  - `$env:OPENAI_PROXY_KEY = "<your-key>"`
- 以 Windows 目录布局为前提的说明

这些内容不会直接影响代码运行，但会误导在 macOS 上的使用方式。

### 4.2 VS Code 任务与调试配置

以下文件假设使用 VS Code，并依赖其环境注入方式：

- [.vscode/tasks.json](f:/AI4Mechanics/coding/pipeline1/.vscode/tasks.json)
- [.vscode/launch.json](f:/AI4Mechanics/coding/pipeline1/.vscode/launch.json)

它们依赖：

- `${workspaceFolder}/src` 作为 `PYTHONPATH`
- `.env` 文件
- VS Code integrated terminal

这些并非 Windows 独占，但属于**开发工具绑定**。迁移到 MacBook 后如果继续用 VS Code，可以沿用思路；如果改用纯终端，则需要手工重建这些环境变量。

### 4.3 CLI 中的 Windows 控制台编码分支

[cli.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py) 中有 `_configure_utf8_console()`，内部在 `os.name == "nt"` 时会调用：

- `ctypes.windll.kernel32.SetConsoleOutputCP(65001)`
- `ctypes.windll.kernel32.SetConsoleCP(65001)`

这是 Windows 专属逻辑，但已经有系统判断保护：

- 在 macOS 上不会执行

因此这部分**不是迁移阻塞项**，只是一个 Windows 分支。

## 5. 其它可能导致迁移失败的内容

### 5.1 `lake-manifest.json` 的机器相关性

当前 [lake-manifest.json](f:/AI4Mechanics/coding/pipeline1/lake-manifest.json) 中记录了大量本地路径依赖快照。即使在 MacBook 上手工复制了 `MechLib` 与 `PhysLean`，如果不重新生成 manifest，旧 manifest 仍可能保留错误路径。

建议迁移后：

- 重新执行 `lake update` 或等效构建流程
- 让 manifest 在新机器上重新解析

### 5.2 `src/mech_baseline_pipeline.egg-info/PKG-INFO`

该文件中也包含旧的本地路径与环境描述：

- `F:/AI4Mechanics/...`
- `OPENAI_API_KEY`

这不是主运行入口，但属于已生成元数据，可能与当前文档不一致。迁移后如果重新安装包，通常应重新生成，而不是依赖当前目录内旧的 `egg-info`。

### 5.3 历史报告与运行产物中的绝对路径

仓库中的历史报告、运行结果、日志中存在大量 `F:/...` 路径。它们不会阻止主流程运行，但会造成以下问题：

- 新设备上点击路径无效
- 报告中的环境描述与实际设备不一致
- 容易误判某些路径仍然有效

这类内容主要存在于：

- `reports/`
- `runs/`
- `outputs/`

## 6. 当前最可能的迁移失败链路

如果直接把当前仓库拷到 MacBook，然后运行：

```bash
python -m mech_pipeline.cli run --config configs/mechanics101_proxy_gpt54_20260409.yaml
```

最可能出现的失败顺序是：

1. Python 依赖未安装或 `PYTHONPATH` 未设置，导致导入失败。
2. 配置中的 `F:/...` 路径找不到，导致数据集或 Lean 路径校验失败。
3. 即使手工改了 YAML，`lakefile.toml` / `lake-manifest.json` 仍因本地依赖路径不对而无法构建 Lean 环境。
4. 即使 Lean 环境修好，若未设置 `OPENAI_PROXY_KEY` / `OPENAI_API_KEY`，真实 API 仍无法运行。

## 7. 建议的迁移处理顺序

建议在 MacBook 上按以下顺序处理，而不是直接尝试运行主流程：

1. 安装 Lean 工具链并确认 [lean-toolchain](f:/AI4Mechanics/coding/pipeline1/lean-toolchain) 对应版本可用。
2. 准备本地仓库布局：
   - `pipeline1`
   - `MechLib`
   - `PhysLean-master`
   - `Lean4PHYS` benchmark 数据
3. 修正 [lakefile.toml](f:/AI4Mechanics/coding/pipeline1/lakefile.toml) 与 [lake-manifest.json](f:/AI4Mechanics/coding/pipeline1/lake-manifest.json) 中的路径依赖。
4. 修改主配置文件中的本地路径：
   - [config.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)
   - 以及你实际会使用的 `configs/*.yaml`
5. 配置 API key 与 `base_url`。
6. 先运行一个最小样本或 smoke 配置，再运行全量实验。

## 8. 推荐优先修改的文件

如果目标是在 MacBook 上尽快跑起来，优先检查这几个文件：

1. [config.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)
2. [lakefile.toml](f:/AI4Mechanics/coding/pipeline1/lakefile.toml)
3. [lake-manifest.json](f:/AI4Mechanics/coding/pipeline1/lake-manifest.json)
4. 你将实际使用的那一份 `configs/*.yaml`
5. [README.md](f:/AI4Mechanics/coding/pipeline1/README.md)

## 9. 简明检查清单

在 MacBook 上开始运行前，至少确认以下事项：

- Lean 版本与 [lean-toolchain](f:/AI4Mechanics/coding/pipeline1/lean-toolchain) 一致
- `MechLib` 与 `PhysLean-master` 已就位
- `lakefile.toml` / `lake-manifest.json` 中的依赖路径有效
- `bench_path` 指向真实存在的数据文件
- `physlean_dir` / `mechlib_dir` 指向真实存在的目录
- `summary_corpus_path` 指向真实存在的 `theorem_corpus.jsonl`
- Python 依赖已安装
- `PYTHONPATH` 已设置为 `src`
- API key 环境变量已设置
- 选中的 YAML 已替换掉 `F:/...` 路径

## 10. 总结

当前仓库的可迁移性问题并不在于代码逻辑本身依赖 Windows，而在于：

- 路径默认值高度本地化
- Lean 依赖通过本地目录绑定
- 配置模板与文档默认假设当前机器的目录结构和 API 环境

因此，迁移到 MacBook 的关键不是“改代码兼容 macOS”，而是**先清理路径与环境假设**。在未完成这一步之前，直接运行主流程的失败概率很高。
