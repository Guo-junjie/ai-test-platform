# Spring PetClinic REST 测试项目

## 项目定位

Spring PetClinic REST 是 Java/Spring Boot 的经典领域示例，包含主人、宠物、宠物类型、兽医、专业方向和就诊记录等关联资源。它适合验证大规模 OpenAPI 解析、关联 CRUD、路径参数、分页查询、数据一致性和错误处理。

| 配置项 | 值 |
|---|---|
| 上游源码 | <https://github.com/spring-petclinic/spring-petclinic-rest> |
| 被测服务 URL | `http://192.168.125.128:8301/petclinic` |
| 健康检查 | `GET /actuator/health` |
| Swagger UI | `http://192.168.125.128:8301/petclinic/swagger-ui.html` |
| 在线 OpenAPI | `http://192.168.125.128:8301/petclinic/v3/api-docs` |
| 数据包 OpenAPI | `openapi.json`（19 个路径、43 个操作） |
| 默认账号 | 当前部署未启用接口鉴权；上游启用鉴权时通常使用 `admin / admin` |

## 数据包内容

| 文件 | 平台用途 |
|---|---|
| `openapi.json` | 接口文档解析并导入接口资产 |
| `requirements.md` | 需求解析和 AI 用例生成 |
| `test-spec.md` | 知识库、用例补全和失败分析 |
| `glossary.md` | 项目术语表 |
| `requests/create-owner.json` | 创建主人接口的可执行请求样例 |

## 推荐测试流程

1. 创建平台项目，填写上面的被测服务 URL。
2. 上传 `openapi.json`，确认解析结果包含 owners、pets、visits、vets、pettypes、specialties 等资源。
3. 上传 `requirements.md` 生成用例，评审后落库。
4. 导入 `test-spec.md` 和术语表，为 AI 生成和知识问答提供项目上下文。
5. 先执行 `GET /api/owners` 获取当前数据，再用 `POST /api/owners` 和 `requests/create-owner.json` 创建主人。
6. 从响应提取主人 ID，继续验证查询、更新、创建宠物、创建就诊和删除清理。

## 建议用例

| 场景 | 请求 | 预期 |
|---|---|---|
| 健康检查 | `GET /actuator/health` | HTTP 200，`status=UP` |
| 查询主人 | `GET /api/owners` | HTTP 200，返回主人数组 |
| 创建主人 | `POST /api/owners`，使用样例请求体 | HTTP 201，响应包含新 ID |
| 查询不存在主人 | `GET /api/owners/2147483647` | HTTP 404 |
| 必填字段校验 | 创建主人时删除 `firstName` | HTTP 400 |
| 数据链路 | 主人下创建宠物，再为宠物创建就诊 | 各资源的关联 ID 一致 |
| 清理数据 | 删除本轮新增的就诊、宠物和主人 | 删除成功，之后查询返回 404 |

创建类用例应使用唯一姓氏或电话号码，并在测试计划结尾执行清理，避免多次运行相互影响。

## 源码接入

需要验证源码分析能力时，在平台的数据源中填写上游 Git 地址。当前镜像是稳定的共享被测环境，不要让普通接口测试任务停止或重启该容器。
