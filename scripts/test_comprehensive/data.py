# 测试数据模板
import random

# 短期记忆测试 - 偏好话题
SHORT_TERM_PREFERENCES = [
    "我喜欢科技数码类的内容，尤其是手机评测",
    "我更关注美食生活方面的内容",
    "我需要时尚美妆的推荐",
    "我对职场成长内容感兴趣",
    "我喜欢旅游户外的分享",
    "我关注健康养生的信息",
    "我需要教育培训类内容",
    "我爱看音乐影视作品",
    "我关注家居生活的设计",
    "我兴趣是汽车科技",
]

# 长期记忆测试 - 自我介绍
LONG_TERM_INTROS = [
    ("张三", "电商"),    # 品牌名、行业
    ("李四", "教育培训"),
    ("王五", "餐饮"),
    ("赵六", "服装"),
    ("钱七", "数码"),
    ("孙八", "美容"),
    ("周九", "旅游"),
    ("吴十", "健身"),
    ("郑十一", "母婴"),
    ("刘十二", "家居"),
]

# 闲聊分类测试输入
CASUAL_QUERIES = [
    ("你好", "casual_chat"),
    ("在吗", "casual_chat"),
    ("嗨", "casual_chat"),
    ("还好吧", "casual_chat"),
    ("嗯", "casual_chat"),
    ("不错", "casual_chat"),
    ("你能做什么", "casual_chat"),
    ("怎么用", "casual_chat"),
    ("帮我写个文案", "free_discussion"),
    ("推广我的产品", "free_discussion"),
    ("生成营销方案", "free_discussion"),
    ("品牌推广", "free_discussion"),
    ("写小红书", "free_discussion"),
    ("做短视频", "free_discussion"),
    ("营销策划", "free_discussion"),
]

# 自定义提取测试输入
EXTRACT_QUERIES = [
    ("我叫李四", "李四", ""),
    ("我是开咖啡店的", "", "咖啡店"),
    ("我叫王五，做教育培训", "王五", "教育培训"),
    ("我叫赵六，我是做餐饮的", "赵六", "餐饮"),
    ("我是做服装生意的", "", "服装"),
    ("我叫钱七，卖数码产品", "钱七", "数码"),
    ("我做美容行业", "", "美容"),
    ("我叫孙八，干旅游的", "孙八", "旅游"),
    ("我是健身教练", "", "健身"),
    ("我做母婴用品", "", "母婴"),
]

# 交叉意图测试 - 第一轮输入（设置品牌/产品/话题）
CROSS_INTENT_FIRST = [
    ("推广华为手机", "华为", "手机"),
    ("小米电视推广", "小米", "电视"),
    ("推广比亚迪汽车", "比亚迪", "汽车"),
    ("OPPO手机营销", "OPPO", "手机"),
    ("vivo手机推广", "vivo", "手机"),
    ("荣耀产品营销", "荣耀", "产品"),
    ("一加手机推广", "一加", "手机"),
    ("realme手机营销", "realme", "手机"),
    ("三星手机推广", "三星", "手机"),
    ("苹果产品营销", "苹果", "产品"),
]

# 交叉意图测试 - 第二轮输入（追加信息）
CROSS_INTENT_SECOND = [
    "目标人群是年轻人",
    "针对白领用户",
    "面向学生群体",
    "主打性价比",
    "强调高品质",
    "突出创新特点",
    "针对女性用户",
    "面向高端市场",
    "主打年轻化",
    "注重实用性",
]

# 完整创作测试输入
CREATION_QUERIES = [
    "帮我写一个小红书种草文案，产品是降噪耳机",
    "生成一个抖音短视频脚本，关于奶茶店开业",
    "策划一个B站UP主合作方案",
    "写一个微信朋友圈推广文案，关于护肤品",
    "生成微博营销文案，关于新品手机",
    "帮我创作小红书笔记，关于咖啡机",
    "写抖音直播话术，关于服装促销",
    "生成B站视频创意，关于数码测评",
    "策划小红书营销方案，关于美妆产品",
    "写一个内容营销脚本，关于智能手表",
]

# 澄清流程测试输入（信息不完整）
CLARIFY_QUERIES = [
    "帮我推广",
    "写个文案",
    "生成内容",
    "做个营销",
    "帮我宣传",
]

# 热点插件测试
HOTSPOT_QUERIES = [
    ("看看b站热点", "bilibili_hotspot"),
    ("b站热门内容", "bilibili_hotspot"),
    ("抖音热门是什么", "douyin_hotspot"),
    ("抖音流量推荐", "douyin_hotspot"),
    ("小红书种草", "xiaohongshu_hotspot"),
    ("小红书热门笔记", "xiaohongshu_hotspot"),
]

# 诊断插件测试
DIAGNOSIS_QUERIES = [
    ("诊断账号问题", "account_diagnosis"),
    ("账号健康分析", "account_diagnosis"),
    ("预测点击率", "ctr_prediction"),
    ("点击率分析", "ctr_prediction"),
    ("预测视频爆款", "viral_prediction"),
    ("视频表现预测", "viral_prediction"),
]

# 生成插件测试
GENERATOR_QUERIES = [
    ("写文案", "text_generator"),
    ("生成文案", "text_generator"),
    ("推广方案", "campaign_plan_generator"),
    ("营销方案", "campaign_plan_generator"),
]

def get_random_item(items: list) -> any:
    return random.choice(items)

def get_user_id(prefix: str, index: int) -> str:
    """生成用户ID"""
    return f"{prefix}{index:03d}"
