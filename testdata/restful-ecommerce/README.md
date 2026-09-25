# RESTful E-Commerce 测试项目

## 项目定位

RESTful E-Commerce 是 Node.js/Express 接口服务，提供订单增删改查、JWT 鉴权、健康检查和图片上传。它适合验证令牌提取与传递、接口依赖、请求体校验、部分更新、文件上传和数据清理。

| 配置项 | 值 |
|---|---|
| 上游源码 | <https://github.com/mfaisalkhatri/Restful-Ecommerce> |
| 被测服务 URL | `http://192.168.125.128:8302` |
| 健康检查 | `GET /health` |
| Swagger UI | `http://192.168.125.128:8302/api-docs` |
| 在线 OpenAPI | `http://192.168.125.128:8302/swagger.json` |
| 数据包 OpenAPI | `openapi.json`（10 个路径、10 个操作） |
| 测试账号 | `admin / secretPass123` |

## 数据包内容

| 文件 | 平台用途 |
|---|---|
| `openapi.json` | 接口文档解析并导入接口资产 |
| `requirements.md` | 需求解析和 AI 用例生成 |
| `test-spec.md` | 知识库、用例补全和失败分析 |
| `glossary.md` | 项目术语表 |
| `requests/auth.json` | 获取 JWT 的请求体 |
| `requests/add-order.json` | 批量新增订单的请求体 |

## 推荐测试流程

1. 创建平台项目并填写被测服务 URL。
2. 上传 `openapi.json`，确认解析出 10 个接口操作。
3. 上传 `requirements.md` 生成候选用例，评审后落库。
4. 导入 `test-spec.md` 和术语表。
5. 执行 `POST /auth`，从响应提取 `token` 到环境变量。
6. 执行新增、查询、完整更新、部分更新、图片上传和删除接口；受保护接口设置 `Authorization: Bearer {{token}}`。

## 建议用例

| 场景 | 请求 | 预期 |
|---|---|---|
| 健康检查 | `GET /health` | HTTP 200，状态为运行中 |
| 正确登录 | `POST /auth`，使用样例请求体 | HTTP 201，响应包含 JWT |
| 错误密码 | `POST /auth`，密码错误 | HTTP 401 |
| 新增订单 | `POST /addOrder`，使用样例数组 | HTTP 201，返回新增订单 |
| 缺少字段 | 新增订单时删除 `product_id` | HTTP 400 |
| 无令牌更新 | `PUT /updateOrder/{id}` | HTTP 403 |
| 合法令牌更新 | 带 Bearer Token 更新已存在订单 | HTTP 200 |
| 删除清理 | 删除本轮创建的订单 | HTTP 204 |

`addOrder` 接口接收数组。写入用例应给 `user_id`、`product_id` 增加运行编号，执行后按响应 ID 删除，避免共享环境中的数据互相干扰。

## 已知产品行为

- 新增和查询接口无需令牌，更新、删除和图片上传需要 Bearer Token。
- 这是用于接口自动化练习的示例产品，业务规则较简单；平台测试应把文档与实测不一致记录为被测产品问题，而不是修改预期掩盖问题。
- `DELETE /deleteAllOrders` 会清除共享环境全部订单，不应放入日常测试计划。

## 源码接入

需要验证源码分析能力时，在平台的数据源中填写上游 Git 地址。共享接口测试不应停止或重启常驻容器。
