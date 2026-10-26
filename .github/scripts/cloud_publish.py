# -*- coding: utf-8 -*-
"""햄찌노트 인스타 클라우드 발행 (2026-10-19) — GitHub Actions 에서 돈다. 피식니혼고 cloud_publish.py 의 이미지판.

큐 = 이 저장소의 초안(draft) 릴리스. 초안은 저장소 권한자만 보인다 — 발행 전 이미지·캡션이 새지 않는다.
  태그 q-<번호>, 본문 JSON {no, title, due, caption, done}, 첨부 image.jpg.  노트북 발행.py --stage 가 만든다.
  릴스(영상)는 태그 r-<번호>, 본문에 kind="reel" (no = 1000+글 번호), 첨부 video.mp4.
  캐러셀(여러 장)은 첨부 s01.jpg … s10.jpg (있으면 캐러셀로, image.jpg 는 표지 사본).
실행: 발행 시각(due)이 지났고 3시간 안이면 올린다. 넘었으면 missed 로 남긴다. 한 번 실행에 1편만.
이미지 공개 URL = media/ 에 잠깐 올려 Pages 로 열고, 게시 후 지운다(인스타 API 는 공개 https JPEG 주소가 필요).
결과 = log.json. 비밀값 IG_TOKEN = 인스타 장기 토큰 문자열.
"""
import datetime as dt, json, os, subprocess, sys, time, urllib.parse, urllib.request, urllib.error

REPO = os.environ.get("GITHUB_REPOSITORY", "kuo97/hamzzi-note-media")
GH = os.environ.get("GITHUB_TOKEN", "")
IG = (os.environ.get("IG_TOKEN") or "").replace("﻿", "").strip()   # 윈도우 PowerShell 로 등록하면 BOM 이 붙는다
PAGES = "https://kuo97.github.io/hamzzi-note-media/"
API = "https://graph.instagram.com/v21.0/"
KST = dt.timezone(dt.timedelta(hours=9))
LOG = "log.json"
LATE = dt.timedelta(hours=3)


def now():
    return dt.datetime.now(KST)


def gh(method, path, body=None):
    url = "https://api.github.com/repos/%s/%s" % (REPO, path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + GH, "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read().decode()
        return json.loads(t) if t else {}


def ig(path, data=None):
    """오류에는 응답 본문만 남긴다(토큰이 로그에 찍히지 않게)."""
    if data is None:
        req = urllib.request.Request(API + path + ("&" if "?" in path else "?") + "access_token=" + IG)
    else:
        req = urllib.request.Request(API + path, data=urllib.parse.urlencode(dict(data, access_token=IG)).encode())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("API %s: %s" % (e.code, e.read().decode()[:400]))


def git(*a):
    return subprocess.run(["git"] + list(a), capture_output=True, text=True)


def commit_push(paths, msg):
    git("add", "-A", *paths)
    if not git("status", "--porcelain", *paths).stdout.strip():
        return
    git("commit", "-q", "-m", msg)
    for _ in range(4):
        if git("push", "-q").returncode == 0:
            return
        git("pull", "-q", "--rebase")
    raise RuntimeError("git push 실패: " + msg)


def pages_build():
    try:
        gh("POST", "pages/builds")
    except Exception as e:
        print("  pages 빌드 요청 실패(무시):", e)


def host(local, name):
    os.makedirs("media", exist_ok=True)
    os.replace(local, "media/" + name)
    commit_push(["media"], "media: " + name)
    pages_build()
    url = PAGES + "media/" + name
    for i in range(48):
        try:
            if urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=15).status == 200:
                print("  공개 확인 %d초" % ((i + 1) * 15))
                return url
        except Exception:
            pass
        time.sleep(15)
    raise RuntimeError("Pages 에 이미지가 12분 안에 안 열렸다")


def unhost(name):
    p = "media/" + name
    if os.path.exists(p):
        os.remove(p)
        commit_push(["media"], "media: remove " + name)
        pages_build()


