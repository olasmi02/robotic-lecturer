import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { UploadCloud, FileText, Send, BookOpen, Loader2 } from 'lucide-react';

const API_BASE = "http://localhost:8000";

function App() {
  const [documents, setDocuments] = useState([]);
  const [chatHistory, setChatHistory] = useState([
    {
      role: 'ai',
      text: "Hello! I am your Robotic Lecturer. Upload your materials (PDF, Word, or PPTX) to the left, and ask me anything about them!",
      citations: []
    }
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);

  // Fetch documents on load
  const fetchDocuments = async () => {
    try {
      const res = await axios.get(`${API_BASE}/documents`);
      setDocuments(res.data);
    } catch (err) {
      console.error("Failed to fetch documents. Make sure FastAPI backend is running.", err);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  useEffect(() => {
    // Auto-scroll to bottom of chat
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, isTyping]);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      await axios.post(`${API_BASE}/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      // Refresh documents list
      fetchDocuments();
    } catch (err) {
      alert("Failed to upload document. Please ensure it's a PDF, DOCX, or PPTX and the backend is running.");
      console.error(err);
    } finally {
      setIsUploading(false);
      // Reset input so they can upload same file again if needed
      e.target.value = null;
    }
  };

  const handleSendMessage = async () => {
    if (!inputValue.trim()) return;
    
    const userMsg = inputValue;
    setInputValue("");
    setChatHistory(prev => [...prev, { role: 'user', text: userMsg }]);
    setIsTyping(true);

    try {
      const res = await axios.post(`${API_BASE}/chat`, { query: userMsg });
      
      setChatHistory(prev => [...prev, {
        role: 'ai',
        text: res.data.response,
        citations: res.data.citations
      }]);
    } catch (err) {
      setChatHistory(prev => [...prev, {
        role: 'ai',
        text: "Sorry, my brain disconnected! Please make sure the backend server (FastAPI) is running.",
        citations: []
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="app-container">
      {/* Sidebar for Documents */}
      <aside className="sidebar glass-panel">
        <div className="logo-area">
          <BookOpen /> Robotic Lecturer
        </div>
        
        <label className={`upload-zone ${isUploading ? 'drag-active' : ''}`}>
          <input 
            type="file" 
            style={{ display: 'none' }} 
            onChange={handleFileUpload}
            accept=".pdf,.docx,.pptx"
            disabled={isUploading}
          />
          {isUploading ? (
            <Loader2 className="animate-spin" size={32} color="#6366f1" />
          ) : (
            <UploadCloud size={32} color="#6366f1" />
          )}
          <p>{isUploading ? "Ingesting data..." : "Click to upload notes (PDF, Word, PPTX)"}</p>
        </label>

        <div className="documents-list">
          <h4 style={{ color: "var(--text-muted)", marginBottom: "0.5rem", fontSize: "0.8rem", textTransform: "uppercase" }}>
            Course Materials
          </h4>
          {documents.length === 0 ? (
            <p style={{ fontSize: "0.875rem", color: "var(--text-muted)" }}>No materials uploaded yet.</p>
          ) : (
            documents.map((doc, idx) => (
              <div key={idx} className="document-item">
                <FileText size={16} color="#94a3b8" />
                <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={doc.filename}>
                  {doc.filename}
                </span>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Chat Area */}
      <main className="main-chat-area">
        <div className="chat-history">
          {chatHistory.length === 0 && (
            <div className="empty-state">
              <BookOpen size={48} color="#94a3b8" style={{margin: "0 auto 1rem auto"}} />
              <h2>Welcome to class!</h2>
              <p>Upload a course document to the left to begin.</p>
            </div>
          )}

          {chatHistory.map((msg, idx) => (
            <div key={idx} className={`message-bubble ${msg.role === 'user' ? 'message-user' : 'message-ai'}`}>
              {msg.role === 'user' ? (
                <p>{msg.text}</p>
              ) : (
                <>
                  <ReactMarkdown>{msg.text}</ReactMarkdown>
                  
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="citations-container">
                      <p style={{ fontSize: "0.8rem", fontWeight: "600", color: "var(--text-main)", marginBottom: "0.5rem", textTransform: "uppercase" }}>
                        Sources:
                      </p>
                      {msg.citations.map((cite) => (
                        <div key={cite.id} className="citation-source">
                          <strong>{cite.source}</strong>
                          "{cite.snippet}"
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          
          {isTyping && (
            <div className="message-bubble message-ai" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <Loader2 className="animate-spin" size={20} color="#6366f1" /> 
              <span>Analyzing your materials...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <div className="input-container">
            <input 
              className="input-field"
              placeholder="Ask the lecturer a question..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              disabled={isTyping || isUploading}
            />
            <button className="send-button" onClick={handleSendMessage} disabled={isTyping || isUploading || !inputValue.trim()}>
              <Send size={20} />
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
