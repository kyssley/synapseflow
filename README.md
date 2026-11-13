<div align="center">

# 🧠 SynapseFlow

**A Self-Evolving Digital Nervous System for Multi-System Workflows**  
**面向多系统连接与自我进化的“数字神经中枢”智能体框架**

[English](#english) | [中文说明](#中文说明)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Architecture: Cortex-Spinal](https://img.shields.io/badge/Architecture-Cortex--Spinal-purple.svg)](#architecture)

</div>

---

<a name="english"></a>
## 🌍 English

### 💡 Core Philosophy: Why Another Agent Framework?

Most LLM Agents treat the foundation model as an all-purpose worker—reasoning from scratch on every single step. In real-world multi-system environments (ERP, CRM, Databases, IoT), this leads to **compounding errors, high latency, and prohibitive API costs**.

**SynapseFlow** is inspired by biological nervous systems. It shifts the LLM from a *"hardworking laborer"* to a *"system architect"* through a **Perceive → Decide → Act → Feedback → Distill** closed loop:

1. **Cortex & Spinal Dual-Engine**: High-frequency, deterministic workflows run on the **Spinal Layer** (fast, cheap, predictable). Only novel or complex cross-system anomalies escalate to the **Cortex** (LLM).
2. **Skill Distillation (Self-Evolution)**: Once the Cortex successfully navigates a complex multi-system workflow, or a human modifies an action during approval, the **Distiller** crystallizes the reviewed trajectory into a deterministic **Skill**, pushing it down to the Spinal Layer.
3. **Standardized Synapses**: Connect heterogeneous systems through unified **MCP / OpenAPI** adapters with semantic input/output mapping and safety guardrails.

> **"The more you use SynapseFlow, the less it relies on LLMs—becoming faster, cheaper, and more deterministic over time."**

<a name="architecture"></a>
### 🏗️ Architecture

```text
[ Environment / Sensors ] ──(Perceive)──> [ Spinal Router ]
                                              │       │
                          (Hit: Reflex Arc) ◄─┘       └─► (Miss / Anomaly)
                                │                               │
                                ▼                               ▼
                     [ Deterministic DAG ]             [ LLM Cortex Planner ]
                                │                               │
                                └───────────┬───────────────────┘
                                            ▼
                               [ Pain Guardrails (HITL) ]
                                            │ (Act)
                                            ▼
                             [ Multi-System Synapses (API) ]
                                            │ (Feedback & Diff)
                                            ▼
                              [ Skill Distiller (Evolution) ]
                                            │ (Crystallize)
                                            ▼
                                     [ Skills Vault ]
```

The same DAG executor and guardrail funnel serve both routes. A cached reflex therefore **cannot bypass permission checks, human approval, or high-risk execution limits**.

### ⚡ Quick Start

**Requirements:** Python 3.11+. Both examples use in-memory mocks and run directly from a source checkout without API keys, external services, or package installation.

```bash
# Monitoring alert -> logs -> approved isolation -> notification
python examples/01_ops_auto_heal.py

# ERP semantic mapping -> reviewed CRM ticket -> distilled reusable skill
python examples/02_erp_crm_sync.py
```

Each example demonstrates a first Cortex run and a second Spinal run after a **cold restart**, proving that the learned JSON skill is reloaded from disk rather than cached only in memory.

For real OpenAPI/MCP connections, install the lightweight HTTP dependency and package:

```bash
python -m pip install -e .
```

Application wiring uses the actual micro-kernel API:

```python
from synapse_flow import Cortex, Guardrails, Hub, SynapseRegistry

registry = SynapseRegistry()
# registry.register(Synapse(...))  # Register OpenAPI or MCP capabilities.

hub = Hub(
    synapses=registry,
    cortex=Cortex(llm=your_llm_client),       # async complete(prompt: str) -> str
    guardrails=Guardrails(reviewer=your_reviewer),
    vault_dir="./skills_vault",
)

result = await hub.dispatch("Read ERP order 42 and escalate it if delayed")
print(result.route, result.outputs)
await hub.aclose()
```

`your_llm_client` and `your_reviewer` are integration points, not hidden network dependencies. The examples provide deterministic mock implementations of both.

### 📁 Project Structure

```text
SynapseFlow/
├── README.md                  # Bilingual project homepage / 双语主页说明
├── pyproject.toml             # Minimal modern packaging / 极简依赖配置
├── synapse_flow/              # Core micro-kernel (< 1000 lines)
│   ├── __init__.py
│   ├── cortex.py              # [Brain] LLM planning & runtime reflection / 大脑
│   ├── spinal.py              # [Spinal] Deterministic DAG & reflex arcs / 脊髓
│   ├── synapse.py             # [Synapses] MCP / OpenAPI adapters / 突触
│   ├── guardrails.py          # [Pain] Permissions, HITL diffs & limits / 痛觉
│   ├── distiller.py           # [Evolution] Trajectory & Diff distillation / 进化
│   └── hub.py                 # [Hub] Dual-engine routing orchestration / 中枢
├── skills_vault/              # Readable, auditable JSON skills / 可审计技能库
└── examples/
    ├── 01_ops_auto_heal.py    # Alert -> logs -> isolate -> notify / 运维自愈
    └── 02_erp_crm_sync.py     # ERP/CRM semantic alignment / 异构系统协同
```

### 🔐 Safety and Skill Persistence

- **Human approval is route-independent.** High-risk actions require a reviewer on both Cortex and Spinal execution.
- **Diffs are learned.** Approved argument modifications are applied to the distilled skill; unified diffs are stored in skill metadata.
- **Data flow remains reusable.** `${steps.step_id.field}` references survive distillation instead of being replaced by observed output values.
- **Business outputs are not persisted.** The vault contains intents, actions, dependencies, timestamps, rationale, and review diffs—not step responses.
- **Atomic JSON writes and deterministic lookup.** Skills are matched by normalized intent and loaded from the vault at startup.
- **Timeout is not a security boundary.** The built-in `TimeoutSandbox` limits adapter execution time. Use a process, container, or remote sandbox for untrusted code.

### 🗺️ Roadmap

- [x] **Micro-Kernel**: Cortex-Spinal routing, DAG execution, and MCP/OpenAPI adapters
- [x] **Semantic Mapping**: Explicit cross-system input/output field mapping
- [x] **Diff Capture**: Preserve human approval modifications and audit diffs in skills
- [ ] **Constraint Learning**: Generalize repeated human diffs into reusable policy constraints
- [ ] **Semantic Intent Matching**: Optional retrieval-based skill matching beyond exact normalized intents
- [ ] **Visual Nerve Center**: Monitor signal flow, approvals, and skill distillation

### 🤝 Contributing & Vision

This project is a **minimalist micro-kernel** designed to spark ideas around **Agentic Self-Evolution** and **Enterprise System Glue**. PRs, architectural discussions, and new Synapse adapters are warmly welcomed!

---

<a name="中文说明"></a>
## 🇨🇳 中文说明

### 💡 核心哲学：为什么需要 SynapseFlow？

当前的多数 Agent 框架把大模型当成“事必躬亲的打工人”——每次面对任务都从头进行长链路推理。在真实的复杂业务环境中（ERP、CRM、异构数据库、物联网设备），这种模式会导致**错误率级联放大、响应延迟高、以及高昂的 Token 成本**。

**SynapseFlow（突触流）**借鉴生物神经系统的演化智慧，构建了**“感知 → 决策 → 行动 → 反馈 → 蒸馏进化”**的完整内循环，让大模型从“现场苦思冥想的工人”进化为“编写自动化流水线的工程师”：

1. **大脑-脊髓双层控制（Cortex-Spinal Architecture）**：高频、确定性的跨系统联动下沉在**脊髓层**（零 Token 消耗、毫秒级响应、确定性执行）；只有遇到未知异常或模糊意图时，信号才上传至**大脑皮层**（大模型）进行动态规划与错误反射。
2. **技能蒸馏与自进化（Skill Distillation）**：当大脑成功走通一次复杂的跨系统调用，或吸收人类审批时的参数微调（Diff）后，**蒸馏器**会自动将这次成功且经过审核的执行轨迹固化为确定性的**复合技能（Skill）**，沉淀至脊髓层。
3. **痛觉阻断与标准突触（Guardrails & Synapses）**：通过 MCP 与 OpenAPI 适配器将遗留系统抽象为标准“突触”；高危写操作自动触发“痛觉阻断”，交由人类在环（Human-in-the-loop）确认。

> **“越用越聪明，越用越便宜，越用越稳定——随着业务运转，系统对大模型实时推理的依赖持续下降。”**

### 🏗️ 系统架构

```text
[ 环境感知 / 业务事件 ] ──(感知 Perceive)──> [ 脊髓路由 Spinal Router ]
                                                 │              │
                             (命中: 条件反射) ◄───┘              └───► (未命中 / 复杂异常)
                                   │                                        │
                                   ▼                                        ▼
                        [ 确定性工作流 (DAG) ]                     [ 大脑规划器 (LLM Cortex) ]
                                   │                                        │
                                   └───────────────────┬────────────────────┘
                                                       ▼
                                          [ 痛觉阻断阀 (高危操作审批) ]
                                                       │ (行动 Act)
                                                       ▼
                                        [ 跨系统突触总线 (MCP / OpenAPI) ]
                                                       │ (反馈与人类 Diff)
                                                       ▼
                                         [ 技能蒸馏器 (Skill Distiller) ]
                                                       │ (固化沉淀)
                                                       ▼
                                                [ 技能库 Vault ]
```

两条路由共用同一个 DAG 执行器与安全执行入口，因此即使命中缓存技能，也**不能绕过权限校验、人工审批或高危执行限制**。

### ⚡ 快速上手

**环境要求：** Python 3.11+。两个示例均使用内存 Mock，无需 API Key、外部服务或预先安装依赖，可在源码目录直接运行：

```bash
# 监控报警 -> 日志排查 -> 人工批准隔离 -> 通知闭环
python examples/01_ops_auto_heal.py

# ERP 语义映射 -> CRM 高危审批 -> 技能蒸馏与复用
python examples/02_erp_crm_sync.py
```

每个示例都会比较首次 Cortex 执行与冷启动后的第二次 Spinal 执行，验证技能确实从 JSON 文件重新加载，而不是仅命中进程内缓存。

真实 OpenAPI/MCP 接入需要安装轻量 HTTP 依赖：

```bash
python -m pip install -e .
```

应用中使用真实的微内核 API 进行装配：

```python
from synapse_flow import Cortex, Guardrails, Hub, SynapseRegistry

registry = SynapseRegistry()
# registry.register(Synapse(...))  # 注册 OpenAPI 或 MCP 能力。

hub = Hub(
    synapses=registry,
    cortex=Cortex(llm=your_llm_client),       # 实现 async complete(prompt) -> str
    guardrails=Guardrails(reviewer=your_reviewer),
    vault_dir="./skills_vault",
)

result = await hub.dispatch("读取 ERP 订单 42，如果延期则生成 CRM 事件")
print(result.route, result.outputs)
await hub.aclose()
```

`your_llm_client` 与 `your_reviewer` 是显式集成点，而非隐藏的网络依赖。两个示例提供了确定性的 Mock 实现，可作为真实适配器的接入参考。

### 🔐 安全与技能持久化

- **审批与路由无关**：无论 Cortex 还是 Spinal，高危动作都必须经过 Reviewer。
- **吸收人工 Diff**：审批后的参数修改会进入技能，统一 Diff 会写入技能元数据供审计。
- **保留数据流模板**：`${steps.step_id.field}` 在蒸馏后仍然保留，不会被一次运行的输出常量替代。
- **不持久化业务输出**：技能库只保存意图、动作、依赖、时间、规划理由和审批 Diff，不保存步骤响应。
- **原子 JSON 写入与确定性匹配**：按规范化意图精确匹配，启动时从技能库加载。
- **超时不等于安全沙盒**：内置 `TimeoutSandbox` 只限制适配器执行时间；不可信代码应使用进程、容器或远程沙盒隔离。

### 🤝 抛砖引玉与贡献

本项目旨在以**最精炼的微内核代码**，探讨智能体框架如何通过**内部迭代闭环**真正融入企业级多系统工作流。欢迎提交 Issue 探讨架构设计，或贡献新的系统突触适配器！
