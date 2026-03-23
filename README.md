# Baseline V1 运行说明（中文）

本项目是面向力学题目的模块化 baseline pipeline，流程为：

`输入 -> A结构化 -> B命题候选 -> C Lean检查 -> D语义筛选 -> E证明生成 -> F指标与报告`

当前目标是可运行、可评测、可归因，不做训练/微调。

## 1. 环境要求

- Python `>=3.10`
- Lean4 / Lake（建议与本机 `PhysLean` 版本一致）
- 本地 `PhysLean`（默认路径：`F:/AI4Mechanics/PhysLean-master`）

数据源：

- 本地归档：`F:/AI4Mechanics/数据集/归档`
- PhyX：按 `hf-mirror -> huggingface` 自动回退

## 2. 安装

在项目根目录 `coding/pipeline1` 执行：

```bash
pip install -e .[dev]
```

如果不安装包，也可以这样运行：

```powershell
$env:PYTHONPATH='src'
python -m mech_pipeline.cli run --config configs/smoke_mock_local_text.yaml
```

## 2.1 Windows 终端编码（避免中文乱码）

项目 CLI 已在启动时自动切换到 UTF-8（含 `stdout/stderr` 与 Windows console codepage）。
如果你在当前终端仍看到乱码，请在运行前手动执行一次：

```powershell
chcp 65001 > $null
[Console]::InputEncoding  = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

## 3. 快速运行

### 3.1 Smoke（最快，mock + 不走 Lean）

```powershell
mech-baseline run --config configs/smoke_mock_local_text.yaml
```

### 3.2 MVP 文本模式（本地归档 + Lean preflight）

```powershell
mech-baseline run --config configs/mvp_local_text.yaml
```

### 3.3 MVP 图文模式（默认仅单图样本）

```powershell
mech-baseline run --config configs/mvp_local_image.yaml
```

### 3.4 MVP PhyX 模式

```powershell
mech-baseline run --config configs/mvp_phyx.yaml
```

### 3.5 常用参数

```powershell
mech-baseline run --config configs/mvp_local_text.yaml --limit 10 --tag myrun
mech-baseline run --config configs/mvp_local_text.yaml --dry-run
```

## 4. API_test 接口已写入项目（可直接运行）

已将你在 `coding/API_test` 中的三套接口与 API Key 直接写入以下配置：

- `configs/api_openai_proxy_gpt52.yaml`
- `configs/api_qwen_vl_plus.yaml`
- `configs/api_deepseek_chat.yaml`

对应参数：

1. OpenAI Proxy  
   - `base_url`: `https://api.openai-proxy.org/v1`  
   - `model_id`: `gpt-5.2`
2. Qwen  
   - `base_url`: `https://dashscope.aliyuncs.com/compatible-mode/v1`  
   - `model_id`: `qwen3-vl-plus`
3. DeepSeek  
   - `base_url`: `https://api.deepseek.com/v1`  
   - `model_id`: `deepseek-chat`

说明：

- 这三套配置已内置 `model.api_key`，不依赖环境变量即可运行。
- 同时保留了 `api_key_env` 作为后备。
- 默认 `lean.enabled=false`，用于先验证 API 通路稳定性。

运行命令：

```powershell
mech-baseline run --config configs/api_openai_proxy_gpt52.yaml --limit 1
mech-baseline run --config configs/api_qwen_vl_plus.yaml --limit 1
mech-baseline run --config configs/api_deepseek_chat.yaml --limit 1
```

如果需要开启 Lean 检查，请在对应配置中改为：

```yaml
lean:
  enabled: true
  preflight_enabled: true
```

## 5. 输出文件说明

每次运行会生成：

- `runs/<run_id>/`：本次运行归档
- `outputs/latest/`：最近一次运行快照

核心文件：

- `problem_ir.jsonl`
- `statement_candidates.jsonl`
- `compile_checks.jsonl`
- `semantic_rank.jsonl`
- `proof_attempts.jsonl`
- `proof_checks.jsonl`
- `sample_summary.jsonl`
- `metrics.json`
- `analysis.md`

## 6. 常见问题

### 6.1 `No module named mech_pipeline`

先执行：

1. `pip install -e .[dev]`，或
2. `$env:PYTHONPATH='src'`

### 6.2 `data_source_unavailable`

说明 `phyx_urls` 里所有地址都失败，请检查网络或镜像可达性。

### 6.3 图文模式样本被跳过

MVP 默认只处理单图样本，多图会标记：

- `unsupported_multi_image_sample`
