# -*- coding: utf-8 -*-
"""统一命名模块(单一真相源): manifest官方元数据 → 规范文件名。下载器+重命名脚本共用。
铁律: 用官网label/metadata,不自己编。按馆适配,输出 人能看懂"什么书 第几册 谁写 哪年"。"""
import re

_NENGO = r'(明治|大正|昭和|平成|令和|嘉永|安政|文化|文政|天保|弘化|万延|元治|慶応|慶長|寛文|寛政|享保|宝暦|明和|安永|天明|寛延|延享|宝永|正徳|享和|文久|延宝|天和|貞享|元禄|正保|慶安|承応|明暦|万治|寛永|元和|文禄|永禄|天文|享徳|応永|嘉吉|文明|延徳|大永|天正|至徳|康暦|永和|貞治|観応)'

def _lbl(x):
    if isinstance(x, list): x = x[0] if x else ""
    if isinstance(x, dict):
        v = next(iter(x.values()), "")
        x = (v[0] if isinstance(v, list) and v else v)
    return str(x).strip()

def parse_manifest(man):
    """→ (label, {metadata_key: value})"""
    label = _lbl(man.get("label", ""))
    meta = {}
    for it in (man.get("metadata") or []):
        k = _lbl(it.get("label", "")); v = _lbl(it.get("value", ""))
        if k: meta[k] = v
    return label, meta

def nengo(s):
    m = re.search(_NENGO + r'\s*([元\d]+)', str(s))
    return (m.group(1) + m.group(2)) if m else ""

def clean_author(a):
    a = re.sub(r'^著者[:：]', '', a)                    # 内閣"著者:"
    a = re.split(r'\|\|', a)[0]                          # NDL多作者取首
    a = re.sub(r'^[\[（(][明清宋元唐漢晉隋金遼後周梁陳齊魏][\]）)]\s*', '', a)  # BUG-08: 去[明]式朝代标注
    a = re.sub(r'^[明清宋元唐漢晉隋金遼後周梁陳齊魏][\s・·]+(?=[㐀-鿿])', '', a)  # BUG-08: 朝代字后须有分隔符才去(防误删陳念祖/唐慎微/魏荔彤姓氏)
    a = re.sub(r'[（(][^）)]*[）)]', '', a)              # 去括号注(漢)
    a = re.sub(r'[撰編校註注輯著纂閲訂述録集修删補刊輯録校訂]+\s*$', '', a).strip()  # 去尾职衔
    return norm_name(a)

def norm_name(a):
    """人名去内部空格,跨馆统一(吉益 南涯→吉益南涯,与NDL一致)"""
    a = re.sub(r'(?<=[㐀-鿿])\s+(?=[㐀-鿿])', '', a.strip())
    return re.sub(r'\s{2,}', ' ', a).strip()

def sanitize(name):
    """只去Windows非法字符 + 折叠空格"""
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', name).strip()
    t = re.sub(r'\s{2,}', ' ', t)
    return t[:200] if t else "untitled"

def pull_vol(base):
    """铁律: 从label抽册次/卷次 → ('卷NN'补零, 去掉册次的base)。
    认 '. [5]' / '[5]' / 'Vol. 5' / '. 5' 尾注。无则 ('', base原样)。"""
    s = str(base)
    m = re.search(r'(?:Vol\.?\s*)(\d+)\s*$', s) \
        or re.search(r'\.?\s*\[\s*(\d+)\s*\]', s) \
        or re.search(r'\s\.\s*(\d{1,3})\s*$', s)   # BUG-05: 须空格+点+≤3位,防误把书名尾年代(1868)当册次
    if not m:
        return ("", s.strip(" ."))
    vno = "卷%02d" % int(m.group(1))
    nb = (s[:m.start()] + " " + s[m.end():]).strip(" .")
    nb = re.sub(r'\s{2,}', ' ', nb)
    return (vno, nb)

def assemble(book, author, year, volno):
    """铁律装配: 书名 总卷 责任者 年号 卷NN (总卷已含在book里)。"""
    parts = [book]
    if author and author not in book: parts.append(author)
    if year: parts.append(year)
    if volno: parts.append(volno)
    return sanitize(" ".join(p for p in parts if p))

def has_cjk(s):
    return bool(re.search(r'[㐀-鿿]', s or ''))

def extract_cjk_title(s):
    """从混合串抽中文主名(去罗马音/法文/编号): 取最长的汉字+中文标点连续段。"""
    if not s: return ""
    runs = re.findall(r'[㐀-鿿](?:[㐀-鿿0-9一二三四五六七八九十百千零兩卷册冊上中下首附錄録目篇·、，．。.\-~～]| (?=[㐀-鿿]))*', str(s))  # BUG-06: 仅单空格且后接汉字才连,防两段无关书名被空格拼成一个
    return max(runs, key=len).strip(' ·-~～') if runs else ""

def manifest_name(man, source="", csv_title=""):
    """按馆适配出规范名(不含.pdf)。man=manifest dict。"""
    label, meta = parse_manifest(man)
    s = (source or "").upper()

    if "NDL" in s:
        # label已含书名+总卷+册次(本草綱目52卷. [5]). 铁律: 抽册次→末尾卷NN, 责任者+年号在前
        vno, base = pull_vol(label or csv_title)
        au = clean_author(meta.get("Creator", ""))
        yr = nengo(meta.get("Publication Date", ""))
        return assemble(base, au, yr, vno)

    if "NIJL" in s or "国文研" in source:
        # label不稳(有时章节)→用metadata.Title; +Author+年号 区分异版
        title = meta.get("Title") or label or csv_title
        title = title.replace("/", " ")                 # 傷寒論/太陽中篇 → 傷寒論 太陽中篇
        au = norm_name(meta.get("Author") or "")         # 吉益 南涯→吉益南涯
        yr = nengo(meta.get("Date", ""))
        parts = [title] + ([au] if au and au not in title else []) + ([yr] if yr else [])
        return sanitize(" ".join(parts))

    if "内閣" in source or "NAIKAKU" in s:
        # label=书名(+册号). 作者去"著者:". 年代00000000无效跳过
        base = label or meta.get("タイトル(Title)") or csv_title
        au = clean_author(meta.get("作成・取得部局(Creator)", ""))
        parts = [base] + ([au] if au and au not in base else [])
        return sanitize(" ".join(parts))

    if "京大" in source or "KYODAI" in s:
        # label=书名卷数(干净), metadata是HTML脏数据不用
        return sanitize(label or csv_title)

    if "BSB" in s:
        # label是罗马音(Xue shi yi an. 1. han 12 ce). 用CSV中文书名 + label函册号
        han = re.search(r'(\d+)\.\s*han', label)         # "1. han" → 第1函
        ce  = re.search(r'(\d+)\s*ce', label)
        author = meta.get("en", "")                      # BSB中文作者在en字段
        parts = [csv_title or label]
        if han: parts.append(f"第{han.group(1)}函")
        if ce: parts.append(f"第{ce.group(1)}册")   # BUG-07: 册次也入名,防同函多册文件名相同互覆
        if author and author not in (csv_title or ""): parts.append(author)
        return sanitize(" ".join(parts))

    # 普林/Gallica/柏林/梵蒂冈/archive/ÖNB/默认: 要干净中文名(去罗马音/法文/编号)
    ct = csv_title or ""; lt = label or ""
    if has_cjk(ct):
        return sanitize(ct if not re.search(r'[A-Za-z]', ct) else (extract_cjk_title(ct) or ct))
    if has_cjk(lt):
        return sanitize(extract_cjk_title(lt) or lt)
    return sanitize(ct or lt)
