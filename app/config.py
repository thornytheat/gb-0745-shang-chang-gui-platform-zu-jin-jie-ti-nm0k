from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {"mall": "北馆十一月", "clean": "南馆核对样例", "gap": "西馆补签空档"}
DEFAULT_PERIOD = "2026-11"
RULE_VERSION = "rent-1.1"
MISSING = {"", "-", "N/A", "NULL", "未知"}
MAX_SOURCE_BYTES = 256 * 1024
MAX_SECTION_ROWS = 1000
# 合同到期后仍营业的空档，最多顺延上一版条款暂估多少天。
# 超过该窗口说明柜台可能已停业或合同长期缺失，不能继续凭空暂估。
PROVISIONAL_MAX_DAYS = 31
