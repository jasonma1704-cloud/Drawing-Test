# AI Mail Workflow

一个面向询价场景的自动化项目：

1. 通过 IMAP 自动拉取客户邮件，识别附件图纸。
2. 将图纸交给 Qwen-VL 做结构化信息提取。
3. 将结果自动推送到飞书群，并 @ 对应工程师。
4. 提供 Web UI 查看任务、日志和运行状态。

## 目录

- `app/main.py`：FastAPI Web UI 与 API
- `app/mail/`：IMAP 收件与附件解析
- `app/ai/`：Qwen-VL 结构化提取
- `app/feishu/`：飞书机器人推送
- `app/storage/`：SQLite 任务存储
- `app/utils/`：日志与文件工具
- `app/scheduler/task.py`：完整工作流执行器

## 快速开始

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

浏览器访问：

- `http://127.0.0.1:8000/`：仪表盘
- `http://127.0.0.1:8000/tasks`：任务列表
- `http://127.0.0.1:8000/settings`：配置查看

## 运行前要填的配置

- `IMAP_HOST / IMAP_USER / IMAP_PASSWORD`
- `QWEN_API_KEY`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_ENGINEER_USER_IDS`

## 说明

- 支持 `.pdf/.png/.jpg/.jpeg/.webp`
- PDF 会先渲染成图片，再交给 Qwen-VL
- 任务、状态、日志保存在 `workflow.db` 和 `logs/app.log`
- 工程师 @ 通过飞书 webhook 的 `<at user_id="ou_xxx">Name</at>` 方式拼接

## Docker

```bash
docker compose up --build
```

## 可继续增强的点

- 增加 Web UI 的“配置编辑”页面
- 增加邮件规则引擎（按客户、主题、图号自动分流到不同工程师）
- 增加失败重试队列和告警
- 增加 PDF 页码预览
