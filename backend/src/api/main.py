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
from src.agent.nodes.citation_guard_node import citation_guard_node
from src.agent.prompt_builder import LegalPromptBuilder, build_generation_prompt
from src.config import get_settings
from src.services.voice_service import (
    DEFAULT_VOICE,
    VOICE_MALE,
    LOCAL_VOICE,
    OfflineVoiceError,
    text_to_speech_bytes,
    stream_text_to_speech,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
agent_instance: LegalAgent | None = None
db_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi tạo agent, asyncpg connection pool và pre-load retrieval cache khi server bật lên."""
    global agent_instance, db_pool
    logger.info("Đang khởi động Legal QA Assistant API và chuẩn bị chỉ mục...")
    agent_instance = LegalAgent()

    # Khởi tạo connection pool tập trung chia sẻ cho toàn bộ ứng dụng
    try:
        import asyncpg
        pg_cfg = settings.legal_assistant.postgres
        db_pool = await asyncpg.create_pool(
            dsn=pg_cfg.database_url,
            min_size=2,
            max_size=15,
            command_timeout=60,
        )
        agent_instance.retriever.set_pool(db_pool)
        logger.info("Đã khởi tạo asyncpg Connection Pool (min=2, max=15) thành công.")
    except Exception as e:
        logger.warning(f"Không thể tạo asyncpg Connection Pool ({e}). Retriever sẽ tự mở connection độc lập khi cần.")

    try:
        await agent_instance.retriever.initialize()
        from src.domain.legal_registry import get_legal_registry
        get_legal_registry()  # Pre-load LKB vào cache RAM
        logger.info("Khởi động hoàn tất, sẵn sàng nhận request!")
    except Exception as e:
        logger.warning(f"Chưa thể kết nối CSDL khi khởi động ({e}). Sẽ tự động kết nối lại khi có request.")

    yield

    logger.info("Đang tắt dịch vụ...")
    if db_pool:
        await db_pool.close()
        logger.info("Đã đóng asyncpg Connection Pool an toàn.")
    if agent_instance:
        if hasattr(agent_instance.retriever.vector_client, "close"):
            await agent_instance.retriever.vector_client.close()
        if hasattr(agent_instance.llm, "close"):
            await agent_instance.llm.close()
        logger.info("Đã đóng và dọn dẹp các HTTP/DB clients.")


app = FastAPI(
    title="Trợ lý Hỏi đáp Pháp luật Việt Nam API",
    version="3.0",
    lifespan=lifespan,
)

# Giới hạn CORS domain tin cậy (ngăn chặn tấn công CSRF / cross-origin trái phép)
allowed_origins = settings.app.cors_origins or [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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
    """Endpoint stream câu trả lời qua Server-Sent Events (SSE) — True token-level streaming.

    Kiến trúc 2-phase:
      Phase 1 (non-stream): Chạy toàn bộ Agentic RAG pipeline để lấy context và citations.
      Phase 2 (stream): Gọi LLM với stream=True, đẩy từng token vào SSE ngay khi nhận.
    Kết quả: Người dùng thấy text xuất hiện ngay khi LLM sinh ra, không đợi đến cuối.
    """
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")

    async def event_generator() -> AsyncGenerator[str, None]:
        # ── Phase 1: Chạy RAG pipeline với sự kiện tiến trình thời gian thực ────────────
        progress_queue = asyncio.Queue()

        async def push_progress(prog_data: dict):
            await progress_queue.put(prog_data)

        pipeline_task = asyncio.create_task(
            agent_instance.invoke_for_stream(
                query=req.query,
                session_id=req.session_id,
                history=req.history,
                on_progress=push_progress,
            )
        )

        while not pipeline_task.done() or not progress_queue.empty():
            try:
                prog_data = await asyncio.wait_for(progress_queue.get(), timeout=0.05)
                yield f"data: {json.dumps({'event': 'progress', **prog_data})}\n\n"
            except asyncio.TimeoutError:
                continue

        try:
            ctx_state = await pipeline_task
        except Exception as e:
            logger.error(f"Lỗi khi chạy RAG pipeline cho stream: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
            return

        intent = ctx_state.get("intent", "legal_query")
        messages, citations, enriched_docs = build_generation_prompt(ctx_state)

        # Báo kết quả pipeline (intent, citations, standalone_query, retrieved_docs)
        yield f"data: {json.dumps({'event': 'retrieved', 'intent': intent, 'standalone_query': ctx_state.get('standalone_query'), 'citations': citations, 'docs_count': len(enriched_docs), 'retrieved_docs': enriched_docs[:4]})}\n\n"

        # Non-legal intents (smalltalk, out_of_scope): không cần stream RAG nặng
        if intent in ("smalltalk", "out_of_scope"):
            answer = ctx_state.get("answer") or "Xin chào! Tôi là Trợ lý Pháp luật Việt Nam. Bạn có câu hỏi pháp lý nào cần giải đáp không?"
            followup_questions = ctx_state.get("followup_questions") or []
            for i in range(0, len(answer), 8):
                yield f"data: {json.dumps({'event': 'token', 'delta': answer[i:i+8]})}\n\n"

            try:
                agent_instance.session_manager.save_turn(
                    session_id=req.session_id,
                    user_query=req.query,
                    assistant_answer=answer,
                    intent=intent,
                    citations=[],
                    standalone_query=req.query,
                    followup_questions=followup_questions,
                    retrieved_docs=[],
                )
            except Exception as e:
                logger.error(f"Lỗi lưu session sau smalltalk: {e}")

            yield f"data: {json.dumps({'event': 'done', 'session_id': req.session_id, 'stage': 0, 'percent': 100, 'guard_status': 'passed', 'followup_questions': followup_questions})}\n\n"
            return

        # Nhánh chốt chặn điều kiện áp dụng pháp luật (Applicability Hard Gate: BLOCKED)
        if ctx_state.get("eligibility_status") == "BLOCKED":
            answer = ctx_state.get("answer") or ""
            followup_questions = ctx_state.get("followup_questions") or []
            citations = ctx_state.get("citations") or []
            enriched_docs = ctx_state.get("retrieved_docs") or []

            yield f"data: {json.dumps({'event': 'progress', 'stage': 3, 'percent': 90, 'message': 'Đang hoàn tất văn bản tư vấn loại trừ trách nhiệm hình sự & biện pháp thay thế...'})}\n\n"

            for i in range(0, len(answer), 32):
                yield f"data: {json.dumps({'event': 'token', 'delta': answer[i:i+32]})}\n\n"

            try:
                agent_instance.session_manager.save_turn(
                    session_id=req.session_id,
                    user_query=req.query,
                    assistant_answer=answer,
                    intent=intent,
                    citations=citations,
                    standalone_query=ctx_state.get("standalone_query") or req.query,
                    followup_questions=followup_questions,
                    retrieved_docs=enriched_docs,
                )
            except Exception as e:
                logger.error(f"Lỗi lưu session sau inapplicability: {e}")

            yield f"data: {json.dumps({'event': 'done', 'session_id': req.session_id, 'stage': 3, 'percent': 100, 'guard_status': 'passed', 'followup_questions': followup_questions})}\n\n"
            return

        # ── Phase 2: True token-level streaming từ LLM ──────────────────
        yield f"data: {json.dumps({'event': 'progress', 'stage': 3, 'percent': 90, 'message': 'Đang tổng hợp luận điểm & chuẩn bị biên soạn văn bản tư vấn...'})}\n\n"
        yield f"data: {json.dumps({'event': 'generating', 'message': 'Đang sinh câu trả lời pháp lý...'})}\n\n"

        full_answer = ""

        try:
            first_token = True
            async for token in agent_instance.llm.generate_stream(messages):
                if first_token:
                    first_token = False
                    yield f"data: {json.dumps({'event': 'progress', 'stage': 3, 'percent': 95, 'message': 'Đang truyền tải nội dung phản hồi...'})}\n\n"
                full_answer += token
                # Buffer until Citation Guard has validated the complete answer.
        except Exception as e:
            logger.error(f"Lỗi stream từ LLM: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': f'Lỗi kết nối LLM: {e}'})}\n\n"
            return

        # ── Phase 3: Citation Guard Validation trên Streaming Response ────
        # Tách danh sách câu hỏi gợi ý đào sâu và chuẩn hóa phản hồi
        clean_answer, followup_questions = LegalPromptBuilder.extract_followup_and_clean_answer(full_answer)

        # Chốt chặn bảo vệ tiền đề pháp lý đặc biệt (Độ tuổi chịu trách nhiệm hình sự)
        premise_corr = ctx_state.get("premise_correction")
        if premise_corr and premise_corr.get("is_age_ineligible"):
            age = premise_corr.get("age", 12)
            if re.search(r"\b(sẽ bị truy cứu hình sự|phạt tù từ|chịu hình phạt tù|bị phạt tù từ)\b", clean_answer, re.I):
                logger.warning(f"[Guard] Phát hiện LLM ảo giác phạt tù đối với người {age} tuổi -> Đính chính dứt khoát theo Điều 12 BLHS.")
                clean_answer = re.sub(
                    r"(?s)### 1\. Kết luận\s*.*?(?=### 2\. Căn cứ pháp lý)",
                    f"### 1. Kết luận\nNgười {age} tuổi HOÀN TOÀN KHÔNG BỊ TRUY CỨU TRÁCH NHIỆM HÌNH SỰ VÀ KHÔNG BỊ PHẠT TÙ. Theo quy định tại Điều 12 Bộ luật Hình sự 2015, người dưới 14 tuổi chưa đủ tuổi chịu trách nhiệm hình sự đối với bất kỳ tội phạm nào.\n\n",
                    clean_answer,
                )

        # Kiểm định Citation Guard trên toàn bộ câu trả lời vừa sinh (Ngăn chặn Streaming Bypass)
        guard_state = await citation_guard_node({
            "intent": intent,
            "answer": clean_answer,
            "retrieved_docs": enriched_docs,
            "retry_count": ctx_state.get("retry_count", 0),
        })
        guard_status = guard_state.get("guard_status", "passed")
        hallucinated_articles = guard_state.get("hallucinated_articles", [])

        if guard_status == "violation" and hallucinated_articles:
            guard_warning_msg = (
                f"Lưu ý đối chiếu: Hệ thống phát hiện viện dẫn ({', '.join(hallucinated_articles)}) "
                f"chưa có trong nguồn văn bản pháp luật được đối chiếu."
            )
            yield f"data: {json.dumps({'event': 'guard_warning', 'status': guard_status, 'message': guard_warning_msg, 'hallucinated': hallucinated_articles})}\n\n"
            clean_answer = (
                "Tôi chưa thể đưa ra câu trả lời đáng tin cậy vì phát hiện căn cứ pháp lý "
                "chưa được xác minh trong nguồn dữ liệu. Vui lòng thử lại với câu hỏi cụ thể hơn "
                "hoặc đối chiếu văn bản pháp luật hiện hành."
            )

        # Do not expose legal content before the guard has completed.
        for i in range(0, len(clean_answer), 64):
            yield f"data: {json.dumps({'event': 'token', 'delta': clean_answer[i:i + 64]})}\n\n"

        try:
            agent_instance.session_manager.save_turn(
                session_id=req.session_id,
                user_query=req.query,
                assistant_answer=clean_answer,
                intent=intent,
                citations=citations,
                standalone_query=ctx_state.get("standalone_query"),
                followup_questions=followup_questions,
                retrieved_docs=enriched_docs,
            )
        except Exception as e:
            logger.error(f"Lỗi lưu session sau stream: {e}")

        # Sự kiện done kết thúc stream với tiến trình 100%
        yield f"data: {json.dumps({'event': 'done', 'session_id': req.session_id, 'stage': 3, 'percent': 100, 'guard_status': guard_status, 'hallucinated_articles': hallucinated_articles, 'followup_questions': followup_questions})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        raise HTTPException(status_code=500, detail=f"Không thể xóa phiên hội thoại: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@app.delete("/sessions")
async def clear_all_sessions_endpoint():
    """Xóa sạch toàn bộ các phiên trò chuyện trong chế độ local/demo."""
    if not agent_instance:
        raise HTTPException(status_code=503, detail="Agent chưa sẵn sàng")
    deleted_count = agent_instance.session_manager.clear_all()
    return {"status": "cleared", "deleted_count": deleted_count}


@app.post("/ingest")
async def ingest_documents_endpoint(records: list[dict]):
    """Nạp và đánh chỉ mục danh sách văn bản pháp luật mới trong chế độ local/demo."""
    from src.ingestion.pipeline import LegalDocumentIngestionPipeline
    pipeline = LegalDocumentIngestionPipeline()
    result = await pipeline.ingest_records(records)
    return result


# ==============================================================================
# DỊCH VỤ GIỌNG NÓI TIẾNG VIỆT (VOICE AI: TTS)
# ==============================================================================

@app.get("/voice/voices")
async def get_available_voices():
    """Danh sách các giọng đọc tiếng Việt khả dụng (hỗ trợ Edge-TTS trực tuyến và Local TTS nội bộ)."""
    tts_cfg = settings.legal_assistant.tts
    return {
        "provider": tts_cfg.provider,
        "enabled": tts_cfg.enabled,
        "voices": [
            {
                "id": DEFAULT_VOICE,
                "name": "Hoài My (Nữ - Giọng đọc chuẩn phát thanh viên, truyền cảm)",
                "gender": "Female",
                "locale": "vi-VN",
                "provider": "edge-tts",
            },
            {
                "id": VOICE_MALE,
                "name": "Nam Minh (Nam - Trầm ấm, rành mạch, chuẩn mực)",
                "gender": "Male",
                "locale": "vi-VN",
                "provider": "edge-tts",
            },
            {
                "id": LOCAL_VOICE,
                "name": "Giọng đọc Nội bộ (100% On-Premise / Mạng cách ly)",
                "gender": "Neutral",
                "locale": "vi-VN",
                "provider": "local_http",
            },
        ],
    }


@app.post("/voice/tts")
async def text_to_speech_endpoint(req: TTSRequest):
    """Chuyển đổi câu trả lời pháp lý thành file âm thanh MP3 để trợ lý đọc."""
    tts_cfg = settings.legal_assistant.tts
    if not tts_cfg.enabled:
        raise HTTPException(
            status_code=503,
            detail="Tính năng Voice AI (TTS) hiện đang tắt trong cấu hình hệ thống (config.yaml: legal_assistant.tts.enabled = false).",
        )

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
    except OfflineVoiceError as e:
        logger.warning(f"Voice AI Offline: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Lỗi tạo giọng nói TTS: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi sinh âm thanh TTS: {str(e)}")


@app.post("/admin/reload-registry")
async def reload_registry():
    """Tải lại danh mục luật và taxonomy từ PostgreSQL vào in-memory cache."""
    try:
        from src.domain.legal_registry import get_legal_registry
        reg = get_legal_registry()
        reg.reload()
        return {
            "status": "success",
            "message": "Đã tải lại Structured Legal Knowledge Base thành công.",
            "laws_count": len(reg._laws_by_id),
            "taxonomy_count": len(reg._taxonomy_list)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.app.host, port=settings.app.port)
