import { lazy, Suspense, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, readAPIResponse } from './api';
import type { components } from './api.generated';
import { conceptName } from './sec-api';
import { periodLabel, ReportedCell } from './Research';

const Chart = lazy(() => import('./Chart'));
type S = components['schemas'];
type Kind = 'explore' | 'compare' | 'model';
export async function mutate<T>(
  path: string,
  method: string,
  value?: unknown,
  revision?: number,
): Promise<T> {
  const response = await fetch('/api/v1' + path, {
    method,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(revision ? { 'If-Match': String(revision) } : {}),
    },
    body: value === undefined ? undefined : JSON.stringify(value),
  });
  const body = await readAPIResponse(response, 'Research workspace');
  if (!response.ok) throw new Error(body.error?.message || 'Request failed');
  return body.data as T;
}

export function Saves<T extends object>({
  kind,
  symbol,
  state,
  restore,
  ready = true,
}: {
  kind: Kind;
  symbol: string;
  state: T;
  restore: (value: T) => void;
  ready?: boolean;
}) {
  const [name, setName] = useState('');
  const [item, setItem] = useState<S['WorkspaceItem']>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const list = useQuery({
    queryKey: ['saved', kind, symbol],
    queryFn: ({ signal }) => api<S['WorkspaceItem'][]>(`/workspaces?kind=${kind}&symbol=${symbol}`, signal),
    retry: false,
  });
  async function act(action: 'open' | 'save' | 'copy' | 'delete', id?: string) {
    setBusy(true);
    setMessage('');
    try {
      if (action === 'open') {
        const saved = await api<S['WorkspaceItem']>('/workspaces/' + id);
        restore(saved.payload as T);
        setItem(saved);
        setName(saved.name);
      } else if (action === 'delete' && item) {
        await mutate('/workspaces/' + item.id, 'DELETE', undefined, item.revision);
        setItem(undefined);
        setName('');
        setMessage('Deleted saved item.');
      } else {
        const editing = action === 'save' && item;
        const saved = await mutate<S['WorkspaceItem']>(
          editing ? '/workspaces/' + editing.id : '/workspaces',
          editing ? 'PUT' : 'POST',
          { kind, symbol, name, payload: state },
          editing ? editing.revision : undefined,
        );
        setItem(saved);
        setName(saved.name);
        setMessage('Saved revision ' + saved.revision + '.');
      }
      await list.refetch();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h3>Saved {kind === 'model' ? 'models' : 'views'}</h3>
      <div className="sec-filters">
        <label>
          Open saved item
          <select disabled={busy} value="" onChange={(e) => void act('open', e.target.value)}>
            <option value="">Choose a saved item</option>
            {list.data?.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name} · v{x.revision}
              </option>
            ))}
          </select>
        </label>
        <label>
          Name
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </label>
        <button disabled={busy || !ready || !name.trim()} onClick={() => void act('save')}>
          {item ? 'Update saved item' : 'Save'}
        </button>
        {item && (
          <>
            <button disabled={busy || !ready || !name.trim()} onClick={() => void act('copy')}>
              Save a copy
            </button>
            <button
              disabled={busy}
              onClick={() => {
                if (confirm('Delete this saved item?')) void act('delete');
              }}
            >
              Delete
            </button>
          </>
        )}
      </div>
      {list.error && <p role="status">{list.error.message}</p>}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
