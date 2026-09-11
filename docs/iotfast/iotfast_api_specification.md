# IOTFast 物联网安全管理平台 - 企业级接口定义与联调规范

> **文档版本**：`v1.0.0`  
> **基准环境**：`http://192.168.125.128:8201`  
> **认证方式**：`Bearer JWT Token` (`Authorization: Bearer <token>`)  
> **文档用途**：供前端开发、自动化测试、接口评审与端到端系统集成联调。

---

## 一、全局接口设计规范

### 1.1 通信协议与数据格式
- **传输协议**：HTTP/1.1 与 WebSocket（支持 TLS 1.2+ 加密）；
- **数据交互格式**：请求与响应正文统一采用 `application/json; charset=utf-8`；
- **字符集编码**：全链路采用 `UTF-8` 编码。

### 1.2 认证与安全机制 (Authentication)
除验证码获取 (`/api/v1/pub/captcha/get`)、系统登录 (`/api/v1/system/login`) 与系统初始化接口外，平台所有受保护的业务接口均受 **GToken + Casbin RBAC** 鉴权体系保护。
客户端调用受保护接口时，必须在 HTTP Request Header 中注入：
```http
Authorization: Bearer <Your-Access-Token>
```
- Token 默认有效时间为 10 天（可通过服务端配置调整）；
- 未携带 Token 或 Token 过期失效时，统一返回 HTTP 200，响应体内 `code: 401` 或提示权限未授权。

### 1.3 统一响应报文格式 (Unified Response)
平台接口统一返回标准 JSON 封装结构：
```json
{
  "code": 0,
  "message": "操作成功",
  "data": {}
}
```
| 字段名 | 类型 | 含义说明 | 示例值 |
| :--- | :--- | :--- | :--- |
| `code` | `integer` | 业务状态码。`0` 表示操作成功，非 `0` 表示业务异常 | `0` |
| `message` | `string` | 状态描述信息或失败原因提示 | `"操作成功"` / `"密码错误"` |
| `data` | `object / array` | 接口实际业务数据载荷。查询无数据时返回 `null` 或 `[]` | `{ "id": 1, ... }` |

### 1.4 分页查询规范 (Pagination Schema)
所有列表类分页查询接口请求参数统一包含：
| 参数名 | 类型 | 必填 | 默认值 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| `pageNum` | `integer` | 否 | `1` | 当前查询页码（从 1 开始） |
| `pageSize` | `integer` | 否 | `10` | 每页记录数（最大推荐不超过 100） |
| `orderBy` | `string` | 否 | - | 排序规则字段（如 `created_at desc`） |

