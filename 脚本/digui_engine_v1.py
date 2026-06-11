# -*- coding: utf-8 -*-
# 【CC-CTO 数字归乡下载引擎 v1 · 2026-06-11】
# 工业化通用下载引擎:CSV 清单驱动 → CF Worker 云端抓图(全球 IP 抗封)→ 本地拼 PDF 落 F 盘 + 转 WebP 入 R2。
# 抓取 100% 走 Worker,本地永不直连各馆。设计在 GitHub Actions matrix 里 --shard 扇出并行。
# 核心逻辑沿用已验证的 universal_sync_r2.py(下过 5000+),解混淆 + 稳定化 + 加分片/运行账本。
# 标准见 报告/下载引擎打法_v1.md。依赖同目录 _naming.py(统一命名单一真相源)。
import os, sys, io, json, time, re, csv, argparse
import urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import fitz  # PyMuPDF
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _naming import manifest_name, sanitize

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 配置(环境变量可覆盖)──────────────────────────────────────────────
# 活的 Worker 域(2.x 系;1.1fz 已死)。多域 = fallback + 分散负载。
WORKERS = [d.strip() for d in os.environ.get(
    "WORKERS",
    "https://2.1fz.dpdns.org,https://2.freezz.dpdns.org,https://2.bnp.indevs.in"
).split(",") if d.strip()]
IIIF_SIZE    = os.environ.get("IIIF_SIZE", "max").strip()       # IIIF 取图尺寸
UA           = os.environ.get("UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GF/2.1")  # CF Worker 白名单 UA(原型 universal_sync_r2.py 已验证 5000+);DiguiEngine/1.0 触发 CF 1010
GET_TIMEOUT  = int(os.environ.get("GET_TIMEOUT", "45"))
GET_RETRY    = int(os.environ.get("GET_RETRY", "5"))
WEBP_QUALITY = int(os.environ.get("WEBP_QUALITY", "92"))


def log(m):
    print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)


def _opener():
    # 塞空 ProxyHandler:不吃系统代理,云端直连 Worker
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ── HTTP ──────────────────────────────────────────────────────────────
def http_get(url, binary=False):
    """直接 GET(用于拉各馆 IIIF manifest JSON),带重试。"""
    for i in range(GET_RETRY):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with _opener().open(req, timeout=GET_TIMEOUT) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception:
            if i == GET_RETRY - 1:
                raise
            time.sleep(1 + i * 2)


def worker_call(path, *, data=None, method=None, timeout=60, retry=2, content_type=None):
    """调 CF Worker:多域 round-robin + fallback,返回 bytes。"""
    last = None
    for idx, dom in enumerate(WORKERS):
        for a in range(retry):
            try:
                headers = {"User-Agent": UA}
                if content_type:
                    headers["Content-Type"] = content_type
                req = urllib.request.Request(f"{dom}{path}", data=data, headers=headers, method=method)
                with _opener().open(req, timeout=timeout) as r:
                    return r.read()
            except Exception as e:
                last = e
                time.sleep(1 + a * 2)
        if idx < len(WORKERS) - 1:
            log(f"[fb] {dom} 失败({last}),切下一域")
    if last:
        raise last
    raise RuntimeError("worker_call: 无可用 Worker 域")


def r2_exists(key):
    try:
        res = json.loads(worker_call(f"/exists?key={urllib.parse.quote(key)}", timeout=10, retry=2).decode("utf-8"))
        return res.get("exists", False)
    except Exception as e:
        log(f"[W] R2 exists 查询失败: {e}")
        return False


def r2_upload(key, data):
    ct = "application/pdf" if key.endswith(".pdf") else "image/webp"
    try:
        res = json.loads(worker_call(f"/upload?key={urllib.parse.quote(key)}", data=data, method="POST",
                                     timeout=60, retry=GET_RETRY, content_type=ct).decode("utf-8"))
        return bool(res.get("ok"))
    except Exception as e:
        log(f"[E] R2 上传失败({key}): {e}")
        return False


