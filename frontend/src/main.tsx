import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import * as maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import * as echarts from 'echarts'
import './style.css'

type EventSummary = { event_id: string; detector_id: string; direction: string; lane_id: string; prediction_time: string; onset_time: string; termination_reason: string; label_15m: number | null; label_30m: number | null; label_60m: number | null }
type EventDetail = EventSummary & { onset_confirmed_at: string; recovery_time: string | null; followup_end: string; baseline_kmh: number; congestion_ratio: number; recovery_ratio: number; speed_kmh: number; speed_ratio: number }
type Detail = { event: EventDetail; detector: { latitude: number; longitude: number; road_description: string; metadata_direction: string; coordinate_caveat: string }; predictions: { status: 'available' | 'unavailable'; reason: string; values: Record<string, number | null> | null; model_id?: string }; notice: string }
type Point = { timestamp: string; available_at: string | null; speed_kmh: number | null; usable: boolean; present_slots: number; valid_slots: number; flow_slots: number; offline_slots: number | null; conflict_slots: number | null }
type Curve = { points: Point[]; notice: string }

async function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal })
  if (!res.ok) { let message = `${res.status} ${res.statusText}`; try { const body = await res.json(); message = body.detail || message } catch { /* preserve HTTP message */ }; throw new Error(message) }
  return res.json() as Promise<T>
}
const label = (value: number | null) => value === null ? 'Unknown / censored' : value === 1 ? 'Recovered within horizon' : 'Not recovered within horizon'
const time = (value: string | null) => value ? new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Hong_Kong', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) + ' HKT' : 'Not observed'

function DetectorMap({ lat, lon }: { lat: number; lon: number }) {
  const node = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!node.current) return
    let map: maplibregl.Map | undefined
    try {
      map = new maplibregl.Map({ container: node.current, center: [lon, lat], zoom: 14,
        style: { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] } })
      map.addControl(new maplibregl.NavigationControl(), 'top-right')
      new maplibregl.Marker({ color: '#dc2626' }).setLngLat([lon, lat]).addTo(map)
      map.on('error', () => setError('Map tiles may be unavailable; the coordinates below remain visible.'))
    } catch { setError('Map rendering unavailable (WebGL or network). Coordinates remain visible.') }
    return () => map?.remove()
  }, [lat, lon])
  return <><div className="map" ref={node} aria-label="Detector map"/>{error && <p className="warning">{error}</p>}<p>Current metadata position: {lat.toFixed(5)}, {lon.toFixed(5)}. Coordinates are approximate pending datum and historical-location review.</p></>
}

function SpeedChart({ detail, curve }: { detail: EventDetail; curve: Curve }) {
  const node = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!node.current) return
    const chart = echarts.init(node.current)
    const points = curve.points
    const x = points.map(p => time(p.timestamp))
    const mark = (name: string, value: string | null) => value && points.some(p => p.timestamp === value) ? [{ name, xAxis: time(value) }] : []
    chart.setOption({ tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 60, right: 24, top: 65, bottom: 75 },
      xAxis: { type: 'category', data: x, axisLabel: { rotate: 35, hideOverlap: true } }, yAxis: { type: 'value', name: 'Speed (km/h)', min: 0 },
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 5 }],
      series: [
        { name: 'Valid positive-flow median', type: 'line', connectNulls: false, showSymbol: true, data: points.map(p => p.usable ? p.speed_kmh : null),
          markLine: { symbol: 'none', data: [ { name: 'Congestion threshold', yAxis: detail.baseline_kmh * detail.congestion_ratio }, { name: 'Recovery threshold', yAxis: detail.baseline_kmh * detail.recovery_ratio }, ...mark('Onset', detail.onset_time), ...mark('Prediction', detail.prediction_time), ...mark('Recovery confirmation', detail.recovery_time), ...mark('Last follow-up', detail.followup_end) ] } },
        { name: 'Missing/unusable (axis marker)', type: 'scatter', symbol: 'cross', symbolSize: 9, data: points.map(p => p.usable && p.speed_kmh !== null ? null : 0) }
      ] })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { window.removeEventListener('resize', resize); chart.dispose() }
  }, [detail, curve])
  return <><div className="chart" ref={node} role="img" aria-label="Historical speed and thresholds"/><p>Crosses mark missing or unusable bins at the axis baseline, not zero-speed observations. The curve includes observations after prediction time.</p></>
}

