import os
import tempfile
import uuid
import json
import base64
import asyncio
import time
import edge_tts
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredPowerPointLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate

# ─── Session-isolated state ───────────────────────────────────────────────────
# Each session_id maps to its own vectorstore + document list
session_stores: dict = {}   # session_id -> FAISS | None
session_docs:   dict = {}   # session_id -> {doc_id: {filename, chunk_ids}}

# ─── Model cascade ────────────────────────────────────────────────────────────
MODEL_CASCADE = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
]

# Track per-model 429 cool-down timestamps
_model_cooldown: dict = {}      # model_name -> epoch time when it becomes available again
COOLDOWN_SECONDS = 60           # back-off window

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")


def _make_llm(model: str, temperature: float) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=model, temperature=temperature)


def _pick_model(base_temperature: float = 0.5):
    """Return the best currently-available LLM from the cascade."""
    now = time.time()
    for model in MODEL_CASCADE:
        if _model_cooldown.get(model, 0) <= now:
            print(f"[MODEL] Using {model}")
            return model, _make_llm(model, base_temperature)
    # All are throttled – use the last one anyway (least likely to be primary)
    fallback = MODEL_CASCADE[-1]
    print(f"[MODEL] All throttled – forcing {fallback}")
    return fallback, _make_llm(fallback, base_temperature)


def _run_with_cascade(prompt_template, invoke_kwargs: dict, temperature: float = 0.5):
    """Try every model in the cascade; mark 429s and move on."""
    now = time.time()
    for model in MODEL_CASCADE:
        if _model_cooldown.get(model, 0) > now:
            continue
        try:
            llm = _make_llm(model, temperature)
            chain = prompt_template | llm
            result = chain.invoke(invoke_kwargs)
            # On success, un-throttle this model so it gets priority next time
            _model_cooldown.pop(model, None)
            print(f"[MODEL] Success with {model}")
            return result
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                _model_cooldown[model] = time.time() + COOLDOWN_SECONDS
                print(f"[MODEL] {model} rate-limited – cooling down for {COOLDOWN_SECONDS}s")
            else:
                raise   # non-quota errors bubble up immediately
    raise RuntimeError("All models in the cascade are currently rate-limited. Please wait a minute.")


# ─── Prompts ─────────────────────────────────────────────────────────────────
template = """You are a highly intelligent, warm, and charismatic university lecturer named Professor Mark.
Your personality is enthusiastic, encouraging, and deeply knowledgeable across all academic subjects.

Your behaviour depends on whether course materials have been uploaded:

WHEN NO CONTEXT IS PROVIDED (no materials uploaded yet):
- Greet the student warmly and ask what subject or topic they want to study today.
- If the student mentions a topic or subject area, briefly share 2-3 interesting and accurate facts about it to show your expertise and get the student excited.
- Then naturally and conversationally ask: "Do you have any lecture notes, slides, or a textbook chapter I can help you break down? Upload them and I'll turn them into a full learning session!"
- Keep the tone friendly and encouraging — like a real professor who genuinely loves their subject.
- Do NOT make up detailed course-specific content; keep it general until materials are uploaded.

WHEN CONTEXT IS PROVIDED (materials have been uploaded):
- You MUST answer ONLY from the provided context. Do NOT invent or assume facts.
- Give comprehensive, well-structured answers with examples from the material.
- Cite specific sections or sources when relevant.
- If a question cannot be answered from the context, say so honestly and encourage the student.

Context Materials: 
{context}

Student: {question}

Professor Mark:"""
prompt = ChatPromptTemplate.from_template(template)

audio_template = """You are an expert script writer for educational podcasts (exactly like NotebookLM's Audio Overview).
Based ONLY on the provided context, generate a lively, conversational, and energetic podcast script between two hosts named Mark and Sarah.
Mark is the main explainer (intelligent, enthusiastic, male persona).
Sarah is the curious co-host (asks great questions, summarizes points, reacts with amazement, female persona).

Make the conversation flow naturally and cover the primary key themes of the context. 
Keep the podcast script concise and short! Generate a MAXIMUM of 6 lines of dialogue in total!

The output MUST be a strict JSON array of objects, where each object has 'speaker' (Mark or Sarah) and 'text' (what they say).
Example:
[
  {{"speaker": "Mark", "text": "Welcome back! Today we are diving into..."}},
  {{"speaker": "Sarah", "text": "I can't wait. This topic is fascinating!"}}
]

Return ONLY the raw JSON array. DO NOT wrap it in ```json blocks.

Context:
{context}
"""
audio_prompt = ChatPromptTemplate.from_template(audio_template)

audio_interrupt_template = """You are writing a live continuation of an educational podcast script between two hosts, Mark and Sarah.
They were just explaining the course material when suddenly, a listener (the user) interrupted with a live question!

Based ONLY on the provided course context, generate the immediate reaction and answer from Mark and Sarah.
They should sound surprised but eager to answer. They must directly address the user's question with facts from the context.
If the answer is not in the context, they should admit they don't see it in the syllabus but offer a quick helpful thought.
Generate a MAXIMUM of 5 lines of dialogue in total.

The output MUST be a strict JSON array of objects, where each object has 'speaker' (Mark or Sarah) and 'text' (what they say).
Return ONLY the raw JSON array. DO NOT wrap it in ```json blocks.

Course Context:
{context}

Listener's Interruption Question: {question}
"""
audio_interrupt_prompt = ChatPromptTemplate.from_template(audio_interrupt_template)


