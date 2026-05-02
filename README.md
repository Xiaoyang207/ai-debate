> **本程序 100% 由人工智能生成，无任何人工编写、修改，仅人工引导AI**  
> 设计、代码、文档全部由 AI 自动完成。  
> 包括此 README。

---
这是一个 **AI 辩论赛系统**，100% 由 AI 生成，用于让大模型模拟正反双方进行结构化辩论。

## 核心功能

- **四环节辩论赛制**：立论陈词 → 攻辩交锋 → 质询追问 → 总结陈词，每环节可独立设置发言轮数
- **立场强制约束**：正方必须支持辩题，反方必须反对，系统会自动检测并过滤“立场漂移”
- **实时可视化**：Tkinter 图形界面，区分正反方颜色（蓝/红），显示进度条、耗时统计
- **导入/导出**：支持将辩论记录导出为 Markdown 或 JSON 格式

## 技术栈

- **UI**：Tkinter
- **辩论引擎**：AutoGen AgentChat（`RoundRobinGroupChat`）
- **大模型**：兼容 OpenAI API 格式（默认 DeepSeek）

## 项目结构

| 文件 | 职责 |
|------|------|
| `main.py` | 程序入口 |
| `ui.py` | Tkinter 界面，用户交互 |
| `debate_engine.py` | 辩论引擎核心，管理 AutoGen 团队、流式处理 |
| `models.py` | 配置类、环节定义、主题色板 |
| `text_filters.py` | 文本清洗、立场漂移检测 |
| `export.py` | 导出 Markdown/JSON 及摘要统计 |

## 许可证

**CC BY-NC 4.0**（禁止商用）

<img width="1458" height="1392" alt="QQ20260503-015743" src="https://github.com/user-attachments/assets/0c0c73c9-d03a-4c7f-8dfc-c3a65d8c3b9e" />


---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10 或更高版本
- 能够连接互联网（用于调用大模型 API）
- 操作系统：Windows / macOS / Linux 均可

### 2. 安装依赖

打开终端（命令行），执行以下命令：

pip install autogen-agentchat autogen-ext
————
Tkinter 是 Python 标准库的一部分，通常不需要额外安装。
若 Linux 下提示缺少 tkinter，请使用包管理器安装（如 sudo apt install python3-tk）。

### 3. 获取 API 密钥
本应用默认使用 DeepSeek 提供的大模型服务。

访问 DeepSeek 开放平台 并注册账号

在「API Keys」页面创建一个新的 API Key

复制该 Key（形如 sk-xxxxxxxxxxxxxxxx）

⚠️ 请妥善保管您的 API Key，切勿泄露。

🔧 更换模型服务商
本应用默认使用 DeepSeek，但支持任意兼容 OpenAI API 格式的服务商（如 OpenAI、通义千问、智谱、零一万物等）。

修改方法
打开 models.py 文件，找到 DebateConfig 类（约第 120 行），修改以下两个字段的默认值：

python
# 修改前（DeepSeek 默认）
base_url: str = "https://api.deepseek.com/"
model: str = "deepseek-v4-pro"

# 修改后示例（以 OpenAI 为例）
base_url: str = "https://api.openai.com/v1/"
model: str = "gpt-4o"
注意事项
API 密钥需从对应平台获取

模型名称须与平台提供的模型 ID 完全一致

本应用调用的是 /v1/chat/completions 接口，请确认服务商支持该端点

修改后保存文件，重新启动 main.py 即可生效

4. 启动程序
在项目目录下运行：

bash
python main.py
稍等片刻，图形界面将启动。

⚠️ 注意事项
本软件仅供学习、研究、个人娱乐使用，禁止用于商业用途

辩论内容由大模型实时生成，可能包含不当言论；请酌情判断

请勿输入任何个人隐私信息

若使用 DeepSeek API，请遵守其服务条款

🧾 关于
作者：人工智能

and  xiaoyang207

代码贡献：0 行人工代码

协议：CC BY-NC 4.0
