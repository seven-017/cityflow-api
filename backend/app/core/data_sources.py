from enum import StrEnum


class DataSource(StrEnum):
    """一条记录是"从哪来的"，只有两种可能。

    这不是个普通分类字段 —— 它决定"这条记录能不能改"。
    整个项目所有写接口的第一道闸门都是拿它比的。

    REAL_PUBLIC
        纽约市开放数据平台（AMPS）导进来的。代表"已经发生过的事"，
        业务接口一条都不许改（不许分派、不许流转、不许加处理记录）。
        文档里写得很硬：原始文件不可修改，而且所有转换结果都得能追溯到
        source_record_id —— 这也是 work_order_labor.source_record_id 那一列
        为什么是 NOT NULL。

    SYNTHETIC_PLATFORM
        平台用户自己录的，能改。

    有一个地方特别容易踩：data_source 这一列在模型上带着默认值
    （default="REAL_PUBLIC"）。也就是说平台自己建的记录，
    要是构造对象时忘了显式写 SYNTHETIC_PLATFORM，数据库会默默给它
    REAL_PUBLIC —— 于是这条记录变成"谁都不许改"，而且不报任何错。
    所以每个写接口都要显式写出目标数据源，别指望默认值。

    为什么用 StrEnum 而不是两个裸字符串：跟 RoleCode / PermissionCode
    一个道理 —— 拼错是 AttributeError 当场炸，不会悄悄变成另一个值。
    它同时还是 str 的子类，所以直接拿去跟数据库里读出来的字符串比较没问题。

    （这两个值原来是 services/work_orders.py 里的两个模块级字符串常量。
    2026-10-02 挪到 core 来，因为 labor 的写接口也要用，
    而 labor 不该反过来依赖 work_orders 那个模块 ——
    双数据源是个跨模块的领域概念，不是工单私有的。）
    """

    REAL_PUBLIC = "REAL_PUBLIC"
    SYNTHETIC_PLATFORM = "SYNTHETIC_PLATFORM"
