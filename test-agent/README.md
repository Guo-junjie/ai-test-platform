# 远程代码覆盖率 Agent（Java / Python / Go）

本 Agent 在**被测服务主机**运行，平台只选择管理员预先登记的服务。每次测试创建独立的覆盖率会话：启动插桩实例 → 原有 API/性能/集成测试向该实例发请求 → 停止实例 → 生成 `coverage.xml` 或 `coverage.out` → 平台解析入库。普通业务服务 URL 本身无法提供代码覆盖率。现有手动上传、HTTP XML 报告和工作空间报告仍可使用。

Java 使用不同的常驻模式：CI 先部署带 JaCoCo Java Agent 的测试服务；平台开始测试时通过 Test Agent 清零 JaCoCo 计数器，结束后导出 `jacoco.exec` 并用相同构建产物的 classfiles 生成 `jacoco.xml`。业务 JVM 在整个过程中持续运行。平台不会尝试对已运行的普通 JVM 事后插桩。

## Java 常驻服务：Jenkins → 测试平台 → JaCoCo

1. Jenkins 在独立测试环境构建并部署 Java 服务，在 JVM 启动参数加入：

   ```text
   -javaagent:/opt/jacoco/jacocoagent.jar=output=tcpserver,address=127.0.0.1,port=6300,dumponexit=false
   ```

   若 Agent 位于同一 Docker 网络的另一个容器，`address` 应绑定容器内可达地址；**不要把无认证的 JaCoCo TCP 端口发布到公网或宿主机**。测试业务 HTTP 端口照常保持服务。Agent 可以在同一主机，也可以与业务容器共享受限网络。
2. 从**同一次构建**保留 classfiles 和可选源码。在 Spring Boot fat JAR 场景，将 `BOOT-INF/classes` 提取到 Agent 可读目录；多模块项目可配置多个 classfiles 目录。将同版本 `jacococli.jar` 安装到 Agent 可读路径。不要把 `.exec` 当作报告直接上传，它缺少 classfiles 映射。
3. 主机管理员在 Agent 静态配置中登记服务（平台只提交服务名，不提交命令或文件路径）：

   ```json
   {
     "name": "orders-java",
     "language": "java",
     "tool": "jacoco",
     "workdir": "/srv/orders-coverage",
     "service_url": "http://orders-test.internal:8080",
     "health_url": "http://orders-test.internal:8080/health",
     "jacoco_host": "127.0.0.1",
     "jacoco_port": 6300,
     "jacoco_cli": "/opt/jacoco/jacococli.jar",
     "classfiles": ["/srv/orders-coverage/classes"],
     "sourcefiles": ["/srv/orders-coverage/src/main/java"],
     "commit_sha": "Jenkins 本次部署的完整 Git SHA"
   }
   ```

4. 在平台后端和 Celery Worker 注入相同的 `COVERAGE_AGENT_...` 令牌变量，配置 Agent 主机白名单和 HTTPS。项目的“探针配置”选择 **远程 Agent → Java（JaCoCo 常驻服务）**，设置唯一测试入口与严格模式。Jenkins 部署成功且健康检查通过后，调用平台创建测试任务；任务所带 Git commit 必须与 Agent 登记的部署 commit 一致。
   Jenkins 可使用专用 `tester` 账号和凭据库，在部署完成的阶段运行仓库的 [CI 触发脚本](examples/ci_trigger_java_plan.py)。脚本登录平台、向 `POST /api/plans/{plan_id}/execute` 传 `commit_sha`，轮询 Test Run 与 Coverage Run；采集失败或覆盖率门槛未通过时以非零状态退出：

   ```bash
   export AITP_URL=https://test-platform.example.com
   export AITP_PLAN_ID=计划的 UUID
   export DEPLOY_COMMIT_SHA="$GIT_COMMIT"
   # AITP_USER / AITP_PASSWORD 由 Jenkins Credentials 注入，不写入仓库或构建日志
   python3 test-agent/examples/ci_trigger_java_plan.py
   ```

   流程顺序是 **构建 → 部署 JaCoCo 测试 JVM 与相同版本 classfiles → 更新并重启 Agent → 健康检查 → 触发脚本**。GitHub Push Webhook 会在推送时触发计划，可能早于 Jenkins 部署完成；正式接入应选用部署完成后的 CI 触发入口，避免两个入口同时执行同一套用例。