# ── IIIF 解析(v2 sequences + v3 items 都认)────────────────────────────
def _size_url(u):
    if not u:
        return u
    u = re.sub(r"/full/[^/]+/0/default\.(jpg|png)$", f"/full/{IIIF_SIZE}/0/default.\\1", u, flags=re.I)
    u = re.sub(r"/full/[^/]+/0/default$", f"/full/{IIIF_SIZE}/0/default", u, flags=re.I)
    return u


def extract_images(man):
    """从单本 IIIF manifest 抽全部页图 URL。"""
    urls = []
    for seq in man.get("sequences") or []:                       # IIIF v2
        for canvas in seq.get("canvases", []):
            for img in canvas.get("images", []):
                res = img.get("resource", {})
                svc = res.get("service") or {}
                sid = svc.get("@id") or svc.get("id")
                u = (sid.rstrip("/") + f"/full/{IIIF_SIZE}/0/default.jpg") if sid else res.get("@id")
                u = _size_url(u)
                if u:
                    urls.append(u)
    if urls:
        return urls
    for item in man.get("items", []):                            # IIIF v3
        for page in item.get("items", []):
            for anno in page.get("items", []):
                body = anno.get("body", {})
                svc = body.get("service")
                svc = (svc[0] if isinstance(svc, list) and svc else svc or {})
                sid = (svc.get("@id") or svc.get("id")) if isinstance(svc, dict) else None
                u = (sid.rstrip("/") + f"/full/{IIIF_SIZE}/0/default.jpg") if sid else body.get("id")
                u = _size_url(u)
                if u:
                    urls.append(u)
    return urls


def resolve_book(man, manifest_url, source):
    """→ (书名, [(卷label, 子manifest_url, [页图urls]), ...])。处理多卷 collection。"""
    book = sanitize(manifest_name(man, source, ""))
    subs = man.get("manifests")
    if subs:
        vols = []
        log(f"多卷: {len(subs)} 卷")
        for s in subs:
            surl = s.get("@id") or s.get("id")
            label = s.get("label")
            if isinstance(label, list):
                label = label[0]
            try:
                vols.append((label, surl, extract_images(json.loads(http_get(surl)))))
            except Exception as e:
                log(f"  [E] 子卷失败 {label}: {e}")
            time.sleep(0.1)

        def vnum(x):
            m = re.search(r"(\d+)", str(x) or "")
            return int(m.group(1)) if m else 9999

        vols.sort(key=lambda v: vnum(v[0]))
        return book, vols
    return book, [(None, manifest_url, extract_images(man))]


def fetch_page(worker_id, num):
    """从 Worker 临时区拉单页 JPG。"""
    for _ in range(10):
        try:
            b = worker_call(f"/page?id={worker_id}&num={num}", timeout=60, retry=2)
            if b and len(b) > 2000:
                return b
        except Exception as e:
            log(f"     [p{num}] {e}")
            time.sleep(1)
    return None


