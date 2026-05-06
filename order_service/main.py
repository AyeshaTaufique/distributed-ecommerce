from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import redis
import json
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
load_dotenv() 

app = FastAPI(title="Order Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Railway Redis Connection
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise Exception("REDIS_URL environment variable is required")
r = redis.from_url(REDIS_URL + "/0", decode_responses=True)

# Service URLs (from environment variables)
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:5001")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:5002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:5004")

class OrderItem(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    price: float

class OrderCreate(BaseModel):
    user_id: int
    items: List[OrderItem]
    payment_method: str = "Visa"
    total_amount: float

@app.get("/health")
def health():
    return {"service": "Order Service", "status": "running"}

@app.post("/orders")
def create_order(order: OrderCreate):
    if not order.items:
        raise HTTPException(status_code=400, detail="📦 Order must have at least one item")

    # 1. Check User Service
    try:
        user_res = requests.get(f"{USER_SERVICE_URL}/users/{order.user_id}", timeout=5)
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="👤 User service is currently unavailable. Please try again later."
        )
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=504,
            detail="⏱️ User service is taking too long. Please try again."
        )
    except requests.exceptions.RequestException:
        raise HTTPException(
            status_code=502,
            detail="👤 User service error. Please check if the service is running."
        )

    if user_res.status_code != 200:
        raise HTTPException(status_code=404, detail="👤 User not found. Please login again.")
    user = user_res.json()

    # 2. Validate stock for all items
    for item in order.items:
        try:
            product_res = requests.get(f"{PRODUCT_SERVICE_URL}/products/{item.product_id}", timeout=5)
        except requests.exceptions.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail=f"📦 Product service is unavailable. Cannot check stock for {item.product_name}."
            )
        except requests.exceptions.Timeout:
            raise HTTPException(
                status_code=504,
                detail=f"⏱️ Product service timeout. Please try again."
            )
        except requests.exceptions.RequestException:
            raise HTTPException(
                status_code=502,
                detail=f"📦 Product service error for {item.product_name}."
            )

        if product_res.status_code != 200:
            raise HTTPException(status_code=404, detail=f"📦 Product '{item.product_name}' not found")

        product = product_res.json()
        if product["stock"] < item.quantity:
            raise HTTPException(
                status_code=400, 
                detail=f"⚠️ Not enough stock for {item.product_name}. Only {product['stock']} left in stock."
            )

    # 3. Process payment
    order_id = r.incr("orders:next_id")

    try:
        payment_res = requests.post(
            f"{PAYMENT_SERVICE_URL}/pay",
            json={
                "order_id": order_id,
                "amount": order.total_amount,
                "payment_method": order.payment_method
            },
            timeout=5
        )
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="💳 Payment service is currently unavailable. Please try again later."
        )
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=504,
            detail="⏱️ Payment service is taking too long. Please try again."
        )
    except requests.exceptions.RequestException:
        raise HTTPException(
            status_code=502,
            detail="💳 Payment service error. Please check if payment service is running."
        )

    if payment_res.status_code != 200:
        raise HTTPException(
            status_code=502, 
            detail="💳 Payment service returned an error. Please try again."
        )

    payment = payment_res.json()

    if payment["status"] != "success":
        raise HTTPException(
            status_code=402, 
            detail="💳 Payment failed. Please check your payment method and try again."
        )

    # 4. Reduce stock for all items
    for item in order.items:
        try:
            reduce_res = requests.patch(
                f"{PRODUCT_SERVICE_URL}/products/{item.product_id}/reduce-stock",
                json={"quantity": item.quantity},
                timeout=5
            )
        except requests.exceptions.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail=f"📦 Cannot update stock for {item.product_name}. Product service is down."
            )
        except requests.exceptions.RequestException:
            raise HTTPException(
                status_code=502,
                detail=f"📦 Stock update error for {item.product_name}. Please contact support."
            )

        if reduce_res.status_code != 200:
            raise HTTPException(
                status_code=400, 
                detail=f"⚠️ Could not reduce stock for {item.product_name}. Please try again."
            )

    # 5. Save order
    record = {
        "id": order_id,
        "user_id": order.user_id,
        "user_name": user["username"],
        "user_email": user["email"],
        "items": [item.dict() for item in order.items],
        "total_amount": order.total_amount,
        "payment_method": order.payment_method,
        "status": "completed",
        "delivery_days": payment.get("delivery_days", 3),
        "payment": payment,
        "created_at": datetime.utcnow().isoformat()
    }

    r.set(f"order:{order_id}", json.dumps(record))

    item_list = ", ".join([f"{item.product_name} (x{item.quantity})" for item in order.items])

    return {
        "message": f"✅ Order placed successfully! Your payment via {order.payment_method} is confirmed. Items: {item_list}. Delivery in {record['delivery_days']} days.",
        "order": record
    }

@app.get("/orders")
def get_orders():
    orders = []
    for key in r.scan_iter("order:*"):
        value = r.get(key)
        if value:
            orders.append(json.loads(value))
    orders.sort(key=lambda x: x["id"], reverse=True)
    return orders

@app.get("/orders/{order_id}")
def get_order(order_id: int):
    value = r.get(f"order:{order_id}")
    if not value:
        raise HTTPException(status_code=404, detail="Order not found")
    return json.loads(value)
# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from typing import List
# import redis
# import json
# import os
# import requests
# from datetime import datetime

# app = FastAPI(title="Order Service")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
# REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=3, decode_responses=True)

# USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:5001")
# PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:5002")
# PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:5004")

# class OrderItem(BaseModel):
#     product_id: int
#     product_name: str
#     quantity: int
#     price: float

# class OrderCreate(BaseModel):
#     user_id: int
#     items: List[OrderItem]
#     payment_method: str = "Visa"
#     total_amount: float

