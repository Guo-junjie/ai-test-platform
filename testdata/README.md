# 企业测试平台被测产品数据包

`testdata` 只保留两套长期复用的开源被测产品。每套产品的数据相互独立，可用于验证平台的项目接入、需求解析、接口文档解析、AI 用例生成、用例评审、接口测试、缺陷与报告等基础流程。

## 产品清单

| 产品 | 技术栈 | 被测服务 URL | Swagger UI | 数据包 |
|---|---|---|---|---|
| Spring PetClinic REST | Java / Spring Boot | `http://192.168.125.128:8301/petclinic` | `http://192.168.125.128:8301/petclinic/swagger-ui.html` | [`spring-petclinic-rest/`](spring-petclinic-rest/README.md) |
| RESTful E-Commerce | Node.js / Express | `http://192.168.125.128:8302` | `http://192.168.125.128:8302/api-docs` | [`restful-ecommerce/`](restful-ecommerce/README.md) |

当前虚拟机部署目录为 `/opt/aitp-test-products`，容器使用 `restart: unless-stopped`，虚拟机重启后会自动恢复。若容器没有运行，可执行：

```bash
cd /opt/ai-test-platform
sudo docker compose -p aitp-test-products -f testdata/compose.yml up -d
python3 testdata/smoke-test.py
```

`-p aitp-test-products` 与虚拟机现有部署的 Compose 项目名一致，可继续管理已经创建的容器。首次部署到其他机器时也建议固定使用这个项目名。

## 平台完整体验顺序

对每个产品分别执行以下流程，避免把两个产品的数据导入同一个平台项目：

1. 在平台创建项目，名称和被测服务 URL 参考上表。
2. 在“测试资产”中选择“接口文档解析”，上传项目目录下的 `openapi.json`，解析后导入接口资产。
3. 选择“需求文档解析”，上传 `requirements.md`，生成候选用例并完成人工评审、采纳和落库。
4. 将 `test-spec.md` 上传知识库，将 `glossary.md` 中的术语录入项目术语表。
5. 参考 `requests/` 中的请求体配置接口用例；需要鉴权时先执行登录接口并提取令牌。
6. 建立测试计划并执行，检查运行明细、断言、失败原因、缺陷关联和测试报告。

每个项目的 README 给出了具体接口、推荐用例和预期结果。

## 数据维护

OpenAPI 文档来自运行中的服务，并把 `servers` 地址统一改为当前虚拟机地址。服务升级后执行：

```bash
python3 testdata/refresh-interface-docs.py
python3 testdata/smoke-test.py
```

刷新脚本会覆盖两套 `openapi.json`，并检查 PetClinic 至少包含 40 个操作、E-Commerce 至少包含 10 个操作。若虚拟机地址变化，可传入 `--host`：

```bash
python3 testdata/refresh-interface-docs.py --host 192.168.125.200
python3 testdata/smoke-test.py --host 192.168.125.200
```

## 上游项目

- Spring PetClinic REST：<https://github.com/spring-petclinic/spring-petclinic-rest>
- RESTful E-Commerce：<https://github.com/mfaisalkhatri/Restful-Ecommerce>

数据包中的需求、测试规范和术语表用于平台功能验收，不是上游项目的正式产品文档。