分页查询响应的 `data` 统一封装：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "total": 120,
    "list": [
      { ... },
      { ... }
    ]
  }
}
```

---

## 二、接口分类概览

| 模块分类 | 描述说明 | 接口数量 | 核心特性 |
| :--- | :--- | :--- | :--- |
| **认证鉴权** | 涵盖 认证鉴权 相关增删改查及生命周期业务操作 | 12 | RESTful / GToken 鉴权 |
| **设备标签** | 涵盖 设备标签 相关增删改查及生命周期业务操作 | 10 | RESTful / GToken 鉴权 |
| **用户管理** | 涵盖 用户管理 相关增删改查及生命周期业务操作 | 9 | RESTful / GToken 鉴权 |
| **物模型属性** | 涵盖 物模型属性 相关增删改查及生命周期业务操作 | 7 | RESTful / GToken 鉴权 |
| **设备状态** | 涵盖 设备状态 相关增删改查及生命周期业务操作 | 6 | RESTful / GToken 鉴权 |
| **MQTT客户端状态** | 涵盖 MQTT客户端状态 相关增删改查及生命周期业务操作 | 6 | RESTful / GToken 鉴权 |
| **字典数据** | 涵盖 字典数据 相关增删改查及生命周期业务操作 | 6 | RESTful / GToken 鉴权 |
| **定时任务** | 涵盖 定时任务 相关增删改查及生命周期业务操作 | 6 | RESTful / GToken 鉴权 |
| **菜单与规则** | 涵盖 菜单与规则 相关增删改查及生命周期业务操作 | 6 | RESTful / GToken 鉴权 |
| **角色权限** | 涵盖 角色权限 相关增删改查及生命周期业务操作 | 6 | RESTful / GToken 鉴权 |
| **设备品类** | 涵盖 设备品类 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **设备分组** | 涵盖 设备分组 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **设备管理** | 涵盖 设备管理 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **设备类型** | 涵盖 设备类型 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **链路管理** | 涵盖 链路管理 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **网络链路** | 涵盖 网络链路 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **串口链路** | 涵盖 串口链路 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **消息日志** | 涵盖 消息日志 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **MQTT主题** | 涵盖 MQTT主题 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **主题流转记录** | 涵盖 主题流转记录 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **系统配置** | 涵盖 系统配置 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **部门管理** | 涵盖 部门管理 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **字典类型** | 涵盖 字典类型 相关增删改查及生命周期业务操作 | 5 | RESTful / GToken 鉴权 |
| **岗位管理** | 涵盖 岗位管理 相关增删改查及生命周期业务操作 | 4 | RESTful / GToken 鉴权 |
| **系统初始化** | 涵盖 系统初始化 相关增删改查及生命周期业务操作 | 3 | RESTful / GToken 鉴权 |
| **登录日志** | 涵盖 登录日志 相关增删改查及生命周期业务操作 | 3 | RESTful / GToken 鉴权 |
| **遥测数据** | 涵盖 遥测数据 相关增删改查及生命周期业务操作 | 2 | RESTful / GToken 鉴权 |
| **功能演示** | 涵盖 功能演示 相关增删改查及生命周期业务操作 | 1 | RESTful / GToken 鉴权 |
| **公共服务** | 涵盖 公共服务 相关增删改查及生命周期业务操作 | 1 | RESTful / GToken 鉴权 |
| **服务监控** | 涵盖 服务监控 相关增删改查及生命周期业务操作 | 1 | RESTful / GToken 鉴权 |

---

## 三、核心模块接口详解

### 3.1 模块：认证鉴权 (共 12 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/system/gen/columnList` | 认证鉴权 - columnList操作 | Bearer Token |
| `DELETE` | `/api/v1/system/gen/delete` | 认证鉴权 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/gen/downGenCode` | 认证鉴权 - downGenCode操作 | Bearer Token |
| `PUT` | `/api/v1/system/gen/edit` | 认证鉴权 - 更新编辑 | Bearer Token |
| `PUT` | `/api/v1/system/gen/genCode` | 认证鉴权 - genCode操作 | Bearer Token |
| `GET` | `/api/v1/system/gen/getDbTable` | 认证鉴权 - getDbTable操作 | Bearer Token |
| `GET` | `/api/v1/system/gen/preview` | 认证鉴权 - 预览代码生成模板产物 | Bearer Token |
| `GET` | `/api/v1/system/gen/relationTable` | 认证鉴权 - relationTable操作 | Bearer Token |
| `POST` | `/api/v1/system/gen/tableImport` | 认证鉴权 - tableImport操作 | Bearer Token |
| `GET` | `/api/v1/system/gen/tableList` | 认证鉴权 - tableList操作 | Bearer Token |
| `POST` | `/api/v1/system/login` | 认证鉴权 - 用户账号密码与验证码登录 | 公开接口 |
| `DELETE` | `/api/v1/system/loginOut` | 认证鉴权 - loginOut操作 | 公开接口 |

#### 3.1.1 重点接口定义与示例

##### 【GET】 `/api/v1/system/gen/columnList`
- **功能说明**：认证鉴权 - columnList操作
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `TableId` | `query` | `integer` | 否 | - |
  | `DateRange` | `query` | `array` | 否 | - |
  | `PageNum` | `query` | `integer` | 否 | - |
  | `PageSize` | `query` | `integer` | 否 | - |
  | `OrderBy` | `query` | `string` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/gen/delete`
