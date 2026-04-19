import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.analyze import router as analyze_router
from app.api.routes.ask import router as ask_router
from app.api.routes.equation_image import router as equation_image_router
from app.api.routes.upload import router as upload_router


def _configure_app_logging() -> None:
    """
    让 app.* logger 在 uvicorn 终端里输出 INFO 级别日志，
    方便观察上传解析缓存的 HIT / MISS / INVALID_FALLBACK / SAVE。
    """
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root_logger.setLevel(logging.INFO)

    logging.getLogger("app").setLevel(logging.INFO)


_configure_app_logging()

app = FastAPI(title="Paper Reading Assistant API")

# 先放开本地前端开发地址，方便 React 页面直接调用接口。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(analyze_router)
app.include_router(ask_router)
app.include_router(equation_image_router)


@app.get("/")
def read_root() -> dict[str, str]:
    # 用一个简单接口确认后端服务是否正常启动。
    return {"message": "Paper Reading Assistant backend is running."}
