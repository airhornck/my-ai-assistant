-- 为已有 user_profiles 表添加 brand_facts、success_cases 列
-- 若使用 create_tables 新建库可忽略；若表已存在，请备份后执行：
-- psql -U postgres -d ai_assistant -f scripts/add_brand_memory_columns.sql

ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS brand_facts JSONB DEFAULT NULL;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS success_cases JSONB DEFAULT NULL;

COMMENT ON COLUMN user_profiles.brand_facts IS '品牌事实库，如 [{"fact":"...","category":"..."}]';
COMMENT ON COLUMN user_profiles.success_cases IS '成功案例库，如 [{"title":"...","description":"...","outcome":"..."}]';
