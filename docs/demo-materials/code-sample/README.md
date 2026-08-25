# e2e-demo-project 代码示例

> 用途：仅用于测试 AI 测试平台的【代码解析】功能（POST /api/analysis/run）

## 文件说明

| 文件 | 内容 | 数量 |
|---|---|---|
| `main.py` | FastAPI 入口，含 7 个 REST 接口（用户 5 + 订单 3 部分去重） | 290 行 |
| `requirements.txt` | 依赖列表 | - |
| `README.md` | 本文件 | - |

## 接口清单（已被 stack_detector 识别为 python_fastapi）

```
POST /api/v1/users/register    用户注册
POST /api/v1/users/login       账号密码登录
POST /api/v1/users/refresh     刷新 Token
GET  /api/v1/users/me          查询当前用户
PUT  /api/v1/users/password    修改密码
POST /api/v1/orders            创建订单
GET  /api/v1/orders/{id}       订单详情
POST /api/v1/orders/{id}/pay   订单支付（幂等）
POST /api/v1/orders/{id}/cancel 取消订单
```

`/api/analysis/run` 工具的解析流程：

1. **StackDetector** 扫描 → 识别语言 python + 框架 fastapi（看到 `from fastapi import`，加 routes 装饰器）
2. **APIExtractor** 正则提取 `@app.{method}("/path")` 装饰器行 → 拿到 path / method / 函数
3. **AICodeAnalyzer** 把 APIExtractor 结果喂 LLM → 补充业务领域、风险点

## 部署机调用

代码解析要求容器能读到该路径（Docker 容器内）。最简单做法：

```bash
# 1. 把整个 code-sample 目录上传到部署机的某个位置
# 例如用户 gjj 普通用户： scp -r ./code-sample gjj@gjj-virtual-machine:/tmp/
# 2. 调 API：
curl -X POST http://localhost:8000/api/analysis/run \
  -H "Content-Type: application/json" \
  -d '{"local_path": "/tmp/code-sample"}'
```
