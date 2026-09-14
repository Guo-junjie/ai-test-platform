"""仅用于第一阶段验证的最小 Python 被测服务。"""

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Coverage sample service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    if order_id == 1:
        return {"id": 1, "status": "paid"}
    if order_id <= 0:
        raise HTTPException(400, "invalid order id")
    raise HTTPException(404, "order not found")