def sync_book(manifest_url, source, out_dir, page_workers, upload_pdf, bu="", folder="", fname=""):
    log(f"R: {manifest_url}")
    try:
        man = json.loads(http_get(manifest_url))
    except Exception as e:
        log(f"[E] manifest 拉取失败: {e}")
        return False
    book, vols = resolve_book(man, manifest_url, source)
    if len([v for v in vols if v[2]]) == 0:
        log(f"[W] 「{book}」无图")
        return False
    log(f"「{book}」{len(vols)} 卷")
    id_tail = re.sub(r"[^0-9A-Za-z._-]+", "_", manifest_url.split("://", 1)[-1])[:40]
    ok_all = True
    for vi, (vlabel, vurl, imgs) in enumerate(vols, 1):
        if not imgs:
            continue
        pages = len(imgs)
        if len(vols) > 1:
            w = max(2, len(str(len(vols))))
            book_v, id_v = f"{book}v{vi:0{w}d}", f"{id_tail}_v{vi}"
        else:
            book_v, id_v = book, id_tail
        # 本地 PDF 路径:out/部/夹名/{fname或书名}.pdf
        pdir = out_dir
        if bu:
            pdir = os.path.join(pdir, sanitize(str(bu)))
        if folder:
            pdir = os.path.join(pdir, sanitize(str(folder)))
        base = sanitize(str(fname)) if fname else book_v
        if len(vols) > 1 and fname:
            base = f"{base}v{vi:0{max(2, len(str(len(vols))))}d}"
        pdf_name = f"{base}.pdf"
        pdf_path = os.path.join(pdir, pdf_name)
        # R2 路径 + 末页门牌(补漏检查:末页在=整本齐)
        r2_dir = f"{source}/{book_v}_{id_tail}"
        r2_pdf, r2_last = f"{r2_dir}/{pdf_name}", f"{r2_dir}/p{pages:05d}.webp"
        if r2_exists(r2_pdf) or r2_exists(r2_last):
            log(f"  [skip] {book_v} 已齐")
            continue
        log(f"同步 {book_v} {pages}p → 触发云端抓取...")
        # 触发 Worker 把该卷抓进临时区,轮询直到齐
        st = f"/status?id={id_v}&manifest={urllib.parse.quote(vurl)}"
        dl = f"/download?id={id_v}&manifest={urllib.parse.quote(vurl)}"
        got = 0
        try:
            res = json.loads(worker_call(st, timeout=GET_TIMEOUT, retry=2).decode("utf-8"))
            if res.get("ok"):
                got = res.get("downloaded_count", 0)
        except Exception:
            pass
        tries = 0
        while got < pages and tries < 120:
            tries += 1
            try:
                d = json.loads(worker_call(dl, timeout=GET_TIMEOUT, retry=2).decode("utf-8"))
                s = json.loads(worker_call(st, timeout=GET_TIMEOUT, retry=2).decode("utf-8"))
                if s.get("ok"):
                    got = s.get("downloaded_count", 0)
                    log(f"     [c] {got}/{pages}")
                if d.get("status") == "completed":
                    break
            except Exception as e:
                log(f"     [W] {e}")
            time.sleep(2)
        if got < pages:
            log(f"   [F] {book_v} 云端未集齐 ({got}/{pages})")
            ok_all = False
            continue
        # 并发拉页 + 3 轮补抓
        log("  -> 拉页...")
        data = {}
        with ThreadPoolExecutor(max_workers=page_workers) as ex:
            futs = {ex.submit(fetch_page, id_v, p): p for p in range(1, pages + 1)}
            for f in as_completed(futs):
                data[futs[f]] = f.result()
        for _ in range(3):
            miss = [p for p in range(1, pages + 1) if not data.get(p)]
            if not miss:
                break
            time.sleep(0.6)
            with ThreadPoolExecutor(max_workers=min(page_workers, len(miss))) as ex:
                futs = {ex.submit(fetch_page, id_v, p): p for p in miss}
                for f in as_completed(futs):
                    b = f.result()
                    if b:
                        data[futs[f]] = b
        # 逐页:转 WebP 上 R2 + 拼 PDF
        up, bad, doc = 0, False, fitz.open()
        for p in range(1, pages + 1):
            jpg = data.get(p)
            if not jpg:
                log(f"   [E] 缺第 {p} 页")
                bad = True
                break
            try:
                im = Image.open(io.BytesIO(jpg))
                if im.mode != "RGB":
                    im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="WEBP", quality=WEBP_QUALITY)
                if r2_upload(f"{r2_dir}/p{p:05d}.webp", buf.getvalue()):
                    up += 1
            except Exception as e:
                log(f"   [E] 第 {p} 页 WebP: {e}")
                bad = True
                break
            try:
                imgpdf = fitz.open(stream=jpg, filetype="jpg")
                doc.insert_pdf(fitz.open("pdf", imgpdf.convert_to_pdf()))
                imgpdf.close()
            except Exception as e:
                log(f"   [E] 第 {p} 页 PDF: {e}")
                bad = True
                break
        if bad or up < pages:
            doc.close()
            log(f"   [F] {book_v} 不全,跳过(下次自动补)")
            ok_all = False
            continue
        # 落 PDF 到 F 盘(④落地);可选也上 R2
        try:
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            doc.save(pdf_path)
            doc.close()
            log(f"   [ok] {pdf_path}")
            if upload_pdf:
                with open(pdf_path, "rb") as f:
                    if r2_upload(r2_pdf, f.read()):
                        log(f"   [R2] {r2_pdf}")
            try:
                worker_call(f"/delete-temp?id={id_v}", timeout=20, retry=1)
            except Exception:
                pass
        except Exception as e:
            log(f"   [E] 存 PDF 失败: {e}")
            ok_all = False
    return ok_all