- **功能说明**：认证鉴权 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 是 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.2 模块：设备标签 (共 10 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceLabel/add` | 设备标签 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceLabel/delete` | 设备标签 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceLabel/edit` | 设备标签 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceLabel/get` | 设备标签 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceLabel/list` | 设备标签 - 分页查询列表 | Bearer Token |
| `POST` | `/api/v1/device/deviceLabelData/add` | 设备标签 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceLabelData/delete` | 设备标签 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceLabelData/edit` | 设备标签 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceLabelData/get` | 设备标签 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceLabelData/list` | 设备标签 - 分页查询列表 | Bearer Token |

#### 3.2.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceLabel/add`
- **功能说明**：设备标签 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/device/deviceLabel/delete`
- **功能说明**：设备标签 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.3 模块：用户管理 (共 9 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/user/add` | 用户管理 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/user/delete` | 用户管理 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/user/edit` | 用户管理 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/user/getEdit` | 用户管理 - 获取编辑回显数据 | Bearer Token |
| `GET` | `/api/v1/system/user/getUserMenus` | 用户管理 - 获取当前登录用户的菜单与权限规则 | Bearer Token |
| `GET` | `/api/v1/system/user/list` | 用户管理 - 分页查询列表 | Bearer Token |
| `GET` | `/api/v1/system/user/params` | 用户管理 - 获取字段元数据字典 | Bearer Token |
| `PUT` | `/api/v1/system/user/resetPwd` | 用户管理 - 重置登录密码 | Bearer Token |
| `PUT` | `/api/v1/system/user/setStatus` | 用户管理 - 变更启用/禁用状态 | Bearer Token |

#### 3.3.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/user/add`
- **功能说明**：用户管理 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/user/delete`
- **功能说明**：用户管理 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.4 模块：物模型属性 (共 7 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceCategoryData/add` | 物模型属性 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceCategoryData/delete` | 物模型属性 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceCategoryData/edit` | 物模型属性 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceCategoryData/get` | 物模型属性 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceCategoryData/history` | 物模型属性 - 查询物模型历史时序数据 | Bearer Token |
| `GET` | `/api/v1/device/deviceCategoryData/list` | 物模型属性 - 分页查询列表 | Bearer Token |
| `GET` | `/api/v1/device/deviceCategoryData/recent` | 物模型属性 - 查询最新遥测数据 | Bearer Token |

#### 3.4.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceCategoryData/add`
- **功能说明**：物模型属性 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/device/deviceCategoryData/delete`
- **功能说明**：物模型属性 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.5 模块：设备状态 (共 6 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceStatus/add` | 设备状态 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceStatus/delete` | 设备状态 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceStatus/edit` | 设备状态 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceStatus/get` | 设备状态 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceStatus/list` | 设备状态 - 分页查询列表 | Bearer Token |
| `PUT` | `/api/v1/device/deviceStatus/status` | 设备状态 - status操作 | Bearer Token |

#### 3.5.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceStatus/add`
- **功能说明**：设备状态 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/device/deviceStatus/delete`
- **功能说明**：设备状态 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.6 模块：MQTT客户端状态 (共 6 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/mqtt/mqttStatus/add` | MQTT客户端状态 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/mqtt/mqttStatus/delete` | MQTT客户端状态 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/mqtt/mqttStatus/edit` | MQTT客户端状态 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttStatus/get` | MQTT客户端状态 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttStatus/list` | MQTT客户端状态 - 分页查询列表 | Bearer Token |
| `PUT` | `/api/v1/mqtt/mqttStatus/status` | MQTT客户端状态 - status操作 | Bearer Token |

#### 3.6.1 重点接口定义与示例

##### 【POST】 `/api/v1/mqtt/mqttStatus/add`
- **功能说明**：MQTT客户端状态 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/mqtt/mqttStatus/delete`
- **功能说明**：MQTT客户端状态 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.7 模块：字典数据 (共 6 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/dict/data/add` | 字典数据 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/dict/data/delete` | 字典数据 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/dict/data/edit` | 字典数据 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/dict/data/get` | 字典数据 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/system/dict/data/getDictData` | 字典数据 - getDictData操作 | Bearer Token |
| `GET` | `/api/v1/system/dict/data/list` | 字典数据 - 分页查询列表 | Bearer Token |

#### 3.7.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/dict/data/add`
- **功能说明**：字典数据 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/dict/data/delete`
- **功能说明**：字典数据 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.8 模块：定时任务 (共 6 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/job/add` | 定时任务 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/job/delete` | 定时任务 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/job/edit` | 定时任务 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/job/get` | 定时任务 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/system/job/list` | 定时任务 - 分页查询列表 | Bearer Token |
| `PUT` | `/api/v1/system/job/status` | 定时任务 - status操作 | Bearer Token |

#### 3.8.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/job/add`
- **功能说明**：定时任务 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/job/delete`
- **功能说明**：定时任务 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.9 模块：菜单与规则 (共 6 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/menu/add` | 菜单与规则 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/menu/delete` | 菜单与规则 - 删除记录 | Bearer Token |
| `GET` | `/api/v1/system/menu/get` | 菜单与规则 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/system/menu/getParams` | 菜单与规则 - 获取配置关联参数 | Bearer Token |
| `GET` | `/api/v1/system/menu/list` | 菜单与规则 - 分页查询列表 | Bearer Token |
| `PUT` | `/api/v1/system/menu/update` | 菜单与规则 - update操作 | Bearer Token |

#### 3.9.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/menu/add`
- **功能说明**：菜单与规则 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | `header` | `string` | 否 | Bearer {{token}} |
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/menu/delete`
- **功能说明**：菜单与规则 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | `header` | `string` | 否 | Bearer {{token}} |
  | `Ids` | `query` | `array` | 是 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.10 模块：角色权限 (共 6 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/role/add` | 角色权限 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/role/delete` | 角色权限 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/role/edit` | 角色权限 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/role/get` | 角色权限 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/system/role/getParams` | 角色权限 - 获取配置关联参数 | Bearer Token |
| `GET` | `/api/v1/system/role/list` | 角色权限 - 分页查询列表 | Bearer Token |

#### 3.10.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/role/add`
- **功能说明**：角色权限 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/role/delete`
- **功能说明**：角色权限 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 是 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.11 模块：设备品类 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceCategoty/add` | 设备品类 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceCategoty/delete` | 设备品类 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceCategoty/edit` | 设备品类 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceCategoty/get` | 设备品类 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceCategoty/list` | 设备品类 - 分页查询列表 | Bearer Token |

#### 3.11.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceCategoty/add`
- **功能说明**：设备品类 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/device/deviceCategoty/delete`
- **功能说明**：设备品类 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.12 模块：设备分组 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceGroup/add` | 设备分组 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceGroup/delete` | 设备分组 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceGroup/edit` | 设备分组 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceGroup/get` | 设备分组 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceGroup/list` | 设备分组 - 分页查询列表 | Bearer Token |

#### 3.12.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceGroup/add`
- **功能说明**：设备分组 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/device/deviceGroup/delete`
- **功能说明**：设备分组 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.13 模块：设备管理 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceInfo/add` | 设备管理 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceInfo/delete` | 设备管理 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceInfo/edit` | 设备管理 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceInfo/get` | 设备管理 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceInfo/list` | 设备管理 - 分页查询列表 | Bearer Token |

#### 3.13.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceInfo/add`
- **功能说明**：设备管理 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/device/deviceInfo/delete`
- **功能说明**：设备管理 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.14 模块：设备类型 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceKind/add` | 设备类型 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/device/deviceKind/delete` | 设备类型 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/device/deviceKind/edit` | 设备类型 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/device/deviceKind/get` | 设备类型 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/device/deviceKind/list` | 设备类型 - 分页查询列表 | Bearer Token |

#### 3.14.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceKind/add`
- **功能说明**：设备类型 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/device/deviceKind/delete`
- **功能说明**：设备类型 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.15 模块：链路管理 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/link/linkInfo/add` | 链路管理 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/link/linkInfo/delete` | 链路管理 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/link/linkInfo/edit` | 链路管理 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/link/linkInfo/get` | 链路管理 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/link/linkInfo/list` | 链路管理 - 分页查询列表 | Bearer Token |

#### 3.15.1 重点接口定义与示例

##### 【POST】 `/api/v1/link/linkInfo/add`
- **功能说明**：链路管理 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/link/linkInfo/delete`
- **功能说明**：链路管理 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.16 模块：网络链路 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/link/linkNet/add` | 网络链路 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/link/linkNet/delete` | 网络链路 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/link/linkNet/edit` | 网络链路 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/link/linkNet/get` | 网络链路 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/link/linkNet/list` | 网络链路 - 分页查询列表 | Bearer Token |

#### 3.16.1 重点接口定义与示例

##### 【POST】 `/api/v1/link/linkNet/add`
- **功能说明**：网络链路 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/link/linkNet/delete`
- **功能说明**：网络链路 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.17 模块：串口链路 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/link/linkSerial/add` | 串口链路 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/link/linkSerial/delete` | 串口链路 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/link/linkSerial/edit` | 串口链路 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/link/linkSerial/get` | 串口链路 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/link/linkSerial/list` | 串口链路 - 分页查询列表 | Bearer Token |

#### 3.17.1 重点接口定义与示例

##### 【POST】 `/api/v1/link/linkSerial/add`
- **功能说明**：串口链路 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/link/linkSerial/delete`
- **功能说明**：串口链路 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.18 模块：消息日志 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/mqtt/mqttMsgRecord/add` | 消息日志 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/mqtt/mqttMsgRecord/delete` | 消息日志 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/mqtt/mqttMsgRecord/edit` | 消息日志 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttMsgRecord/get` | 消息日志 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttMsgRecord/list` | 消息日志 - 分页查询列表 | Bearer Token |

#### 3.18.1 重点接口定义与示例

##### 【POST】 `/api/v1/mqtt/mqttMsgRecord/add`
- **功能说明**：消息日志 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/mqtt/mqttMsgRecord/delete`
- **功能说明**：消息日志 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.19 模块：MQTT主题 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/mqtt/mqttTopic/add` | MQTT主题 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/mqtt/mqttTopic/delete` | MQTT主题 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/mqtt/mqttTopic/edit` | MQTT主题 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttTopic/get` | MQTT主题 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttTopic/list` | MQTT主题 - 分页查询列表 | Bearer Token |

#### 3.19.1 重点接口定义与示例

##### 【POST】 `/api/v1/mqtt/mqttTopic/add`
- **功能说明**：MQTT主题 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/mqtt/mqttTopic/delete`
- **功能说明**：MQTT主题 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.20 模块：主题流转记录 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/mqtt/mqttTopicRecord/add` | 主题流转记录 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/mqtt/mqttTopicRecord/delete` | 主题流转记录 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/mqtt/mqttTopicRecord/edit` | 主题流转记录 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttTopicRecord/get` | 主题流转记录 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/mqtt/mqttTopicRecord/list` | 主题流转记录 - 分页查询列表 | Bearer Token |

#### 3.20.1 重点接口定义与示例

##### 【POST】 `/api/v1/mqtt/mqttTopicRecord/add`
- **功能说明**：主题流转记录 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/mqtt/mqttTopicRecord/delete`
- **功能说明**：主题流转记录 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.21 模块：系统配置 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/config/add` | 系统配置 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/config/delete` | 系统配置 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/config/edit` | 系统配置 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/config/get` | 系统配置 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/system/config/list` | 系统配置 - 分页查询列表 | Bearer Token |

#### 3.21.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/config/add`
- **功能说明**：系统配置 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/config/delete`
- **功能说明**：系统配置 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.22 模块：部门管理 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/dept/add` | 部门管理 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/dept/delete` | 部门管理 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/dept/edit` | 部门管理 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/dept/list` | 部门管理 - 分页查询列表 | Bearer Token |
| `GET` | `/api/v1/system/dept/treeSelect` | 部门管理 - 获取下拉树形结构 | Bearer Token |

#### 3.22.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/dept/add`
- **功能说明**：部门管理 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/dept/delete`
- **功能说明**：部门管理 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Id` | `query` | `integer` | 是 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.23 模块：字典类型 (共 5 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/dict/type/add` | 字典类型 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/dict/type/delete` | 字典类型 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/dict/type/edit` | 字典类型 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/dict/type/get` | 字典类型 - 根据ID获取详情 | Bearer Token |
| `GET` | `/api/v1/system/dict/type/list` | 字典类型 - 分页查询列表 | Bearer Token |

#### 3.23.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/dict/type/add`
- **功能说明**：字典类型 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/dict/type/delete`
- **功能说明**：字典类型 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `DictIds` | `query` | `array` | 是 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.24 模块：岗位管理 (共 4 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/post/add` | 岗位管理 - 创建新增 | Bearer Token |
| `DELETE` | `/api/v1/system/post/delete` | 岗位管理 - 删除记录 | Bearer Token |
| `PUT` | `/api/v1/system/post/edit` | 岗位管理 - 更新编辑 | Bearer Token |
| `GET` | `/api/v1/system/post/list` | 岗位管理 - 分页查询列表 | Bearer Token |

#### 3.24.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/post/add`
- **功能说明**：岗位管理 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【DELETE】 `/api/v1/system/post/delete`
- **功能说明**：岗位管理 - 删除记录
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.25 模块：系统初始化 (共 3 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/system/dbInit/createDb` | 系统初始化 - 执行数据库初始化安装 | 公开接口 |
| `GET` | `/api/v1/system/dbInit/getEnvInfo` | 系统初始化 - 获取安装环境依赖信息 | 公开接口 |
| `GET` | `/api/v1/system/dbInit/isInit` | 系统初始化 - 检测系统是否已初始化 | 公开接口 |

#### 3.25.1 重点接口定义与示例

##### 【POST】 `/api/v1/system/dbInit/createDb`
- **功能说明**：系统初始化 - 执行数据库初始化安装
- **请求头要求**：无（免鉴权）
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "id": 1
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【GET】 `/api/v1/system/dbInit/getEnvInfo`
- **功能说明**：系统初始化 - 获取安装环境依赖信息
- **请求头要求**：无（免鉴权）
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.26 模块：登录日志 (共 3 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `DELETE` | `/api/v1/system/loginLog/clear` | 登录日志 - 一键清空全部日志 | 公开接口 |
| `DELETE` | `/api/v1/system/loginLog/delete` | 登录日志 - 删除记录 | 公开接口 |
| `GET` | `/api/v1/system/loginLog/list` | 登录日志 - 分页查询列表 | 公开接口 |

#### 3.26.1 重点接口定义与示例

##### 【DELETE】 `/api/v1/system/loginLog/clear`
- **功能说明**：登录日志 - 一键清空全部日志
- **请求头要求**：无（免鉴权）
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "登录成功",
    "data": {
      "token": "eyJhbGciOiJIUzI1NiIsIn...",
      "expire": 864000
    }
  }
  ```

##### 【DELETE】 `/api/v1/system/loginLog/delete`
- **功能说明**：登录日志 - 删除记录
- **请求头要求**：无（免鉴权）
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `Ids` | `query` | `array` | 是 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "登录成功",
    "data": {
      "token": "eyJhbGciOiJIUzI1NiIsIn...",
      "expire": 864000
    }
  }
  ```

### 3.27 模块：遥测数据 (共 2 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/device/deviceData/add` | 遥测数据 - 创建新增 | Bearer Token |
| `GET` | `/api/v1/device/deviceData/get` | 遥测数据 - 根据ID获取详情 | Bearer Token |

#### 3.27.1 重点接口定义与示例

##### 【POST】 `/api/v1/device/deviceData/add`
- **功能说明**：遥测数据 - 创建新增
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "name": "示例名称",
    "status": "1",
    "remark": "企业测试数据"
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

##### 【GET】 `/api/v1/device/deviceData/get`
- **功能说明**：遥测数据 - 根据ID获取详情
- **请求头要求**：`Authorization: Bearer <token>`
- **请求参数 (Parameters)**：
  | 参数名 | 位置 | 类型 | 必填 | 说明 |
  | :--- | :--- | :--- | :--- | :--- |
  | `DeviceId` | `query` | `integer` | 否 | - |
  | `DeviceSn` | `query` | `string` | 否 | - |
  | `DevicePwd` | `query` | `string` | 否 | - |
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.28 模块：功能演示 (共 1 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/demo/demo` | 功能演示 - Demo演示接口 | Bearer Token |

#### 3.28.1 重点接口定义与示例

##### 【POST】 `/api/v1/demo/demo`
- **功能说明**：功能演示 - Demo演示接口
- **请求头要求**：`Authorization: Bearer <token>`
- **请求 Body 示例 (JSON)**：
  ```json
  {
    "id": 1
  }
  ```
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.29 模块：公共服务 (共 1 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/pub/captcha/get` | 公共服务 - 根据ID获取详情 | 公开接口 |

#### 3.29.1 重点接口定义与示例

##### 【GET】 `/api/v1/pub/captcha/get`
- **功能说明**：公共服务 - 根据ID获取详情
- **请求头要求**：无（免鉴权）
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```

### 3.30 模块：服务监控 (共 1 个接口)

| 请求方法 | 请求路径 | 接口名称/摘要 | 鉴权要求 |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/system/monitor/server` | 服务监控 - 获取服务器硬件指标信息 | Bearer Token |

#### 3.30.1 重点接口定义与示例

##### 【GET】 `/api/v1/system/monitor/server`
- **功能说明**：服务监控 - 获取服务器硬件指标信息
- **请求头要求**：`Authorization: Bearer <token>`
- **成功响应示例 (HTTP 200)**：
  ```json
  {
    "code": 0,
    "message": "操作成功",
    "data": true
  }
  ```
