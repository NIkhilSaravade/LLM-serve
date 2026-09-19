import { useEffect, useState } from 'react'
import data from './data.json'
import Hero from './components/Hero.jsx'
import BatchingSim from './components/BatchingSim.jsx'
import PagedSim from './components/PagedSim.jsx'
import Results from './components/Results.jsx'
import Cpu from './components/Cpu.jsx'
import Negatives from './components/Negatives.jsx'
import Method from './components/Method.jsx'
import Reveal from './components/Reveal.jsx'

const LINKS = [['results', 'Results'], ['how-it-works', 'How it works'], ['cpu', 'CPU limits'], ['negative-results', 'Negative results'], ['methodology', 'Method'], ['limitations', 'Limits'], ['reproduce', 'Reproduce']]

function Nav() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('theme', theme) } catch { /* private mode */ }
  }, [theme])
  return (
    <header className="nav">
      <div className="wrap nav-in">
        <a className="brand" href="#top"><i />llm-serve</a>
        <nav className="nav-links" aria-label="Sections">
          {LINKS.map(([id, l]) => <a key={id} href={`#${id}`}>{l}</a>)}
        </nav>
        <button className="icon-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            {theme === 'dark'
              ? <><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" /></>
              : <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z" />}
          </svg>
        </button>
      </div>
    </header>
  )
}

export default function App() {
  const row = (wl, k) => data.ablation[wl].rows.find((r) => r.key === k)
  return (
    <>
      <Nav />
      <main id="main">
        <Hero data={data} />
        <Results data={data} />
        <section id="how-it-works">
          <div className="wrap">
            <Reveal className="sec-head">
              <h2>Two ideas, in motion</h2>
              <p className="body">
                The results above come from two mechanisms. These are simplified simulations so you can watch them work. They are
                illustrations, not data, and are labelled that way. The measured value each one is standing in for is underneath.
              </p>
            </Reveal>
            <div className="split">
              <Reveal><BatchingSim measured={data.milestones} /></Reveal>
              <Reveal delay={0.08}><PagedSim measured={{ contig: row('B', 'm3_continuous').kv_eff.median, paged: row('B', 'm4_full').kv_eff.median }} /></Reveal>
            </div>
          </div>
        </section>
        <Cpu data={data} />
        <Negatives data={data} />
        <Method data={data} />
      </main>
      <footer className="foot">
        <div className="wrap">llm-serve. A from-scratch inference server built to measure scheduling and memory management, not to compete with production systems.</div>
      </footer>
    </>
  )
}
