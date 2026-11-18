import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from './api';
import SECPanel, { ScrapeButton } from './SECPanel';
import Research, { type ResearchTable } from './Research';
import { secAPI, type SECCompany, type SECJob } from './sec-api';
import type { components } from './api.generated';

type View = 'overview' | 'statements' | 'sec';
function pathView(): View | null {
  const view = new URLSearchParams(location.search).get('view');
  return view === 'overview' || view === 'statements' || view === 'sec' ? view : null;
}
function pathJob() { return new URLSearchParams(location.search).get('job') || ''; }
function pathSymbol() {
  try { return decodeURIComponent(location.pathname.match(/^\/companies\/([^/]+)\/?$/)?.[1] || '').toUpperCase(); }
  catch { return ''; }
}
function initialTheme() {
  return localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}
export function Notice({ text, retry }: { text: string; retry?: () => void }) {
  return <div className="notice" role="status"><span>{text}</span>{retry && <button onClick={retry}>Try again</button>}</div>;
}
const validTicker = /^[A-Z0-9][A-Z0-9.-]{0,19}$/;

export default function App() {
  const [symbol, setSymbol] = useState(pathSymbol);
  const [search, setSearch] = useState('');
  const [requestedView, setRequestedView] = useState(pathView);
  const [jobId, setJobId] = useState(pathJob);
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
  }, [theme]);
  useEffect(() => {
    const listener = () => { setSymbol(pathSymbol()); setRequestedView(pathView()); setJobId(pathJob()); };
    window.addEventListener('popstate', listener);
    return () => window.removeEventListener('popstate', listener);
  }, []);

  const exactSearch = search.trim().toUpperCase();
  const companies = useQuery({
    queryKey: ['sec-companies', search.trim()],
    queryFn: ({ signal }) => secAPI<SECCompany[]>(`/companies?limit=2000&q=${encodeURIComponent(search.trim())}`, { signal }),
    retry: false,
  });
  const company = useQuery({
    queryKey: ['sec-company', symbol],
    queryFn: ({ signal }) => secAPI<SECCompany>(`/companies/${encodeURIComponent(symbol)}`, { signal }),
    enabled: validTicker.test(symbol),
    retry: false,
  });
  const issuer = company.data?.data;
  const metrics = useQuery({
    queryKey: ['research-metrics', symbol],
    queryFn: ({ signal }) => api<ResearchTable>(`/companies/${encodeURIComponent(symbol)}/metrics?limit=200`, signal),
    enabled: !!issuer && requestedView !== 'sec',
    retry: false,
  });
  const hasMappedData = metrics.data?.rows.some(row => Object.values(row.values).some(cell => cell.value !== null));
  const view = requestedView || (hasMappedData || metrics.isError ? 'overview' : 'sec');

  function navigate(next: string, target: View | null = null, job = '') {
    const query = new URLSearchParams();
    if (target) query.set('view', target);
    if (job) query.set('job', job);
    const href = `/companies/${encodeURIComponent(next)}${query.size ? `?${query}` : ''}`;
    if (href !== location.pathname + location.search) history.pushState({}, '', href);
    setSymbol(next);
    setRequestedView(target);
    setJobId(job);
  }
  function showJob(job: SECJob) {
    navigate(job.symbol || symbol, 'sec', job.id);
    setSearch('');
  }
  const results = companies.data?.data || [];
  const suggestions = (companies.data?.meta?.suggestions || []).filter(row => !results.some(issuer => issuer.symbol === row.symbol));
  const missing = company.error instanceof ApiError && company.error.status === 404;
  const canScrapeSearch = companies.isSuccess && validTicker.test(exactSearch) && !results.some(row => row.symbol === exactSearch);
  const related = useQuery({
    queryKey: ['research-related', symbol],
    queryFn: ({ signal }) => api<components['schemas']['RelatedIssuer'][]>(`/companies/${encodeURIComponent(symbol)}/related`, signal),
    enabled: !!issuer && view === 'overview',
    retry: false,
  });

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark" aria-hidden="true">◈</span><div><strong>Ledger</strong><small>SEC research</small></div></div>
      <label className="search"><span aria-hidden="true">⌕</span><input aria-label="Search companies" placeholder="Search ticker or company" value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => {
        if (event.key === 'Enter' && validTicker.test(exactSearch)) navigate(exactSearch);
      }} /></label>
      <div className="list-heading">Imported companies</div>
      <nav aria-label="Company navigation" className="company-list">
        {companies.isPending && <p role="status">Loading companies…</p>}
        {companies.isError && <Notice text={companies.error.message} retry={() => void companies.refetch()} />}
        {companies.isSuccess && !results.length && <p>No imported companies match.</p>}
        {[...results, ...suggestions].map(row => <a key={row.symbol} href={`/companies/${encodeURIComponent(row.symbol)}`}
          className={`company-link${row.symbol === symbol ? ' active' : ''}`} aria-current={row.symbol === symbol ? 'page' : undefined}
          onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate(row.symbol); } }}>
          <strong>{row.symbol}</strong><small>{row.imported ? row.name : `${row.name} · SEC registry`}</small>
        </a>)}
        {canScrapeSearch && exactSearch !== symbol && <ScrapeButton symbol={exactSearch} onJob={showJob} />}
      </nav>
    </aside>
    <main className="workspace">
      <header className="topbar"><span>SEC research</span><button className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</button></header>
      {!symbol ? <section className="panel"><h1>Explore SEC filings</h1><p>Choose an imported company or search for a ticker to start an import.</p></section> : <>
        <section className="company-heading">
          <div><div className="eyebrow">SEC filings</div><h1>{issuer?.name || symbol}{issuer?.name && <span className="company-symbol">{symbol}</span>}</h1>
          {issuer && <p>{[issuer.sicDescription, issuer.exchanges?.join(', ')].filter(Boolean).join(' · ')} <small>CIK {issuer.cik}</small></p>}</div>
        </section>
        {!validTicker.test(symbol) && <Notice text="Enter a valid ticker symbol." />}
        {!issuer && !jobId && company.isFetching && <Notice text="Loading company…" />}
        {!issuer && !jobId && company.isError && !missing && <Notice text={company.error.message} retry={() => void company.refetch()} />}
        {issuer && (requestedView || !metrics.isPending) && <div className="toolbar"><div className="tabs" role="tablist" aria-label="Company views">
          {(['overview', 'statements', 'sec'] as const).map(tab => <button role="tab" key={tab} aria-selected={view === tab} onClick={() => navigate(symbol, tab, jobId)}>
            {{ overview: 'Overview', statements: 'Statements', sec: 'Filings' }[tab]}
          </button>)}
        </div></div>}
        {issuer && !requestedView && metrics.isPending && <Notice text="Checking financial statement coverage…" />}
        {(missing || !!jobId || (!!issuer && view === 'sec' && (!!requestedView || !metrics.isPending))) &&
          <div hidden={!!issuer && view !== 'sec'}><SECPanel key={symbol} symbol={symbol} company={issuer} companyError={company.error} jobId={jobId} onJob={showJob} canDiscover={companies.isSuccess} theme={theme} /></div>}
        {issuer && view !== 'sec' && <>
          <Research key={symbol} symbol={symbol} view={view} theme={theme} metrics={metrics} />
          {view === 'overview' && (related.isError ? <Notice text={related.error.message} retry={() => void related.refetch()} /> :
            !!related.data?.length && <section className="panel"><h2>Related SEC issuers</h2><p>Imported companies with the same SEC SIC code.</p>
              <ul>{related.data.flatMap(row => row.symbols.slice(0, 1).map(ticker => <li key={row.cik}><a href={`/companies/${encodeURIComponent(ticker)}`}>{ticker} · {row.name}</a></li>))}</ul>
            </section>)}
        </>}
      </>}
    </main>
  </div>;
}
