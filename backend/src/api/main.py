"""FastAPI Application phục vụ API hỏi đáp pháp lý và Streaming SSE (Phase 6)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field

from src.agent.graph import LegalAgent
from src.config import get_settings
from src.services.voice_service import (
    DEFAULT_VOICE,
    VOICE_MALE,
    text_to_speech_bytes,
    stream_text_to_speech,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
agent_instance: LegalAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi tạo agent và pre-load retrieval cache khi server bật lên."""
    global agent_instance
    logger.info("Đang khởi động Legal QA Assistant API và chuẩn bị chỉ mục...")
    agent_instance = LegalAgent()
    try:
        await agent_instance.retriever.initialize()
        logger.info("Khởi động hoàn tất, sẵn sàng nhận request!")
    except Exception as e:
        logger.warning(f"Chưa thể kết nối CSDL khi khởi động ({e}). Sẽ tự động kết nối lại khi có request.")
    yield
    logger.info("Đang tắt dịch vụ...")


app = FastAPI(
    title="Trợ lý Hỏi đáp Pháp luật Việt Nam API",
    version="3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str = Field(..., description="Câu hỏi người dùng")
    session_id: str = Field("default", description="Mã định danh phiên hội thoại (thread_id)")
    history: list[dict] | None = Field(default=None, description="Danh sách lịch sử hội thoại nếu client tự quản lý")


class ChatResponse(BaseModel):
    query: str
    session_id: str
    standalone_query: str | None = None
    intent: str
    answer: str
    citations: list[str]
    guard_status: str
    retrieved_docs: list[dict]
    history: list[dict] = []
    followup_questions: list[str] = []
    is_multi_violation: bool | None = None
    sub_queries: list[str] = []


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, description="Tiêu đề gợi nhớ của phiên trò chuyện")
    session_id: str | None = Field(default=None, description="Mã định danh phiên tùy chọn nếu client muốn tự sinh")


class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=150, description="Tiêu đề mới cho phiên trò chuyện")


class TTSRequest(BaseModel):
    text: str = Field(..., description="Văn bản cần chuyển đổi thành giọng nói")
    voice: str = Field(default=DEFAULT_VOICE, description="Mã giọng đọc (vi-VN-HoaiMyNeural hoặc vi-VN-NamMinhNeural)")
    rate: str = Field(default="+0%", description="Tốc độ nói (vd: +10%, -10%)")
    pitch: str = Field(default="+0Hz", description="Cao độ giọng nói")
    stream: bool = Field(default=False, description="Stream audio bytes trực tiếp")


@app.get("/health")
async def health_check():
    """Kiểm tra tình trạng hoạt động của hệ thống."""
    is_ready = bool(agent_instance and agent_instance.retriever._is_ready)
    return {
        "status": "ok",
        "service": "legal-qa-backend",
        "retriever_ready": is_ready,
        "database": "connected" if is_ready else "disconnected",
    }


@app.get("/articles/lookup")
async def lookup_article(citation: str):
    """Tra cứu trực tiếp toàn văn điều luật theo chuỗi trích dẫn hoặc số hiệu điều."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")

    records = agent_instance.retriever.records
    if not records:
        try:
            await agent_instance.retriever.initialize()
            records = agent_instance.retriever.records
        except Exception:
            records = []

    citation_clean = citation.strip()
    match_num = re.search(r"Điều\s+(\d+[a-zA-Z]?)", citation_clean, re.IGNORECASE)
    target_num = match_num.group(1) if match_num else None

    candidates = []
    for r in records:
        art = r.get("article", "")
        if target_num:
            if re.search(rf"\b{target_num}\b", art):
                score = 0
                title = r.get("article_title", "")
                law = r.get("law_name", "")
                for word in (title + " " + law).split():
                    if len(word) > 2 and word.lower() in citation_clean.lower():
                        score += 1
                candidates.append((score, r))
        elif art.lower() in citation_clean.lower():
            candidates.append((1, r))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best = dict(candidates[0][1])
        return {
            "id": best.get("id"),
            "article": best.get("article"),
            "article_title": best.get("article_title"),
            "law_name": best.get("law_name"),
            "doc_type": best.get("doc_type"),
            "content": best.get("content"),
            "text": best.get("content"),
            "article_number": f"{best.get('article')}: {best.get('article_title')}" if best.get("article_title") else best.get("article"),
            "score": 1.0,
        }

    # Fallback BM25 chỉ khi không chỉ định số Điều cụ thể (hoặc tra cứu theo từ khóa)
    if not target_num:
        bm25_matches = agent_instance.retriever.keyword_store.search(citation_clean, top_k=1)
        if bm25_matches and bm25_matches[0][1] > 1.0:
            best = dict(bm25_matches[0][0])
            return {
                "id": best.get("id"),
                "article": best.get("article"),
                "article_title": best.get("article_title"),
                "law_name": best.get("law_name"),
                "doc_type": best.get("doc_type"),
                "content": best.get("content"),
                "text": best.get("content"),
                "article_number": f"{best.get('article')}: {best.get('article_title')}" if best.get("article_title") else best.get("article"),
                "score": 0.9,
            }

    raise HTTPException(status_code=404, detail="Không tìm thấy toàn văn điều luật")


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Endpoint hỏi đáp đồng bộ có hỗ trợ trí nhớ hội thoại."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")

    result = await agent_instance.invoke(
        query=req.query,
        session_id=req.session_id,
        history=req.history
    )
    return ChatResponse(
        query=result["query"],
        session_id=result.get("session_id", req.session_id),
        standalone_query=result.get("standalone_query"),
        intent=result["intent"],
        answer=result["answer"],
        citations=result.get("citations", []),
        guard_status=result.get("guard_status", "passed"),
        retrieved_docs=result.get("retrieved_docs", []),
        history=result.get("history", []),
        followup_questions=result.get("followup_questions", []),
        is_multi_violation=result.get("is_multi_violation"),
        sub_queries=result.get("sub_queries", []),
    )


@app.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    """Endpoint stream câu trả lời qua Server-Sent Events (SSE) có nhớ hội thoại."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")

    async def event_generator() -> AsyncGenerator[str, None]:
        # 1. Báo trạng thái phân loại ý định
        yield f"data: {json.dumps({'event': 'intent_classifying', 'message': 'Đang phân tích câu hỏi & ngữ cảnh hội thoại...'})}\n\n"
        await asyncio.sleep(0.05)

        result = await agent_instance.invoke(
            query=req.query,
            session_id=req.session_id,
            history=req.history
        )

        # 2. Báo trạng thái truy hồi và standalone query nếu có
        if result["intent"] == "legal_query":
            yield f"data: {json.dumps({'event': 'retrieved', 'standalone_query': result.get('standalone_query'), 'citations': result.get('citations', [])})}\n\n"
            await asyncio.sleep(0.05)

        # 3. Stream từng phần câu trả lời
        full_answer = result["answer"]
        chunk_size = 8  # Stream từng cụm từ để giao diện mượt mà
        for i in range(0, len(full_answer), chunk_size):
            chunk = full_answer[i : i + chunk_size]
            yield f"data: {json.dumps({'event': 'token', 'delta': chunk})}\n\n"
            await asyncio.sleep(0.01)

        # 4. Báo kết thúc kèm trạng thái guard, session_id và followup_questions
        yield f"data: {json.dumps({'event': 'done', 'session_id': result.get('session_id', req.session_id), 'guard_status': result.get('guard_status', 'passed'), 'followup_questions': result.get('followup_questions', [])})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ==============================================================================
