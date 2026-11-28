# -*- coding: utf-8 -*-
"""按公开仓库现有 Release 重写 README 里的软件列表。

列表夹在 <!-- APPS:START --> / <!-- APPS:END --> 之间，由 publish.yml 每次发布后调用。
每行的「最新版本」直接链到该软件最新的 Release，方便一键下载。
"""
import json
import os
import re
import time
import urllib.request

REPO = os.environ.get("REPO") or "YSBXS/apk-release"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
HERE = os.path.dirname(os.path.abspath(__file__))
README = os.path.join(os.path.dirname(HERE), "README.md")
START, END = "<!-- APPS:START -->", "<!-- APPS:END -->"


def api(url):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "apk-release-readme",
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r), dict(r.headers)


def all_releases():
    out, page = [], 1
    while page <= 10:
        batch, _ = api(f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}")
        if not batch:
            break
        out += batch
        page += 1
    return out


def split_title(rel):
    """标题统一为「应用名【版本】」，取不到就用 tag 兜底。"""
    title = (rel.get("name") or "").strip()
    m = re.match(r"^(.+?)【(.+)】$", title)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return title or rel.get("tag_name") or "", ""


def main():
    latest, order = {}, []
    for rel in all_releases():  # API 已按创建时间从新到旧返回
        if rel.get("draft"):
            continue
        app, ver = split_title(rel)
        if not app or app in latest:
            continue
        latest[app] = (ver or rel.get("tag_name") or "", rel.get("html_url") or "")
        order.append(app)

    rows = ["| 序号 | 软件名称 | 最新版本 | 下载 |", "| --- | --- | --- | --- |"]
    for i, app in enumerate(order, 1):
        ver, url = latest[app]
        rows.append(f"| {i} | {app} | {ver} | [点击下载]({url}) |")
    block = (f"{START}\n目前共 {len(order)} 款，均为上游官方安装包。"
             f"点最后一列「点击下载」可直达该软件的最新 Release。\n\n"
             + "\n".join(rows) + f"\n{END}")

    text = open(README, encoding="utf-8").read()
    if START in text and END in text:
        pre, rest = text.split(START, 1)
        _, post = rest.split(END, 1)
        text = pre + block + post
    else:
        text = text.rstrip() + "\n\n## 包含的软件\n\n" + block + "\n"

    now = time.strftime("%Y.%m.%d %H:%M", time.gmtime(time.time() + 8 * 3600))
    out = []
    for line in text.splitlines():
        if line.startswith("最后更新："):
            line = f"最后更新：{now}"
        out.append(line)
    open(README, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"[README] 已写入 {len(order)} 款软件")


if __name__ == "__main__":
    main()
