"""
Repository analyzer — scans, reads, and summarizes team code repos.

Pipeline:
    1. clone_repo()      — git clone --depth 1 (or pull if already cloned)
    2. scan_structure()   — walk directory, detect languages/frameworks/entry points
    3. read_key_files()   — read up to 50 key files (500 lines max each), prioritized by relevance
    4. scan_all_symbols() — extract function/class names from ALL source files (full repo)
    5. analyze_repo()     — combines 2+3+4 into a structured dict for LLM evaluation

Skips: .git, node_modules, __pycache__, binaries, images, lock files.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from collections import Counter

logger = logging.getLogger("jurybot.repo")

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea",
    ".vscode", "dist", "build", ".next", ".nuxt", "target", ".gradle",
}

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".lock", ".min.js", ".min.css", ".map",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".sqlite", ".db",
}

LANGUAGE_MAP = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript (React)", ".jsx": "JavaScript (React)",
    ".java": "Java", ".kt": "Kotlin", ".go": "Go",
    ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".cpp": "C++", ".c": "C", ".h": "C/C++ Header",
    ".swift": "Swift", ".dart": "Dart",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sql": "SQL", ".sh": "Shell", ".bat": "Batch",
    ".yml": "YAML", ".yaml": "YAML", ".json": "JSON",
    ".toml": "TOML", ".xml": "XML", ".md": "Markdown",
}

ENTRY_POINT_NAMES = {
    "main.py", "app.py", "server.py", "index.py", "manage.py",
    "main.ts", "index.ts", "server.ts", "app.ts",
    "main.js", "index.js", "server.js", "app.js",
    "Main.java", "App.java",
    "main.go", "main.rs",
    "Program.cs",
}

FRAMEWORK_FILES = {
    "package.json": "Node.js",
    "requirements.txt": "Python",
    "Pipfile": "Python (Pipenv)",
    "pyproject.toml": "Python",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "pubspec.yaml": "Dart/Flutter",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    "Dockerfile": "Docker",
}


async def clone_repo(url: str, target_dir: str) -> str:
    """Git clone a repo to target_dir. Return local path.
    Uses subprocess.run in a thread to avoid Windows asyncio subprocess issues."""
    import subprocess

    target = Path(target_dir)
    if target.exists():
        logger.info("clone_repo: Repo existiert bereits, git pull in %s", target)
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["git", "-C", str(target), "pull"],
                capture_output=True, timeout=60,
            ),
        )
        logger.debug("clone_repo: git pull returncode=%d stdout=%s stderr=%s",
            result.returncode, result.stdout.decode()[:200], result.stderr.decode()[:200])
        return str(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    logger.info("clone_repo: git clone --depth 1 %s → %s", url, target)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            ["git", "clone", "--depth", "1", url, str(target)],
            capture_output=True, timeout=120,
        ),
    )
    if result.returncode != 0:
        stderr = result.stderr.decode()
        logger.error("clone_repo: git clone FEHLGESCHLAGEN (rc=%d): %s", result.returncode, stderr)
        raise RuntimeError(f"git clone failed: {stderr}")
    logger.info("clone_repo: Clone erfolgreich → %s", target)
    return str(target)


async def scan_structure(repo_path: str) -> dict:
    """Walk the repo directory and return structure metadata."""
    root = Path(repo_path)
    file_tree = []
    lang_counter: Counter = Counter()
    frameworks = set()
    entry_points = []
    total_lines = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip ignored dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = Path(dirpath).relative_to(root)

        for fname in filenames:
            rel_path = str(rel_dir / fname) if str(rel_dir) != "." else fname
            ext = Path(fname).suffix.lower()

            if ext in SKIP_EXTENSIONS:
                continue

            file_tree.append(rel_path)

            if ext in LANGUAGE_MAP:
                lang_counter[LANGUAGE_MAP[ext]] += 1

            if fname in ENTRY_POINT_NAMES:
                entry_points.append(rel_path)

            if fname in FRAMEWORK_FILES:
                frameworks.add(FRAMEWORK_FILES[fname])

            # Rough line count
            full_path = Path(dirpath) / fname
            try:
                total_lines += sum(1 for _ in open(full_path, "r", encoding="utf-8", errors="ignore"))
            except (OSError, UnicodeDecodeError):
                pass

    # Detect frameworks from config file contents
    frameworks_from_content = await _detect_frameworks_from_files(root)
    frameworks.update(frameworks_from_content)

    return {
        "file_tree": sorted(file_tree),
        "languages": dict(lang_counter.most_common()),
        "frameworks": sorted(frameworks),
        "entry_points": entry_points,
        "total_files": len(file_tree),
        "total_lines": total_lines,
    }


async def _detect_frameworks_from_files(root: Path) -> set:
    """Read config files to detect specific frameworks."""
    detected = set()

    # package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            import json
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
            all_deps = {}
            all_deps.update(data.get("dependencies", {}))
            all_deps.update(data.get("devDependencies", {}))
            framework_markers = {
                "react": "React", "next": "Next.js", "vue": "Vue.js",
                "nuxt": "Nuxt.js", "angular": "Angular", "svelte": "Svelte",
                "express": "Express.js", "fastify": "Fastify", "nestjs": "NestJS",
                "@nestjs/core": "NestJS", "tailwindcss": "Tailwind CSS",
            }
            for dep, name in framework_markers.items():
                if dep in all_deps:
                    detected.add(name)
        except Exception:
            pass

    # requirements.txt
    req_txt = root / "requirements.txt"
    if req_txt.exists():
        try:
            content = req_txt.read_text(encoding="utf-8", errors="ignore").lower()
            req_markers = {
                "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
                "streamlit": "Streamlit", "gradio": "Gradio",
                "sqlalchemy": "SQLAlchemy", "pandas": "pandas",
                "torch": "PyTorch", "tensorflow": "TensorFlow",
            }
            for marker, name in req_markers.items():
                if marker in content:
                    detected.add(name)
        except Exception:
            pass

    # pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
            for marker in ["fastapi", "flask", "django"]:
                if marker in content:
                    detected.add(marker.capitalize() if marker != "fastapi" else "FastAPI")
        except Exception:
            pass

    return detected


async def read_key_files(repo_path: str, structure: dict) -> dict:
    """Read the most important files for evaluation.
    Returns dict of filepath -> content. Max 50 files, max 500 lines each.
    """
    root = Path(repo_path)
    files_to_read: list[str] = []

    file_tree = structure["file_tree"]

    # 1. README
    for name in ["README.md", "README", "readme.md", "Readme.md"]:
        if name in file_tree:
            files_to_read.append(name)

    # 2. Entry points
    for ep in structure["entry_points"]:
        if ep not in files_to_read:
            files_to_read.append(ep)

    # 3. Config files
    config_names = {
        "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
        ".env.example", "package.json", "requirements.txt",
        "pyproject.toml", "Cargo.toml", "go.mod", "tsconfig.json",
        "vite.config.ts", "vite.config.js", "next.config.js",
        "webpack.config.js",
    }
    for f in file_tree:
        if Path(f).name in config_names and f not in files_to_read:
            files_to_read.append(f)

    # 4. API routes / endpoints / controllers
    route_dirs = {"routes", "api", "endpoints", "controllers", "routers", "views"}
    for f in file_tree:
        parts = Path(f).parts
        if any(p.lower() in route_dirs for p in parts):
            if f not in files_to_read:
                files_to_read.append(f)

    # 5. Database models / schemas
    model_dirs = {"models", "schemas", "database", "entities", "domain"}
    for f in file_tree:
        parts = Path(f).parts
        if any(p.lower() in model_dirs for p in parts):
            if f not in files_to_read:
                files_to_read.append(f)

    # 6. Tests
    test_dirs = {"test", "tests", "__tests__", "spec"}
    for f in file_tree:
        parts = Path(f).parts
        if any(p.lower() in test_dirs for p in parts):
            if f not in files_to_read:
                files_to_read.append(f)

    # 7. Fill remaining slots with other source files (skip binary/config already added)
    source_exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".rb", ".php", ".cs", ".cpp", ".c"}
    for f in file_tree:
        if len(files_to_read) >= 50:
            break
        ext = Path(f).suffix.lower()
        if ext in source_exts and f not in files_to_read:
            files_to_read.append(f)

    # Trim to 50
    files_to_read = files_to_read[:50]

    # Read contents
    result = {}
    for rel_path in files_to_read:
        full_path = root / rel_path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            if len(lines) > 500:
                lines = lines[:500]
                lines.append(f"\n... [TRUNCATED — {len(content.splitlines())} lines total]")
            result[rel_path] = "\n".join(lines)
        except (OSError, UnicodeDecodeError):
            pass

    return result


_SYMBOL_PATTERNS = [
    # Python: def func_name(  /  class ClassName
    re.compile(r'^\s*def\s+(\w+)\s*\('),
    re.compile(r'^\s*class\s+(\w+)'),
    # JS/TS: function funcName(  /  export function  /  export default function
    re.compile(r'^\s*(?:export\s+(?:default\s+)?)?function\s+(\w+)\s*\('),
    # JS/TS: const funcName = (  /  export const funcName =
    re.compile(r'^\s*(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\('),
    # JS/TS arrow: const Component = () =>  /  const handler = async () =>
    re.compile(r'^\s*(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>'),
    # Java/C#/Go: public void methodName(  /  func methodName(
    re.compile(r'^\s*(?:public|private|protected|static|async|func)\s+\w*\s*(\w+)\s*\('),
    # React component: export default function Component(  — already covered above
    # Go: type StructName struct
    re.compile(r'^\s*type\s+(\w+)\s+struct'),
    # Rust: fn func_name(  /  struct StructName  /  impl TraitName
    re.compile(r'^\s*(?:pub\s+)?fn\s+(\w+)\s*[<(]'),
    re.compile(r'^\s*(?:pub\s+)?struct\s+(\w+)'),
]

# Skip trivial/boilerplate symbol names
_SKIP_SYMBOLS = {
    "__init__", "main", "setUp", "tearDown", "setup", "teardown",
    "constructor", "render", "toString", "equals", "hashCode",
}

SOURCE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".rb", ".php", ".cs", ".cpp", ".c"}


def scan_all_symbols(repo_path: str, file_tree: list[str]) -> list[dict]:
    """Scan ALL source files in repo for function/class names.
    Returns list of {name, file, line} dicts — the complete code index."""
    root = Path(repo_path)
    symbols = []

    for rel_path in file_tree:
        ext = Path(rel_path).suffix.lower()
        if ext not in SOURCE_EXTS:
            continue

        full_path = root / rel_path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for line_no, line in enumerate(content.splitlines(), 1):
            for pat in _SYMBOL_PATTERNS:
                m = pat.match(line)
                if m:
                    name = m.group(1)
                    if name not in _SKIP_SYMBOLS and len(name) > 2:
                        symbols.append({
                            "name": name,
                            "file": rel_path,
                            "line": line_no,
                        })
                    break  # one match per line

    return symbols


def build_evidence_report(repo_path: str, structure: dict, key_files: dict, all_symbols: list[dict] | None = None) -> dict:
    """Extract structured facts from a repo without LLM involvement.
    Returns a dict of evidence sections that can be fed to the LLM
    instead of (or alongside) raw code."""

    # --- 1. readme_claims ---
    readme_claims = []
    readme_content = ""
    for name in ["README.md", "readme.md", "Readme.md", "README"]:
        if name in key_files:
            readme_content = key_files[name]
            break
    if readme_content:
        for line in readme_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("- ") or stripped.startswith("* "):
                readme_claims.append(stripped)
                if len(readme_claims) >= 30:
                    break

    # --- 2. endpoints ---
    endpoints = []
    route_patterns = [
        # Python: @app.get("/path") / @router.post("/path")
        re.compile(r'@(?:app|router)\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']'),
        # Python: @app.route("/path", methods=["GET"])
        re.compile(r'@(?:app|router)\.route\(\s*["\']([^"\']+)["\'](?:.*?methods\s*=\s*\[([^\]]+)\])?'),
        # JS/TS: app.get("/path", ...) / router.post("/path", ...)
        re.compile(r'(?:app|router)\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']'),
    ]
    for filepath, content in key_files.items():
        ext = Path(filepath).suffix.lower()
        if ext not in (".py", ".js", ".ts", ".tsx", ".jsx"):
            continue
        for line in content.splitlines():
            for pat in route_patterns:
                m = pat.search(line)
                if m:
                    groups = m.groups()
                    if len(groups) == 2 and groups[0] in ("get", "post", "put", "delete", "patch"):
                        method = groups[0].upper()
                        path = groups[1]
                        entry = f"{method} {path}"
                    else:
                        # @app.route style
                        path = groups[0]
                        methods_str = groups[1] if len(groups) > 1 and groups[1] else "GET"
                        methods_str = methods_str.replace('"', '').replace("'", "").strip()
                        entry = f"{methods_str} {path}"
                    if entry not in endpoints:
                        endpoints.append(entry)
                    break  # one match per line is enough

    # --- 3. dependencies ---
    dep_patterns = [
        re.compile(r'^import\s+([\w]+)'),                          # Python: import X
        re.compile(r'^from\s+([\w]+)'),                            # Python: from X import ...
        re.compile(r'''import\s+.*?\s+from\s+['"]([^'"./][^'"]*?)['"]'''),  # JS/TS: import ... from 'X'
        re.compile(r'''require\(\s*['"]([^'"./][^'"]*?)['"]'''),   # JS: require('X')
    ]
    deps = set()
    for filepath, content in key_files.items():
        ext = Path(filepath).suffix.lower()
        if ext not in (".py", ".js", ".ts", ".tsx", ".jsx"):
            continue
        for line in content.splitlines():
            stripped = line.strip()
            for pat in dep_patterns:
                m = pat.match(stripped) if pat.pattern.startswith('^') else pat.search(stripped)
                if m:
                    pkg = m.group(1)
                    # top-level only (e.g. @scope/pkg -> @scope/pkg, but os.path -> os)
                    top = pkg.split("/")[0] if pkg.startswith("@") else pkg.split(".")[0]
                    deps.add(top)
    dependencies = sorted(deps)[:30]

    # --- 4. file_sizes ---
    file_sizes = []
    for filepath, content in key_files.items():
        lines = len(content.splitlines())
        file_sizes.append({"file": filepath, "lines": lines})
    file_sizes.sort(key=lambda x: x["lines"], reverse=True)
    file_sizes = file_sizes[:15]

    # --- 5. empty_files ---
    empty_files = []
    for filepath, content in key_files.items():
        non_blank = sum(1 for l in content.splitlines() if l.strip())
        if non_blank < 5:
            empty_files.append(filepath)

    # --- 6. test_coverage ---
    test_files_count = 0
    test_functions_count = 0
    has_real_assertions = False
    for filepath, content in key_files.items():
        if "test" in filepath.lower():
            test_files_count += 1
            for line in content.splitlines():
                stripped = line.strip()
                if (stripped.startswith("def test_")
                        or stripped.startswith("it(")
                        or stripped.startswith("test(")
                        or stripped.startswith("describe(")):
                    test_functions_count += 1
                if "assert" in stripped or "expect(" in stripped:
                    has_real_assertions = True
    test_coverage = {
        "test_files": test_files_count,
        "test_functions": test_functions_count,
        "has_real_assertions": has_real_assertions,
    }

    # --- 7. functions_classes (from full symbol scan if available) ---
    if all_symbols:
        # Use the full repo scan — counts ALL source files, not just key_files
        fn_names = {s["name"] for s in all_symbols}
        # Heuristic: PascalCase = class/component, snake_case/camelCase = function
        cls_count = sum(1 for s in all_symbols if s["name"][0].isupper())
        fn_count = len(all_symbols) - cls_count
    else:
        fn_count = 0
        cls_count = 0
        for filepath, content in key_files.items():
            ext = Path(filepath).suffix.lower()
            if ext not in SOURCE_EXTS:
                continue
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("def ") or stripped.startswith("function "):
                    fn_count += 1
                if stripped.startswith("class "):
                    cls_count += 1
    functions_classes = {"functions": fn_count, "classes": cls_count}

    # --- 8. code_index (complete function/class listing from ALL files) ---
    code_index = []
    if all_symbols:
        for s in all_symbols:
            code_index.append(f"{s['name']}  ({s['file']}:{s['line']})")

    # --- 9. readme_vs_code ---
    # Extract feature keywords from readme claims (nouns after bullets)
    feature_keywords = []
    stop_words = {
        "the", "a", "an", "and", "or", "is", "in", "to", "for", "of", "with",
        "on", "at", "by", "it", "be", "as", "that", "this", "are", "was",
        "from", "has", "have", "not", "but", "can", "all", "will", "do",
        "use", "using", "used", "how", "your", "you", "our", "we", "my",
        "no", "so", "if", "up", "out", "about", "into", "over", "after",
    }
    for claim in readme_claims:
        # strip leading #, -, * and whitespace
        text = re.sub(r'^[#*\-\s]+', '', claim).strip()
        words = re.findall(r'[a-zA-Z]{3,}', text.lower())
        for w in words:
            if w not in stop_words and w not in feature_keywords:
                feature_keywords.append(w)

    # Check which keywords appear in code — scan ALL source files, not just key_files
    all_code = ""
    root = Path(repo_path)
    for filepath in structure["file_tree"]:
        ext = Path(filepath).suffix.lower()
        if ext not in SOURCE_EXTS:
            continue
        try:
            content = (root / filepath).read_text(encoding="utf-8", errors="ignore")
            all_code += content.lower() + "\n"
        except OSError:
            pass

    implemented = []
    gaps = []
    for kw in feature_keywords:
        if kw in all_code:
            implemented.append(kw)
        else:
            gaps.append(kw)

    readme_vs_code = {
        "readme_features": feature_keywords,
        "implemented_evidence": implemented,
        "gaps": gaps,
    }

    return {
        "readme_claims": readme_claims,
        "endpoints": endpoints,
        "dependencies": dependencies,
        "file_sizes": file_sizes,
        "empty_files": empty_files,
        "test_coverage": test_coverage,
        "functions_classes": functions_classes,
        "code_index": code_index,
        "readme_vs_code": readme_vs_code,
    }


async def analyze_repo(repo_path: str) -> dict:
    """Full pipeline: scan structure + read key files + symbol scan + build analysis summary."""
    logger.info("analyze_repo: Starte für %s", repo_path)
    structure = await scan_structure(repo_path)
    logger.info("analyze_repo: Scan fertig — %d Dateien, %d Zeilen", len(structure["file_tree"]), structure.get("total_lines", 0))
    key_files = await read_key_files(repo_path, structure)
    logger.info("analyze_repo: %d Key-Files gelesen (%d chars gesamt)",
        len(key_files), sum(len(v) for v in key_files.values()))

    all_symbols = scan_all_symbols(repo_path, structure["file_tree"])
    logger.info("analyze_repo: %d Symbole in %d Dateien gefunden (Full-Scan)",
        len(all_symbols), len({s["file"] for s in all_symbols}))

    evidence = build_evidence_report(repo_path, structure, key_files, all_symbols)

    return {
        "structure": structure,
        "key_files": key_files,
        "evidence": evidence,
        "summary": {
            "total_files": structure["total_files"],
            "total_lines": structure["total_lines"],
            "languages": structure["languages"],
            "frameworks": structure["frameworks"],
            "entry_points": structure["entry_points"],
            "has_readme": any(
                f.lower().startswith("readme") for f in structure["file_tree"]
            ),
            "has_tests": any(
                p.lower() in ("test", "tests", "__tests__", "spec")
                for f in structure["file_tree"]
                for p in Path(f).parts
            ),
            "has_docker": any(
                f.lower().startswith("dockerfile") or "docker-compose" in f.lower()
                for f in structure["file_tree"]
            ),
        },
    }
