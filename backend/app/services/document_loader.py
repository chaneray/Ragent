import os
import re

from app.core.config import get_settings

settings = get_settings()

# 语义分隔符，按粒度从大到小排列
_PARA_SEP = re.compile(r"\n{2,}")
_SENT_SEP = re.compile(r"(?<=[。！？.!?])\s*")
_PHRASE_SEP = re.compile(r"(?<=[，；,;：:])\s*")


class SemanticChunker:
    """层级递进语义分块器

    切分逻辑：
    1. 按段落(\n\n)切分
    2. 段落超长 → 按句子(。！？)切分
    3. 句子超长 → 按短语(，；,)切分
    4. 每个 chunk 末尾附带下一个 chunk 的开头（overlap）
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(self, docs: list) -> list:
        """将 LangChain Document 列表切分为 chunk 列表"""
        from langchain_core.documents import Document as LCDocument

        all_chunks = []
        for doc in docs:
            units = self._split_text(doc.page_content)
            merged = self._merge_units(units)
            chunks_with_overlap = self._add_overlap(merged)
            for i, chunk_text in enumerate(chunks_with_overlap):
                metadata = dict(doc.metadata)
                metadata["chunk_index"] = i
                metadata["char_count"] = len(chunk_text)
                all_chunks.append(LCDocument(page_content=chunk_text, metadata=metadata))
        return all_chunks

    def _split_text(self, text: str) -> list[str]:
        """层级递进切分文本为语义单元"""
        paragraphs = [p.strip() for p in _PARA_SEP.split(text) if p.strip()]
        units = []
        for para in paragraphs:
            if len(para) <= self.chunk_size:
                units.append(para)
            else:
                units.extend(self._split_by_sentences(para))
        return units

    def _split_by_sentences(self, text: str) -> list[str]:
        """按句子切分，超长句子继续按短语切分"""
        sentences = [s.strip() for s in _SENT_SEP.split(text) if s.strip()]
        units = []
        for sent in sentences:
            if len(sent) <= self.chunk_size:
                units.append(sent)
            else:
                units.extend(self._split_by_phrases(sent))
        return units

    def _split_by_phrases(self, text: str) -> list[str]:
        """按短语切分，超长短语强制截断"""
        phrases = [p.strip() for p in _PHRASE_SEP.split(text) if p.strip()]
        units = []
        for phrase in phrases:
            if len(phrase) <= self.chunk_size:
                units.append(phrase)
            else:
                # 强制按字数截断
                for i in range(0, len(phrase), self.chunk_size):
                    units.append(phrase[i : i + self.chunk_size])
        return units

    def _merge_units(self, units: list[str]) -> list[str]:
        """将小的语义单元合并到接近 chunk_size"""
        if not units:
            return []

        chunks = []
        current = units[0]
        for unit in units[1:]:
            if len(current) + len(unit) + 1 <= self.chunk_size:
                current += "\n" + unit
            else:
                chunks.append(current)
                current = unit
        if current:
            chunks.append(current)
        return chunks

    def _add_overlap(self, chunks: list[str]) -> list[str]:
        """每个 chunk 末尾附带下一个 chunk 的前 chunk_overlap 个字"""
        if len(chunks) <= 1 or self.chunk_overlap <= 0:
            return chunks

        result = []
        for i, chunk in enumerate(chunks):
            if i < len(chunks) - 1:
                overlap_text = chunks[i + 1][: self.chunk_overlap]
                result.append(chunk + "\n" + overlap_text)
            else:
                result.append(chunk)
        return result


def parse_document(file_path: str):
    """解析文档为 LangChain Document 列表（懒加载依赖）"""
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
            with open(file_path, "rb") as f:
                content = f.read()
            docs = [Document(page_content=content.decode("utf-8", errors="replace"))]
    return docs, len(docs)


def split_documents(docs: list) -> list:
    """使用 SemanticChunker 将文档按语义边界切分"""
    chunker = SemanticChunker(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
    )
    return chunker.split_documents(docs)


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
