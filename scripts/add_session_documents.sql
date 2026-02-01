-- 会话-文档关联表：支持「会话中附加文件」
-- 若使用 create_tables 自动建表，可忽略此脚本；
-- 仅在需手动迁移时执行（如已有生产库且未自动创建 session_documents）
CREATE TABLE IF NOT EXISTS session_documents (
    id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    doc_id VARCHAR(64) NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    attached_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_session_documents_session_id ON session_documents(session_id);
CREATE INDEX IF NOT EXISTS ix_session_documents_doc_id ON session_documents(doc_id);