# ─── TTS helpers ─────────────────────────────────────────────────────────────
async def text_to_base64_audio(text: str, voice: str) -> str:
    try:
        communicate = edge_tts.Communicate(text, voice, rate="+15%")
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return base64.b64encode(audio_data).decode("utf-8")
    except Exception as e:
        print(f"TTS failed for text: {text[:30]}... Error: {e}")
        return None


async def inject_audio_into_script(script: list):
    for line in script:
        speaker = line.get("speaker", "Mark")
        voice = "en-US-ChristopherNeural" if speaker == "Mark" else "en-US-AriaNeural"
        text = line.get("text", "")
        line["audio_data"] = await text_to_base64_audio(text, voice)
    return script


# ─── Session helpers ──────────────────────────────────────────────────────────
def _get_session(session_id: str):
    if session_id not in session_stores:
        session_stores[session_id] = None
        session_docs[session_id] = {}
    return session_stores[session_id], session_docs[session_id]


# ─── Document management (session-scoped) ─────────────────────────────────────
def process_and_store_document(file_content: bytes, filename: str, session_id: str):
    ext = os.path.splitext(filename)[1].lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        if ext == ".pdf":
            loader = PyPDFLoader(tmp_path)
        elif ext == ".docx":
            loader = Docx2txtLoader(tmp_path)
        elif ext == ".pptx":
            loader = UnstructuredPowerPointLoader(tmp_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        documents = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(documents)

        doc_id = str(uuid.uuid4())
        chunk_ids = [str(uuid.uuid4()) for _ in chunks]
        for chunk in chunks:
            chunk.metadata["source"] = filename
            chunk.metadata["doc_id"] = doc_id

        vs = session_stores.get(session_id)
        if vs is None:
            session_stores[session_id] = FAISS.from_documents(chunks, embeddings, ids=chunk_ids)
        else:
            vs.add_documents(chunks, ids=chunk_ids)

        if session_id not in session_docs:
            session_docs[session_id] = {}
        session_docs[session_id][doc_id] = {"filename": filename, "chunk_ids": chunk_ids}

        return doc_id, len(chunks)
    finally:
        os.remove(tmp_path)


def get_all_documents(session_id: str):
    docs = session_docs.get(session_id, {})
    return [{"id": k, "filename": v["filename"]} for k, v in docs.items()]


def delete_document(doc_id: str, session_id: str):
    docs = session_docs.get(session_id, {})
    if doc_id in docs:
        chunk_ids = docs[doc_id]["chunk_ids"]
        vs = session_stores.get(session_id)
        if vs is not None:
            vs.delete(chunk_ids)
        del docs[doc_id]
        if not docs:
            session_stores[session_id] = None
        return True
    return False


# ─── Chat ─────────────────────────────────────────────────────────────────────
def chat_with_context(query: str, session_id: str):
    vs = session_stores.get(session_id)
    context_text = ""
    docs = []

    if vs is not None:
        retriever = vs.as_retriever(search_kwargs={"k": 4})
        docs = retriever.invoke(query)
        context_text = "\n\n---\n\n".join(
            [f"Source: {d.metadata.get('source', 'Unknown')}\nContent: {d.page_content}" for d in docs]
        )

    ai_response = _run_with_cascade(prompt, {"context": context_text, "question": query}, temperature=0.3)

    citations = []
    seen = set()
    for d in docs:
        snippet = d.page_content[:200] + "..."
        if snippet not in seen:
            citations.append({"id": len(citations) + 1, "source": d.metadata.get("source", "Unknown"), "snippet": snippet})
            seen.add(snippet)

    return {"response": ai_response.content, "citations": citations}


# ─── Audio overview ───────────────────────────────────────────────────────────
async def generate_audio_script(session_id: str):
    vs = session_stores.get(session_id)
    if vs is None:
        raise ValueError("No documents uploaded to summarize into audio.")

    retriever = vs.as_retriever(search_kwargs={"k": 8})
    docs = retriever.invoke("What is the comprehensive overview and main key themes of this entire course material?")
    context_text = "\n\n---\n\n".join([d.page_content for d in docs])

    ai_response = _run_with_cascade(audio_prompt, {"context": context_text}, temperature=0.7)

    response_text = ai_response.content.strip().replace("```json", "").replace("```", "").strip()
    try:
        script = json.loads(response_text)
        return {"script": await inject_audio_into_script(script)}
    except json.JSONDecodeError:
        return {"script": [{"speaker": "Mark", "text": "Sorry, I couldn't generate the script properly. Please try again."}]}


async def generate_interrupt_script(question: str, session_id: str):
    vs = session_stores.get(session_id)
    if vs is None:
        raise ValueError("No documents uploaded.")

    retriever = vs.as_retriever(search_kwargs={"k": 4})
    docs = retriever.invoke(question)
    context_text = "\n\n---\n\n".join([d.page_content for d in docs])

    ai_response = _run_with_cascade(audio_interrupt_prompt, {"context": context_text, "question": question}, temperature=0.7)

    response_text = ai_response.content.strip().replace("```json", "").replace("```", "").strip()
    try:
        script = json.loads(response_text)
        return {"script": await inject_audio_into_script(script)}
    except json.JSONDecodeError:
        return {"script": [{"speaker": "Mark", "text": "Sorry, we had a technical glitch processing your question!"}]}