# QUẢN LÝ PHIÊN HỘI THOẠI (MULTI-SESSION CHAT MANAGEMENT)
# ==============================================================================

@app.get("/sessions")
async def list_sessions_endpoint():
    """Lấy danh sách tất cả các phiên hội thoại được lưu trữ trên hệ thống."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")
    return {"sessions": agent_instance.session_manager.list_sessions()}


@app.post("/sessions")
async def create_session_endpoint(req: CreateSessionRequest = CreateSessionRequest()):
    """Tạo một phiên trò chuyện mới hoàn toàn độc lập."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")
    session = agent_instance.session_manager.create_session(
        title=req.title,
        session_id=req.session_id,
    )
    return {"status": "created", "session": session}


@app.get("/sessions/{session_id}")
async def get_session_endpoint(session_id: str):
    """Lấy chi tiết toàn bộ các lượt tin nhắn trong một phiên trò chuyện cũ."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")
    session = agent_instance.session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy phiên hội thoại: {session_id}")
    return session


@app.patch("/sessions/{session_id}")
@app.put("/sessions/{session_id}")
async def rename_session_endpoint(session_id: str, req: RenameSessionRequest):
    """Cập nhật đổi tên tiêu đề phiên trò chuyện."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")
    session = agent_instance.session_manager.rename_session(session_id, req.title)
    if not session:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy phiên hội thoại để đổi tên: {session_id}")
    return {"status": "renamed", "session": session}


@app.delete("/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    """Xóa vĩnh viễn một phiên trò chuyện cũ."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")
    success = agent_instance.session_manager.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Phiên hội thoại không tồn tại hoặc đã bị xóa: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@app.delete("/sessions")
async def clear_all_sessions_endpoint():
    """Xóa sạch toàn bộ tất cả các phiên trò chuyện."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")
    deleted_count = agent_instance.session_manager.clear_all()
    return {"status": "cleared", "deleted_count": deleted_count}


# ==============================================================================
# DỊCH VỤ GIỌNG NÓI TIẾNG VIỆT (VOICE AI: TTS)
# ==============================================================================

@app.get("/voice/voices")
async def get_available_voices():
    """Danh sách các giọng đọc tiếng Việt chất lượng cao Microsoft Edge-TTS."""
    return {
        "voices": [
            {
                "id": DEFAULT_VOICE,
                "name": "Hoài My (Nữ - Giọng đọc chuẩn phát thanh viên, truyền cảm)",
                "gender": "Female",
                "locale": "vi-VN",
            },
            {
                "id": VOICE_MALE,
                "name": "Nam Minh (Nam - Trầm ấm, rành mạch, chuẩn mực)",
                "gender": "Male",
                "locale": "vi-VN",
            },
        ]
    }


@app.post("/voice/tts")
async def text_to_speech_endpoint(req: TTSRequest):
    """Chuyển đổi câu trả lời pháp lý thành file âm thanh MP3 để trợ lý đọc."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Văn bản không được để trống")

    if req.stream:
        return StreamingResponse(
            stream_text_to_speech(req.text, voice=req.voice, rate=req.rate, pitch=req.pitch),
            media_type="audio/mpeg",
        )

    try:
        audio_data = await text_to_speech_bytes(
            text=req.text,
            voice=req.voice,
            rate=req.rate,
            pitch=req.pitch,
        )
        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=legal_voice.mp3"},
        )
    except Exception as e:
        logger.error(f"Lỗi tạo giọng nói TTS: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi sinh âm thanh TTS: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.app.host, port=settings.app.port)
