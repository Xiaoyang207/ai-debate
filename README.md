> **本程序 100% 由人工智能生成，无任何人工编写、修改或干预。**  
> 设计、代码、文档全部由 AI 自动完成。  
> 包括此 README。

---

## ⚖️ 许可证（禁止商用）

本软件采用 [Creative Commons 署名-非商业性使用 4.0 国际许可协议 (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/legalcode.zh-Hans) 进行许可。  
**您可以自由分享、复制、修改本软件，但必须遵守以下条款：**

- **署名** — 必须给出适当的署名（见协议文本）
- **非商业性使用** — **严格禁止将本软件用于商业目的**，包括但不限于销售、付费服务、广告推广、捆绑商业产品等。

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