# @app.get("/health")
# def health():
#     return {"service": "Order Service", "status": "running"}

# @app.post("/orders")
# def create_order(order: OrderCreate):
#     if not order.items:
#         raise HTTPException(status_code=400, detail="📦 Order must have at least one item")

#     # 1. Check User Service
#     try:
#         user_res = requests.get(f"{USER_SERVICE_URL}/users/{order.user_id}", timeout=5)
#     except requests.exceptions.ConnectionError:
#         raise HTTPException(
#             status_code=503,
#             detail="👤 User service is currently unavailable. Please try again later."
#         )
#     except requests.exceptions.Timeout:
#         raise HTTPException(
#             status_code=504,
#             detail="⏱️ User service is taking too long. Please try again."
#         )
#     except requests.exceptions.RequestException as e:
#         raise HTTPException(
#             status_code=502,
#             detail="👤 User service error. Please check if the service is running."
#         )

#     if user_res.status_code != 200:
#         raise HTTPException(status_code=404, detail="👤 User not found. Please login again.")
#     user = user_res.json()

#     # 2. Validate stock for all items
#     products_data = []
#     for item in order.items:
#         try:
#             product_res = requests.get(f"{PRODUCT_SERVICE_URL}/products/{item.product_id}", timeout=5)
#         except requests.exceptions.ConnectionError:
#             raise HTTPException(
#                 status_code=503,
#                 detail=f"📦 Product service is unavailable. Cannot check stock for {item.product_name}."
#             )
#         except requests.exceptions.Timeout:
#             raise HTTPException(
#                 status_code=504,
#                 detail=f"⏱️ Product service timeout. Please try again."
#             )
#         except requests.exceptions.RequestException as e:
#             raise HTTPException(
#                 status_code=502,
#                 detail=f"📦 Product service error for {item.product_name}."
#             )

#         if product_res.status_code != 200:
#             raise HTTPException(status_code=404, detail=f"📦 Product '{item.product_name}' not found")

#         product = product_res.json()
#         if product["stock"] < item.quantity:
#             raise HTTPException(
#                 status_code=400, 
#                 detail=f"⚠️ Not enough stock for {item.product_name}. Only {product['stock']} left in stock."
#             )
        
#         products_data.append(product)

#     # 3. Process payment
#     order_id = r.incr("orders:next_id")

#     try:
#         payment_res = requests.post(
#             f"{PAYMENT_SERVICE_URL}/pay",
#             json={
#                 "order_id": order_id,
#                 "amount": order.total_amount,
#                 "payment_method": order.payment_method
#             },
#             timeout=5
#         )
#     except requests.exceptions.ConnectionError:
#         raise HTTPException(
#             status_code=503,
#             detail="💳 Payment service is currently unavailable. Please try again later."
#         )
#     except requests.exceptions.Timeout:
#         raise HTTPException(
#             status_code=504,
#             detail="⏱️ Payment service is taking too long. Please try again."
#         )
#     except requests.exceptions.RequestException as e:
#         raise HTTPException(
#             status_code=502,
#             detail="💳 Payment service error. Please check if payment service is running."
#         )

#     if payment_res.status_code != 200:
#         raise HTTPException(
#             status_code=502, 
#             detail="💳 Payment service returned an error. Please try again."
#         )

#     payment = payment_res.json()

#     if payment["status"] != "success":
#         raise HTTPException(
#             status_code=402, 
#             detail="💳 Payment failed. Please check your payment method and try again."
#         )

#     # 4. Reduce stock for all items
#     for item in order.items:
#         try:
#             reduce_res = requests.patch(
#                 f"{PRODUCT_SERVICE_URL}/products/{item.product_id}/reduce-stock",
#                 json={"quantity": item.quantity},
#                 timeout=5
#             )
#         except requests.exceptions.ConnectionError:
#             raise HTTPException(
#                 status_code=503,
#                 detail=f"📦 Cannot update stock for {item.product_name}. Product service is down."
#             )
#         except requests.exceptions.RequestException as e:
#             raise HTTPException(
#                 status_code=502,
#                 detail=f"📦 Stock update error for {item.product_name}. Please contact support."
#             )

#         if reduce_res.status_code != 200:
#             raise HTTPException(
#                 status_code=400, 
#                 detail=f"⚠️ Could not reduce stock for {item.product_name}. Please try again."
#             )

#     # 5. Save order
#     record = {
#         "id": order_id,
#         "user_id": order.user_id,
#         "user_name": user["username"],
#         "user_email": user["email"],
#         "items": [item.dict() for item in order.items],
#         "total_amount": order.total_amount,
#         "payment_method": order.payment_method,
#         "status": "completed",
#         "delivery_days": payment.get("delivery_days", 3),
#         "payment": payment,
#         "created_at": datetime.utcnow().isoformat()
#     }

#     r.set(f"order:{order_id}", json.dumps(record))

#     # Build item list string for message
#     item_list = ", ".join([f"{item.product_name} (x{item.quantity})" for item in order.items])

#     return {
#         "message": f"✅ Order placed successfully! Your payment via {order.payment_method} is confirmed. Items: {item_list}. Delivery in {record['delivery_days']} days.",
#         "order": record
#     }

# @app.get("/orders")
# def get_orders():
#     orders = []
#     for key in r.scan_iter("order:*"):
#         value = r.get(key)
#         if value:
#             orders.append(json.loads(value))
#     orders.sort(key=lambda x: x["id"], reverse=True)
#     return orders

# @app.get("/orders/{order_id}")
# def get_order(order_id: int):
#     value = r.get(f"order:{order_id}")
#     if not value:
#         raise HTTPException(status_code=404, detail="Order not found")
#     return json.loads(value)