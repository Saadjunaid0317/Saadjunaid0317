"""Build the GitHub activity cards (dark + light SVG) for the profile README.

Runs in GitHub Actions once a day. Uses only the Python standard library.

  python scripts/stats.py --user Saadjunaid0317 --out dist          (live data, needs GITHUB_TOKEN)
  python scripts/stats.py --sample scripts/sample.json --out dist   (offline preview)
"""
import argparse
import datetime as dt
import json
import os
import urllib.request
from html import escape
from pathlib import Path

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100, privacy: PUBLIC) {
      totalCount
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

THEMES = {
    "dark": dict(bg="#0b1020", card="#111831", line="#1f2a44", text="#e6edf7", muted="#8b98b4",
                 accent="#22d3ee", accent2="#7c3aed", bar="#22d3ee", empty="#1a2340",
                 fire="#f97316", gold="#facc15"),
    "light": dict(bg="#ffffff", card="#f6f8fb", line="#e2e8f0", text="#0f172a", muted="#64748b",
                  accent="#0891b2", accent2="#7c3aed", bar="#0891b2", empty="#e8edf4",
                  fire="#ea580c", gold="#ca8a04"),
}


def fetch(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json", "User-Agent": "profile-stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "errors" in data:
        raise SystemExit(f"GraphQL error: {data['errors']}")
    return data["data"]["user"]


def summarise(user):
    cc = user["contributionsCollection"]
    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    days.sort(key=lambda d: d["date"])
    counts = [d["contributionCount"] for d in days]

    # longest streak in the last year
    longest = run = 0
    best_end = cur_start = None
    for i, c in enumerate(counts):
        if c > 0:
            run += 1
            if run == 1:
                cur_start = i
            if run > longest:
                longest, best_end, best_start = run, i, cur_start
        else:
            run = 0
    # current streak: today may still be empty, so start from yesterday in that case
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    current, cur_end = 0, i
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1

    def span(a, b):
        if a is None or b is None or a < 0 or b < 0:
            return ""
        f = lambda s: dt.date.fromisoformat(s).strftime("%b %d")
        return f"{f(days[a]['date'])} – {f(days[b]['date'])}"

    weekly = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in cc["contributionCalendar"]["weeks"]]

    langs = {}
    for repo in user["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            langs.setdefault(name, [0, e["node"]["color"] or "#94a3b8"])
            langs[name][0] += e["size"]
    total = sum(v[0] for v in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1][0])[:6]
    top = [(n, v[0] / total * 100, v[1]) for n, v in top]

    return dict(
        total=cc["contributionCalendar"]["totalContributions"],
        commits=cc["totalCommitContributions"], prs=cc["totalPullRequestContributions"],
        issues=cc["totalIssueContributions"], repos=user["repositories"]["totalCount"],
        current=current, current_span=span(current and cur_end - current + 1, cur_end if current else -1),
        longest=longest, longest_span=span(best_start, best_end) if longest else "",
        weekly=weekly[-52:], langs=top,
        updated=dt.date.today().strftime("%b %d, %Y"),
    )


def card(x, y, w, h, t):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{t["card"]}" stroke="{t["line"]}"/>'


def render(s, t):
    W, H = 860, 470
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Segoe UI,Inter,Helvetica,Arial,sans-serif">',
         '<style>.fade{opacity:0;animation:fade .6s ease forwards}@keyframes fade{to{opacity:1}}'
         '.grow{transform-box:fill-box;transform-origin:bottom;transform:scaleY(0);animation:grow .8s cubic-bezier(.2,.8,.2,1) forwards}'
         '@keyframes grow{to{transform:scaleY(1)}}</style>',
         f'<rect width="{W}" height="{H}" rx="18" fill="{t["bg"]}" stroke="{t["line"]}"/>']

    # 1. annual activity
    o.append(card(20, 20, 820, 200, t))
    o.append(f'<text x="40" y="52" font-size="13" font-weight="700" letter-spacing="1.5" fill="{t["accent"]}">ANNUAL CONTRIBUTIONS &amp; ACTIVITY</text>')
    stats = [(s["total"], "Contributions"), (s["commits"], "Commits"), (s["prs"], "Pull requests"),
             (s["issues"], "Issues"), (s["repos"], "Public repos")]
    for i, (v, label) in enumerate(stats):
        x = 40 + i * 120
        o.append(f'<g class="fade" style="animation-delay:{0.1 * i:.1f}s">'
                 f'<text x="{x}" y="92" font-size="28" font-weight="800" fill="{t["text"]}">{v}</text>'
                 f'<text x="{x}" y="112" font-size="12" fill="{t["muted"]}">{label}</text></g>')
    weekly = s["weekly"]
    peak = max(weekly) or 1
    bx, bw, base, maxh = 40, 780 / max(len(weekly), 1), 205, 72
    for i, v in enumerate(weekly):
        h = max(2, v / peak * maxh)
        col = t["bar"] if v else t["empty"]
        o.append(f'<rect class="grow" style="animation-delay:{0.3 + i * 0.012:.3f}s" x="{bx + i * bw:.1f}" y="{base - h:.1f}" '
                 f'width="{bw * 0.68:.1f}" height="{h:.1f}" rx="1.5" fill="{col}"/>')
    o.append(f'<text x="820" y="52" font-size="11" text-anchor="end" fill="{t["muted"]}">Weekly, last 52 weeks</text>')

    # 2. streaks
    for i, (v, title, sub, col) in enumerate([
            (s["current"], "CURRENT STREAK", s["current_span"], t["fire"]),
            (s["longest"], "LONGEST STREAK", s["longest_span"], t["gold"])]):
        x = 20 + i * 415
        o.append(card(x, 236, 405, 96, t))
        o.append(f'<g class="fade" style="animation-delay:{0.9 + i * 0.15:.2f}s">'
                 f'<text x="{x + 20}" y="264" font-size="12" font-weight="700" letter-spacing="1.5" fill="{col}">{title}</text>'
                 f'<text x="{x + 20}" y="306" font-size="32" font-weight="800" fill="{t["text"]}">{v}'
                 f'<tspan font-size="14" font-weight="500" fill="{t["muted"]}"> {"day" if v == 1 else "days"}</tspan></text>'
                 f'<text x="{x + 385}" y="306" font-size="12" text-anchor="end" fill="{t["muted"]}">{escape(sub)}</text></g>')

    # 3. top languages
    o.append(card(20, 348, 820, 102, t))
    o.append(f'<text x="40" y="376" font-size="12" font-weight="700" letter-spacing="1.5" fill="{t["accent2"]}">TOP LANGUAGES (BY CODE SIZE)</text>')
    x = 40.0
    o.append(f'<clipPath id="lb"><rect x="40" y="388" width="780" height="10" rx="5"/></clipPath><g clip-path="url(#lb)">')
    for name, pct, col in s["langs"]:
        w = 780 * pct / 100
        o.append(f'<rect x="{x:.1f}" y="388" width="{w:.1f}" height="10" fill="{col}"/>')
        x += w
    o.append('</g>')
    for i, (name, pct, col) in enumerate(s["langs"]):
        lx, ly = 40 + (i % 3) * 260, 420 + (i // 3) * 20
        o.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{col}"/>'
                 f'<text x="{lx + 16}" y="{ly}" font-size="13" fill="{t["text"]}">{escape(name)} '
                 f'<tspan fill="{t["muted"]}">{pct:.1f}%</tspan></text>')
    o.append(f'<text x="820" y="376" font-size="11" text-anchor="end" fill="{t["muted"]}">Updated {s["updated"]}</text>')
    o.append('</svg>')
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="Saadjunaid0317")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--sample")
    a = ap.parse_args()
    if a.sample:
        user = json.loads(Path(a.sample).read_text(encoding="utf-8"))
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("GITHUB_TOKEN is not set")
        user = fetch(a.user, token)
    s = summarise(user)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        (out / f"stats-{name}.svg").write_text(render(s, theme), encoding="utf-8")
    print(f"stats cards written to {out}: {s['total']} contributions, streak {s['current']}/{s['longest']}")


if __name__ == "__main__":
    main()
