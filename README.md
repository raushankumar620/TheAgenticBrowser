# 🌐 Agentic Browser

## 📑 Table of Contents

- [📝 Overview](#overview)
- [✨ Features](#features)
- [🏗️ Architecture](#architecture)
- [🤖 Agents Workflow](#agents-workflow)
- [⚡ Quick Start](#quick-start)
- [📄 License](#license)
- [🙏 Acknowledgements](#acknowledgements)

---

## 📝 Overview

**Agentic Browser** is an agent-powered system that automates browser interactions using natural language commands. Built atop the [PydanticAI Python agent framework](https://github.com/pydantic/pydantic-ai), it empowers users to automate tasks like form filling, product search, data extraction, media interaction, and project management on diverse platforms—all with simple text instructions.

---

## ✨ Features

### 🧠 Browser Automation

- **🔍 Web Research & Analysis**  
  Natural language search across academic papers, travel portals, and code repositories.

- **📊 Data Extraction**  
  Extracts and compiles sports stats, historical figures, stock market data, currencies, and more.

- **🛒 E-commerce Scraping**  
  Retrieves price, specs, and availability from various shopping sites.

- **🌍 Smart Web Traversal**  
  Context-aware navigation and cross-domain data correlation.

---

## 🏗️ Architecture

![Agentic Browser Workflow](ta_browser_workflow.png)

Agentic Browser employs a tri-agent collaborative architecture:

- **🧩 Planner Agent**  
  Strategizes and decomposes user requests into actionable steps. Adapts plans based on ongoing results.

- **🕹️ Browser Agent**  
  Executes browser actions (clicks, typing, navigation, extraction) using automation tools.

- **🔬 Critique Agent**  
  Evaluates outcomes, analyzes screenshots & DOM, and guides workflow quality.

Together, these agents form an iterative feedback loop to ensure tasks are completed accurately and efficiently.

---

## 🤖 Agents Workflow

### 1️⃣ Planning Phase  
- **Planner Agent:**  
  - Receives request  
  - Analyzes requirements  
  - Generates step-by-step plan  
  - Determines first action

### 2️⃣ Execution Phase  
- **Browser Agent:**  
  - Executes plan step  
  - Performs browser actions (navigation, click, input)  
  - Uses DOM/screenshot analysis  
  - Reports results

### 3️⃣ Evaluation Phase  
- **Critique Agent:**  
  - Reviews execution  
  - Analyzes screenshots/DOM  
  - Verifies success  
  - Decides:  
    - Complete task  
    - Continue to next step  
    - Request plan modification

This loop continues until the task is completed or a terminal condition is reached.

---

## ⚡ Quick Start

### 🛠️ Setup

Follow these steps to install and configure Agentic Browser:

#### 1. 📦 Install `uv`

Agentic Browser uses [`uv`](https://github.com/astral-sh/uv) for Python environment and dependency management.

- **macOS/Linux**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows**
  ```bash
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
  _Or install using pip_

#### 2. 🚀 Clone the Repository
```bash
git clone https://github.com/TheAgenticAI/TheAgenticBrowser
cd TheAgenticBrowser
```

#### 3. 🐍 Create & Activate Virtual Environment
```bash
uv venv --python=3.11
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

#### 4. 📥 Install Dependencies
```bash
uv pip install -r requirements.txt
```

#### 5. 🌐 Install Playwright Drivers
```bash
playwright install
```
*To use your local Chrome with Playwright, set `BROWSER_STORAGE_DIR` to your Chrome profile path in `.env`.*

#### 6. ⚙️ Configure Environment Variables
Copy and edit the `.env` file:
```bash
cp .env.example .env
```
Set the following in `.env`:
```
# AGENTIC_BROWSER Configuration
AGENTIC_BROWSER_TEXT_MODEL=<text model name, e.g. "gpt-4o">
AGENTIC_BROWSER_TEXT_API_KEY=<your text model API key>
AGENTIC_BROWSER_TEXT_BASE_URL=<text model base url, e.g. "https://api.openai.com/v1">

# Screenshot Analysis Configuration
AGENTIC_BROWSER_SS_ENABLED=<true/false>
AGENTIC_BROWSER_SS_MODEL=<screenshot model name, e.g. "gpt-4o">
AGENTIC_BROWSER_SS_API_KEY=<your screenshot model API key>
AGENTIC_BROWSER_SS_BASE_URL=<screenshot model base url, e.g. "https://api.openai.com/v1">

# Logging
LOGFIRE_TOKEN=<your logfire write token>

# Google Search Configuration
GOOGLE_API_KEY=<your Custom Search JSON API>
GOOGLE_CX=<your Google Custom Search Engine ID>

# Browser Configuration
BROWSER_STORAGE_DIR=<path to browser storage dir, e.g. "./browser_storage">
STEEL_DEV_API_KEY=<Optional: Enable remote browser via Steel Dev CDP>
```

#### 7. 🏃‍♂️ Run the Project
- **Direct**
  ```bash
  python3 -m core.main
  ```
- **API Server**
  ```bash
  uvicorn core.server.api_routes:app --loop asyncio
  ```
  _Sample API call:_
  ```http
  POST http://127.0.0.1:8000/execute_task
  {
      "command": "Give me the price of RTX 3060ti on amazon.in and give me the latest delivery date."
  }
  ```

### 🐳 Running API with Docker (for AgenticBench)

#### Ubuntu/Windows:
```bash
docker build -t agentic_browser .
docker run -it --net=host --env-file .env agentic_browser
```
#### macOS:
```bash
docker build -t agentic_browser .
docker run -it -p 8000:8000 --env-file .env agentic_browser
```

---

## 📄 License

This repository is licensed under the [MIT License](LICENSE).

---

## 🙏 Acknowledgements

- [Agent-E](https://github.com/EmergenceAI/Agent-E?tab=readme-ov-file)
- [PydanticAI Python Agent Framework](https://github.com/pydantic/pydantic-ai)

---
