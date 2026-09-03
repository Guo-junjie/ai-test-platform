# 电商订单中心（order-service）

供 AI 自动化测试平台全流程验证的被测示例服务。

## 接口一览

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | /health | 健康检查 | 否 |
| POST | /api/v1/auth/register | 注册（密码 ≥6 位，重名 409） | 否 |
| POST | /api/v1/auth/login | 登录（返回 JWT） | 否 |
| GET | /api/v1/products | 商品列表 | 否 |
| GET | /api/v1/products/{id或sku} | 商品详情 | 否 |
| POST | /api/v1/products | 上架商品 | 是 |
| POST | /api/v1/orders | 下单（扣库存、VIP 折扣） | 是 |
| GET | /api/v1/orders | 我的订单列表 | 是 |
| GET | /api/v1/orders/{id} | 订单详情 | 是 |
| POST | /api/v1/orders/{id}/cancel | 取消订单（回滚库存） | 是 |

## 业务规则

- 价格计算：VIP 8 折；满 100 减 10；两者可叠加；结果保留两位小数
- 库存：下单扣减，不足返回 409；取消订单回滚库存；重复取消返回 409
- 认证：`Authorization: Bearer <token>`；过期/伪造返回 401

## 种子数据

- 用户：`admin / admin123`（VIP）
- 商品：SKU-001 机械键盘 ¥399×50、SKU-002 无线鼠标 ¥129×200、SKU-003 显示器支架 ¥89×0（无库存）

## 本地运行

```bash
pip install -r requirements.txt
python app.py   # 监听 :5000，SQLite 落在 /tmp/order_center.db
```
