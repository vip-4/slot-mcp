"""把静态站发布到 Cloudflare Pages 与 GitHub Pages。

    python -m slotmcp.tools.deploy_pages --cloudflare          # 直传到 Cloudflare Pages
    python -m slotmcp.tools.deploy_pages --github              # 建仓 + 推送 + 开启 GitHub Pages
    python -m slotmcp.tools.deploy_pages --all                 # 两者都做
    python -m slotmcp.tools.deploy_pages --all --dry-run       # 只打印计划动作

凭证（环境变量，或直接写在已 gitignore 的 deploy/services.local.json）：
    CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID
    GITHUB_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.services.cloudflare import CloudflareClient, collect_files  # noqa: E402
from slotmcp.services.github import GitHubClient  # noqa: E402

OUT_DIR = ROOT / "static"
DEFAULT_PROJECT = "slot-games"
DEFAULT_BRANCH = "main"


def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "cloudflare_token": os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        "cloudflare_account": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
        "github_token": os.environ.get("GITHUB_TOKEN", ""),
        "project": DEFAULT_PROJECT,
        "branch": DEFAULT_BRANCH,
    }
    for name in ("services.local.json", "services.json"):
        path = ROOT / "deploy" / name
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            cf = raw.get("cloudflare") or {}
            gh = raw.get("github") or {}
            cfg["cloudflare_token"] = cfg["cloudflare_token"] or cf.get("api_token", "")
            cfg["cloudflare_account"] = cfg["cloudflare_account"] or str(cf.get("account_id", ""))
            cfg["github_token"] = cfg["github_token"] or gh.get("token", "")
            cfg["project"] = cf.get("project") or gh.get("repo") or cfg["project"]
            break
    return cfg


def git_exe() -> str:
    for candidate in ("git", r"C:\Program Files\Git\bin\git.exe", r"C:\Program Files\Git\cmd\git.exe"):
        found = shutil.which(candidate) if candidate == "git" else candidate
        if found and Path(found).is_file():
            return found
    return ""


def run_cloudflare(cfg: Dict[str, Any], src: Path, dry_run: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {"state": "skipped"}
    if not cfg["cloudflare_token"] or not cfg["cloudflare_account"]:
        print("  [NG] 缺少 CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID")
        return {"state": "no-credential"}

    files = collect_files(src)
    total = sum(len(v) for v in files.values())
    print(f"  待上传: {len(files)} 个文件 / {total / 1024:.1f} KB（来自 {src}）")
    if dry_run:
        return {"state": "dry-run", "files": len(files), "bytes": total}

    client = CloudflareClient(cfg["cloudflare_token"], cfg["cloudflare_account"])
    project, state = client.ensure_project(cfg["project"])
    if project is None:
        print(f"  [NG] 项目准备失败: {state}")
        return {"state": "failed", "detail": state}
    print(f"  [{state}] 项目 {project.get('name')} · 生产分支 {project.get('production_branch')}")

    ok, status, payload = client.deploy(cfg["project"], files)
    if not ok:
        print(f"  [NG] 上传失败 HTTP {status}: {str(payload)[:200]}")
        return {"state": "failed", "detail": str(payload)[:200]}
    dep = payload.get("result") if isinstance(payload, dict) else None
    url = client.project_url(project)
    result = {
        "state": "deployed",
        "project": project.get("name"),
        "url": url,
        "deployment": (dep or {}).get("id", ""),
        "files": len(files),
        "bytes": total,
    }
    print(f"  [OK] 部署成功 -> {url}  (deployment {result['deployment']})")
    return result


def run_github(cfg: Dict[str, Any], src: Path, dry_run: bool) -> Dict[str, Any]:
    if not cfg["github_token"]:
        print("  [NG] 缺少 GITHUB_TOKEN")
        return {"state": "no-credential"}

    client = GitHubClient(cfg["github_token"])
    owner = client.login()
    if not owner:
        print("  [NG] GitHub Token 无效或权限不足")
        return {"state": "failed", "detail": "无法读取 /user"}
    print(f"  账号: {owner}")

    if dry_run:
        existing = client.get_repo(f"{owner}/{cfg['project']}")
        plan_url = GitHubClient.pages_url(owner, cfg["project"])
        print(
            f"  [DRY] 仓库 {owner}/{cfg['project']}"
            f"（{'已存在' if existing else '将创建'}），Pages 地址 {plan_url}"
        )
        return {"state": "dry-run", "repo": f"{owner}/{cfg['project']}", "url": plan_url}

    repo, state = client.ensure_repo(
        cfg["project"],
        description="10 款免费在线老虎机：纯静态站（SEO + GEO 优化），统一 CONFIG 引擎驱动",
        homepage="",
    )
    if repo is None:
        print(f"  [NG] 仓库准备失败: {state}")
        return {"state": "failed", "detail": state}
    full = repo["full_name"]
    print(f"  [{state}] 仓库 {full}")

    git = git_exe()
    if not git:
        print("  [NG] 未找到 git，无法推送内容")
        return {"state": "failed", "detail": "git not found"}
    if dry_run:
        print(f"  [DRY] 将推送 {src} -> {full}@{cfg['branch']} 并开启 Pages")
        return {"state": "dry-run", "repo": full}

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        work.mkdir()
        for item in src.iterdir():
            target = work / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = env.get("GIT_AUTHOR_NAME", "Slot MCP")
        env["GIT_AUTHOR_EMAIL"] = env.get("GIT_AUTHOR_EMAIL", "slot-mcp@example.com")
        env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"]
        env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"]

        def run(args: List[str]) -> subprocess.CompletedProcess:
            return subprocess.run(
                [git, *args], cwd=str(work), env=env, capture_output=True, text=True
            )

        run(["init", "-b", cfg["branch"]])
        remote = f"https://{cfg['github_token']}@github.com/{full}.git"
        run(["remote", "add", "origin", remote])
        # 仓库已有历史时先对齐远端（保留提交历史），否则首次推送会因无关历史被拒。
        # 用 reset --soft 而不是 checkout：工作区里已是本次产物，checkout 会覆盖它们。
        if run(["fetch", "origin", cfg["branch"]]).returncode == 0:
            run(["reset", "--soft", f"origin/{cfg['branch']}"])
        run(["add", "-A"])
        res = run(["commit", "-q", "-m", "deploy: 静态站产物"])
        if res.returncode != 0 and "nothing to commit" not in (res.stdout + res.stderr):
            print(f"  [NG] 提交失败: {(res.stdout + res.stderr).strip()[:200]}")
            return {"state": "failed", "detail": "commit failed"}
        push = run(["push", "-u", "origin", cfg["branch"]])
        if push.returncode != 0:
            print(f"  [NG] 推送失败: {(push.stdout + push.stderr).strip()[:200]}")
            return {"state": "failed", "detail": "push failed"}
        print(f"  [OK] 已推送 {full}@{cfg['branch']}")

    ok, status, payload = client.enable_pages(full, cfg["branch"], "/")
    url = GitHubClient.pages_url(owner, cfg["project"])
    if ok:
        print(f"  [OK] GitHub Pages 已开启 -> {url}")
        state = "deployed"
    elif status == 409:
        print(f"  [OK] GitHub Pages 已存在（无需重复开启）-> {url}")
        state, ok = "deployed", True
    else:
        print(f"  [NG] 开启 Pages 失败 HTTP {status}: {str(payload)[:200]}")
        return {"state": "failed", "detail": str(payload)[:200]}
    return {"state": state, "repo": full, "url": url}


def main() -> int:
    ap = argparse.ArgumentParser(description="发布静态站到 Cloudflare Pages / GitHub Pages")
    ap.add_argument("--dir", default=str(OUT_DIR), help=f"站点根目录（默认 {OUT_DIR}）")
    ap.add_argument("--project", default=None, help=f"Pages 项目 / 仓库名（默认 {DEFAULT_PROJECT}）")
    ap.add_argument("--branch", default=DEFAULT_BRANCH, help="生产分支")
    ap.add_argument("--cloudflare", action="store_true", help="直传到 Cloudflare Pages")
    ap.add_argument("--github", action="store_true", help="建仓 + 推送 + 开启 GitHub Pages")
    ap.add_argument("--all", action="store_true", help="两者都执行")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划动作")
    args = ap.parse_args()

    cfg = load_config()
    if args.project:
        cfg["project"] = args.project
    cfg["branch"] = args.branch
    src = Path(args.dir)
    if not src.is_dir():
        print(f"[NG] 站点目录不存在: {src}（先运行 tools/build_static.py）")
        return 1

    print("== 发布静态站 ==")
    print(f"  目录: {src}   项目: {cfg['project']}   分支: {cfg['branch']}")

    cf: Dict[str, Any] = {}
    gh: Dict[str, Any] = {}
    if args.cloudflare or args.all:
        print("\n== Cloudflare Pages（直传） ==")
        cf = run_cloudflare(cfg, src, args.dry_run)
    if args.github or args.all:
        print("\n== GitHub Pages ==")
        gh = run_github(cfg, src, args.dry_run)

    print()
    urls = [r for r in (cf, gh) if r.get("state") == "deployed" and r.get("url")]
    for r in urls:
        print(f"  上线地址: {r['url']}")
    if urls:
        primary: Optional[str] = urls[0]["url"]
        print("\n下一步（同步 canonical / sitemap 后再发布一次）：")
        print(f"  python tools/build_static.py --site-url {primary}")
        print("  python -m slotmcp.tools.deploy_pages --all --dir static")
    failed = [r for r in (cf, gh) if r.get("state") in ("failed", "no-credential")]
    print("[OK] 发布完成" if not failed else f"[NG] 存在失败项：{len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