def main():
    ap = argparse.ArgumentParser(description="数字归乡下载引擎 v1")
    ap.add_argument("--csv", required=True, help="清单 CSV(需 manifest 列)")
    ap.add_argument("--source", required=True, help="馆名,决定命名规则:NDL/内閣/京大/普林…")
    ap.add_argument("--out", default=r"F:\数字归乡\PDF_成品", help="PDF 落盘根目录")
    ap.add_argument("--workers", type=int, default=10, help="单本页级并发")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 本(0=全部)")
    ap.add_argument("--shard-count", type=int, default=1, help="分片总数(matrix 用)")
    ap.add_argument("--shard-index", type=int, default=0, help="本分片序号(0 基)")
    ap.add_argument("--upload-pdf", action="store_true", help="PDF 也上 R2(默认只 WebP 上)")
    ap.add_argument("--result", default="", help="运行结果 CSV(账本);默认 _result_{源}_s{片}.csv")
    a = ap.parse_args()
    if not os.path.exists(a.csv):
        print(f"清单不存在: {a.csv}")
        sys.exit(1)
    os.makedirs(a.out, exist_ok=True)
    rows = list(csv.DictReader(open(a.csv, encoding="utf-8-sig")))
    log(f"清单 {len(rows)} 行")
    # 列名自适应
    col_m = col_t = col_bu = col_fo = col_fn = None
    for c in (rows[0].keys() if rows else []):
        cl = c.lower()
        if "manifest" in cl:
            col_m = c
        if any(k in cl or k in c for k in ["title", "書名", "书名", "题名"]):
            col_t = c
        if c == "部":
            col_bu = c
        if "夹名" in c:
            col_fo = c
        if cl == "fname" or "fname" in cl:
            col_fn = c
    if not col_m:
        log("[E] 清单缺 manifest 列")
        sys.exit(1)
    # 分片(matrix 并行:每 runner 只认领 i % shard_count == shard_index)
    if a.shard_count > 1:
        rows = [r for i, r in enumerate(rows) if i % a.shard_count == a.shard_index]
        log(f"分片 {a.shard_index}/{a.shard_count} → 本片 {len(rows)} 本")
    result_path = a.result or f"_result_{a.source}_s{a.shard_index}.csv"
    rf = open(result_path, "a", encoding="utf-8-sig", newline="")
    rw = csv.writer(rf)
    if os.stat(result_path).st_size == 0:
        rw.writerow(["manifest", "title", "status", "ts"])
    done = fail = seen = 0
    for r in rows:
        url = r.get(col_m)
        if not url or not str(url).startswith("http"):
            continue
        ok = sync_book(url, a.source, a.out, a.workers, a.upload_pdf,
                       r.get(col_bu, "") if col_bu else "",
                       r.get(col_fo, "") if col_fo else "",
                       r.get(col_fn, "") if col_fn else "")
        rw.writerow([url, r.get(col_t, "") if col_t else "", "done" if ok else "fail",
                     time.strftime("%Y-%m-%d %H:%M:%S")])
        rf.flush()
        done += ok
        fail += (not ok)
        seen += 1
        if a.limit and seen >= a.limit:
            break
    rf.close()
    log(f"完成: done {done} / fail {fail} / 共 {seen}。账本: {result_path}")


if __name__ == "__main__":
    main()
