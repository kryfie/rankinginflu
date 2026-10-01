import argparse, json, sys
from pathlib import Path
from apps.scanner.scanner.db import connect, save_snapshot, DEFAULT_DB, utcnow
from apps.scanner.scanner.tiktok_public import TikTokPublicProvider
from apps.scanner.scanner.provider import PublicAccessLimitedError
from packages.classifier.pl_classifier import pl_confidence, infer_category
from packages.ranking.ranking import build_ranking

ROOT=Path(__file__).resolve().parents[3]; CONFIG=ROOT/'apps'/'scanner'/'config'; WEB_DATA=ROOT/'apps'/'web'/'data'/'creators.json'
def _lines(path):
    path=Path(path)
    if not path.exists(): return []
    return [x.strip() for x in path.read_text(encoding='utf-8').splitlines() if x.strip() and not x.lstrip().startswith('#')]
def _classifier_text(s): return ' '.join([s.bio]+[p.description for p in s.posts])

def scan_handles(handles,posts,db_path,seed_context=False):
    conn=connect(db_path); provider=TikTokPublicProvider(); ok=0
    try:
        for h in handles:
            try: snap=provider.get_creator(h,posts_limit=posts)
            except PublicAccessLimitedError as e: print(f'STOP: {e}',file=sys.stderr); break
            except Exception as e: print(f'WARN @{h.lstrip("@")} : {e}',file=sys.stderr); continue
            if not snap: print(f'WARN @{h.lstrip("@")} : no public profile payload found',file=sys.stderr); continue
            text=_classifier_text(snap); conf=pl_confidence(text,seed_context); cat=infer_category(text)
            save_snapshot(conn,snap,conf,cat); print(f'OK @{snap.handle}: followers={snap.followers:,}, posts={len(snap.posts)}, PL={conf:.0f}, category={cat or "-"}'); ok+=1
    finally: provider.close(); conn.close()
    return ok

def export_web(db_path):
    conn=connect(db_path); ranking=build_ranking(conn); conn.close(); payload={'generated_at':utcnow(),'source':'scanner-v0.5','creators':ranking}; WEB_DATA.parent.mkdir(parents=True,exist_ok=True); WEB_DATA.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); print(f'Exported {len(ranking)} creators -> {WEB_DATA}')

def cmd_discover(args):
    hashtags=_lines(args.hashtags); conn=connect(args.db); run_id=conn.execute('INSERT INTO discovery_runs(started_at,source,status) VALUES(?,?,?)',(utcnow(),'hashtags','running')).lastrowid; conn.commit(); conn.close()
    provider=TikTokPublicProvider(); discovered=[]; seen=set()
    try:
        for tag in hashtags:
            if len(discovered)>=args.limit: break
            try: handles=provider.discover_from_hashtag(tag)
            except PublicAccessLimitedError as e: print(f'STOP: {e}',file=sys.stderr); break
            except Exception as e: print(f'WARN #{tag}: {e}',file=sys.stderr); continue
            print(f'#{tag}: {len(handles)} handles')
            for h in handles:
                if h.lower() not in seen: seen.add(h.lower()); discovered.append(h)
                if len(discovered)>=args.limit: break
    finally: provider.close()
    print(f'Discovered unique handles: {len(discovered)}'); ok=scan_handles(discovered,args.posts,args.db,True)
    conn=connect(args.db); conn.execute('UPDATE discovery_runs SET finished_at=?,status=?,discovered_handles=?,scanned_profiles=? WHERE id=?',(utcnow(),'done',len(discovered),ok,run_id)); conn.commit(); conn.close(); export_web(args.db)

def main():
    p=argparse.ArgumentParser(description='InfluRank TikTok scanner v0.5'); sub=p.add_subparsers(dest='cmd',required=True)
    d=sub.add_parser('discover'); d.add_argument('--hashtags',default=str(CONFIG/'hashtags.txt')); d.add_argument('--limit',type=int,default=100); d.add_argument('--posts',type=int,default=10); d.add_argument('--db',default=str(DEFAULT_DB)); d.set_defaults(func=cmd_discover)
    s=sub.add_parser('scan-seeds'); s.add_argument('--seeds',default=str(CONFIG/'seed_creators.txt')); s.add_argument('--posts',type=int,default=10); s.add_argument('--db',default=str(DEFAULT_DB)); s.set_defaults(func=lambda a:(scan_handles(_lines(a.seeds),a.posts,a.db,False),export_web(a.db)))
    one=sub.add_parser('scan'); one.add_argument('handles',nargs='+'); one.add_argument('--posts',type=int,default=10); one.add_argument('--db',default=str(DEFAULT_DB)); one.set_defaults(func=lambda a:(scan_handles(a.handles,a.posts,a.db,False),export_web(a.db)))
    e=sub.add_parser('export'); e.add_argument('--db',default=str(DEFAULT_DB)); e.set_defaults(func=lambda a:export_web(a.db))
    args=p.parse_args(); args.func(args)
if __name__=='__main__': main()