function App() {
  const [events, setEvents] = useState<EventSummary[]>([])
  const [selected, setSelected] = useState('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [curve, setCurve] = useState<Curve | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => { const c = new AbortController(); get<{ items: EventSummary[] }>('/api/events?limit=200', c.signal).then(data => { setEvents(data.items); setSelected(data.items[0]?.event_id || ''); setLoading(false) }).catch(e => { if (e.name !== 'AbortError') { setError(e.message); setLoading(false) } }); return () => c.abort() }, [])
  useEffect(() => {
    if (!selected) return
    const c = new AbortController(); setDetail(null); setCurve(null); setError('')
    Promise.all([get<Detail>(`/api/events/${encodeURIComponent(selected)}`, c.signal), get<Curve>(`/api/events/${encodeURIComponent(selected)}/curve`, c.signal)])
      .then(([d, p]) => { setDetail(d); setCurve(p) }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => c.abort()
  }, [selected])
  return <main><header><p className="eyebrow">RESEARCH PILOT · HONG KONG</p><h1>Congestion recovery explorer</h1><p>Authentic historical observations, provisional retrospective labels. Not a live service or validated model.</p></header>
    <section className="notice"><strong>Scientific limits:</strong> 40 convenience-sample lane events; thresholds and baselines are provisional. Outcomes use future observations. No directed-road relationships are verified.</section>
    {loading && <p>Loading real event evidence…</p>}{error && <section role="alert" className="error"><strong>Data unavailable:</strong> {error}<p>Start the local API and reproduce the checksummed medium pilot as described in README.</p></section>}
    {events.length > 0 && <section><label htmlFor="event">Select historical event</label><select id="event" value={selected} onChange={e => setSelected(e.target.value)}>{events.map(e => <option key={e.event_id} value={e.event_id}>{time(e.prediction_time)} · {e.detector_id} · {e.direction} · {e.lane_id} · {e.event_id}</option>)}</select><p>{events.length} events in this local pilot. Lane samples may represent the same road episode.</p></section>}
    {detail && curve && <><div className="grid"><section><h2>Detector</h2><p><strong>{detail.event.detector_id}</strong> · {detail.event.direction} · {detail.event.lane_id}</p><p>{detail.detector.road_description}</p><DetectorMap lat={detail.detector.latitude} lon={detail.detector.longitude}/><p>{detail.detector.coordinate_caveat} Metadata direction: {detail.detector.metadata_direction}.</p></section>
    <section><h2>Recovery outcome</h2><p>Onset: {time(detail.event.onset_time)}<br/>Prediction time: {time(detail.event.prediction_time)}<br/>Recovery confirmation: {time(detail.event.recovery_time)}<br/>Follow-up end: {time(detail.event.followup_end)}</p><p>Follow-up: {detail.event.termination_reason.replaceAll('_', ' ')}</p><ul>{([15,30,60] as const).map(h => <li key={h}><strong>{h} min:</strong> {label(detail.event[`label_${h}m`])}</li>)}</ul><p><strong>Model prediction:</strong> {detail.predictions.status === 'available' && detail.predictions.values ? <>model {detail.predictions.model_id || '(model ID missing)'}: {Object.entries(detail.predictions.values).map(([h, v]) => `${h}: ${v === null ? 'unknown' : v}`).join(', ')}</> : <>unavailable — {detail.predictions.reason}</>}</p><p>Provisional historical reference: {detail.event.baseline_kmh.toFixed(1)} km/h; event-time speed: {detail.event.speed_kmh.toFixed(1)} km/h.</p></section></div>
    <section><h2>Historical speed and observation quality</h2><SpeedChart detail={detail.event} curve={curve}/><p>{curve.notice}</p><details><summary>Observation quality by bin</summary><div className="table"><table><thead><tr><th>Bin end</th><th>Speed km/h</th><th>Usable</th><th>Present</th><th>Valid</th><th>Positive flow</th><th>Offline</th><th>Conflicts</th><th>Available</th></tr></thead><tbody>{curve.points.map(p => <tr key={p.timestamp}><td>{time(p.timestamp)}</td><td>{p.speed_kmh ?? '—'}</td><td>{p.usable ? 'Yes' : 'No'}</td><td>{p.present_slots}</td><td>{p.valid_slots}</td><td>{p.flow_slots}</td><td>{p.offline_slots ?? '—'}</td><td>{p.conflict_slots ?? '—'}</td><td>{time(p.available_at)}</td></tr>)}</tbody></table></div></details></section></>}
    <footer>Source: Transport Department / DATA.GOV.HK; basemap © OpenStreetMap contributors. Local development only.</footer></main>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
