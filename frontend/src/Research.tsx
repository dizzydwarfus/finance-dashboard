import { lazy, Suspense, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { components } from './api.generated';
import { api } from './api';
import { factValue, sourceLink } from './sec-api';
const Chart = lazy(() => import('./Chart'));

export type ResearchTable = components['schemas']['ResearchTable'];
type Period = components['schemas']['ResearchPeriod'];
type Cell = components['schemas']['ResearchCell'];
const modeNames = { annual: 'Annual', quarter: 'Standalone quarter', ytd: 'Year to date' } as const;
const issues: Record<string, string> = {
  not_reported: 'Not reported', conflicting_values: 'Conflicting reported values', conflicting_units: 'Incompatible units',
  invalid_value: 'Invalid reported value', missing_inputs: 'Required inputs unavailable', zero_denominator: 'Zero denominator',
  unexpected_capex_sign: 'Unexpected capital expenditure sign',
};

export function periodLabel(period: Period) {
  return period.fiscalYear && period.fiscalPeriod ? `${period.fiscalYear} ${period.fiscalPeriod} · ${period.end}` : period.end;
}

export function ReportedCell({ cell }: { cell?: Cell }) {
  const text = cell?.value == null ? '—' : cell.unit === 'ratio'
    ? new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 2 }).format(Number(cell.value))
    : `${factValue(cell.value)}${cell.unit && !cell.unit.includes('{') ? ` ${cell.unit}` : ''}`;
  return <><span>{text}</span>
    {cell?.issue && <small className="cell-note">{issues[cell.issue] || cell.issue}</small>}
    {!!cell?.sources.length && <small className="cell-note">{[...new Map(cell.sources.map(source => [source.accession, source])).values()].map(source =>
      <a key={source.accession} title={source.accession} href={sourceLink(source.url)} target="_blank" rel="noreferrer">{source.form} ↗</a>)}</small>}
  </>;
}

