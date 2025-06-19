import datetime
import jwt
from contextlib import asynccontextmanager
from typing import Optional

import databases
import sqlalchemy
from fastapi import FastAPI, HTTPException, status, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    Integer, String, Text, Boolean, DateTime
)


# ===================== ⚙️ CONFIG ===================== #

DATABASE_URL = "postgresql://postgres:lumino1337@localhost:5432/postgres"
db = databases.Database(DATABASE_URL)
metadata = MetaData()
JWT_SECRET = "SOFI@LUMINO1337"

# ===================== 🗂️ MODELS ===================== #

articles = Table(
    "articles",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("title", String(255), nullable=False),
    Column("slug", String(255), unique=True, nullable=False),
    Column("content", Text, nullable=False),
    Column("category", String(50), nullable=False),
    Column("created_at", DateTime, default=datetime.datetime.utcnow),
    Column("updated_at", DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow),
    Column("is_featured", Boolean, default=False),
    Column("status", String, default="draft"),
    Column("thumbnail_url", String(255), nullable=True),
)
    

class ArticleSchema(BaseModel):
    title: str
    slug: Optional[str] = None
    content: str
    category: str
    is_featured: bool = False
    status: str = "draft"
    thumbnail_url: Optional[str] = None


# ===================== 🌱 APP INITIALIZATION ===================== #

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    engine = create_engine(DATABASE_URL)
    metadata.create_all(engine)
    yield
    await db.disconnect()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ Allow "*" only for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== 🔐 AUTHENTICATION ===================== #


def create_jwt_token(username: str):
    payload = {
        "sub": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
        "role": "admin"
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return token


def decode_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    



def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = authorization.split(" ")[1]
    payload = decode_jwt_token(token)
    return payload


def is_admin(token: dict = Depends(get_current_user)):
    if token.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return True




# ===================== 📌 PUBLIC ROUTES ===================== #

@app.get("/api/articles/featured", summary="Get featured article")
async def get_featured_article():
    query = articles.select().where(articles.c.is_featured == True)
    result = await db.fetch_one(query)
    if not result:
        return {"message": "No featured articles found"}
    return dict(result)


@app.get("/api/articles/latest", summary="Get latest articles")
async def get_latest_articles(limit: int = 10):
    query = articles.select().order_by(articles.c.created_at.desc()).limit(limit)
    results = await db.fetch_all(query)
    return [dict(r) for r in results]


@app.get("/api/articles", summary="Get articles with optional filters")
async def get_articles(category: Optional[str] = None, status: Optional[str] = None, limit: int = 20, offset: int = 0):
    query = articles.select()
    if category:
        query = query.where(articles.c.category == category)
    if status:
        query = query.where(articles.c.status == status)
    query = query.order_by(articles.c.created_at.desc()).limit(limit).offset(offset)
    results = await db.fetch_all(query)
    return [dict(r) for r in results]


@app.get("/api/articles/{slug}", summary="Get article by slug")
async def get_article_by_slug(slug: str):
    query = articles.select().where(articles.c.slug == slug)
    result = await db.fetch_one(query)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return dict(result)



# ===================== 📌 ADMIN ROUTES ===================== #


@app.get("/api/admin/token", summary="Get admin token")
async def get_admin_token(username : str):
    if username != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid username")
    token = create_jwt_token(username)
    return {"token": token}

@app.post("/api/admin/articles", status_code=status.HTTP_201_CREATED, summary="Create new article", dependencies=[Depends(is_admin)])
async def create_article(article: ArticleSchema):
    now = datetime.datetime.utcnow()

    if article.is_featured:
        unfeature_query = articles.update().where(articles.c.is_featured == True).values(is_featured=False)
        await db.execute(unfeature_query)

    insert_query = articles.insert().values(
        title=article.title,
        slug=article.slug or article.title.replace(" ", "-").lower(),
        content=article.content,
        category=article.category,
        is_featured=article.is_featured,
        status=article.status,
        thumbnail_url=article.thumbnail_url,
        created_at=now,
        updated_at=now,
    )
    article_id = await db.execute(insert_query)

    response = article.dict()
    response.update({
        "id": article_id,
        "created_at": now,
        "updated_at": now,
    })
    return {"message": "Article created", "article": response}


@app.put("/api/admin/articles/{article_id}", summary="Update existing article", dependencies=[Depends(is_admin)])
async def update_article(article_id: int, article: ArticleSchema):
    now = datetime.datetime.utcnow()

    select_query = articles.select().where(articles.c.id == article_id)
    existing_article = await db.fetch_one(select_query)
    if not existing_article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    if article.is_featured:
        unfeature_query = articles.update().where(articles.c.is_featured == True).values(is_featured=False)
        await db.execute(unfeature_query)

    update_query = articles.update().where(articles.c.id == article_id).values(
        title=article.title,
        slug=article.slug or article.title.replace(" ", "-").lower(),
        content=article.content,
        category=article.category,
        is_featured=article.is_featured,
        status=article.status,
        thumbnail_url=article.thumbnail_url,
        updated_at=now,
    )
    await db.execute(update_query)

    return {"message": "Article updated", "article_id": article_id}


@app.delete("/api/admin/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete article", dependencies=[Depends(is_admin)])
async def delete_article(article_id: int):
    select_query = articles.select().where(articles.c.id == article_id)
    existing_article = await db.fetch_one(select_query)
    if not existing_article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    delete_query = articles.delete().where(articles.c.id == article_id)
    await db.execute(delete_query)
    return {"message": "Article deleted", "article_id": article_id}








# ===================== ▶️ MAIN ===================== #



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apis:app", port=8080, reload=True)