def host_many(pairs):
    """캐러셀: 여러 장을 한 번에 올리고(커밋 1번) 모두 열릴 때까지 기다린다. pairs = [(로컬 파일, 이름)]"""
    os.makedirs("media", exist_ok=True)
    for local, name in pairs:
        os.replace(local, "media/" + name)
    commit_push(["media"], "media: %d장" % len(pairs))
    pages_build()
    urls = [PAGES + "media/" + n for _, n in pairs]
    for i in range(48):
        try:
            if all(urllib.request.urlopen(urllib.request.Request(u, method="HEAD"), timeout=15).status == 200 for u in urls):
                print("  공개 확인 %d초 (%d장)" % ((i + 1) * 15, len(urls)))
                return urls
        except Exception:
            pass
        time.sleep(15)
    raise RuntimeError("Pages 에 캐러셀 이미지가 12분 안에 다 안 열렸다")


def unhost_many(names):
    gone = [n for n in names if os.path.exists("media/" + n)]
    for n in gone:
        os.remove("media/" + n)
    if gone:
        commit_push(["media"], "media: remove %d장" % len(gone))
        pages_build()


def wait_ready(cid, tries=30):
    for _ in range(tries):
        st = ig(cid + "?fields=status_code,status")
        if st.get("status_code") == "FINISHED":
            return
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError("인스타 처리 실패: %s" % st.get("status"))
        time.sleep(5)
    raise RuntimeError("인스타 처리가 늦다")


