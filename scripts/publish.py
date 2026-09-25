import os
import re
import sys
import json
import time
import argparse
import subprocess
import urllib.error
import urllib.parse
import urllib.request

DL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_dl")

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def download(url, dest, tries=3):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as resp:
                total = int(resp.headers.get("Content-Length", "0") or "0")
                got = 0
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                print(f"    {os.path.basename(dest)}  {got / 1048576:.1f} MB"
                      + (f" / {total / 1048576:.1f} MB" if total else ""))
            return True
        except Exception as e:
            last = e
            if attempt < tries - 1:
                time.sleep(2)
    print(f"    download failed: {last}")
    return False


def run_gh(args):
    try:
        proc = subprocess.run(["gh"] + args, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, "gh: not found"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def release_exists(tag, repo):
    code, _ = run_gh(["release", "view", tag, "--repo", repo])
    return code == 0


def asset_dl(a):
    dl = (a.get("dl") or "").strip()
    if dl:
        return dl
    s = re.sub(r"[^0-9A-Za-z._-]", "-", a.get("name") or "")
    s = re.sub(r"-{2,}", "-", s).strip("-._")
    return s or "file"


def api(method, url, token, data=None, ctype="application/json"):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "apk-release",
        "Content-Type": ctype,
    })
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def get_release(repo, tag, token):
    try:
        return api("GET", f"https://api.github.com/repos/{repo}/releases/tags/"
                          f"{urllib.parse.quote(tag, safe='')}", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def upload_asset(repo, token, release_id, path, name, label):
    q = urllib.parse.urlencode({"name": name, "label": label or name})
    url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?{q}"
    with open(path, "rb") as f:
        blob = f.read()
    return api("POST", url, token, data=blob, ctype="application/octet-stream")


def publish(item, repo, dry_run=False):
    tag = item["tag_name"]
    title = item.get("release_title") or tag
    notes = item.get("notes") or ""
    assets = item.get("assets") or []

    if not assets:
        print("    no files in plan")
        return False

    if dry_run:
        for a in assets:
            print(f"   [dry-run] {asset_dl(a)}")
        return True

    local, failed = [], []
    for a in assets:
        dl = asset_dl(a)
        dest = os.path.join(DL_DIR, dl)
        print(f"   {dl}")
        if download(a["url"], dest):
            local.append((a, dest))
        else:
            failed.append(dl)

    if failed:
        print(f"    {len(failed)} file(s) failed, skip release")
        return False

    os.makedirs(DL_DIR, exist_ok=True)
    notes_file = os.path.join(DL_DIR, "_notes.md")
    with open(notes_file, "w", encoding="utf-8") as f:
        f.write(notes)

    if not release_exists(tag, repo):
        code, out = run_gh(["release", "create", tag, "--repo", repo,
                            "--title", title, "--notes-file", notes_file,
                            "--latest=false"])
        if code != 0:
            print(f"    create failed: {out.strip()[:500]}")
            return False

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        code, out = run_gh(["release", "upload", tag, "--repo", repo,
                            "--clobber"] + [p for _, p in local])
        if code != 0:
            print(f"    upload failed: {out.strip()[:500]}")
            return False
    else:
        rel = get_release(repo, tag, token)
        if not rel:
            print("    release not found, assets not uploaded")
            return False
        old = {a.get("name"): a.get("id") for a in rel.get("assets", [])}
        for a, path in local:
            dl = asset_dl(a)
            if dl in old:
                api("DELETE", f"https://api.github.com/repos/{repo}/releases/assets/{old[dl]}", token)
            upload_asset(repo, token, rel["id"], path, dl, a["name"])
            print(f"   up {dl}")

    print(f"    https://github.com/{repo}/releases/tag/{tag}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-file", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.plan_file:
        with open(args.plan_file, "r", encoding="utf-8") as f:
            plan = json.load(f)
        items = plan if isinstance(plan, list) else [plan]
    else:
        raw = os.environ.get("ITEM_JSON", "").strip()
        if not raw or raw in ("null", "{}"):
            print("no plan received")
            return 0
        items = [json.loads(raw)]

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        code, out = run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
        repo = out.strip() if code == 0 else ""

    ok = 0
    for item in items:
        if publish(item, repo, dry_run=args.dry_run):
            ok += 1

    print(f"[done] {ok}/{len(items)}")
    return 0 if ok == len(items) else 1


if __name__ == "__main__":
    sys.exit(main())
