"""
VEXIS バージョン別開発時期推定スクリプト

親フォルダ内の全サブフォルダについて、ファイル更新日時を解析し、
開発期間を推定します。

使い方:
    1. このスクリプトを親フォルダに配置
    2. python collect_version_dates.py を実行
    3. 同じ階層にあるすべてのサブフォルダを自動検出して解析
"""

import os
from datetime import datetime
from pathlib import Path

# 除外するフォルダ名（これらはスキャン対象外）
EXCLUDE_FOLDERS = [
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".idea",
    ".vscode",
]

# 除外するファイルパターン
EXCLUDE_FILE_PATTERNS = [
    ".pyc",
    ".DS_Store",
    "Thumbs.db",
]


def should_exclude_folder(folder_name: str) -> bool:
    """フォルダを除外すべきか判定"""
    return folder_name in EXCLUDE_FOLDERS


def should_exclude_file(file_path: Path) -> bool:
    """ファイルを除外すべきか判定"""
    for pattern in EXCLUDE_FILE_PATTERNS:
        if pattern in str(file_path):
            return True
    return False


def get_file_stats(folder_path: Path) -> dict:
    """フォルダ内の全ファイルの更新日時を収集"""
    stats = {
        "files": [],
        "earliest": None,
        "latest": None,
        "file_count": 0,
    }
    
    if not folder_path.exists():
        return stats
    
    for root, dirs, files in os.walk(folder_path):
        # 除外フォルダをスキップ
        dirs[:] = [d for d in dirs if not should_exclude_folder(d)]
        
        for file in files:
            file_path = Path(root) / file
            if should_exclude_file(file_path):
                continue
            
            try:
                mtime = os.path.getmtime(file_path)
                mtime_dt = datetime.fromtimestamp(mtime)
                
                stats["files"].append({
                    "path": str(file_path.relative_to(folder_path)),
                    "modified": mtime_dt,
                })
                
                if stats["earliest"] is None or mtime_dt < stats["earliest"]:
                    stats["earliest"] = mtime_dt
                if stats["latest"] is None or mtime_dt > stats["latest"]:
                    stats["latest"] = mtime_dt
                    
                stats["file_count"] += 1
                
            except (OSError, PermissionError):
                continue
    
    return stats


def get_subfolders(parent_dir: Path) -> list:
    """親フォルダ内のサブフォルダを取得（除外対象を除く）"""
    subfolders = []
    for item in parent_dir.iterdir():
        if item.is_dir() and not should_exclude_folder(item.name):
            subfolders.append(item)
    # フォルダ名でソート
    return sorted(subfolders, key=lambda x: x.name.lower())


def main():
    script_dir = Path(__file__).parent
    
    print("=" * 60)
    print("開発時期推定スクリプト")
    print(f"対象: {script_dir}")
    print("=" * 60)
    print()
    
    # 親フォルダ内のすべてのサブフォルダを自動検出
    subfolders = get_subfolders(script_dir)
    
    if not subfolders:
        print("サブフォルダが見つかりませんでした。")
        return
    
    print(f"検出したフォルダ: {len(subfolders)}個\n")
    
    results = []
    
    for folder_path in subfolders:
        folder_name = folder_path.name
        stats = get_file_stats(folder_path)
        
        if stats["file_count"] == 0:
            print(f"[{folder_name}] ファイルがありません（スキップ）")
            continue
        
        results.append({
            "folder": folder_name,
            "stats": stats,
        })
        
        print(f"[{folder_name}]")
        print(f"  ファイル数: {stats['file_count']}")
        print(f"  最古の更新: {stats['earliest'].strftime('%Y-%m-%d %H:%M')}")
        print(f"  最新の更新: {stats['latest'].strftime('%Y-%m-%d %H:%M')}")
        
        # 開発期間を推定
        if stats["earliest"] and stats["latest"]:
            duration = stats["latest"] - stats["earliest"]
            print(f"  開発期間:   約{duration.days}日間")
        print()
    
    # サマリー表（最古の更新日順でソート）
    if results:
        results_sorted = sorted(results, key=lambda x: x["stats"]["earliest"] or datetime.max)
        
        print("=" * 60)
        print("サマリー（開発開始日順）")
        print("=" * 60)
        print()
        print("| フォルダ名 | 開発開始推定 | 開発終了推定 | ファイル数 |")
        print("|------------|--------------|--------------|------------|")
        for r in results_sorted:
            s = r["stats"]
            start = s["earliest"].strftime("%Y-%m-%d") if s["earliest"] else "-"
            end = s["latest"].strftime("%Y-%m-%d") if s["latest"] else "-"
            print(f"| {r['folder'][:20]:<20} | {start} | {end} | {s['file_count']:>10} |")
    
    # 詳細ログ出力（オプション）
    output_detail = input("\n詳細ファイルリストを出力しますか? (y/N): ").strip().lower()
    if output_detail == "y":
        output_path = script_dir / "version_dates_detail.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            for r in results_sorted:
                f.write(f"\n{'='*40}\n")
                f.write(f"{r['folder']}\n")
                f.write(f"{'='*40}\n")
                # 更新日時でソート
                sorted_files = sorted(r["stats"]["files"], key=lambda x: x["modified"])
                for file_info in sorted_files:
                    f.write(f"{file_info['modified'].strftime('%Y-%m-%d %H:%M')} | {file_info['path']}\n")
        print(f"詳細を {output_path} に出力しました")


if __name__ == "__main__":
    main()
