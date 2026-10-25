"""Complete, source-labelled game catalogue and independent browsing state."""
import hashlib
import json
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from xianniu_router.manager import search_key, fuzzy_match


def platform_for(title):
    title = title.casefold()
    if 'switch' in title or 'ns通用' in title: return 'switch'
    if any(word in title for word in ('ps5', 'ps4', 'xbox', '主机', 'playstation')): return 'console'
    return 'pc'


def validate_games(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError('官方游戏目录为空或格式异常，已保留上一次可用目录')
    result, ids = [], set()
    for row in rows:
        identity = int(row['id'])
        if identity <= 0 or identity in ids: raise ValueError('游戏目录包含重复或无效编号')
        title = str(row['title']).strip()[:200]
        if not title: raise ValueError('游戏目录缺少游戏名称')
        areas, area_ids = [], set()
        for area in row.get('areas', []):
            area_id = int(area['id'])
            if area_id > 0 and area_id not in area_ids:
                areas.append({'id':area_id, 'title':str(area.get('title', area_id))[:160]})
                area_ids.add(area_id)
        result.append({'id':identity, 'title':title, 'areas':areas,
            'is_free':row.get('is_free') if type(row.get('is_free')) is bool else None,
            'keywords':str(row.get('keywords',''))[:800], 'platform':platform_for(title),
            'hot':bool(row.get('hot')), 'icon':str(row.get('icon',''))[:1000]})
        ids.add(identity)
    return result


def parse_official_xml(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024: raise ValueError('官方目录文件过大')
    raw = path.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('不支持包含外部声明的目录文件')
    root = ET.fromstring(raw)
    rows = []
    for node in root.findall('./games/game'):
        if not node.get('id','').isdigit(): continue
        icon = node.get('icon','')
        rows.append({'id':int(node.get('id')), 'title':node.get('title',''),
            'is_free':True if node.get('is_free')=='1' else False if node.get('is_free')=='0' else None,
            'keywords':node.get('keywords',''), 'hot':node.get('is_hot') == '1',
            'icon':'https://picture.xianniu.com'+icon if icon.startswith('/') else '',
            'areas':[{'id':int(a.get('id')), 'title':a.get('title','')} for a in node.findall('area') if a.get('id','').isdigit()]})
    return validate_games(rows), hashlib.sha256(raw).hexdigest()


def official_catalog_paths(config):
    paths = []
    if config.get('official_catalog_path'): paths.append(Path(config['official_catalog_path']))
    for key in ('ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(key): paths.append(Path(os.environ[key])/'xianniu/gamedata/gamelist.xml')
    return list(dict.fromkeys(paths))


class CatalogRepository:
    def __init__(self, bundled, private, config):
        self.bundled, self.private, self.config = Path(bundled), Path(private), config
        self.cache = self.private/'game-catalog.json'
        self.info = {}
        self.games = []
        self.source_stamp = None

    def source(self):
        return next((p for p in official_catalog_paths(self.config) if p.is_file()),None)

    @staticmethod
    def stamp(path):
        stat=path.stat()
        return (str(path.resolve()),stat.st_mtime_ns,stat.st_size)

    def check_updates(self):
        path=self.source()
        if path is None:raise ValueError('未找到鲜牛官方客户端目录，继续使用已缓存游戏')
        if self.stamp(path)==self.source_stamp:return None
        previous=self.info.get('source_sha256')
        games=self.sync(path)
        return games if self.info.get('source_sha256')!=previous else None

    def sync(self, path=None):
        path = Path(path) if path else self.source()
        if path is None: raise ValueError('未找到鲜牛客户端目录，可选择其 gamedata/gamelist.xml 文件')
        stamp=self.stamp(path)
        games, digest = parse_official_xml(path)
        if self.stamp(path)!=stamp:raise ValueError('鲜牛正在更新目录，稍后自动重试')
        info = {'kind':'official_client', 'label':'鲜牛客户端目录', 'count':len(games),
                'source_sha256':digest, 'source_modified_at':int(path.stat().st_mtime), 'read_at':int(time.time())}
        self.private.mkdir(parents=True, exist_ok=True)
        temporary = self.cache.with_suffix('.tmp')
        temporary.write_text(json.dumps({'games':games,'info':info},ensure_ascii=False),encoding='utf-8')
        os.replace(temporary,self.cache)
        self.games, self.info = games, info
        self.source_stamp=stamp
        return games

    def load(self):
        try: return self.sync()
        except (OSError, ValueError, ET.ParseError, KeyError): pass
        try:
            cached = json.loads(self.cache.read_text(encoding='utf-8'))
            self.games = validate_games(cached['games'])
            self.info = {**cached['info'], 'kind':'cached', 'label':'上次同步的官方目录'}
        except (OSError, ValueError, KeyError, TypeError):
            self.games = validate_games(json.loads(self.bundled.read_text(encoding='utf-8')))
            self.info = {'kind':'bundled', 'label':'内置官方目录快照', 'count':len(self.games)}
        return self.games


class LibraryModel:
    def __init__(self, games, config):
        self.config = config
        self.replace(games)
        self.selected_id = config.get('library_selected_game', config.get('game_id'))
        if self.selected_id not in self.by_id: self.selected_id = None

    def replace(self, games):
        self.games = games
        self.by_id = {g['id']:g for g in games}
        self.keys = {g['id']:search_key(g['title']+' '+g.get('keywords','')) for g in games}
        if getattr(self,'selected_id',None) not in self.by_id: self.selected_id = None

    @property
    def selected(self): return self.by_id.get(self.selected_id)

    def page(self, query='', category='', offset=0, limit=24):
        if len(query) > 64: raise ValueError('搜索内容最多 64 个字符')
        if category not in ('','pc','console','switch','mine','recent'): raise ValueError('无效分类')
        if offset < 0 or not 1 <= limit <= 48: raise ValueError('无效分页')
        terms = [search_key(t) for t in query.split() if search_key(t)]
        favorites = self.config.get('favorite_games',[])
        recent = self.config.get('recent_games',[])
        found = []
        for game in self.games:
            identity = game['id']
            if category == 'mine' and identity not in favorites: continue
            if category == 'recent' and identity not in recent: continue
            if category in ('pc','console','switch') and game['platform'] != category: continue
            if query.strip().isdigit() and query.strip() != str(identity): continue
            if terms and not all(t == str(identity) or fuzzy_match(t,self.keys[identity]) for t in terms): continue
            found.append(game)
        if category == 'recent': found.sort(key=lambda g:recent.index(g['id']))
        total = len(found)
        offset = min(offset, ((total-1)//limit)*limit) if total else 0
        return {'games':found[offset:offset+limit], 'total':total, 'offset':offset, 'limit':limit}

    def select(self, identity):
        if identity not in self.by_id: raise ValueError('所选游戏不在当前目录中')
        self.selected_id = identity
        self.config['library_selected_game'] = identity
        self.config['recent_games'] = ([identity]+[x for x in self.config.get('recent_games',[]) if x != identity])[:32]
        return self.by_id[identity]

    def toggle_favorite(self, identity):
        if identity not in self.by_id: raise ValueError('游戏不存在')
        ids = self.config.setdefault('favorite_games',[])
        if identity in ids: ids.remove(identity)
        else: ids.append(identity)
        return identity in ids
