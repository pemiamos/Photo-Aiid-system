#!/usr/bin/env python3
"""一次性迁移：把历史投稿的「特别标注」(content_label) 回填进 tags 标签数组。

复用 backend.intake._merge_label_into_tags，保证与新提交逻辑完全一致。
幂等：重复运行不会重复写入（去重 + 已合并则跳过）。

用法（项目根目录）：
    .venv-build/bin/python scripts/backfill_label_tags.py [--db backend/photo_aiid.db] [--dry-run]
"""
import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from intake import _merge_label_into_tags  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "backend", "photo_aiid.db"))
    ap.add_argument("--dry-run", action="store_true", help="只打印将要变更，不写库")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content_label, tags FROM submission_files"
    ).fetchall()

    changed = 0
    for r in rows:
        new_tags = _merge_label_into_tags(r["content_label"], r["tags"])
        if new_tags != r["tags"]:
            changed += 1
            print(f"#{r['id']}: label={r['content_label']!r}  "
                  f"{r['tags']!r} -> {new_tags!r}")
            if not args.dry_run:
                conn.execute(
                    "UPDATE submission_files SET tags = ? WHERE id = ?",
                    (new_tags, r["id"]),
                )

    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"\n共 {len(rows)} 条，{'将更新' if args.dry_run else '已更新'} {changed} 条"
          f"{'（dry-run，未写库）' if args.dry_run else ''}。")


if __name__ == "__main__":
    main()
