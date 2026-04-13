import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# We import the services AFTER load_dotenv
from services.ai_service import process_and_store_document, get_all_documents, delete_document, chat_with_context, generate_audio_script, generate_interrupt_script

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

@app.get("/")
def read_root():
    return {"status": "Lecturer backend is online (FAISS Engine)!"}

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    valid_extensions = (".pdf", ".pptx", ".docx")
    if not file.filename.lower().endswith(valid_extensions):
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Only {', '.join(valid_extensions)} are supported."
        )
    
    try:
        content = await file.read()
        doc_id, chunk_count = process_and_store_document(content, file.filename)
        return {"filename": file.filename, "document_id": doc_id, "chunks_processed": chunk_count, "status": "Uploaded and Indexed in memory"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
def list_documents():
    return get_all_documents()

@app.delete("/documents/{doc_id}")
async def remove_document(doc_id: str):
    success = delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted"}

@app.post("/chat")
async def chat_interaction(chat_query: ChatQuery):
    try:
        result = chat_with_context(chat_query.query)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/audio-overview")
async def audio_overview():
    try:
        result = await generate_audio_script()
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/audio-interrupt")
async def audio_interrupt(chat_query: ChatQuery):
    try:
        result = await generate_interrupt_script(chat_query.query)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
