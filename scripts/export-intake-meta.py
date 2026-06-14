#!/usr/bin/env python3
"""
导出某本书的投稿 / 版权授权记录为 CSV，供归档进 {书}/_meta/submissions.csv。

用法：
    python3 scripts/export-intake-meta.py --book 2026-sanxia --db backend/photo_aiid.db \
        --out submissions.csv

原图与授权记录同存归档，是图书出版的版权举证依据（见 PRD 第 3.2 / 第 6 章）。
"""

import argparse
import csv
import sqlite3
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="2026-sanxia", help="书目代号")
    ap.add_argument("--db", default="backend/photo_aiid.db", help="SQLite 数据库路径")
    ap.add_argument("--out", default="-", help="输出 CSV 路径（- 表示标准输出）")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT p.invite_code, p.name, p.contact,
               sf.content_label, sf.file_name, sf.object_key, sf.file_size,
               s.license_at, sf.created_at
        FROM submission_files sf
        JOIN submissions s   ON sf.submission_id = s.id
        JOIN photographers p ON s.photographer_id = p.id
        WHERE p.book_code = ?
        ORDER BY p.invite_code, sf.content_label, sf.file_name
        """,
        (args.book,),
    ).fetchall()
    conn.close()

    def ts(v):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(v)) if v else ""

    out = sys.stdout if args.out == "-" else open(args.out, "w", newline="", encoding="utf-8-sig")
    w = csv.writer(out)
    w.writerow(
        ["投稿码", "姓名", "联系方式", "内容标注", "文件名",
         "object_key", "大小(字节)", "授权时间", "上传时间"]
    )
    for r in rows:
        w.writerow(
            [r["invite_code"], r["name"], r["contact"] or "", r["content_label"],
             r["file_name"], r["object_key"], r["file_size"],
             ts(r["license_at"]), ts(r["created_at"])]
        )
    if out is not sys.stdout:
        out.close()
    sys.stderr.write(f"已导出 {len(rows)} 条记录（书目 {args.book}）\n")


if __name__ == "__main__":
    main()
