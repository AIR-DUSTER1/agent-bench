"""生成演示业务数据库 seed/demo.db（sql_query 工具的数据源）。幂等：重建。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "demo.db"

SCHEMA = """
DROP TABLE IF EXISTS sales; DROP TABLE IF EXISTS products; DROP TABLE IF EXISTS employees;
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL, stock INTEGER);
CREATE TABLE sales (id INTEGER PRIMARY KEY, product_id INTEGER, region TEXT,
                    amount REAL, quantity INTEGER, sale_date TEXT);
CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, department TEXT, title TEXT, hire_date TEXT);
"""

PRODUCTS = [
    (1, "智能音箱 Pro X", "智能硬件", 899.0, 320),
    (2, "智能音箱 Mini", "智能硬件", 299.0, 850),
    (3, "无线充电底座", "配件", 129.0, 60),
    (4, "防尘网罩", "配件", 59.0, 980),
    (5, "智能门锁 S2", "智能家居", 1599.0, 45),
]
SALES = [
    # (product_id, region, amount, quantity, sale_date)  2024 年数据
    (1, "华东", 251720.0, 280, "2024-01-15"),
    (1, "华南", 107880.0, 120, "2024-03-02"),
    (1, "华北", 89890.0, 100, "2024-07-21"),
    (2, "华东", 59700.0, 200, "2024-02-11"),
    (2, "西南", 29900.0, 100, "2024-05-18"),
    (3, "华东", 6450.0, 50, "2024-04-09"),
    (4, "华南", 2360.0, 40, "2024-06-30"),
    (5, "华北", 159900.0, 100, "2024-08-25"),
    (5, "华东", 319800.0, 200, "2024-10-12"),
    (5, "华南", 79950.0, 50, "2024-12-03"),
    (1, "华东", 89900.0, 100, "2024-11-20"),
    (2, "华北", 44850.0, 150, "2024-09-14"),
]
EMPLOYEES = [
    (1, "李明", "研发部", "高级工程师", "2021-03-15"),
    (2, "王芳", "市场部", "市场经理", "2020-07-01"),
    (3, "张伟", "客服部", "客服专员", "2023-01-09"),
    (4, "赵静", "财务部", "财务主管", "2019-05-20"),
    (5, "陈强", "研发部", "架构师", "2018-11-11"),
    (6, "刘洋", "市场部", "专员", "2024-02-26"),
]


def main() -> None:
    conn = sqlite3.connect(DB)
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?)", PRODUCTS)
        conn.executemany("INSERT INTO sales VALUES (?,?,?,?,?,?)",
                         [(i + 1, *s) for i, s in enumerate(SALES)])
        conn.executemany("INSERT INTO employees VALUES (?,?,?,?,?)", EMPLOYEES)
        conn.commit()
        print(f"demo.db 已生成：products={len(PRODUCTS)} sales={len(SALES)} employees={len(EMPLOYEES)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
