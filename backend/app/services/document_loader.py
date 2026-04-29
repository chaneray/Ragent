import os

from app.core.config import get_settings

settings = get_settings()


def parse_document(file_path: str):
    """解析文档为 LangChain Document 列表（懒加载依赖）"""
    from langchain_community.document_loaders import PyPDFLoader, TextLoader
    from langchain_core.documents import Document

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(file_path)
        docs = loader.load()
    elif ext == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        loader = Docx2txtLoader(file_path)
        docs = loader.load()
    else:
        from langchain_community.document_loaders import TextLoader
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                loader = TextLoader(file_path, encoding=enc)
                docs = loader.load()
                break
            except Exception:
                continue
        else:
            # 所有编码都失败，尝试以二进制读
            with open(file_path, "rb") as f:
                content = f.read()
            docs = [Document(page_content=content.decode("utf-8", errors="replace"))]
    return docs, len(docs)


def split_documents(docs):
    """将文档按块切分"""
    from langchain_text_splitters.character import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", " ", ""],
    )
    return splitter.split_documents(docs)


def save_uploaded_file(kb_id: int, user_id: int, filename: str, content: bytes) -> str:
    """保存上传文件到本地"""
    upload_dir = settings.UPLOAD_DIR
    user_dir = os.path.join(upload_dir, str(user_id), str(kb_id))
    os.makedirs(user_dir, exist_ok=True)

    safe_name = "%d_%s" % (len(os.listdir(user_dir)), filename)
    file_path = os.path.join(user_dir, safe_name)

    with open(file_path, "wb") as f:
        f.write(content)

    return file_path