5. 平台执行 `prepare → start(清零) → API/集成/性能用例 → stop(导出+清零) → JaCoCo CLI report → 解析入库`。Coverage Run 与 Test Run 绑定；采集失败或低于配置的行/分支覆盖率门槛时，严格模式使任务失败，CI 可据此阻断后续部署。**同一 JaCoCo 服务一次仅允许一个采集会话**。要统计“本次请求”必须使用隔离测试环境，防止其他用户、健康探测和并发流水线的请求混入计数器。

仓库提供持续运行的 Java HTTP 验收样例，JaCoCo TCP 只在平台 Docker 内网可达：

```bash
# .env 中先设置 COVERAGE_AGENT_JAVA_SAMPLE_TOKEN 为随机密钥
sudo docker compose --env-file .env -f test-agent/compose.java.example.yml up -d --build
sudo docker compose up -d --no-deps --force-recreate backend celery-worker
sudo docker exec -e PYTHONPATH=/app aitp-backend python /app/tests/manual_verify_coverage_agent.py --language java
sudo docker exec -e PYTHONPATH=/app aitp-backend python /app/tests/manual_verify_java_plan_coverage.py
sudo docker exec -e PYTHONPATH=/app aitp-backend python /app/tests/manual_verify_java_plan_coverage.py --mismatch
```

验收后 `http://<虚拟机>:8204/orders/1` 仍应返回 200；重复执行应得到不同 Test Run 的报告。样例中的 Agent 为内网演示使用 HTTP，正式部署应使用 HTTPS。

`examples/` 和 `compose.example.yml` 提供独立的 Python 验证服务（8202）与 Agent（8765）。它只为链路验收使用，不会替换已有 Go 被测服务（8201）；为内网演示方便使用 HTTP，生产部署应改为 HTTPS。

在平台根目录的 `.env` 中提供随机生成的 `COVERAGE_AGENT_SAMPLE_TOKEN`，然后运行：

```bash
sudo docker compose --env-file .env -f test-agent/compose.example.yml up -d --build
sudo docker compose up -d --no-deps --force-recreate backend celery-worker
sudo docker exec -e PYTHONPATH=/app aitp-backend python /app/tests/manual_verify_coverage_agent.py
```

验收脚本会复用名为「覆盖率验收样例（Python）」的独立项目，并新建一次测试任务。平台原有 Celery 执行器发送 `GET /orders/1`，脚本检查测试结果、Coverage Run 和关联 XML 报告。8202 服务只在测试窗口内运行，测试结束后 Agent 会停止它；普通浏览器在测试结束后访问 8202 会得到连接拒绝，这是预期行为。

## 部署

1. 准备一个与生产版本一致的隔离被测实例，使用**独立端口**。不要让 Agent 的启动命令与正在服务用户的进程争用端口。将 `coverage` 安装在该实例使用的 Python 虚拟环境中。
2. 在 Agent 主机安装 `requirements.txt`，将下面的 JSON 放在仅管理员可写的路径（示例 `/etc/aitp-coverage-agent.json`）：

   ```json
   {
     "artifact_root": "/var/lib/aitp-coverage",
     "services": [{
       "name": "orders",
       "workdir": "/srv/orders/current",
       "source": "/srv/orders/current/orders",
       "python_executable": "/srv/orders/venv/bin/python",
       "command": ["-m", "uvicorn", "orders.main:app", "--host", "0.0.0.0", "--port", "8202"],
       "service_url": "http://orders-test.internal:8202",
       "health_url": "http://orders-test.internal:8202/health",
       "commit_sha": "由部署流水线写入的 Git commit"
     }]
   }
   ```

3. 设置 `COVERAGE_AGENT_CONFIG`、`COVERAGE_AGENT_TOKEN`，使用 `uvicorn agent:app --host 127.0.0.1 --port 8765` 启动 Agent。通过 HTTPS 反向代理暴露给平台，并限制平台所在网段访问。业务进程及其子进程需要在退出时正常写出 coverage 数据；若进程被强制杀死，状态会显示 `NO_ARTIFACT` 或 `FAILED`。
4. 在平台 **API 和 Celery worker** 的环境中设置同一个 `COVERAGE_AGENT_...` 凭据环境变量，在 worker 中设置 `COVERAGE_AGENT_ALLOWED_HOSTS=coverage-agent.internal`。远程 Agent 默认要求 HTTPS；仅在受控内网演示环境设置 `COVERAGE_AGENT_ALLOW_HTTP=1`。项目页面的「代码覆盖率采集配置」选择远程 Python Agent，填写已登记服务名、Agent 地址和**环境变量名**，不要填写令牌值。
5. 在 Jenkins 部署步骤中把当前部署 commit 写入 Agent 配置的 `commit_sha`，或设置 Agent 环境变量 `COVERAGE_DEPLOY_COMMIT`。平台的测试任务带 commit 时会核对两者；不一致则停止采集并记录失败。部署/启动顺序应为：部署被测版本 → 更新 commit/Agent 配置并启动 Agent → 触发平台测试 → 等待 Coverage Run 结束。

