# IOTFast 物联网安全管理平台 - 常见故障排查与运维经验手册 (FAQ)

## 文档基本信息
- **文档编号**：`IOTFAST-OPS-FAQ-V1.0`
- **维护团队**：DevOps 运维团队 & 平台测试专家组
- **适用场景**：日常开发自测、测试环境联调、自动化测试执行排障、部署上云诊断

---

## 1. 认证鉴权与 HTTP 通信类常见问题

### Q1: 页面打开提示“网络错误”，无法加载验证码或无法登录？
- **现象描述**：浏览器访问前端页面后，控制台大量报错 `net::ERR_CONNECTION_REFUSED`，验证码图片处为裂图。
- **根本原因**：前端静态资源打包时将 Axios `baseURL` 硬编码为 `http://localhost:8201/`。当通过局域网/公网 IP 访问时，前端向用户本地机器发起请求引发跨域与拒绝连接。
- **排查与解决步骤**：
  1. 检查前端 `resource/public/html/assets/index.*.js`，全局搜索 `baseURL`；
  2. 将 `baseURL: "http://localhost:8201/"` 修改为相对路径 `baseURL: ""`；
  3. 强制刷新浏览器缓存（`Ctrl + F5`）后重新登录验证。

### Q2: 登录接口返回 200，但后续接口调用均提示 `401 Unauthorized`？
- **现象描述**：成功登录拿到 Token，但调用用户列表或设备管理接口时均被拦截。
- **排查思路**：
  1. **检查请求头**：确认 HTTP 请求头是否按规范携带了 `Authorization`，格式必须为 `Bearer <token>`（注意 `Bearer` 与 Token 之间必须有一个半角空格）；
  2. **Token 有效期**：查看服务端配置 `manifest/config/config.yaml` 中的 GToken 过期时间设置；
  3. **后端缓存状态**：如果启用了 Redis 缓存，检查 Redis 中对应 Token 键值是否已被驱逐或主动注销。

### Q3: 验证码输入正确却始终提示“验证码错误”？
- **根本原因**：
  1. 验证码生成接口返回了 `id` 与 `base64` 图片，登录接口必须回传该 `id`；如果多次点击刷新了验证码，但登录表单绑定的仍然是旧 `id`，则校验失败；
  2. 服务器端本地验证码缓存设置的 TTL 较短（如 60 秒），超时后自动失效。

---

## 2. 物联网设备与 MQTT 通信类常见问题

### Q1: 设备使用 MQTT 客户端（如 MQTTX）连接提示 Connection Refused？
- **排查步骤**：
  1. **检查服务监听**：在服务器执行 `ss -tulpn | grep 1883`，确认 MQTT 端口是否正常监听；
  2. **防火墙与安全组**：确认宿主机防火墙（`ufw` 或 `firewalld`）是否放行了 1883（TCP）及 8883（TLS）端口；
  3. **认证参数校验**：确认 MQTT ClientId、Username 及 Password 是否与 IOTFast 平台设备认证规则匹配（若开启了严格认证）。

### Q2: 客户端发送了 MQTT 消息，但在平台的“消息记录”或“最新数据”中查不到？
- **排查步骤**：
  1. **检查主题匹配 (Topic Match)**：确认发送消息的 Topic 是否符合平台规则格式（注意大小写敏感以及通配符 `+`、`#` 规范）；
  2. **检查报文格式 (Payload Schema)**：IOTFast 物模型通常要求报文为标准 JSON 格式，若发送纯文本、乱码或无效 JSON，物模型解析引擎将丢弃并打印警告日志；
  3. **查看服务端日志**：
     ```bash
     tail -f /opt/iotfast/resource/log/run/$(date +%Y-%m-%d).log
     ```
     搜索是否有 `unmarshal payload error` 或 `topic router not found`。

---

## 3. 数据库与并发运维类常见问题

### Q1: 高频并发写入时出现 `database is locked` 错误？
- **根本原因**：当前使用的是本地单文件 SQLite 数据库（`data.db`）。SQLite 在并发写入时使用库级写锁，当多个并发事务争抢写锁超过超时阈值时会报错。
- **解决对策**：
  1. **轻量测试环境**：可在 GoFrame ORM 连接串中开启 WAL 模式：`link: "sqlite:./resource/data/data.db?_journal_mode=WAL&_busy_timeout=5000"`；
  2. **高并发生产环境**：在 `manifest/config/config.yaml` 中将数据库驱动切换为 MySQL 8.0 连接池，支持成百上千级并发并发事务。

### Q2: 服务进程异常退出或无法启动？
- **排查步骤**：
  1. 执行 `systemctl status iotfast.service` 查看退出状态码与错误信息；
  2. 执行 `journalctl -u iotfast.service -n 50 --no-pager` 查看详细崩溃栈；
  3. 确认配置文件 `manifest/config/config.yaml` 语法格式是否正确（YAML 缩进错误会导致启动直接 Panic）。