export function Explore({ symbol, theme }: { symbol: string; theme: string }) {
  const [view, setView] = useState({
    q: '',
    through: '',
    id: '',
    concept: '',
    display: 'value',
    members: [] as string[],
  });
  const root = '/companies/' + encodeURIComponent(symbol);
  const catalog = useQuery({
    queryKey: ['dimensions', symbol, view.q, view.through],
    queryFn: ({ signal }) =>
      api<S['AnalystSlice'][]>(
        root + '/dimensions?q=' + encodeURIComponent(view.q) + '&through=' + encodeURIComponent(view.through),
        signal,
      ),
    retry: false,
  });
  const params = new URLSearchParams({
    slice: view.id,
    concept: view.concept,
    display: view.display,
    through: view.through,
  });
  const path = root + '/pivot?' + params;
  const result = useQuery({
    queryKey: [path],
    queryFn: ({ signal }) => api<S['Pivot']>(path, signal),
    enabled: !!view.id,
    retry: false,
  });
  const data = result.data;
  const shown = data?.members.filter((m) => !view.members.length || view.members.includes(m.name)) || [];
  for (const m of view.members) params.append('member', m);
  return (
    <>
      <section className="panel">
        <h2>Explore reported dimensions</h2>
        <div className="sec-filters">
          <label>
            Concept search
            <input
              value={view.q}
              placeholder="Revenue, inventory, customers…"
              onChange={(e) => setView({ ...view, q: e.target.value })}
            />
          </label>
          <label>
            Latest 12 filings through
            <input
              type="date"
              value={view.through}
              onChange={(e) => setView({ ...view, through: e.target.value, id: '', members: [] })}
            />
          </label>
          <label>
            Reported breakdown
            <select
              value={view.id}
              onChange={(e) => {
                const s = catalog.data?.find((x) => x.id === e.target.value);
                if (s) setView({ ...view, id: s.id, concept: s.concept, members: [] });
              }}
            >
              <option value="">Choose metric, axis, unit and period</option>
              {catalog.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label || conceptName(s.concept)} · {conceptName(s.axis)} · {s.mode} ·{' '}
                  {s.unit.replace(/\{[^}]*\}/g, '')}{' '}
                  {s.fixed
                    .map((d) => conceptName(d.axis) + '=' + conceptName(d.member || d.typedValue || ''))
                    .join(', ')}{' '}
                  · {s.concept}
                </option>
              ))}
            </select>
          </label>
          <label>
            Measure
            <select value={view.display} onChange={(e) => setView({ ...view, display: e.target.value })}>
              <option value="value">Reported value</option>
              <option value="growth">Year-over-year change</option>
              <option value="share">Share of reported total</option>
            </select>
          </label>
        </div>
        {catalog.isLoading && <p>Finding reported dimensions…</p>}
        {catalog.error && <p role="alert">{catalog.error.message}</p>}
        {catalog.data?.length === 0 && <p>No matching reported dimensions.</p>}
        {catalog.data?.length === 200 && <p>Showing 200 breakdowns. Narrow the concept search for more.</p>}
        {result.isLoading && <p>Loading reported values…</p>}
        {result.error && <p role="alert">{result.error.message}</p>}
        {data && (
          <>
            <label>
              Members
              <select
                multiple
                aria-label="Members"
                value={view.members}
                onChange={(e) =>
                  setView({ ...view, members: Array.from(e.target.selectedOptions, (o) => o.value) })
                }
              >
                {data.members.map((m) => (
                  <option key={m.name} value={m.name}>
                    {conceptName(m.name)}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={() => setView({ ...view, members: [] })}>Show all members</button>
            <a href={`/api/v1${root}/pivot?${params}&format=csv`} download>
              Download pivot CSV
            </a>
            <Suspense fallback={<p>Loading chart…</p>}>
              <Chart
                theme={theme}
                title="Reported member comparison"
                option={{
                  tooltip: { trigger: 'axis' },
                  legend: { type: 'scroll' },
                  grid: { containLabel: true },
                  xAxis: { type: 'category', data: data.periods.map(periodLabel) },
                  yAxis: { type: 'value', name: view.display === 'value' ? '' : '%' },
                  series: shown.map((m) => ({
                    name: conceptName(m.name),
                    type: 'line',
                    data: m.cells.map((c) =>
                      c.value === null ? null : Number(c.value) * (view.display === 'value' ? 1 : 100),
                    ),
                  })),
                }}
              />
            </Suspense>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Member</th>
                    {data.periods.map((p) => (
                      <th key={p.start + p.end}>{periodLabel(p)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((m) => (
                    <tr key={m.name}>
                      <th title={m.name}>{conceptName(m.name)}</th>
                      {m.cells.map((c, i) => (
                        <td key={i}>
                          <ReportedCell cell={c} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      <Saves kind="explore" symbol={symbol} state={view} restore={setView} ready={!!data} />
    </>
  );
}
const peerFields = {
  revenueGrowth: 'Revenue growth (YoY)',
  operatingMargin: 'Operating income / revenue',
  cashConversion: 'Operating cash flow / net income',
  capitalIntensity: 'Capex / revenue',
};
export function Compare({ symbol, theme }: { symbol: string; theme: string }) {
  const [view, setView] = useState({ peers: [] as string[], trend: false });
  const [input, setInput] = useState('');
  const related = useQuery({
    queryKey: ['research-related', symbol],
    queryFn: ({ signal }) => api<S['RelatedIssuer'][]>(`/companies/${symbol}/related`, signal),
  });
  const symbols = [symbol, ...view.peers];
  const path = '/compare?' + new URLSearchParams({ symbols: symbols.join(','), trend: String(view.trend) });
  const result = useQuery({
    queryKey: [path],
    queryFn: ({ signal }) => api<S['PeerResult'][]>(path, signal),
    retry: false,
  });
  function add(v: string) {
    if (/^[A-Z0-9][A-Z0-9.-]{0,19}$/.test(v) && !symbols.includes(v) && symbols.length < 5) {
      setView({ ...view, peers: [...view.peers, v] });
      setInput('');
    }
  }
  const currencies = [
    ...new Set(
      result.data?.flatMap((p) =>
        p.rows.flatMap((r) => (r.values.revenue?.value ? [r.values.revenue.unit] : [])),
      ),
    ),
  ];
  return (
    <>
      <section className="panel">
        <h2>Peer comparison</h2>
        <form
          className="sec-filters"
          onSubmit={(e) => {
            e.preventDefault();
            add(input.trim().toUpperCase());
          }}
        >
          <label>
            Imported ticker
            <input value={input} onChange={(e) => setInput(e.target.value)} />
          </label>
          <button disabled={symbols.length >= 5}>Add peer</button>
          <label>
            Periods
            <select
              value={String(view.trend)}
              onChange={(e) => setView({ ...view, trend: e.target.value === 'true' })}
            >
              <option value="false">Latest annual</option>
              <option value="true">Annual trends</option>
            </select>
          </label>
        </form>
        {view.peers.map((p) => (
          <button key={p} onClick={() => setView({ ...view, peers: view.peers.filter((x) => x !== p) })}>
            Remove {p}
          </button>
        ))}
        {related.data
          ?.flatMap((p) => p.symbols.slice(0, 1))
          .filter((p) => !symbols.includes(p))
          .map((p) => (
            <button disabled={symbols.length >= 5} key={p} onClick={() => add(p)}>
              Add SIC peer {p}
            </button>
          ))}
        {result.isLoading && <p>Comparing filings…</p>}
        {result.error && <p role="alert">{result.error.message}</p>}
        {result.data && (
          <>
            <a href={'/api/v1' + path + '&format=csv'} download>
              Download comparison CSV
            </a>
            {view.trend && (
              <Suspense fallback={<p>Loading chart…</p>}>
                <Chart
                  theme={theme}
                  title="Operating margin by fiscal year end"
                  option={{
                    tooltip: { trigger: 'axis' },
                    legend: { type: 'scroll' },
                    grid: { containLabel: true },
                    xAxis: { type: 'time' },
                    yAxis: { type: 'value', name: 'Margin %' },
                    series: result.data.map((p) => ({
                      name: p.symbol,
                      type: 'line',
                      data: [...p.rows]
                        .reverse()
                        .map((r) => [
                          r.period.end,
                          r.values.operatingMargin?.value == null
                            ? null
                            : 100 * Number(r.values.operatingMargin.value),
                        ]),
                    })),
                  }}
                />
              </Suspense>
            )}
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Issuer</th>
                    <th>Period ending</th>
                    {currencies.map((c) => (
                      <th key={c}>Revenue · {c}</th>
                    ))}
                    {Object.values(peerFields).map((n) => (
                      <th key={n}>{n}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.data.map((p) =>
                    p.rows.length ? (
                      p.rows.map((r) => (
                        <tr key={p.symbol + r.period.start + r.period.end}>
                          <th>{p.symbol}</th>
                          <td>
                            {periodLabel(r.period)}
                            {p.misaligned && (
                              <small className="cell-note">Latest fiscal ends differ by over 90 days</small>
                            )}
                          </td>
                          {currencies.map((c) => (
                            <td key={c}>
                              {r.values.revenue.unit === c ? <ReportedCell cell={r.values.revenue} /> : '—'}
                            </td>
                          ))}
                          {Object.keys(peerFields).map((k) => (
                            <td key={k}>
                              <ReportedCell cell={r.values[k]} />
                            </td>
                          ))}
                        </tr>
                      ))
                    ) : (
                      <tr key={p.symbol}>
                        <th>{p.symbol}</th>
                        <td>No annual coverage</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      <Saves kind="compare" symbol={symbol} state={view} restore={setView} ready={!!result.data} />
    </>
  );
}
