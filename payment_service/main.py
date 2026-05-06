from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis
import json
import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv() 

app = FastAPI(title="Payment Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Aiven Valkey Connection (Redis compatible)
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise Exception("REDIS_URL environment variable is required")
r = redis.from_url(REDIS_URL + "/0", decode_responses=True)  # Add /0

class PaymentRequest(BaseModel):
    order_id: int
    amount: float
    payment_method: str

@app.get("/health")
def health():
    return {"service": "Payment Service", "status": "running"}

@app.post("/pay")
def pay(req: PaymentRequest):
    payment_id = r.incr("payments:next_id")

    if req.amount <= 0:
        status = "failed"
        message = "Payment failed"
        delivery_days = None
    else:
        status = "success"
        message = f"Payment successful via {req.payment_method}"
        delivery_days = 3

    record = {
        "id": payment_id,
        "order_id": req.order_id,
        "amount": req.amount,
        "payment_method": req.payment_method,
        "status": status,
        "message": message,
        "delivery_days": delivery_days,
        "timestamp": datetime.utcnow().isoformat()
    }

    r.set(f"payment:{payment_id}", json.dumps(record))
    return record

@app.get("/payments")
def get_payments():
    payments = []
    for key in r.scan_iter("payment:*"):
        value = r.get(key)
        if value:
            payments.append(json.loads(value))
    payments.sort(key=lambda x: x["id"])
    return payments
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# import redis
# import json
# import os
# from datetime import datetime

# app = FastAPI(title="Payment Service")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
# REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)

# class PaymentRequest(BaseModel):
#     order_id: int
#     amount: float
#     payment_method: str

# @app.get("/health")
# def health():
#     return {"service": "Payment Service", "status": "running"}

# @app.post("/pay")
# def pay(req: PaymentRequest):
#     payment_id = r.incr("payments:next_id")

#     if req.amount <= 0:
#         status = "failed"
#         message = "Payment failed"
#         delivery_days = None
#     else:
#         status = "success"
#         message = f"Payment successful via {req.payment_method}"
#         delivery_days = 3

#     record = {
#         "id": payment_id,
#         "order_id": req.order_id,
#         "amount": req.amount,
#         "payment_method": req.payment_method,
#         "status": status,
#         "message": message,
#         "delivery_days": delivery_days,
#         "timestamp": datetime.utcnow().isoformat()
#     }

#     r.set(f"payment:{payment_id}", json.dumps(record))
#     return record

# @app.get("/payments")
# def get_payments():
#     payments = []
#     for key in r.scan_iter("payment:*"):
#         value = r.get(key)
#         if value:
#             payments.append(json.loads(value))
#     payments.sort(key=lambda x: x["id"])
#     return payments
