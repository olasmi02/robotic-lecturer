import os
import tempfile
import uuid
import json
import base64
import asyncio
import edge_tts
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredPowerPointLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate

vectorstore = None
uploaded_documents = {}

# Initialization
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)
audio_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7)

# Prompts
template = """You are a highly intelligent, welcoming, and helpful university lecturer. 
Your goal is to help your students understand the study material based ONLY on the provided context.
If no context is provided, you should act as a friendly professor introducing yourself and asking the student what they would like to learn today, or chat with them normally but guide them to upload materials.

When context is present and you answer based on it, you MUST use the exact facts from the context. Answer comprehensively but clearly.

Context Materials: 
{context}

Student Question: {question}

Lecturer Response:"""

prompt = ChatPromptTemplate.from_template(template)

audio_template = """You are an expert script writer for educational podcasts (exactly like NotebookLM's Audio Overview).
Based ONLY on the provided context, generate a lively, conversational, and energetic podcast script between two hosts named Mark and Sarah.
Mark is the main explainer (intelligent, enthusiastic, male persona).
Sarah is the curious co-host (asks great questions, summarizes points, reacts with amazement, female persona).

Make the conversation flow naturally and cover the primary key themes of the context. 
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

The output MUST be a strict JSON array of objects, where each object has 'speaker' (Mark or Sarah) and 'text' (what they say).
Example:
[
  {{"speaker": "Sarah", "text": "Whoa, hold on Mark, we just got a live question from a listener!"}},
  {{"speaker": "Mark", "text": "Oh, great! What's the question?"}},
  {{"speaker": "Sarah", "text": "They want to know..."}}
]

Return ONLY the raw JSON array. DO NOT wrap it in ```json blocks.

Course Context:
{context}

Listener's Interruption Question: {question}
"""
audio_interrupt_prompt = ChatPromptTemplate.from_template(audio_interrupt_template)


async def text_to_base64_audio(text: str, voice: str) -> str:
    communicate = edge_tts.Communicate(text, voice, rate="+15%")
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return base64.b64encode(audio_data).decode("utf-8")

async def inject_audio_into_script(script: list):
    tasks = []
    for line in script:
        speaker = line.get("speaker", "Mark")
        # Azure Neural Voices
        voice = "en-US-ChristopherNeural" if speaker == "Mark" else "en-US-AriaNeural"
        text = line.get("text", "")
        # Create generation task
        tasks.append(text_to_base64_audio(text, voice))
    
    # Process concurrently for maximum speed
    results = await asyncio.gather(*tasks)
    
    for i, line in enumerate(script):
        line["audio_data"] = results[i]
        
    return script


def process_and_store_document(file_content: bytes, filename: str):
    global vectorstore
    ext = os.path.splitext(filename)[1].lower()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
        temp_file.write(file_content)
        temp_file_path = temp_file.name

    try:
        if ext == ".pdf":
            loader = PyPDFLoader(temp_file_path)
        elif ext == ".docx":
            loader = Docx2txtLoader(temp_file_path)
        elif ext == ".pptx":
            loader = UnstructuredPowerPointLoader(temp_file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
        
        documents = loader.load()

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )
        chunks = text_splitter.split_documents(documents)

        doc_id = str(uuid.uuid4())
        chunk_ids = [str(uuid.uuid4()) for _ in chunks]
        for chunk in chunks:
            chunk.metadata["source"] = filename
            chunk.metadata["doc_id"] = doc_id

        if vectorstore is None:
            vectorstore = FAISS.from_documents(chunks, embeddings, ids=chunk_ids)
        else:
            vectorstore.add_documents(chunks, ids=chunk_ids)
            
        uploaded_documents[doc_id] = {"filename": filename, "chunk_ids": chunk_ids}

        return doc_id, len(chunks)
    finally:
        os.remove(temp_file_path)

def get_all_documents():
    return [{"id": k, "filename": v["filename"]} for k, v in uploaded_documents.items()]

def delete_document(doc_id: str):
    global vectorstore, uploaded_documents
    if doc_id in uploaded_documents:
        chunk_ids = uploaded_documents[doc_id]["chunk_ids"]
        if vectorstore is not None:
            vectorstore.delete(chunk_ids)
            
        del uploaded_documents[doc_id]
        if len(uploaded_documents) == 0:
            vectorstore = None
        return True
    return False

def chat_with_context(query: str):
    global vectorstore
    
    context_text = ""
    docs = []
    
    if vectorstore is not None:
        retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
        docs = retriever.invoke(query)
        context_text = "\n\n---\n\n".join([f"Source: {doc.metadata.get('source', 'Unknown')}\nContent: {doc.page_content}" for doc in docs])
    
    chain = prompt | llm
    ai_response = chain.invoke({"context": context_text, "question": query})
    
    citations = []
    if docs:
        seen_snippets = set()
        for i, doc in enumerate(docs):
            snippet = doc.page_content[:200] + "..."
            if snippet not in seen_snippets:
                citations.append({
                    "id": len(citations) + 1,
                    "source": doc.metadata.get("source", "Unknown"),
                    "snippet": snippet
                })
                seen_snippets.add(snippet)
            
    return {
        "response": ai_response.content,
        "citations": citations
    }

async def generate_audio_script():
    global vectorstore
    if vectorstore is None:
        raise ValueError("No documents uploaded to summarize into audio.")
    
    retriever = vectorstore.as_retriever(search_kwargs={"k": 8})
    docs = retriever.invoke("What is the comprehensive overview and main key themes of this entire course material?")
    context_text = "\n\n---\n\n".join([doc.page_content for doc in docs])
    
    chain = audio_prompt | audio_llm
    ai_response = chain.invoke({"context": context_text})
    
    response_text = ai_response.content.strip()
    if response_text.startswith("```json"):
        response_text = response_text.replace("```json", "").replace("```", "").strip()
    
    try:
        script = json.loads(response_text)
        script_with_audio = await inject_audio_into_script(script)
        return {"script": script_with_audio}
    except json.JSONDecodeError:
        return {"script": [{"speaker": "Mark", "text": "Sorry, I couldn't generate the script properly. Please try again."}]}

async def generate_interrupt_script(question: str):
    global vectorstore
    if vectorstore is None:
        raise ValueError("No documents uploaded to summarize into audio.")
    
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
    docs = retriever.invoke(question)
    context_text = "\n\n---\n\n".join([doc.page_content for doc in docs])
    
    chain = audio_interrupt_prompt | audio_llm
    ai_response = chain.invoke({"context": context_text, "question": question})
    
    response_text = ai_response.content.strip()
    if response_text.startswith("```json"):
        response_text = response_text.replace("```json", "").replace("```", "").strip()
    
    try:
        script = json.loads(response_text)
        script_with_audio = await inject_audio_into_script(script)
        return {"script": script_with_audio}
    except json.JSONDecodeError:
        return {"script": [{"speaker": "Mark", "text": "Sorry, we had a technical glitch processing your question!"}]}