安装示例：

```bash
python3 -m venv /opt/aitp-coverage-agent/venv
/opt/aitp-coverage-agent/venv/bin/pip install -r requirements.txt
/srv/orders/venv/bin/pip install coverage==7.6.12
COVERAGE_AGENT_CONFIG=/etc/aitp-coverage-agent.json COVERAGE_AGENT_TOKEN='从密钥管理器注入' \
  /opt/aitp-coverage-agent/venv/bin/uvicorn agent:app --host 127.0.0.1 --port 8765
```

## Go 服务：CI 构建与自动采集

Go HTTP 服务必须使用 Go 1.20+ 在 CI 中构建覆盖率版本。平台和 Agent 不会对已经运行的普通 Go 二进制自动插桩。建议由 Jenkins 为独立测试环境构建并部署，例如：

```bash
go build -cover -o /srv/orders-coverage/orders ./cmd/orders
# 可按需要使用 -coverpkg=./... 扩大模块内插桩范围
```

在被测主机安装与构建版本兼容的 Go 工具链，并由管理员登记 Agent 服务：

```json
{
  "name": "orders-go",
  "language": "go",
  "tool": "go_cover",
  "workdir": "/srv/orders-coverage",
  "command": ["/srv/orders-coverage/orders"],
  "go_executable": "/usr/local/go/bin/go",
  "service_url": "http://orders-test.internal:8203",
  "health_url": "http://orders-test.internal:8203/health",
  "commit_sha": "由部署流水线写入的 Git commit"
}
```

测试前 Agent 启动此二进制并设置本次任务独有的 `GOCOVERDIR`。测试结束后 Agent 发送停止信号；**Go 服务必须处理该信号并让 `main` 正常返回**，否则不会写出完整的 `covmeta`/`covcounters`。Agent 用 `go tool covdata textfmt` 转换成 `coverage.out`，平台按 Go **语句覆盖率**解析和展示。每个服务同一时刻仅允许一个覆盖率会话，避免端口争用。Jenkins 应先部署匹配 commit 的测试二进制及 Agent 配置，再触发平台测试；有版本不一致时严格模式会失败。

仓库提供与 8201 业务服务隔离的 Go 演示服务（8203）和 Agent（8766）：

```bash
# 在平台 .env 中提供随机生成的 COVERAGE_AGENT_GO_SAMPLE_TOKEN
sudo docker compose --env-file .env -f test-agent/compose.go.example.yml up -d --build
sudo docker compose up -d --no-deps --force-recreate backend celery-worker
sudo docker exec -e PYTHONPATH=/app aitp-backend python /app/tests/manual_verify_coverage_agent.py --language go
```

8201 的现有 Go 1.18 二进制并非覆盖率构建，不能直接获得请求级代码覆盖率；不要将演示配置指向它。升级 Go 构建链并为其准备独立覆盖率环境后，可按上述方式登记真实服务。

## 当前边界

- 目前支持 Java JaCoCo 常驻服务，以及 Python coverage.py 与 Go `go build -cover` 临时实例的远程 Agent 自动采集；C++、Kubernetes 自动插桩、Diff Coverage 与 CI 门禁属于后续阶段。
- 同一服务一次只允许一个活跃覆盖率会话，避免产物和端口互相污染。Agent 重启后内存中的进程会话不会恢复；部署时应在无活跃测试的窗口重启。
- 平台默认仅允许 `localhost`、`127.0.0.1`、`host.docker.internal` 或 `COVERAGE_AGENT_ALLOWED_HOSTS` 中的 Agent 主机，且不在数据库保存令牌本身。`required=true` 时启动或采集失败会使测试任务失败；否则测试结果保留，Coverage Run 单独显示失败原因。
