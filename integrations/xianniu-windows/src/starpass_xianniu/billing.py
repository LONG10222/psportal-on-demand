"""Use the official game's explicit free flag; never infer it from its name."""
import json
import sys
from pathlib import Path
from .library import official_catalog_paths,parse_official_xml,validate_games


def from_games(games,identity,source):
    game=next((row for row in games if row['id']==identity),None)
    flag=game.get('is_free') if game else None
    return {'kind':'free' if flag is True else 'paid' if flag is False else 'unknown','source':source}


def resolve_billing(config,private=None):
    identity=int(config['game_id'])
    for path in official_catalog_paths(config):
        if not path.is_file():continue
        try:games,_=parse_official_xml(path)
        except Exception:return {'kind':'unknown','source':'invalid_official_catalog'}
        return from_games(games,identity,'official_client')
    if private:
        try:
            rows=json.loads((Path(private)/'game-catalog.json').read_text(encoding='utf-8'))
            result=from_games(validate_games(rows['games']),identity,'official_cache')
            if result['kind']!='unknown':return result
        except (OSError,ValueError,KeyError,TypeError):pass
    bundled=(Path(sys._MEIPASS)/'catalog.json' if getattr(sys,'frozen',False) else
        Path(__file__).resolve().parents[3]/'xianniu-router/files/usr/share/xianniu-router/catalog.json')
    try:return from_games(validate_games(json.loads(bundled.read_text(encoding='utf-8'))),identity,'bundled_official_snapshot')
    except (OSError,ValueError,KeyError,TypeError):return {'kind':'unknown','source':'unavailable'}