export default function Research({ symbol, view, theme, metrics }: {
  symbol: string;
  view: 'overview' | 'statements';
  theme: string;
  metrics: { data?: ResearchTable; error: Error | null; isPending: boolean; refetch: () => unknown };
}) {
  const [selection, setSelection] = useState<keyof typeof modeNames | ''>('');
  const [kind, setKind] = useState('income');
  const [limit, setLimit] = useState('10');
  const [selectedMetric, setSelectedMetric] = useState('revenue');
  const series = metrics.data?.rows;
  const mode = selection || (series?.some(row => row.period.mode === 'annual') ? 'annual' : series?.some(row => row.period.mode === 'quarter') ? 'quarter' : series?.some(row => row.period.mode === 'ytd') ? 'ytd' : 'annual');
  const prefix = `/companies/${encodeURIComponent(symbol)}`;
  const path = `${prefix}/statements/${kind}?period=${mode}&limit=${limit}`;
  const statements = useQuery({
    queryKey: ['research-statements', symbol, kind, mode, limit],
    queryFn: ({ signal }) => api<ResearchTable>(path, signal),
    enabled: view === 'statements',
    retry: false,
  });
  const rows = useMemo(() => (series || []).filter(row => row.period.mode === mode).slice(0, Number(limit)), [series, mode, limit]);
  const metric = metrics.data?.fields.find(field => field.key === selectedMetric);
  const option = useMemo(() => {
    const points = [...rows].reverse();
    const units = [...new Set(points.flatMap(row => {
      const cell = row.values[selectedMetric];
      return cell?.value == null ? [] : [cell.unit];
    }))];
    const unit = units[0];
    if (units.length !== 1) return null;
    const chartValues = points.map(row => {
      const v = row.values[selectedMetric]?.value;
      if (v == null || !Number.isFinite(Number(v))) return null;
      return Number(v) * (unit === 'ratio' ? 100 : 1);
    });
    return {
      tooltip: { trigger: 'axis' }, legend: { show: true },
      grid: { left: 72, right: 70, bottom: 40, top: 60 },
      xAxis: { type: 'category', data: points.map(row => row.period.end) },
      yAxis: [{ type: 'value', name: unit === 'ratio' ? '%' : unit }, { type: 'value', name: 'YoY %' }],
      series: [{ name: metric?.label || selectedMetric, type: 'line', data: chartValues },
        { name: 'YoY growth', type: 'bar', yAxisIndex: 1, data: points.map(row => row.growth?.[selectedMetric] == null ? null : 100 * row.growth[selectedMetric]!) }],
    };
  }, [rows, selectedMetric, metric]);
  const table = statements.data;
  return <section className="panel" aria-label={view === 'overview' ? 'Overview' : 'Financial statements'}>
    <div className="panel-header"><h2>{view === 'overview' ? 'Financial trends' : 'Financial statements'}</h2>
      {view === 'statements' && table && <a href={`/api/v1${path}&format=csv`} download>Download statement CSV</a>}
    </div>
    <div className="sec-filters">
      {view === 'statements' && <label>Statement<select aria-label="Statement" value={kind} onChange={event => setKind(event.target.value)}>
        <option value="income">Income statement</option><option value="balance">Balance sheet</option><option value="cash-flow">Cash flow</option>
      </select></label>}
      <label>Reporting period<select aria-label="Reporting period" value={mode} onChange={event => setSelection(event.target.value as keyof typeof modeNames)}>
        {Object.entries(modeNames).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select></label>
      <label>Periods shown<select value={limit} onChange={event => setLimit(event.target.value)}><option>5</option><option>10</option><option>20</option><option>50</option></select></label>
      {view === 'overview' && !!metrics.data?.fields.length && <label>Metric<select value={selectedMetric} onChange={event => setSelectedMetric(event.target.value)}>
        {metrics.data.fields.map(field => <option key={field.key} value={field.key}>{field.label}</option>)}
      </select></label>}
    </div>
    {view === 'overview' && <>
      {metrics.isPending && <p role="status">Loading trends…</p>}
      {metrics.error && <p role="alert">{metrics.error.message} <button onClick={() => void metrics.refetch()}>Try again</button></p>}
      {metrics.data && !rows.length && <p>No mapped SEC financials for this period. Open Filings to inspect the reported facts.</p>}
      {option && <Suspense fallback={<p>Loading chart…</p>}><Chart option={option} theme={theme} title={`${metric?.label || 'Financial metric'} trend`} /></Suspense>}
      {!!rows.length && <div className="table-scroll"><table><thead><tr><th scope="col">Period ending</th><th scope="col">{metric?.label || selectedMetric}</th><th scope="col">Year over year</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.period.end + row.period.start}><th scope="row">{periodLabel(row.period)}</th>
          <td><ReportedCell cell={row.values[selectedMetric]} /></td><td>{row.growth?.[selectedMetric] == null ? '—' : new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 }).format(row.growth[selectedMetric]!)}</td></tr>)}</tbody>
      </table></div>}
    </>}
    {view === 'statements' && <>
      {statements.isPending && <p role="status">Loading statements…</p>}
      {statements.error && <p role="alert">{statements.error.message} <button onClick={() => void statements.refetch()}>Try again</button></p>}
      {table && !table.rows.length && <p>No mapped values for this statement and reporting period.</p>}
      {!!table?.rows.length && <div className="table-scroll"><table><thead><tr><th scope="col">Financial line</th>
        {table.rows.map(row => <th scope="col" key={row.period.end + row.period.start}>{periodLabel(row.period)}</th>)}
      </tr></thead><tbody>{table.fields.map(field => <tr key={field.key}><th scope="row">{field.label}</th>
        {table.rows.map(row => <td key={row.period.end + row.period.start}><ReportedCell cell={row.values[field.key]} /></td>)}
      </tr>)}</tbody></table></div>}
    </>}
  </section>;
}
