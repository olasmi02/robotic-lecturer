import os
import tempfile
import uuid
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredPowerPointLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Using Google Gemini's Embedding Model to avoid massive local PyTorch downloads
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
persist_directory = "./chroma_data"

vectorstore = Chroma(embedding_function=embeddings, persist_directory=persist_directory)

def process_and_store_document(file_content: bytes, filename: str):
    """Parses a document, splits it into vector chunks, and saves them to local DB."""
    ext = os.path.splitext(filename)[1].lower()
    
    # Save uploaded bytes to a temp file because loaders require file paths
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
        temp_file.write(file_content)
        temp_file_path = temp_file.name

    try:
        # 1. Load Document based on file type
        if ext == ".pdf":
            loader = PyPDFLoader(temp_file_path)
        elif ext == ".docx":
            loader = Docx2txtLoader(temp_file_path)
        elif ext == ".pptx":
            loader = UnstructuredPowerPointLoader(temp_file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
        
        documents = loader.load()

        # 2. Split into meaningful chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )
        chunks = text_splitter.split_documents(documents)

        # 3. Add custom metadata
        doc_id = str(uuid.uuid4())
        for chunk in chunks:
            chunk.metadata["source"] = filename
            chunk.metadata["doc_id"] = doc_id

        # 4. Embed and Store in ChromaDB
        vectorstore.add_documents(chunks)
        
        return doc_id, len(chunks)
    finally:
        os.remove(temp_file_path)

def get_all_documents():
    """Retrieve list of unique documents from the vector DB."""
    # ChromaDB metadata filtering is complex; this is a simplified approach
    # We can retrieve part of the DB to assemble a list of sources.
    try:
        results = vectorstore.get()
        metadatas = results.get("metadatas", [])
        
        # Deduplicate by document source
        unique_docs = {}
        for m in metadatas:
            if "source" in m and "doc_id" in m:
                source = m["source"]
                doc_id = m["doc_id"]
                unique_docs[doc_id] = source
                
        return [{"id": k, "filename": v} for k, v in unique_docs.items()]
    except Exception as e:
        print(f"Error fetching documents: {e}")
        return []