def publish_carousel(urls, caption):
    """장마다 is_carousel_item 컨테이너 → CAROUSEL 컨테이너(최대 10장) → 게시"""
    kids = []
    for u in urls[:10]:
        c = ig("me/media", {"image_url": u, "is_carousel_item": "true"})
        wait_ready(c["id"]); kids.append(c["id"])
    c = ig("me/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption})
    wait_ready(c["id"])
    return ig("me/media_publish", {"creation_id": c["id"]})["id"]


def publish_reel(url, caption):
    c = ig("me/media", {"media_type": "REELS", "video_url": url, "caption": caption, "share_to_feed": "true"})
    for _ in range(72):                                  # 영상 처리는 오래 걸린다(최대 6분)
        st = ig(c["id"] + "?fields=status_code,status")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError("인스타 릴스 처리 실패: %s" % st.get("status"))
        time.sleep(5)
    else:
        raise RuntimeError("릴스 처리가 6분 안에 안 끝났다")
    return ig("me/media_publish", {"creation_id": c["id"]})["id"]


def publish(url, caption):
    c = ig("me/media", {"image_url": url, "caption": caption})
    for _ in range(30):
        st = ig(c["id"] + "?fields=status_code,status")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError("인스타 처리 실패: %s" % st.get("status"))
        time.sleep(5)
    return ig("me/media_publish", {"creation_id": c["id"]})["id"]


def record(m, status, **kw):
    try:
        L = json.load(open(LOG, encoding="utf-8"))
    except Exception:
        L = {"entries": []}
    e = {"no": m["no"], "title": m["title"], "due": m["due"], "status": status,
         "at": now().strftime("%Y-%m-%dT%H:%M:%S+09:00")}
    e.update({k: v for k, v in kw.items() if v})
    L["entries"] = (L["entries"] + [e])[-500:]
    json.dump(L, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    commit_push([LOG], "log: %02d %s" % (m["no"], status))


def patch_body(rel, m):
    gh("PATCH", "releases/%d" % rel["id"], {"body": json.dumps(m, ensure_ascii=False), "tag_name": rel["tag_name"]})


def download(rel, asset="image.jpg"):
    a = [x for x in rel.get("assets", []) if x["name"] == asset]
    if not a:
        raise RuntimeError(asset + " 첨부 없음")
    out = "_dl" + os.path.splitext(asset)[1]
    r = subprocess.run(["curl", "-sSL", "--fail", "-o", out, "-H", "Authorization: Bearer " + GH,
                        "-H", "Accept: application/octet-stream", a[0]["url"]], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("내려받기 실패: " + r.stderr[-200:])
    return out


def run(force=None):
    if not IG:
        sys.exit("비밀값 IG_TOKEN 이 없다")
    rels = gh("GET", "releases?per_page=100")
    q = sorted([r for r in rels if r.get("draft") and (r.get("tag_name") or "").startswith(("q-", "r-"))],
               key=lambda r: json.loads(r["body"])["due"])
    t = now()
    print("큐 %d건 · 지금 %s KST" % (len(q), t.strftime("%m-%d %H:%M")))
    for rel in q:
        m = json.loads(rel["body"])
        if m.get("done"):
            gh("DELETE", "releases/%d" % rel["id"])
            continue
        due = dt.datetime.fromisoformat(m["due"])
        if force and str(m["no"]) != str(int(force)):
            continue
        if not force:
            if t < due:
                wait = (due - t).total_seconds()
                if wait > 600:
                    continue
                print("  %02d 발행 시각까지 %d초 대기" % (m["no"], wait))
                time.sleep(wait)
            elif t - due > LATE:
                if not m.get("missed"):
                    print("  %02d 3시간 넘게 지났다(%s) — 올리지 않음" % (m["no"], m["due"]))
                    record(m, "missed", error="발행 시각에서 3시간 넘게 지나 자동 발행 안 함")
                    m["missed"] = True
                    patch_body(rel, m)
                continue
        print("▶ %02d %s %s" % (m["no"], m["title"], m["due"]))
        reel = m.get("kind") == "reel"
        name = "%d_%s.%s" % (int(time.time()), rel["tag_name"], "mp4" if reel else "jpg")
        slides = sorted(a["name"] for a in rel.get("assets", []) if a["name"].startswith("s") and a["name"].endswith(".jpg"))
        many = []
        try:
            if slides:                                # 캐러셀: 첨부 s01.jpg … s10.jpg
                pairs = []
                for s in slides:
                    f = download(rel, s); g = "_dl_" + s; os.replace(f, g)
                    pairs.append((g, "%d_%s_%s" % (int(time.time()), rel["tag_name"], s)))
                many = [n for _, n in pairs]
                mid = publish_carousel(host_many(pairs), m["caption"])
            elif reel:
                mid = publish_reel(host(download(rel, "video.mp4"), name), m["caption"])
            else:
                mid = publish(host(download(rel), name), m["caption"])
            m["done"] = mid
            patch_body(rel, m)                        # 먼저 적는다 — 중간에 죽어도 두 번 올리지 않게
            record(m, "published", media_id=mid)
            print("  [OK] %s" % mid)
            gh("DELETE", "releases/%d" % rel["id"])
        except Exception as e:
            print("  [실패] %s" % e)
            record(m, "failed", error=str(e)[:300])
        finally:
            unhost(name)
            unhost_many(many)
        return                                        # 한 번에 1편만


def test_hosting():
    """게시 없이 Pages 호스팅·토큰만 시험한다 (mode=test)."""
    me = ig("me?fields=username,account_type")
    print("[OK] 토큰 계정:", me.get("username"), me.get("account_type"))
    open("_t.txt", "w").write("ok")
    name = "%d_hosting-test.txt" % int(time.time())
    try:
        host("_t.txt", name)
        print("[OK] 호스팅 시험 통과")
    finally:
        unhost(name)


def test_carousel(no):
    """게시 없이 캐러셀을 시험한다(mode=carousel-test): 장 2개를 올려 컨테이너가 FINISHED 되는지만 본다."""
    rel = [r for r in gh("GET", "releases?per_page=100") if r.get("tag_name") == "q-%s" % no][0]
    slides = sorted(a["name"] for a in rel["assets"] if a["name"].startswith("s") and a["name"].endswith(".jpg"))[:2]
    pairs = []
    for s_ in slides:
        f = download(rel, s_); g = "_dl_" + s_; os.replace(f, g); pairs.append((g, "%d_test_%s" % (int(time.time()), s_)))
    try:
        urls = host_many(pairs); kids = []
        for u in urls:
            c = ig("me/media", {"image_url": u, "is_carousel_item": "true"}); wait_ready(c["id"]); kids.append(c["id"])
        c = ig("me/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": "test"}); wait_ready(c["id"])
        print("[OK] 캐러셀 컨테이너 준비 완료(게시 안 함):", c["id"])
    finally:
        unhost_many([n for _, n in pairs])


if __name__ == "__main__":
    git("config", "user.name", "hamzzi-cloud")
    git("config", "user.email", "actions@users.noreply.github.com")
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "test":
        test_hosting()
    elif mode == "carousel-test":
        test_carousel(sys.argv[2])
    else:
        run(force=sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None)
