import { lazy, Suspense, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { components } from './api.generated';
import { api } from './api';
import { periodLabel, ReportedCell } from './Research';
import { conceptName } from './sec-api';
const Chart = lazy(() => import('./Chart'));

export default function SegmentTrend({ symbol, accession, fact, theme, onClose }: {
  symbol: string; accession: string; fact: string; theme: string; onClose: () => void;
}) {
  const query = new URLSearchParams({ accession, fact });
  const path = `/companies/${encodeURIComponent(symbol)}/segments?${query}`;
  const series = useQuery({
    queryKey: ['research-segment', symbol, accession, fact],
    queryFn: ({ signal }) => api<components['schemas']['SegmentSeries']>(path, signal),
    retry: false,
  });
  const data = series.data;
  const option = useMemo(() => {
    if (!data) return null;
    const values = data.points.map(point => point.cell.value == null ? null : Number(point.cell.value)).map(value => Number.isFinite(value) ? value : null);
    return {
      tooltip: { trigger: 'axis' }, grid: { left: 70, right: 35, bottom: 40, top: 40 },
      xAxis: { type: 'category', data: data.points.map(point => point.period.end) },
      yAxis: { type: 'value' }, series: [{ type: 'line', data: values }],
    };
  }, [data]);
  return <section className="panel" aria-label="Segment trends">
    <div className="panel-header"><h2>Segment trend</h2><button onClick={onClose}>Close trend</button></div>
    {series.isPending && <p role="status">Loading segment trend…</p>}
    {series.isError && <p role="alert">{series.error.message} <button onClick={() => void series.refetch()}>Try again</button></p>}
    {data && <>
      <p>{data.label || conceptName(data.concept)} · {data.dimensions.map(d => `${conceptName(d.axis)}: ${d.member ? conceptName(d.member) : d.typedValue}`).join(' · ')} · {data.unit.replace(/\{[^}]+\}/g, '')}</p>
      <a href={`/api/v1${path}&format=csv`} download>Download segment CSV</a>
      {option && <Suspense fallback={<p>Loading chart…</p>}><Chart option={option} theme={theme} title="Segment trend" /></Suspense>}
      <div className="table-scroll"><table><thead><tr><th scope="col">Reporting period</th><th scope="col">Reported value</th></tr></thead>
        <tbody>{data.points.map(point => <tr key={point.period.start + point.period.end}><th scope="row">{periodLabel(point.period)}</th><td><ReportedCell cell={point.cell} /></td></tr>)}</tbody>
      </table></div>
    </>}
  </section>;
}
