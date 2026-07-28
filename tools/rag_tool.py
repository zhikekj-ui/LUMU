"""RAG tools — document ingestion and retrieval for the agent."""
import os
from tools.registry import ToolRegistry

# 复用与知识库统一的语义向量（bge-small-zh-v1.5 / fastembed，512 维），
# 替换默认的 hash-bucket 伪向量，使 RAG 检索为真实语义匹配而非字面 n-gram 重叠。
from knowledge.embedding import get_embedding_fn


def _get_pipeline():
    """Lazy-init RAG pipeline with real semantic embeddings."""
    from rag.pipeline import RAGPipeline
    data_dir = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "rag")
    return RAGPipeline(data_dir=data_dir, embedding_fn=get_embedding_fn())


def handle_rag_ingest_file(**kwargs):
    """Ingest a document file into the RAG knowledge base.
    
    Args:
        file_path: Path to the document file (PDF, Word, Excel, PPT, TXT, MD, CSV, HTML)
        collection: Collection name (default: 'default')
        metadata: Optional JSON metadata
    """
    import json
    
    file_path = kwargs.get("file_path", "")
    collection = kwargs.get("collection", "default")
    metadata = kwargs.get("metadata", {})
    
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    
    try:
        pipeline = _get_pipeline()
        result = pipeline.ingest_file(file_path, collection=collection, metadata=metadata)
        return result
    except ImportError as e:
        return {"error": f"Missing dependency: {str(e)}. Run: pip install PyPDF2 python-docx openpyxl python-pptx"}
    except Exception as e:
        return {"error": str(e)}


def handle_rag_ingest_text(**kwargs):
    """Ingest raw text into the RAG knowledge base.
    
    Args:
        text: The text content to index
        collection: Collection name (default: 'default')
        source: Source identifier for the text
        metadata: Optional JSON metadata
    """
    import json
    
    text = kwargs.get("text", "")
    collection = kwargs.get("collection", "default")
    source = kwargs.get("source", "direct_input")
    metadata = kwargs.get("metadata", {})
    
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    
    if not text.strip():
        return {"error": "Text is empty"}
    
    try:
        pipeline = _get_pipeline()
        result = pipeline.ingest_text(text, collection=collection, source=source, metadata=metadata)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_rag_query(**kwargs):
    """Query the RAG knowledge base for relevant document chunks.
    
    Args:
        question: The question to search for
        collection: Collection to search (default: 'default')
        top_k: Number of results to return (default: 5)
        min_score: Minimum similarity score (default: 0.1)
    """
    question = kwargs.get("question", "")
    collection = kwargs.get("collection", "default")
    top_k = kwargs.get("top_k", 5)
    min_score = kwargs.get("min_score", 0.1)
    
    if not question.strip():
        return {"error": "Question is empty"}
    
    try:
        pipeline = _get_pipeline()
        result = pipeline.query(question, collection=collection, top_k=top_k, min_score=min_score)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_rag_list_collections(**kwargs):
    """List all RAG collections with document counts."""
    try:
        pipeline = _get_pipeline()
        collections = pipeline.list_collections()
        stats = pipeline.stats()
        return {"collections": collections, "stats": stats}
    except Exception as e:
        return {"error": str(e)}


def handle_rag_delete_collection(**kwargs):
    """Delete a RAG collection and all its documents.
    
    Args:
        collection: Collection name to delete
    """
    collection = kwargs.get("collection", "")
    if not collection:
        return {"error": "Collection name required"}
    
    try:
        pipeline = _get_pipeline()
        result = pipeline.delete_collection(collection)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_rag_stats(**kwargs):
    """Get RAG system statistics."""
    try:
        pipeline = _get_pipeline()
        return pipeline.stats()
    except Exception as e:
        return {"error": str(e)}


def register(registry: ToolRegistry):
    """Register RAG tools."""
    registry.register(
        name="rag_ingest_file",
        description="将文档文件导入RAG知识库。支持PDF、Word、Excel、PPT、TXT、Markdown、CSV、HTML格式。文档会被自动分块和向量化索引。",
        handler=handle_rag_ingest_file,
        toolset="rag",
        parameters={
            "file_path": {"type": "string", "description": "文档文件路径", "required": True},
            "collection": {"type": "string", "description": "集合名称（默认default）", "required": False},
            "metadata": {"type": "string", "description": "JSON格式元数据", "required": False},
        },
    )
    
    registry.register(
        name="rag_ingest_text",
        description="将文本内容导入RAG知识库。文本会被自动分块和向量化索引。",
        handler=handle_rag_ingest_text,
        toolset="rag",
        parameters={
            "text": {"type": "string", "description": "要索引的文本内容", "required": True},
            "collection": {"type": "string", "description": "集合名称", "required": False},
            "source": {"type": "string", "description": "来源标识", "required": False},
            "metadata": {"type": "string", "description": "JSON格式元数据", "required": False},
        },
    )
    
    registry.register(
        name="rag_query",
        description="在RAG知识库中搜索相关文档片段。返回最匹配的文档内容及其相似度分数。",
        handler=handle_rag_query,
        toolset="rag",
        parameters={
            "question": {"type": "string", "description": "搜索问题", "required": True},
            "collection": {"type": "string", "description": "搜索集合", "required": False},
            "top_k": {"type": "integer", "description": "返回结果数（默认5）", "required": False},
            "min_score": {"type": "number", "description": "最低相似度（默认0.1）", "required": False},
        },
    )
    
    registry.register(
        name="rag_list_collections",
        description="列出RAG知识库中所有集合及其文档数量。",
        handler=handle_rag_list_collections,
        toolset="rag",
        parameters={},
    )
    
    registry.register(
        name="rag_delete_collection",
        description="删除RAG知识库中的指定集合及其所有文档。",
        handler=handle_rag_delete_collection,
        toolset="rag",
        parameters={
            "collection": {"type": "string", "description": "要删除的集合名称", "required": True},
        },
    )
    
    registry.register(
        name="rag_stats",
        description="获取RAG系统统计信息（集合数、文档总数等）。",
        handler=handle_rag_stats,
        toolset="rag",
        parameters={},
    )
