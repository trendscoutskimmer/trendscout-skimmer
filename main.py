from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    String,
    BigInteger,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session

import os

# ---------- DB SETUP ----------

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./products.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String, index=True)
    price = Column(Float)
    commission = Column(Float)          # percentage
    agent_score = Column(Float, index=True)
    virality = Column(Float)
    views_7d = Column(BigInteger)
    rating = Column(Float)
    tiktok_url = Column(String)
    shop_url = Column(String)


Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- FASTAPI APP ----------

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("tos.html", {"request": request})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/products")
def list_products(limit: int = 100):
    """
    Returns latest products from DB, sorted by agent_score desc.
    """
    db = SessionLocal()
    try:
        items = (
            db.query(Product)
            .order_by(Product.agent_score.desc())
            .limit(limit)
            .all()
        )

        products_json = [
            {
                "name": p.name,
                "category": p.category,
                "price": p.price,
                "commission": p.commission,
                "agentScore": p.agent_score,
                "virality": p.virality,
                "views7d": p.views_7d,
                "rating": p.rating,
                "tiktokUrl": p.tiktok_url,
                "shopUrl": p.shop_url,
            }
            for p in items
        ]
        return {"products": products_json}

    finally:
        db.close()

