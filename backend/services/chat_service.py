import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from services.document_service import vectorstore

# Initialize Google Gemini using the free fast tier
# Note: It automatically picks up GOOGLE_API_KEY from the environment
llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.3)

template = """You are a highly intelligent and helpful university lecturer. Your goal is to help your students understand the study material based ONLY on the provided context.
If the answer is not in the context, do not guess—tell the student that the information isn't in their uploaded materials.

When you answer, you MUST use the exact facts from the context. Answer comprehensively but clearly.

Here are the retrieved materials from the student's syllabus/notes: 
{context}

Student Question: {question}

Lecturer Response:"""

prompt = ChatPromptTemplate.from_template(template)

def chat_with_context(query: str):
    """Retrieves relevant chunks and generates a response using Gemini."""
    
    # Check if there are any documents in the vectorstore first
    try:
        collection_count = vectorstore._collection.count()
    except Exception:
        collection_count = 0
    
    if collection_count == 0:
        return {
            "response": "I see you haven't uploaded any documents yet! Please upload a PDF, Word (.docx), or PowerPoint (.pptx) file first using the sidebar, and then I'll be able to answer questions about your course materials.",
            "citations": []
        }
    
    # Retrieve top 4 most relevant chunks
    retriever = vectorstore.as_retriever(search_kwargs={"k": min(4, collection_count)})
    docs = retriever.invoke(query)
    
    if not docs:
        return {
            "response": "I see you haven't uploaded any documents yet, or I couldn't find anything related to that in your materials. Please upload a PDF, Word, or PPTX file first!",
            "citations": []
        }
    
    # Combine the context
    context_text = "\n\n---\n\n".join([f"Source: {doc.metadata.get('source')}\nContent: {doc.page_content}" for doc in docs])
    
    # Generate the response
    chain = prompt | llm
    ai_response = chain.invoke({"context": context_text, "question": query})
    
    # Build citations mapping for the frontend
    citations = []
    # Deduplicate citations to make it cleaner on UI
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
