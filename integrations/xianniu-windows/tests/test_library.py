import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from starpass_xianniu.library import CatalogRepository, LibraryModel, parse_official_xml, validate_games


def fixtures(count=75):
    return validate_games([{'id':i+1,'title':('Switch ' if i%3==0 else 'PS5 ' if i%3==1 else 'PC ')+f'游戏 {i+1}',
        'keywords':f'game{i+1} youxi{i+1}','areas':[{'id':1000+i,'title':f'区服{i+1}'}]} for i in range(count)])


def write_xml(path,rows):
    root=ET.Element('root');games=ET.SubElement(root,'games')
    for row in rows:
        game=ET.SubElement(games,'game',id=str(row['id']),title=row['title'],keywords=row.get('keywords',''),icon='')
        if type(row.get('is_free')) is bool:game.set('is_free','1' if row['is_free'] else '0')
        for area in row['areas']:ET.SubElement(game,'area',id=str(area['id']),title=area['title'])
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)


class LibraryTests(unittest.TestCase):
    def test_official_free_flag_survives_xml_validation_and_cache_without_name_inference(self):
        from starpass_xianniu.billing import resolve_billing
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);xml=root/'gamelist.xml';bundled=root/'bundled.json'
            rows=fixtures(3)
            rows[0].update(title='Official free fixture',is_free=True)
            rows[1].update(title='Steam paid fixture',is_free=False)
            bundled.write_text(json.dumps(rows));write_xml(xml,rows)
            repo=CatalogRepository(bundled,root/'private',{'official_catalog_path':str(xml)})
            games=repo.load()
            self.assertIs(games[0]['is_free'],True);self.assertIs(games[1]['is_free'],False)
            self.assertIsNone(games[2]['is_free'])
            for identity,kind in ((1,'free'),(2,'paid'),(3,'unknown')):
                self.assertEqual(resolve_billing({'game_id':identity,'official_catalog_path':str(xml)})['kind'],kind)
            # A changed official rule takes precedence over previously cached metadata.
            rows[0]['is_free']=False;write_xml(xml,rows)
            self.assertEqual(resolve_billing({'game_id':1,'official_catalog_path':str(xml)})['kind'],'paid')
            self.assertEqual(resolve_billing({'game_id':1,'official_catalog_path':str(xml),'game_is_free':True})['kind'],'paid')
            xml.write_text('<broken')
            self.assertEqual(resolve_billing({'game_id':1,'official_catalog_path':str(xml)})['kind'],'unknown')
    def test_every_game_can_be_browsed_past_first_48(self):
        rows=fixtures(3018);model=LibraryModel(rows,{'game_id':1})
        ids=[]
        for offset in range(0,3018,24):ids.extend(g['id'] for g in model.page(offset=offset)['games'])
        self.assertEqual(ids,list(range(1,3019)))
        self.assertEqual(model.page(offset=3000)['games'][-1]['id'],3018)

    def test_search_categories_and_pages_never_change_selected_game(self):
        model=LibraryModel(fixtures(),{'game_id':70})
        for query,category,offset in [('', '',48),('game7','',0),('','switch',24),('no-such-title','',0)]:
            model.page(query,category,offset)
            self.assertEqual(model.selected_id,70)

    def test_individual_pick_favorite_and_recent_persist_without_starting(self):
        config={'game_id':1};model=LibraryModel(fixtures(),config)
        model.select(72);model.select(59);model.toggle_favorite(72)
        reopened=LibraryModel(fixtures(),json.loads(json.dumps(config)))
        self.assertEqual(reopened.selected_id,59)
        self.assertEqual([g['id'] for g in reopened.page(category='recent')['games']],[59,72])
        self.assertEqual([g['id'] for g in reopened.page(category='mine')['games']],[72])
        self.assertEqual(config['game_id'],1)
        model.toggle_favorite(72);self.assertEqual(model.page(category='mine')['total'],0)

    def test_search_numeric_id_and_keyword_beyond_first_page(self):
        model=LibraryModel(fixtures(),{})
        self.assertEqual(model.page('72')['games'][0]['id'],72)
        self.assertIn(72,[g['id'] for g in model.page('youxi72')['games']])
        self.assertTrue(all(g['platform']=='switch' for g in model.page(category='switch')['games']))

    def test_invalid_catalogue_cannot_replace_valid_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);xml=root/'gamelist.xml';bundled=root/'bundled.json'
            bundled.write_text(json.dumps(fixtures(3)));write_xml(xml,fixtures())
            repository=CatalogRepository(bundled,root/'private',{})
            self.assertEqual(len(repository.sync(xml)),75)
            good=repository.cache.read_bytes()
            xml.write_text('<root><games/></root>')
            with self.assertRaises(ValueError):repository.sync(xml)
            self.assertEqual(repository.cache.read_bytes(),good)

    def test_missing_client_uses_explicitly_labelled_cache_or_bundle(self):
        with tempfile.TemporaryDirectory() as temp,patch('starpass_xianniu.library.official_catalog_paths',return_value=[]):
            root=Path(temp);bundled=root/'bundled.json';bundled.write_text(json.dumps(fixtures(5)))
            repository=CatalogRepository(bundled,root/'private',{})
            self.assertEqual(len(repository.load()),5);self.assertEqual(repository.info['kind'],'bundled')
            xml=root/'gamelist.xml';write_xml(xml,fixtures(9));repository.sync(xml)
            self.assertEqual(len(repository.load()),9);self.assertEqual(repository.info['kind'],'cached')

    def test_xml_duplicates_and_entities_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'gamelist.xml';rows=fixtures(2);rows[1]['id']=rows[0]['id'];write_xml(path,rows)
            with self.assertRaises(ValueError):parse_official_xml(path)
            path.write_text('<!DOCTYPE root [<!ENTITY value "test">]><root/>')
            with self.assertRaises(ValueError):parse_official_xml(path)

    def test_automatic_official_file_update_adds_games_and_areas_without_rewriting_unchanged_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);xml=root/'gamelist.xml';bundled=root/'bundled.json'
            bundled.write_text(json.dumps(fixtures(2)));write_xml(xml,fixtures(3))
            repo=CatalogRepository(bundled,root/'private',{'official_catalog_path':str(xml)})
            repo.load();before=repo.cache.read_bytes()
            with patch('starpass_xianniu.library.parse_official_xml',side_effect=AssertionError('unchanged file reparsed')):
                self.assertIsNone(repo.check_updates())
            self.assertEqual(repo.cache.read_bytes(),before)
            rows=fixtures(4);rows[0]['areas'].append({'id':9001,'title':'new region'})
            write_xml(xml,rows)
            updated=repo.check_updates()
            self.assertEqual(len(updated),4)
            self.assertEqual(updated[0]['areas'][-1]['id'],9001)
            valid=repo.cache.read_bytes()
            xml.write_text('<invalid')
            with self.assertRaises(ET.ParseError):repo.check_updates()
            self.assertEqual(repo.cache.read_bytes(),valid)
            self.assertEqual(len(repo.games),4)


class LibraryUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from starpass_xianniu.app import App
        from starpass_xianniu.storage import Store
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.xml=root/'gamelist.xml';write_xml(self.xml,fixtures())
        self.patches=[patch('starpass_xianniu.library.official_catalog_paths',return_value=[self.xml]),
            patch('starpass_xianniu.game_grid.IconCache.read',return_value=None),
            patch('xianniu_router.control.call_api',return_value={'pause_state':0,'total_datetime':3600}),
            patch('starpass_xianniu.provider.Catalog.lines',return_value={'lines':[{'id':200,'title':'fixture-line'}],'all_lines':[],'total':1})]
        for item in self.patches:item.start()
        self.store=Store(root/'private');config=self.store.load();config.update(game_id=1,account={'access_token':'fixture-only'})
        config['profile']={'area_id':1000,'line_id':200};self.store.save(config)
        self.root=tk.Tk();self.app=App(self.root,self.store);self.pump(.1)

    def pump(self,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.root.update();time.sleep(.01)

    def tearDown(self):
        async def drain():
            tasks=[t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        asyncio.run_coroutine_threadsafe(drain(),self.app.loop).result(3)
        self.app.loop.call_soon_threadsafe(self.app.loop.stop);self.app.thread.join(2)
        self.app.loop.close()
        for timer in self.root.tk.call('after','info'):self.root.after_cancel(timer)
        self.root.destroy()
        for item in self.patches:item.stop()
        self.temp.cleanup()

    def test_cards_page_and_search_without_replacing_selected_plan(self):
        grid=self.app.library_grid
        self.assertEqual(len(grid.tiles),24)
        grid.change_page(2);self.pump(.05)
        self.assertIn(72,grid.tiles);self.assertEqual(self.app.selected_game['id'],1)
        grid.choose(self.app.library.by_id[72]);self.pump(.05)
        self.assertEqual(self.app.selected_game['id'],72)
        self.assertEqual(self.app.areas[0]['id'],1071)
        grid.set_category('console');grid.query.set('nonexistent');grid.reset()
        self.assertEqual(self.app.selected_game['id'],72)
        self.assertEqual(grid.result_var.get(),'找到 0 款 · 显示 0—0')

    def test_automatic_sync_updates_ui_but_preserves_selection_and_keeps_good_cache_on_failure(self):
        self.app.config['favorite_games']=[1,72]
        before=self.app.selected_game['id']
        rows=fixtures(76);write_xml(self.xml,rows)
        with patch.object(self.app,'start') as start:
            self.app.sync_catalog(automatic=True)
            deadline=time.monotonic()+3
            while self.app.catalog_syncing and time.monotonic()<deadline:self.pump(.02)
            self.assertFalse(self.app.catalog_syncing)
            self.assertIn(76,self.app.library.by_id)
            self.assertEqual(self.app.selected_game['id'],before)
            self.assertEqual(self.app.config['favorite_games'],[1,72])
            good=self.app.repository.cache.read_bytes()
            self.xml.write_text('<broken')
            self.app.sync_catalog(automatic=True)
            deadline=time.monotonic()+3
            while self.app.catalog_syncing and time.monotonic()<deadline:self.pump(.02)
            self.assertIn('缓存',self.app.catalog_status_var.get())
            self.assertEqual(self.app.repository.cache.read_bytes(),good)
            self.assertIn(76,self.app.library.by_id)
            start.assert_not_called()

    def test_reselecting_reads_changed_official_lines_instead_of_a_fixed_snapshot(self):
        with patch.object(self.app.catalog,'lines',side_effect=[
            {'lines':[{'id':201,'title':'old official line'}]},
            {'lines':[{'id':202,'title':'new official line'}]}]) as source:
            self.app.fetch_lines();self.pump(.25)
            self.assertEqual(self.app.lines[0]['id'],201)
            self.app.fetch_lines();self.pump(.25)
            self.assertEqual(self.app.lines[0]['id'],202)
            self.assertEqual(source.call_count,2)

    def test_late_line_response_cannot_overwrite_new_selection(self):
        def lines(game,area):
            if game==1:time.sleep(.25)
            return {'lines':[{'id':game*10,'title':f'line-{game}'}],'all_lines':[],'total':1}
        with patch.object(self.app.catalog,'lines',side_effect=lines):
            self.app.fetch_lines()
            self.app.library.select(72);self.app.select_game_id(72);self.app.fetch_lines()
            self.pump(.4)
            self.assertEqual(self.app.lines[0]['id'],720)
            self.assertEqual(self.app.selected_game['id'],72)

    def test_launch_and_paging_controls_remain_inside_small_window(self):
        self.root.geometry('1040x760');self.pump(.05)
        bottom=self.root.winfo_rooty()+self.root.winfo_height()
        for widget in (self.app.start_button,self.app.library_grid.next,self.app.area,self.app.line):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)


if __name__=='__main__':unittest.main()
