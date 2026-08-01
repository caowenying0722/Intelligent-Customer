import os
from utils.logger_handler import logger
from langchain_core.tools import tool

from rag.rag_service import RagSummarizeService
import random
from utils.config_handler import agent_conf
from utils.path_tool import get_abs_path
from datetime import datetime

rag = RagSummarizeService()

user_ids = ["1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1010",]

external_data = {}

# 城市天气数据库
WEATHER_DATA = {
    "深圳": {"天气": "晴天", "气温": 28, "湿度": 65, "风向": "南风", "风速": 2, "AQI": 35, "降雨": "极低"},
    "合肥": {"天气": "多云", "气温": 24, "湿度": 55, "风向": "东风", "风速": 1, "AQI": 42, "降雨": "低"},
    "杭州": {"天气": "小雨", "气温": 22, "湿度": 75, "风向": "西南风", "风速": 3, "AQI": 38, "降雨": "中"},
    "北京": {"天气": "晴天", "气温": 20, "湿度": 45, "风向": "北风", "风速": 2, "AQI": 28, "降雨": "极低"},
    "上海": {"天气": "多云", "气温": 25, "湿度": 70, "风向": "东风", "风速": 1, "AQI": 45, "降雨": "低"},
}

# 默认城市天气数据
DEFAULT_WEATHER = {"天气": "晴天", "气温": 26, "湿度": 50, "风向": "南风", "风速": 1, "AQI": 21, "降雨": "极低"}


@tool
def rag_summarize(query: str) -> str:
    """从向量存储中检索参考资料"""
    return rag.rag_summarize(query)


@tool
def get_weather(city: str) -> str:
    """获取指定城市的天气，以消息字符串的形式返回"""
    # 如果城市在数据库中，使用对应数据；否则使用默认天气
    weather_info = WEATHER_DATA.get(city, DEFAULT_WEATHER)

    return f"城市{city}天气为{weather_info['天气']}，气温{weather_info['气温']}摄氏度，空气湿度{weather_info['湿度']}%，{weather_info['风向']}{weather_info['风速']}级，AQI{weather_info['AQI']}，最近6小时降雨概率{weather_info['降雨']}"


@tool
def get_user_location() -> str:
    """获取用户所在城市的名称，以纯字符串形式返回"""
    return random.choice(["深圳", "合肥", "杭州"])


@tool
def get_user_id() -> str:
    """获取用户的ID，以纯字符串形式返回"""
    return random.choice(user_ids)


@tool
def get_current_month() -> str:
    """获取当前月份，以纯字符串形式返回"""
    return datetime.now().strftime("%Y-%m")


def generate_external_data():
    """
    {
        "user_id": {
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            ...
        },
        "user_id": {
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            ...
        },
        "user_id": {
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            ...
        },
        ...
    }
    :return:
    """
    if not external_data:
        external_data_path = get_abs_path(agent_conf["external_data_path"])

        if not os.path.exists(external_data_path):
            raise FileNotFoundError(f"外部数据文件{external_data_path}不存在")

        with open(external_data_path, "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                arr: list[str] = line.strip().split(",")

                user_id: str = arr[0].replace('"', "")
                feature: str = arr[1].replace('"', "")
                efficiency: str = arr[2].replace('"', "")
                consumables: str = arr[3].replace('"', "")
                comparison: str = arr[4].replace('"', "")
                time: str = arr[5].replace('"', "")

                if user_id not in external_data:
                    external_data[user_id] = {}

                external_data[user_id][time] = {
                    "特征": feature,
                    "效率": efficiency,
                    "耗材": consumables,
                    "对比": comparison,
                }


@tool
def fetch_external_data(user_id: str, month: str) -> str:
    """从外部系统中获取指定用户在指定月份的使用记录，以纯字符串形式返回，如果未检索到返回空字符串"""
    generate_external_data()

    try:
        return external_data[user_id][month]
    except KeyError:
        logger.warning(f"[fetch_external_data]未能检索到用户：{user_id}在{month}的使用记录数据")
        return ""

@tool
def fill_context_for_report() -> str:
    """无入参，调用后触发为报告生成的场景动态注入上下文信息"""
    return "fill_context_for_report已调用"
