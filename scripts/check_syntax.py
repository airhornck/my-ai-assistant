"""
项目语法与冲突检测：
1. 遍历 .py 做 ast 语法检查
2. 导入 main 检测循环依赖
3. 扫描 main.py 路由，检查路径是否重复
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_syntax():
    errs = []
    for p in sorted(ROOT.rglob("*.py")):
        if "venv" in str(p) or "__pycache__" in str(p):
            continue
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errs.append((str(rel), e.lineno, e.msg))
    return errs


def check_main_import():
    sys.path.insert(0, str(ROOT))
    try:
        import main as _main  # noqa: F401
        return None
    except Exception as e:
        return str(e)


def check_routes():
    main_py = ROOT / "main.py"
    text = main_py.read_text(encoding="utf-8")
    pattern = r'@app\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
    routes = re.findall(pattern, text)
    seen = {}
    dup = []
    for method, path in routes:
        key = f"{method.upper()} {path}"
        if key in seen:
            dup.append(key)
        seen[key] = True
    return dup, list(seen.keys())


def main():
    failed = False

    # 1. 语法
    errs = check_syntax()
    if errs:
        failed = True
        for f, ln, msg in errs:
            print(f"SYNTAX {f}:{ln} {msg}")
    else:
        print("OK: 所有 .py 语法检查通过")

    # 2. 导入 main
    imp_err = check_main_import()
    if imp_err:
        failed = True
        print(f"IMPORT main: {imp_err}")
    else:
        print("OK: main 导入通过（无循环依赖）")

    # 3. 路由重复
    dup, all_routes = check_routes()
    if dup:
        failed = True
        for key in dup:
            print(f"ROUTE 重复: {key}")
    else:
        print("OK: 路由无重复")
        print(f"    共 {len(all_routes)} 个路由: {sorted(all_routes)[:5]}{'...' if len(all_routes) > 5 else ''}")

    if failed:
        return 1
    print("\n全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
