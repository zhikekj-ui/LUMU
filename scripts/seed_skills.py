"""Seed built-in skills into skills.db, divided by space (work / personal).

Run on the server with the project venv:
    .venv/bin/python scripts/seed_skills.py

Idempotent by skill name; deletes the old db first for a clean re-seed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.manager import SkillManager

DATA_DIR = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data")
DB_PATH = os.path.join(DATA_DIR, "skills.db")

# 删除旧库，确保 space 字段干净重建
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

sm = SkillManager(db_path=DB_PATH)

SKILLS = [
    # ---------------- 工作空间 (work) ----------------
    dict(
        name="work_weekly_report", space="work",
        description="根据本周的工作记录/对话，生成结构化的周报（完成事项、进行中、风险与下周计划）。",
        tags="work,周报,汇报",
        content=(
            "## 工作周报生成\n\n"
            "1. 收集本周与用户的对话要点、完成的任务、产出文件。\n"
            "2. 按四类组织：✅ 本周完成 / 🔄 进行中 / ⚠️ 风险阻塞 / 📅 下周计划。\n"
            "3. 每条用「动作 + 结果 + 数据」写法，避免空话。\n"
            "4. 输出 Markdown，标题含日期范围；如用户给模板则套用模板。\n"
            "5. 不适合公开的内容用「详见内部文档」概括，不写敏感细节。"
        ),
    ),
    dict(
        name="meeting_minutes", space="work",
        description="把会议录音转写或聊天记录整理成纪要：决议、待办（负责人/截止）、遗留问题。",
        tags="work,会议,纪要,待办",
        content=(
            "## 会议纪要整理\n\n"
            "1. 通读原始记录，标出「谁说了什么结论」。\n"
            "2. 提取三部分：\n"
            "   - 会议决议（Decision）\n"
            "   - 行动项（Action：事项 / 负责人 / 截止时间）\n"
            "   - 开放问题（Open Issue）\n"
            "3. 用表格呈现行动项，缺失负责人/时间时显式标注「待确认」。\n"
            "4. 结尾给一句话「下次会议前需闭环的事项」。"
        ),
    ),
    dict(
        name="code_review", space="work",
        description="对给定代码做审查：正确性、可读性、性能、安全风险，并给出可落地的修改建议。",
        tags="work,code,review,代码",
        content=(
            "## 代码审查\n\n"
            "1. 先理解这段代码要解决的「问题」，而非只看实现。\n"
            "2. 分维度检查：\n"
            "   - 正确性：边界、空值、并发、异常处理\n"
            "   - 可读性：命名、函数粒度、是否过度设计\n"
            "   - 性能：N+1、重复计算、不必要的拷贝\n"
            "   - 安全：注入、越权、密钥硬编码、日志泄露\n"
            "3. 每条问题给「位置 + 现象 + 建议改法」，按严重程度排序。\n"
            "4. 最后给总体评价：可合并 / 需修改后合并 / 需重构。"
        ),
    ),
    dict(
        name="project_file_search", space="work",
        description="在工作区检索项目文件、定位关键代码或文档，并汇总结果。",
        tags="work,文件,检索,项目",
        content=(
            "## 项目文件检索\n\n"
            "1. 用 list_dir / search_files 在工作目录内检索关键词（函数名、类名、配置项）。\n"
            "2. 优先文本匹配，再结合语义判断相关性。\n"
            "3. 返回「文件路径 : 行号 : 摘要」列表，最多 20 条。\n"
            "4. 跨多个文件时，给出一张「模块 → 作用」的速览表，帮助用户快速定位。"
        ),
    ),
    dict(
        name="email_draft", space="work",
        description="根据要点起草专业工作邮件：汇报、申请、跟进、道歉等场景。",
        tags="work,邮件,沟通",
        content=(
            "## 工作邮件草稿\n\n"
            "1. 确认收件人关系与目的（告知/请求/确认/致歉）。\n"
            "2. 结构：主题行（动作+对象+时限）→ 开场 → 正文（结论先行）→ 行动呼吁 → 落款。\n"
            "3. 语气专业克制，避免模糊词（「尽快」改为具体日期）。\n"
            "4. 涉及多事项时用编号；敏感信息用「私下同步」替代明文。"
        ),
    ),
    dict(
        name="okr_breakdown", space="work",
        description="把模糊的目标拆解成可衡量的 O（目标）与 KR（关键结果），并排优先级。",
        tags="work,okr,目标,规划",
        content=(
            "## OKR / 目标拆解\n\n"
            "1. 澄清最终想达成的「状态」，而非任务列表。\n"
            "2. 写 1-3 个 Objective（鼓舞性、不堆指标）。\n"
            "3. 每个 O 配 2-4 个 KR：可量化、有基线、有终点值。\n"
            "4. 标注置信度与依赖；给出本周可启动的最小一步。\n"
            "5. 避免把「活动」当 KR（「写 10 篇文档」是活动，「文档带来 X 转化」才是结果）。"
        ),
    ),
    dict(
        name="requirement_doc", space="work",
        description="把一句话需求扩展成结构化的需求文档：背景、目标、范围、功能点、验收标准。",
        tags="work,需求,文档,prd",
        content=(
            "## 需求文档撰写\n\n"
            "1. 背景与问题：用户现在痛什么、为什么现在做。\n"
            "2. 目标与非目标：做哪些、明确不做哪些。\n"
            "3. 用户故事：「作为 X，我想 Y，以便 Z」。\n"
            "4. 功能点清单 + 优先级（P0/P1/P2）。\n"
            "5. 验收标准：可测试、可演示的 Done 定义。\n"
            "6. 风险与开放问题单列。"
        ),
    ),
    dict(
        name="competitor_analysis", space="work",
        description="针对一个产品/功能做竞品对比：维度选取、优劣势、差异化机会。",
        tags="work,竞品,分析,战略",
        content=(
            "## 竞品分析\n\n"
            "1. 锁定 2-4 个直接竞品，明确对比维度（定位、价格、核心功能、体验、生态）。\n"
            "2. 用对比表呈现，避免主观形容词，用事实/截图佐证。\n"
            "3. 归纳每个竞品的「强项 / 弱点 / 可借鉴点」。\n"
            "4. 给出我们的差异化切入点与建议优先级。\n"
            "5. 注明数据来源与时效，不编造数字。"
        ),
    ),

    # ---------------- 个人空间 (personal) ----------------
    dict(
        name="weekend_plan", space="personal",
        description="结合天气、预算和兴趣，规划一个松弛有度的周末安排。",
        tags="personal,周末,规划,生活",
        content=(
            "## 周末规划\n\n"
            "1. 先问清：几个人、预算区间、想宅还是想出门、有没有必须做的事。\n"
            "2. 查目的地/城市天气，给出「户外备选 + 室内备选」双方案。\n"
            "3. 时间切成三段（周六上午/下午/晚、周日上午/下午），每段 1 个主活动 + 1 个弹性项。\n"
            "4. 控制节奏：留足睡眠与发呆时间，别排满。\n"
            "5. 输出时间表 + 必带清单 + 预算估算。"
        ),
    ),
    dict(
        name="travel_plan", space="personal",
        description="做一份可执行的旅行计划：行程、交通、住宿、预算、行李与注意事项。",
        tags="personal,旅行,行程,攻略",
        content=(
            "## 旅行计划\n\n"
            "1. 确认：目的地、天数、人数、预算、偏好（美食/自然/人文/亲子）。\n"
            "2. 设计每日动线，遵循「同区集中、减少折返」原则。\n"
            "3. 给出交通方式（飞机/高铁/当地公交）、住宿选址建议（近地铁/景区）。\n"
            "4. 预算表：机票+住宿+餐饮+门票+购物+备用金。\n"
            "5. 行李清单（按天气）+ 必办事项（签证/疫苗/预约）+ 应急联系人。"
        ),
    ),
    dict(
        name="home_cooking", space="personal",
        description="按口味、食材和时长推荐家常菜，并附做法要点。",
        tags="personal,菜谱,做饭,生活",
        content=(
            "## 家常菜推荐\n\n"
            "1. 询问：想吃什么口味（辣/清淡/下饭）、手头有什么食材、多少时间、几人份。\n"
            "2. 推荐 2-3 道搭配合理的菜（有荤有素或一锅出）。\n"
            "3. 每道给：食材清单、关键步骤、火候要点、失败避坑。\n"
            "4. 优先「少油少步骤」的做法；注明可提前准备的部分。\n"
            "5. 新手友好：标注大概用时与难度。"
        ),
    ),
    dict(
        name="shopping_list", space="personal",
        description="把随口说的采购需求整理成分类购物清单，并估算预算。",
        tags="personal,购物,清单,生活",
        content=(
            "## 购物清单\n\n"
            "1. 把用户零散提到的物品汇总，按「生鲜 / 日用 / 数码 / 其他」分类。\n"
            "2. 合并重复项，标注数量与规格（如 2L 牛奶）。\n"
            "3. 标出「急需 / 可暂缓」，帮助控制预算。\n"
            "4. 估算小计，提示是否有大促节点可凑单。\n"
            "5. 输出可直接照着买的清单（可导出为文件）。"
        ),
    ),
    dict(
        name="health_diet", space="personal",
        description="结合目标（减脂/增肌/控糖）生成一周饮食计划与替代方案。",
        tags="personal,健康,饮食,减脂",
        content=(
            "## 健康饮食计划\n\n"
            "1. 确认目标（减脂/增肌/控糖/维持）、忌口、做饭条件。\n"
            "2. 按「蛋白质+复合碳水+蔬菜+好脂肪」搭每餐，给出一日三餐示例。\n"
            "3. 提供可替换食材库，避免单调。\n"
            "4. 标注大概热量区间与饮水建议；不推荐极端节食。\n"
            "5. 附「外食怎么点」的兜底方案。"
        ),
    ),
    dict(
        name="workout_plan", space="personal",
        description="按场地与水平制定可坚持的运动/健身计划，含热身与恢复。",
        tags="personal,运动,健身,计划",
        content=(
            "## 运动健身计划\n\n"
            "1. 确认：目标（增肌/减脂/塑形/健康）、场地（居家/健身房）、每周可练天数、有无伤病史。\n"
            "2. 设计分化（如 推/拉/腿 或 全身循环），每次含热身 5-10 分钟。\n"
            "3. 每个动作给组数×次数 + 要点，新手从空杆/自重起步。\n"
            "4. 安排休息日与拉伸/有氧，强调循序渐进。\n"
            "5. 给「今天没时间」的 15 分钟极简替代方案。"
        ),
    ),
    dict(
        name="family_accounting", space="personal",
        description="整理家庭收支，做月度开支分析与省钱建议。",
        tags="personal,记账,理财,家庭",
        content=(
            "## 家庭记账 / 月度开支分析\n\n"
            "1. 让用户粘贴账单或口述大额支出，按「固定/可变/冲动」分类。\n"
            "2. 生成月度收支表：收入、必要支出、弹性支出、结余率。\n"
            "3. 找出 Top3 可优化项（订阅、外卖、冲动消费）。\n"
            "4. 给出「信封预算」建议：把结余拆成储蓄/消费/应急三份。\n"
            "5. 提示设置自动转账储蓄，先存后花。"
        ),
    ),
    dict(
        name="reading_notes", space="personal",
        description="把读过的书/文章整理成结构化读书笔记与金句卡片。",
        tags="personal,读书,笔记,成长",
        content=(
            "## 读书笔记整理\n\n"
            "1. 让用户给出书名 + 几点感想或摘抄。\n"
            "2. 套用模板：一句话主旨 / 核心观点（3 条）/ 金句 / 我的行动。\n"
            "3. 提炼「可立刻用的一条」，避免只读不练。\n"
            "4. 同类书可归到主题书架，方便复习。\n"
            "5. 输出 Markdown，便于存进知识库反复看。"
        ),
    ),
    dict(
        name="schedule_reminder", space="personal",
        description="把待办与约定转成带时间的日程清单，并提示设置提醒。",
        tags="personal,日程,提醒,效率",
        content=(
            "## 日程与提醒生成\n\n"
            "1. 提取用户提到的「时间 + 事件」（如 周四交水电费、周六体检）。\n"
            "2. 按时间排序成清单，标注重要级。\n"
            "3. 对易忘事项建议提前一天/一小时提醒。\n"
            "4. 区分「一次性」与「周期性」（每周/每月）。\n"
            "5. 输出可复制的日程文本，并建议落到日历 App。"
        ),
    ),
    dict(
        name="gift_recommend", space="personal",
        description="按对象、场合、预算推荐礼物，并说明理由。",
        tags="personal,礼物,推荐,生活",
        content=(
            "## 礼物推荐\n\n"
            "1. 问清：送给谁（关系/年龄/喜好）、场合、预算、是否当面送。\n"
            "2. 给 3 个梯度选项（实惠/适中/用心），各附「为什么合适」。\n"
            "3. 避开踩雷（对方忌讳、预算失衡）。\n"
            "4. 附赠「包装/贺卡」小建议，提升心意。\n"
            "5. 如时间紧，优先「可当天送达」的选项。"
        ),
    ),
    dict(
        name="parenting_routine", space="personal",
        description="给家长做宝宝作息表、辅食安排与早教游戏建议。",
        tags="personal,育儿,辅食,作息",
        content=(
            "## 育儿作息 / 辅食\n\n"
            "1. 确认宝宝月龄、作息现状、过敏史。\n"
            "2. 给一日作息表：睡眠/喂奶或辅食/玩耍时段。\n"
            "3. 按月龄给辅食清单（新增食物单一引入、观察 3 天）。\n"
            "4. 提供适龄早教游戏（大运动/精细动作/语言）。\n"
            "5. 强调个体差异，异常及时就医，不做诊断。"
        ),
    ),
    dict(
        name="finance_basics", space="personal",
        description="用大白话讲清个人理财入门：应急金、保险、基金定投与避坑。",
        tags="personal,理财,投资,入门",
        content=(
            "## 个人理财入门规划\n\n"
            "1. 先建应急金（3-6 个月开支），再谈投资。\n"
            "2. 基础保障：医保 + 意外/重疾险，先大人后小孩。\n"
            "3. 投资用「指数基金定投」降低择时风险，解释复利与分散。\n"
            "4. 明确避坑：高息理财、加杠杆、跟风炒币。\n"
            "5. 给可执行的第一步（开账户/设自动投/记账），不荐具体代码。"
        ),
    ),
    dict(
        name="mood_journal", space="personal",
        description="引导用户写情绪日记，梳理感受与触发点，给出舒缓建议。",
        tags="personal,情绪,日记,心理",
        content=(
            "## 情绪日记\n\n"
            "1. 用温柔提问引导：今天发生了什么、你感受到什么、身体哪里紧。\n"
            "2. 帮用户给情绪命名（焦虑/委屈/愤怒/空虚），不评判。\n"
            "3. 找触发点：「是什么让情绪上来」。\n"
            "4. 给一个可立刻做的小安抚（呼吸/散步/写下来）。\n"
            "5. 严重持续低落时，温和建议寻求专业帮助，不替代医疗。"
        ),
    ),
    dict(
        name="media_recommend", space="personal",
        description="按口味推荐书单/影单，并附一句话推荐理由。",
        tags="personal,书单,影单,推荐",
        content=(
            "## 书单 / 影单推荐\n\n"
            "1. 问清口味（类型/ mood：想哭/想燃/想放松）、近期看过的喜好。\n"
            "2. 给 3-5 个推荐，标注类型与一句话理由。\n"
            "3. 区分「短平快」与「值得沉浸」两类。\n"
            "4. 避免剧透关键情节。\n"
            "5. 可做成主题合集（如「雨天窝沙发片单」）。"
        ),
    ),
]


def main():
    count = 0
    for s in SKILLS:
        sm.save(s["name"], s["description"], s["content"], s["tags"], s["space"])
        count += 1
    print(f"Seeded {count} skills ({sum(1 for s in SKILLS if s['space']=='work')} work, "
          f"{sum(1 for s in SKILLS if s['space']=='personal')} personal).")


if __name__ == "__main__":
    main()
