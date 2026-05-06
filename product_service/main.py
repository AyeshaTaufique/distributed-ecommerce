from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis
import json
import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv() 

app = FastAPI(title="Product Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis Cloud Connection
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

if not REDIS_HOST or not REDIS_PASSWORD:
    raise Exception("REDIS_HOST and REDIS_PASSWORD environment variables are required")

r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    db=0,
    decode_responses=True
)

class ProductCreate(BaseModel):
    name: str
    price: float
    stock: int

class StockUpdate(BaseModel):
    quantity: int

@app.get("/health")
def health():
    return {"service": "Product Service", "status": "running"}

@app.post("/products")
def add_product(product: ProductCreate):
    if product.stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")
    
    normalized_name = product.name.lower().strip()
    existing_product = None
    existing_product_id = None
    
    for key in r.scan_iter("product:*"):
        value = r.get(key)
        if value:
            prod = json.loads(value)
            if prod["name"].lower().strip() == normalized_name:
                existing_product = prod
                existing_product_id = prod["id"]
                break
    
    if existing_product:
        updated_stock = existing_product["stock"] + product.stock
        updated_price = product.price if product.price > 0 else existing_product["price"]
        
        existing_product["stock"] = updated_stock
        existing_product["price"] = updated_price
        existing_product["updated_at"] = datetime.utcnow().isoformat()
        
        r.set(f"product:{existing_product_id}", json.dumps(existing_product))
        
        return {
            "message": f"Product '{product.name}' already exists. Stock updated from {existing_product['stock'] - product.stock} to {updated_stock} units.",
            "product": existing_product,
            "updated": True
        }
    else:
        product_id = r.incr("products:next_id")
        record = {
            "id": product_id,
            "name": product.name,
            "price": product.price,
            "stock": product.stock,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        r.set(f"product:{product_id}", json.dumps(record))
        return {
            "message": f"Product '{product.name}' added successfully",
            "product": record,
            "updated": False
        }

@app.get("/products")
def get_products():
    products = []
    for key in r.scan_iter("product:*"):
        value = r.get(key)
        if value:
            products.append(json.loads(value))
    products.sort(key=lambda x: x["id"])
    return products

@app.get("/products/{product_id}")
def get_product(product_id: int):
    value = r.get(f"product:{product_id}")
    if not value:
        raise HTTPException(status_code=404, detail="Product not found")
    return json.loads(value)

@app.patch("/products/{product_id}/reduce-stock")
def reduce_stock(product_id: int, payload: StockUpdate):
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    value = r.get(f"product:{product_id}")
    if not value:
        raise HTTPException(status_code=404, detail="Product not found")

    product = json.loads(value)

    if product["stock"] < payload.quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")

    product["stock"] -= payload.quantity
    product["updated_at"] = datetime.utcnow().isoformat()
    r.set(f"product:{product_id}", json.dumps(product))

    return {"message": "Stock reduced successfully", "product": product}
# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# import redis
# import json
# import os
# from datetime import datetime

# app = FastAPI(title="Product Service")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
# REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)

# class ProductCreate(BaseModel):
#     name: str
#     price: float
#     stock: int

# class StockUpdate(BaseModel):
#     quantity: int

# @app.get("/health")
# def health():
#     return {"service": "Product Service", "status": "running"}

# @app.post("/products")
# def add_product(product: ProductCreate):
#     if product.stock < 0:
#         raise HTTPException(status_code=400, detail="Stock cannot be negative")
    
#     # Normalize product name for case-insensitive comparison
#     normalized_name = product.name.lower().strip()
    
#     # Check if product already exists
#     existing_product = None
#     existing_product_id = None
    
#     for key in r.scan_iter("product:*"):
#         value = r.get(key)
#         if value:
#             prod = json.loads(value)
#             if prod["name"].lower().strip() == normalized_name:
#                 existing_product = prod
#                 existing_product_id = prod["id"]
#                 break
    
#     if existing_product:
#         # Update existing product - add stock and update price if changed
#         updated_stock = existing_product["stock"] + product.stock
#         updated_price = product.price if product.price > 0 else existing_product["price"]
        
#         existing_product["stock"] = updated_stock
#         existing_product["price"] = updated_price
#         existing_product["updated_at"] = datetime.utcnow().isoformat()
        
#         r.set(f"product:{existing_product_id}", json.dumps(existing_product))
        
#         return {
#             "message": f"Product '{product.name}' already exists. Stock updated from {existing_product['stock'] - product.stock} to {updated_stock} units.",
#             "product": existing_product,
#             "updated": True
#         }
#     else:
#         # Create new product
#         product_id = r.incr("products:next_id")
#         record = {
#             "id": product_id,
#             "name": product.name,
#             "price": product.price,
#             "stock": product.stock,
#             "created_at": datetime.utcnow().isoformat(),
#             "updated_at": datetime.utcnow().isoformat()
#         }
#         r.set(f"product:{product_id}", json.dumps(record))
#         return {
#             "message": f"Product '{product.name}' added successfully",
#             "product": record,
#             "updated": False
#         }

# @app.get("/products")
# def get_products():
#     products = []
#     for key in r.scan_iter("product:*"):
#         value = r.get(key)
#         if value:
#             products.append(json.loads(value))
#     products.sort(key=lambda x: x["id"])
#     return products

# @app.get("/products/{product_id}")
# def get_product(product_id: int):
#     value = r.get(f"product:{product_id}")
#     if not value:
#         raise HTTPException(status_code=404, detail="Product not found")
#     return json.loads(value)

# @app.patch("/products/{product_id}/reduce-stock")
# def reduce_stock(product_id: int, payload: StockUpdate):
#     if payload.quantity <= 0:
#         raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

#     value = r.get(f"product:{product_id}")
#     if not value:
#         raise HTTPException(status_code=404, detail="Product not found")

#     product = json.loads(value)

#     if product["stock"] < payload.quantity:
#         raise HTTPException(status_code=400, detail="Not enough stock")

#     product["stock"] -= payload.quantity
#     product["updated_at"] = datetime.utcnow().isoformat()
#     r.set(f"product:{product_id}", json.dumps(product))

#     return {"message": "Stock reduced successfully", "product": product}