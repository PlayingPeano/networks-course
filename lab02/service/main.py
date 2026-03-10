from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
EXT_BY_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}

products: dict[int, dict] = {}
next_id = 1


class ProductCreate(BaseModel):
    name: str
    description: str


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class Product(BaseModel):
    id: int
    name: str
    description: str
    icon: str = ""


# POST /product
@app.post("/product", response_model=Product)
def create_product(body: ProductCreate):
    global next_id
    p = {"id": next_id, "name": body.name, "description": body.description, "icon": ""}
    products[next_id] = p
    next_id += 1
    return p


# GET /products
@app.get("/products", response_model=list[Product])
def list_products():
    return list(products.values())


# GET /product/{product_id}
@app.get("/product/{product_id}", response_model=Product)
def get_product(product_id: int):
    if product_id not in products:
        raise HTTPException(status_code=404, detail="Product not found")
    return products[product_id]


# PUT /product/{product_id}
@app.put("/product/{product_id}", response_model=Product)
def update_product(product_id: int, body: ProductUpdate):
    if product_id not in products:
        raise HTTPException(status_code=404, detail="Product not found")
    p = products[product_id]
    if body.name is not None:
        p["name"] = body.name
    if body.description is not None:
        p["description"] = body.description
    return p


# DELETE /product/{product_id}
@app.delete("/product/{product_id}", response_model=Product)
def delete_product(product_id: int):
    if product_id not in products:
        raise HTTPException(status_code=404, detail="Product not found")
    p = products.pop(product_id)
    if p.get("icon"):
        icon_path = UPLOAD_DIR / p["icon"]
        if icon_path.exists():
            icon_path.unlink()
    return p


# POST /product/{product_id}/image
@app.post("/product/{product_id}/image")
async def upload_product_image(product_id: int, file: UploadFile = File(...)):
    if product_id not in products:
        raise HTTPException(status_code=404, detail="Product not found")
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="File must be an image (png, jpeg, gif, webp)")
    content = await file.read()
    ext = EXT_BY_MIME.get(file.content_type, ".png")
    filename = f"{product_id}{ext}"
    path = UPLOAD_DIR / filename
    path.write_bytes(content)
    products[product_id]["icon"] = filename
    return {"status": "ok", "icon": filename}


# GET /product/{product_id}/image
@app.get("/product/{product_id}/image")
def get_product_image(product_id: int):
    if product_id not in products:
        raise HTTPException(status_code=404, detail="Product not found")
    icon_name = products[product_id].get("icon")
    if not icon_name:
        raise HTTPException(status_code=404, detail="Image not found")
    path = UPLOAD_DIR / icon_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    media_type = "image/png"
    if icon_name.endswith(".jpg") or icon_name.endswith(".jpeg"):
        media_type = "image/jpeg"
    elif icon_name.endswith(".gif"):
        media_type = "image/gif"
    elif icon_name.endswith(".webp"):
        media_type = "image/webp"
    return FileResponse(path, media_type=media_type)