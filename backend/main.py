import os
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, Cookie, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from services.ai_service import (
    process_and_store_document, get_all_documents, delete_document,
    chat_with_context, generate_audio_script, generate_interrupt_script,
)

app = FastAPI(title="Robotic Lecturer API", description="NotebookLM clone backed by Gemini and FAISS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatQuery(BaseModel):
    query: str


def get_or_create_session(response: Response, session_id: str | None) -> str:
    """Return the existing session ID or mint a fresh one and set the cookie."""
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=60 * 60 * 24 * 7,   # 1-week cookie
            httponly=True,
            samesite="none",
            secure=True,
        )
    return session_id


@app.get("/")
def read_root():
    return {"status": "Lecturer backend is online!"}


@app.post("/upload")
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    session_id: str | None = Cookie(default=None),
):
    valid_extensions = (".pdf", ".pptx", ".docx")
    if not file.filename.lower().endswith(valid_extensions):
        raise HTTPException(status_code=400, detail=f"Invalid file type. Only {', '.join(valid_extensions)} are supported.")

    sid = get_or_create_session(response, session_id)
    try:
        content = await file.read()
        doc_id, chunk_count = process_and_store_document(content, file.filename, sid)
        return {"filename": file.filename, "document_id": doc_id, "chunks_processed": chunk_count, "status": "Uploaded"}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents")
def list_documents(response: Response, session_id: str | None = Cookie(default=None)):
    sid = get_or_create_session(response, session_id)
    return get_all_documents(sid)


@app.delete("/documents/{doc_id}")
async def remove_document(doc_id: str, response: Response, session_id: str | None = Cookie(default=None)):
    sid = get_or_create_session(response, session_id)
    if not delete_document(doc_id, sid):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted"}


@app.post("/chat")
async def chat_interaction(
    chat_query: ChatQuery,
    response: Response,
    session_id: str | None = Cookie(default=None),
):
    sid = get_or_create_session(response, session_id)
    try:
        return chat_with_context(chat_query.query, sid)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/audio-overview")
async def audio_overview(response: Response, session_id: str | None = Cookie(default=None)):
    sid = get_or_create_session(response, session_id)
    try:
        return await generate_audio_script(sid)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/audio-interrupt")
async def audio_interrupt(
    chat_query: ChatQuery,
    response: Response,
    session_id: str | None = Cookie(default=None),
):
    sid = get_or_create_session(response, session_id)
    try:
        return await generate_interrupt_script(chat_query.query, sid)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
