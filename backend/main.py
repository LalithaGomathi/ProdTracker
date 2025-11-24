from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from io import StringIO
from datetime import datetime
import os, csv

app = FastAPI(title="Productivity Tracker API")
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'sample_data')
DEFAULT_SHIFT_HOURS = 8

def parse_tickets_csv(content: str):
    df = pd.read_csv(StringIO(content), parse_dates=['start_time','end_time'])
    return df

def parse_calls_csv(content: str):
    df = pd.read_csv(StringIO(content), parse_dates=['start_time','end_time'])
    return df

def clip_to_period(df, start_period, end_period):
    df['start_time_clipped'] = df['start_time'].clip(lower=start_period, upper=end_period)
    df['end_time_clipped'] = df['end_time'].clip(lower=start_period, upper=end_period)
    df = df[df['end_time_clipped'] > df['start_time_clipped']]
    return df

def compute_agent_metrics(events_df, start_period, end_period, overlap_mode='split', default_shift_hours=DEFAULT_SHIFT_HOURS):
    agents = events_df['agent'].unique().tolist()
    out = []
    for agent in agents:
        adf = events_df[events_df['agent']==agent].copy()
        intervals = adf[['start_time_clipped','end_time_clipped']].sort_values('start_time_clipped').to_numpy()
        productive = 0
        if len(intervals)>0:
            merged = []
            for s,e in intervals:
                if not merged:
                    merged.append([s,e])
                else:
                    if s <= merged[-1][1]:
                        if e > merged[-1][1]:
                            merged[-1][1] = e
                    else:
                        merged.append([s,e])
            productive = sum((e - s).total_seconds() for s,e in merged)
        business_days = pd.bdate_range(start=start_period.date(), end=end_period.date()).size
        scheduled_seconds = business_days * default_shift_hours * 3600
        utilization = (productive / scheduled_seconds) if scheduled_seconds>0 else 0
        cat = adf.copy()
        cat['duration_s'] = (cat['end_time_clipped'] - cat['start_time_clipped']).dt.total_seconds()
        cat_avg = cat.groupby('category')['duration_s'].mean().to_dict()
        out.append({
            'agent': agent,
            'productive_seconds': int(productive),
            'scheduled_seconds': int(scheduled_seconds),
            'utilization': round(utilization,4),
            'avg_handle_time_by_category_seconds': {k:int(v) for k,v in cat_avg.items()}
        })
    return out

@app.post('/process')
async def process_files(tickets: UploadFile = File(None), calls: UploadFile = File(None),
                        start_period: str = Form(...), end_period: str = Form(...),
                        overlap_mode: str = Form('split'), default_shift_hours: int = Form(DEFAULT_SHIFT_HOURS)):
    start_p = pd.to_datetime(start_period)
    end_p = pd.to_datetime(end_period)
    dfs = []
    if tickets is not None:
        tcont = (await tickets.read()).decode()
        tdf = parse_tickets_csv(tcont)
        tdf = clip_to_period(tdf, start_p, end_p)
        tdf['category'] = tdf.get('category','ticket').fillna('ticket')
        dfs.append(tdf)
    if calls is not None:
        ccont = (await calls.read()).decode()
        cdf = parse_calls_csv(ccont)
        cdf = clip_to_period(cdf, start_p, end_p)
        cdf['category'] = cdf.get('category','call').fillna('call')
        dfs.append(cdf)
    if not dfs:
        return JSONResponse({'error':'no files provided'}, status_code=400)
    events = pd.concat(dfs, ignore_index=True, sort=False)
    events = clip_to_period(events, start_p, end_p)
    results = compute_agent_metrics(events, start_p, end_p, overlap_mode=overlap_mode, default_shift_hours=default_shift_hours)
    return {'start_period': str(start_p), 'end_period': str(end_p), 'overlap_mode': overlap_mode, 'results': results}

@app.post('/export/csv')
async def export_csv(tickets: UploadFile = File(None), calls: UploadFile = File(None),
                     start_period: str = Form(...), end_period: str = Form(...),
                     overlap_mode: str = Form('split'), default_shift_hours: int = Form(DEFAULT_SHIFT_HOURS)):
    resp = await process_files(tickets,calls,start_period,end_period,overlap_mode,default_shift_hours)
    if isinstance(resp, dict) and resp.get('results') is None:
        return JSONResponse({'error':'processing failed'}, status_code=400)
    payload = resp
    rows = []
    for r in payload['results']:
        rows.append({
            'agent': r['agent'],
            'productive_hours': r['productive_seconds']/3600,
            'scheduled_hours': r['scheduled_seconds']/3600,
            'utilization_percent': r['utilization']*100,
            'idle_hours': max(0, (r['scheduled_seconds'] - r['productive_seconds'])/3600)
        })
    out_path = os.path.join('/tmp','productivity_export.csv')
    keys = ['agent','productive_hours','scheduled_hours','utilization_percent','idle_hours']
    with open(out_path,'w',newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return FileResponse(out_path, media_type='text/csv', filename='productivity_export.csv')
